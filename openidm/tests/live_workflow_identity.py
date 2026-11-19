#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Opt-in native-subject workflow regression using disposable local records only.

OPENIDM_PASSWORD is required. Does not sign in to Entra or write to Graph.
Privileged script bindings simulate a previously verified subject for this fixture.
"""
import json
import os
import urllib.request
import urllib.error
import uuid

base = os.environ.get('OPENIDM_URL', 'http://localhost:8081/openidm').rstrip('/')
headers = {'X-OpenIDM-Username':'openidm-admin', 'X-OpenIDM-Password':os.environ['OPENIDM_PASSWORD'],
           'Content-Type':'application/json'}


def api(path, data=None, method=None):
    req = urllib.request.Request(base + '/' + path, headers=headers, method=method,
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(str(error.code) + ': ' + json.load(error).get('message', 'Request failed')) from None


def evaluate(source, **bindings):
    return api('script?_action=eval', {'type':'text/javascript', 'source':source, **bindings}, 'POST')


tenant, oid, principal_oid = [str(uuid.uuid4()) for _ in range(3)]
subject = 'workflow-sub-fixture.' + str(uuid.uuid4())
owner = principal = process = None
completed = False
try:
    owner = api('managed/user?_action=create', {'userName':'entra.' + tenant + '.' + oid,
        'givenName':'Workflow', 'sn':'Subject fixture', 'mail':'subject-fixture@example.invalid',
        'accountStatus':'active', 'entraTenantId':tenant, 'entraObjectId':oid}, 'POST')
    principal = api('managed/entraServicePrincipal?_action=create', {'sourceId':principal_oid,
        'tenantId':tenant, 'displayName':'Native OIDC workflow fixture'}, 'POST')
    definitions = api('workflow/processdefinition?_queryId=filtered-query')['result']
    definition = max((d for d in definitions if d['key']=='servicePrincipalOwner'), key=lambda d:d['version'])
    process = api('workflow/processinstance?_action=create', {'_processDefinitionId':definition['_id'],
        'servicePrincipalId':principal_oid, 'newOwnerId':oid, 'reason':'Native subject regression fixture'}, 'POST')
    tasks = api('workflow/taskinstance?_queryId=filtered-query')['result']
    task = next(t for t in tasks if t['processInstanceId']==process['_id'])
    original_id = owner['_id']
    claims = {'tid':tenant, 'oid':oid, 'sub':subject, 'aud':'fixture-client'}
    source = "require('entra/workflowIdentity').bindSubject(openidm.read('managed/user/' + ownerId), claims);"
    evaluate(source, ownerId=original_id, claims=claims)
    owner = api('managed/user/' + original_id)
    assert owner['userName']==subject and owner['entraOidcSubject']==subject
    assert owner['entraWorkflowAliases']==['entra.' + tenant + '.' + oid]
    assert api('workflow/taskinstance/' + task['_id'])['assignee']==subject
    request = api('managed/entraOwnerRequest/' + process['_id'])
    assert request['newOwnerId']==original_id and request['newOwnerUserName']==subject and request['status']=='pending'
    evaluate(source, ownerId=original_id, claims=claims)
    mapping = next(m for m in api('config/sync')['mappings'] if m['name']=='systemEntraAccount_managedUser')
    condition = next(p for p in mapping['properties'] if p['target']=='userName')['condition']
    assert api('script?_action=eval', {**condition, 'target':owner}, 'POST') is False
    assert api('script?_action=eval', {**condition, 'target':{'userName':'pre-login'}}, 'POST') is True
    print('PASS: native subject binding is idempotent; account/task/process IDs preserved')
    # Execute the stock dashboard aggregation with a fixture user context.
    view = api('script?_action=eval', {'type':'text/javascript', 'file':'workflow/gettasksview.js',
        'context':{'security':{'authenticationId':subject,'authorization':{'roles':['openidm-authorized']}}},
        'request':{'method':'query','additionalParameters':{'viewType':'assignee'}}}, 'POST')
    assert task['_id'] in view[0], view
    print('PASS: stock Self Service task endpoint includes the migrated task')
    source = """
        var security = new org.forgerock.services.context.SecurityContext(
            new org.forgerock.services.context.RootContext(), subject,
            {component:'managed/user', id:ownerId, roles:['openidm-authorized']});
        openidm.action('workflow/taskinstance/' + taskId, 'complete', {decision:'accept'}, {}, [], security);
    """
    evaluate(source, ownerId=original_id, subject=subject, taskId=task['_id'])
    completed = True
    request = api('managed/entraOwnerRequest/' + process['_id'])
    assert request['status']=='accepted' and request['decidedBy']==subject
    assert api('managed/entraServicePrincipal/' + principal['_id'] + '?_fields=*,governanceOwner')['governanceOwner']['_ref']=='managed/user/' + original_id
    print('PASS: stock task authorization and BPMN completion accept the native subject; local owner assigned without Graph writes')
finally:
    if process:
        if not completed:
            api('workflow/processinstance/' + process['_id'], method='DELETE')
        api('managed/entraOwnerRequest/' + process['_id'], method='DELETE')
    if principal:
        api('managed/entraServicePrincipal/' + principal['_id'], method='DELETE')
    if owner:
        api('managed/user/' + owner['_id'], method='DELETE')
