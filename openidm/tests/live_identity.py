#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Opt-in local OpenIDM integration check; Graph is read-only.

Creates one temporary local account/link to exercise SOURCE_MISSING, then deletes
only that fixture. Set OPENIDM_PASSWORD; run after install_identity.py.
"""
import argparse
import json
import os
import time
import uuid
import urllib.parse
import urllib.request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',default='http://localhost:8081/openidm')
parser.add_argument('--tenant',required=True)
args=parser.parse_args()
headers={'X-OpenIDM-Username':'openidm-admin','X-OpenIDM-Password':os.environ['OPENIDM_PASSWORD'],'Content-Type':'application/json'}
def api(path,data=None,method=None):
    request_headers = dict(headers)
    if method in ('DELETE','PATCH'):
        request_headers['If-Match'] = json.dumps(api(path)['_rev'])
    req=urllib.request.Request(args.url.rstrip('/')+'/'+path,headers=request_headers,method=method,
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req,timeout=90) as response:return json.load(response)
def users():
    query='/entraTenantId eq '+json.dumps(args.tenant)
    return api('managed/user?_queryFilter='+urllib.parse.quote(query))['result']
def reconcile():
    result=api('recon?_action=recon&mapping=systemEntraAccount_managedUser',{},'POST')
    for _ in range(90):
        result=api('recon/'+result['_id'])
        if result['state']!='ACTIVE':break
        time.sleep(1)
    assert result['state']=='SUCCESS',result['state']
    assert result['statusSummary']['FAILURE']==0,result['statusSummary']
    return result
initial_users = users()
original={u['_id'] for u in initial_users}
bound_logins = {u['_id']:u['userName'] for u in initial_users if u.get('entraOidcSubject')}
assert original,'No preprovisioned Entra accounts'
reconcile()
assert {u['_id'] for u in users()}==original,'Repeated reconciliation created duplicates'
assert all(u['userName']==bound_logins[u['_id']] for u in users() if u['_id'] in bound_logins), 'Reconciliation overwrote a bound native subject'
print('PASS: accounts exist before login; reconciliation preserves IDs and bound native subjects')
uid=str(uuid.uuid4());fixture_name='entra-sync-fixture.'+uid
fixture=None;link=None;principal=None
try:
    fixture=api('managed/user?_action=create',{'userName':fixture_name,'givenName':'Sync test','sn':'Fixture',
        'mail':'openidm-sync-test@example.invalid','accountStatus':'active','entraTenantId':args.tenant,'entraObjectId':uid},'POST')
    principal=api('managed/entraServicePrincipal?_action=create',{'sourceId':str(uuid.uuid4()),
        'tenantId':args.tenant,'displayName':'OpenIDM ownership integration fixture'},'POST')
    principal_path='managed/entraServicePrincipal/'+principal['_id']
    api(principal_path,[{'operation':'add','field':'/governanceOwner','value':{'_ref':'managed/user/'+fixture['_id']}}],'PATCH')
    assert api(principal_path+'?_fields=*,governanceOwner')['governanceOwner']['_ref']=='managed/user/'+fixture['_id']
    print('PASS: a user who never logged in can be stored as an owner relationship')
    link=api('repo/link?_action=create',{'linkType':'systemEntraAccount_managedUser',
        'linkQualifier':'default','firstId':uid,'secondId':fixture['_id']},'POST')
    result=reconcile()
    assert result['situationSummary']['SOURCE_MISSING']>=1,result['situationSummary']
    assert api('managed/user/'+fixture['_id'])['accountStatus']=='inactive'
    print('PASS: missing Entra source disables local account without deleting it')
finally:
    if principal:api('managed/entraServicePrincipal/'+principal['_id'],method='DELETE')
    if link:api('repo/link/'+link['_id'],method='DELETE')
    if fixture:
        path='managed/user/'+fixture['_id']
        assert api(path)['userName']==fixture_name
        api(path,method='DELETE')
assert {u['_id'] for u in users()}==original,'Fixture cleanup failed'
print('PASS: test fixture cleaned; original accounts preserved')
