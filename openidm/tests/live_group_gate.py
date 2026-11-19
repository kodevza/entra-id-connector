#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Read-only installed-group-gate checks. Requires empty iam group for the denial check.

The optional positive group is used only in privileged script bindings; the deployed
login configuration and group memberships are never changed. This exercises the
read-only authorization stage, not subject binding or an interactive OIDC/MFA login.
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',default='http://localhost:8081/openidm')
parser.add_argument('--positive-group-id')
args=parser.parse_args()
headers={'X-OpenIDM-Username':'openidm-admin','X-OpenIDM-Password':os.environ['OPENIDM_PASSWORD'],'Content-Type':'application/json'}
def api(path,data=None,method=None):
    req=urllib.request.Request(args.url.rstrip('/')+'/'+path,headers=headers,method=method,
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)
auth=api('config/authentication')
p=next(m['properties'] for m in auth['serverAuthContext']['authModules']
    if m['name']=='OPENID_CONNECT' and m['properties'].get('entraAccessGroupId'))
users=api('managed/user?_queryFilter=true')['result']
users=[u for u in users if u.get('entraTenantId')==p['entraTenantId'] and u['accountStatus']=='active']
assert users
check_path='system/entra?_action=script&scriptId=isGroupMember&scriptExecuteMode=resource'
def member(group,user):
    r=api(check_path,{'groupId':group,'userId':user['entraObjectId']},'POST')
    assert len(r['actions'])==1 and isinstance(r['actions'][0].get('result'),bool),'Connector lookup failed'
    return r['actions'][0]['result']
assert not member(p['entraAccessGroupId'],users[0]),'iam must be empty for this deployment check'
print('PASS: live Graph lookup rejects a nonmember of iam')
source="var authorized = require('entra/identity').authorizeClaims(claims, security, properties); ({userId:authorized.user._id, roles:authorized.roles, authenticationId:security.authenticationId});"
api('script?_action=compile',{'type':'text/javascript','source':source},'POST')
def augment(group,user):
    claims={'tid':p['entraTenantId'],'oid':user['entraObjectId'],'aud':p['entraClientId'],
        'iss':'https://login.microsoftonline.com/'+p['entraTenantId']+'/v2.0','exp':int(time.time())+300,
        'sub':'group-gate-probe','groups':[p['entraAccessGroupId']]}
    payload={'type':'text/javascript','source':source,'claims':claims,
        'security':{'authenticationId':'group-gate-probe','authorization':{'moduleId':'OpenIDConnect'}},
        'properties':{'entraTenantId':p['entraTenantId'],'entraClientId':p['entraClientId'],'entraAccessGroupId':group,'entraAdminGroupId':p['entraAdminGroupId']}}
    return api('script?_action=eval',payload,'POST')
try:
    augment(p['entraAccessGroupId'],users[0])
    raise AssertionError('Nonmember unexpectedly authorized')
except urllib.error.HTTPError as e:
    assert e.code==403,(e.code,e.read().decode())
print('PASS: actual authorization hook denies the nonmember, even with a groups claim')
try:
    augment(str(uuid.uuid4()),users[0])
    raise AssertionError('Missing group unexpectedly authorized')
except urllib.error.HTTPError as e:
    assert e.code==503,(e.code,e.read().decode())
print('PASS: actual authorization hook denies access when Graph lookup fails')
if args.positive_group_id:
    user=next((u for u in users if member(args.positive_group_id,u)),None)
    assert user,'No synchronized user belongs to the supplied positive test group'
    mapped=augment(args.positive_group_id,user)
    assert mapped['userId']==user['_id']
    assert mapped['authenticationId']=='group-gate-probe'
    print('PASS: live member accepted by the same hook using test-only group bindings')
# Verify that no test changed the configured access group.
current=api('config/authentication')
assert any(m.get('properties',{}).get('entraAccessGroupId')==p['entraAccessGroupId']
           for m in current['serverAuthContext']['authModules'])
print('PASS: deployed iam restriction unchanged; no group memberships modified')
