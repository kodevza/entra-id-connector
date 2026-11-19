#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Install the companion configuration into an existing local OpenIDM container.

Requires an already installed connector and an Entra web app registration.
Secrets come from environment/getpass and are never printed or written to this repo.
"""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from install_workflow_bar import install_bar, validate_archive, ARCHIVE
from install_user_menu import install as install_user_menu
from identity_config import MAPPING, build_auth_module, build_mapping, build_membership_action, extend_managed, merge_named


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8081/openidm')
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--client-id', required=True)
    parser.add_argument('--access-group-id', required=True, help='Object ID of the iam security group')
    parser.add_argument('--admin-group-id', required=True, help='Object ID of the iam-admins security group')
    parser.add_argument('--username', default='openidm-admin')
    args = parser.parse_args()
    password = os.environ.get('OPENIDM_PASSWORD') or getpass.getpass('OpenIDM admin password: ')
    secret = os.environ.get('ENTRA_CLIENT_SECRET') or getpass.getpass('Entra login client secret: ')
    headers = {'X-OpenIDM-Username':args.username,'X-OpenIDM-Password':password,'Content-Type':'application/json'}
    root = Path(__file__).resolve().parent
    validate_archive(ARCHIVE)
    def api(path, data=None, method=None):
        req = urllib.request.Request(args.url.rstrip('/')+'/'+path, headers=headers, method=method,
            data=json.dumps(data).encode() if data is not None else None)
        # Do not log response bodies: configurations may contain connector credentials.
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    def put(path, data):
        return api('config/'+path, data, 'PUT')
    def docker(*command):
        subprocess.run(['docker',*command],check=True,stdout=subprocess.DEVNULL)
    stamp = datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%SZ')
    backup = '/opt/openidm/identity-backups/'+stamp
    docker('exec',args.container,'mkdir','-p',backup)
    docker('exec',args.container,'chmod','700',backup)
    configs = ['managed.json','sync.json','authentication.json','repo.orientdb.json','provisioner.openicf-entra.json']
    for name in configs:
        docker('exec',args.container,'cp','/opt/openidm/conf/'+name,backup+'/'+name)
    docker('exec',args.container,'mkdir','-p','/opt/openidm/script/entra','/opt/openidm/workflow')
    for script in (root/'script'/'entra').glob('*.js'):
        docker('cp',str(script),args.container+':/opt/openidm/script/entra/'+script.name)
    # Define the audit class before enabling its managed collection (OrientDB host).
    repo = api('config/repo.orientdb')
    classes = repo['dbStructure']['orientdbClass']
    if 'managed_entraOwnerRequest' not in classes:
        classes['managed_entraOwnerRequest'] = {'index':[{'propertyName':'_openidm_id','propertyType':'string','indexType':'unique'}]}
        put('repo.orientdb',repo)
        time.sleep(3)
    managed = api('config/managed')
    extend_managed(managed)
    profiles = next(o for o in managed['objects'] if o['name']=='entraUser')
    for field in ['givenName','surname']:
        profiles['schema']['properties'].setdefault(field,{'type':['string','null'],'title':field,
            'viewable':True,'searchable':True,'userEditable':False})
    put('managed',managed)
    provisioner = api('config/provisioner.openicf/entra')
    for field in ['givenName','surname']:
        provisioner['objectTypes']['__ACCOUNT__']['properties'].setdefault(field,{
            'type':'string','nativeName':field,'nativeType':'string','flags':['NOT_CREATABLE','NOT_UPDATEABLE']})
    provisioner['systemActions'] = merge_named(provisioner.get('systemActions',[]),build_membership_action(),key='scriptId')
    put('provisioner.openicf/entra',provisioner)
    sync = api('config/sync')
    mapping = build_mapping(args.tenant)
    sync['mappings'] = merge_named(sync['mappings'],mapping)
    for inventory in sync['mappings']:
        if inventory['target']=='managed/entraUser':
            for field in ['givenName','surname']:
                if not any(p.get('target')==field for p in inventory['properties']):
                    inventory['properties'].append({'source':field,'target':field})
    put('sync',sync)
    # Precompile to avoid the script registry's first-use activation race.
    scripts = [mapping['correlationQuery']]+[p['transform'] for p in mapping['properties'] if 'transform' in p]
    scripts += [p['condition'] for p in mapping['properties'] if 'condition' in p]
    scripts += [{'type':'text/javascript','file':'entra/'+p.name} for p in (root/'script'/'entra').glob('*.js')]
    for script in scripts:
        api('script?_action=compile',script,'POST')
    auth = api('config/authentication')
    modules = auth['serverAuthContext']['authModules']
    # Replace our module only; preserve all other existing login methods/providers.
    modules[:] = [m for m in modules if not (m['name']=='OPENID_CONNECT' and
        any(r.get('name')=='entra' for r in m.get('properties',{}).get('resolvers',[])))]
    modules.append(build_auth_module(args.tenant,args.client_id,secret,args.access_group_id,args.admin_group_id))
    local = next(m for m in modules if m['name']=='MANAGED_USER')
    augment = local['properties'].setdefault('augmentSecurityContext',{'type':'text/javascript'})
    prefix = "require('entra/identity').rejectLocalAuth(security);"
    if 'file' in augment:
        raise RuntimeError('MANAGED_USER uses a file augmentation hook; compose rejectLocalAuth into that hook before installation')
    old_source = augment.get('source',"require('auth/customAuthz').setProtectedAttributes(security);")
    if prefix not in old_source: augment['source'] = prefix+old_source
    put('authentication',auth)
    install_bar(api, args.container)
    put('schedule/entra-users',{'enabled':True,'type':'cron','schedule':'0 0/15 * * * ?',
        'persisted':True,'concurrentExecution':False,'invokeService':'sync',
        'invokeContext':{'action':'reconcile','mapping':MAPPING}})
    # Config application and JSON file persistence are asynchronous. Wait for both
    # before returning; restarting too early can reload an older file view.
    for _ in range(30):
        time.sleep(1)
        raw = subprocess.check_output(['docker','exec',args.container,'cat','/opt/openidm/conf/sync.json'])
        if any(m['name']==MAPPING for m in json.loads(raw)['mappings']):
            break
    else: raise RuntimeError('Configuration file persistence did not complete')
    install_user_menu(args.container)
    print('Installed Entra preprovisioning, OIDC and ownership workflow. Backup: '+backup)
    print('Start reconciliation: POST '+args.url.rstrip('/')+'/recon?_action=recon&mapping='+MAPPING)

if __name__ == '__main__':
    main()
