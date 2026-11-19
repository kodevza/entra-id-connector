#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Install native OIDC subject binding into an existing Entra/OpenIDM integration.

No login client secret is needed: current provider configuration is preserved.
Makes protected schema additions, preserves bound usernames during reconciliation,
installs the connector's hooks, and reloads authentication. Existing sessions need
fresh Microsoft sign-in. Does not modify the OpenIDM authentication bundle.
"""
import argparse
import copy
import datetime
import getpass
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
from identity_config import MAPPING, build_mapping, extend_managed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8081/openidm')
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--username', default='openidm-admin')
    parser.add_argument('--check', action='store_true', help='Validate prerequisites without writing')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    password = os.environ.get('OPENIDM_PASSWORD') or getpass.getpass('OpenIDM admin password: ')
    headers = {'X-OpenIDM-Username':args.username, 'X-OpenIDM-Password':password, 'Content-Type':'application/json'}

    def api(path, data=None, method=None):
        req = urllib.request.Request(args.url.rstrip('/') + '/' + path, headers=headers, method=method,
            data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)

    def docker(*command):
        subprocess.run(['docker', *command], check=True, stdout=subprocess.DEVNULL)

    auth = api('config/authentication')
    modules = [m for m in auth['serverAuthContext']['authModules']
        if m.get('name')=='OPENID_CONNECT' and m.get('properties', {}).get('entraTenantId')]
    if len(modules) != 1:
        raise ValueError('Expected exactly one configured Entra OPENID_CONNECT module')
    props = modules[0]['properties']
    if props['augmentSecurityContext'] != {'type':'text/javascript','file':'entra/populateContext.js'}:
        raise ValueError('Custom Entra authentication hook; compose the binding into that hook manually')
    managed, sync = api('config/managed'), api('config/sync')
    if not any(o['name']=='entraOwnerRequest' for o in managed['objects']):
        raise ValueError('Install the ownership workflow and request collection first')
    mapping = next(m for m in sync['mappings'] if m['name']==MAPPING)
    username = next(p for p in mapping['properties'] if p['target']=='userName')
    condition = next(p for p in build_mapping(props['entraTenantId'])['properties'] if p['target']=='userName')['condition']
    updated_managed = copy.deepcopy(managed)
    extend_managed(updated_managed)
    print('Native subject binding prerequisites OK.')
    if args.check:
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = '/opt/openidm/identity-backups/native-subject-' + stamp
    docker('exec', args.container, 'mkdir', '-p', backup)
    docker('exec', args.container, 'chmod', '700', backup)
    for name in ('authentication.json', 'managed.json', 'sync.json'):
        docker('exec', args.container, 'cp', '/opt/openidm/conf/' + name, backup + '/' + name)
    # Keep the previous hook files with the configuration backup, including on repeat installs.
    docker('exec', args.container, 'cp', '-r', '/opt/openidm/script/entra', backup + '/entra')
    username['condition'] = condition
    if updated_managed != managed:
        api('config/managed', updated_managed, 'PUT')
    # The registry can expose first-use Groovy scripts before activation after a
    # restart. Warm every existing mapping script before the next reconciliation.
    scripts = [condition]
    if mapping.get('correlationQuery'):
        scripts.append(mapping['correlationQuery'])
    scripts += [p['transform'] for p in mapping['properties'] if 'transform' in p]
    for script in scripts:
        api('script?_action=compile', script, 'POST')
    api('config/sync', sync, 'PUT')
    # Persist schema/mapping before enabling a hook that writes the new protected fields.
    for _ in range(30):
        raw = subprocess.check_output(['docker','exec',args.container,'cat','/opt/openidm/conf/sync.json'])
        persisted = next(m for m in json.loads(raw)['mappings'] if m['name']==MAPPING)
        if next(p for p in persisted['properties'] if p['target']=='userName').get('condition') == condition:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Synchronization config did not persist; backup: ' + backup)
    for name in ('workflowIdentity.js', 'identity.js', 'populateContext.js'):
        docker('cp', str(root / 'script/entra' / name), args.container + ':/opt/openidm/script/entra/' + name)
        api('script?_action=compile', {'type':'text/javascript','file':'entra/' + name}, 'POST')
    api('config/authentication', auth, 'PUT')
    # Reloading the auth filter briefly makes its context unavailable. Do not
    # return until the normal managed-user route accepts authenticated requests.
    for _ in range(30):
        try:
            api('managed/user?_queryFilter=false')
            break
        except urllib.error.HTTPError as error:
            if error.code != 503:
                raise
            time.sleep(1)
    else:
        raise RuntimeError('Authentication reload did not become ready; backup: ' + backup)
    print('Installed native subject binding. Backup:', backup)
    print('Sign out of OpenIDM and sign in through Microsoft. Account/task IDs are preserved.')


if __name__ == '__main__':
    main()
