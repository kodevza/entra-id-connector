#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Opt-in local workflow check with disposable records; never writes to Graph.

Set OPENIDM_PASSWORD. Exercises Entra IDs distinct from local IDs and both diagram
endpoints used by the UI, then cancels the process and removes its fixtures.
"""
import json
import os
from pathlib import Path
import urllib.request
import uuid

base = os.environ.get('OPENIDM_URL', 'http://localhost:8081/openidm').rstrip('/')
headers = {'X-OpenIDM-Username': 'openidm-admin',
           'X-OpenIDM-Password': os.environ['OPENIDM_PASSWORD'], 'Content-Type': 'application/json'}


def api(path, data=None, method=None, binary=False):
    request = urllib.request.Request(base + '/' + path, headers=headers, method=method,
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read() if binary else json.load(response)


principal = owner = process = None
tenant, principal_oid, owner_oid = [str(uuid.uuid4()) for _ in range(3)]
try:
    definitions = api('workflow/processdefinition?_queryId=filtered-query')['result']
    definition = max((d for d in definitions if d['key'] == 'servicePrincipalOwner'), key=lambda d: d['version'])
    assert definition['processDiagramResourceName'], 'Definition has no diagram'
    png = api('workflow/processdefinition/' + definition['_id'] + '?_fields=/diagram&_mimeType=image/png', binary=True)
    assert png.startswith(b'\x89PNG\r\n\x1a\n'), 'Definition diagram is not a PNG'
    Path('/tmp/owner-workflow-definition.png').write_bytes(png)
    owner = api('managed/user?_action=create', {'userName': 'workflow-fixture.' + owner_oid,
        'givenName': 'Workflow', 'sn': 'Fixture', 'mail': 'workflow-fixture@example.invalid',
        'accountStatus': 'active', 'entraObjectId': owner_oid, 'entraTenantId': tenant}, 'POST')
    principal = api('managed/entraServicePrincipal?_action=create', {'sourceId': principal_oid,
        'tenantId': tenant, 'displayName': 'Ownership workflow fixture',
        'grantedAccessJson': json.dumps({'collectedAt':'2026-11-18T12:00:00Z', 'coverage':'Direct grants test fixture',
            'permissions':[{'kind':'application','resourceName':'Microsoft Graph','permission':'User.Read.All','description':'Read users <script>alert(1)</script>'}]})}, 'POST')
    assert owner['_id'] != owner_oid and principal['_id'] != principal_oid
    process = api('workflow/processinstance?_action=create', {'_processDefinitionId': definition['_id'],
        'servicePrincipalId': principal_oid.upper(), 'newOwnerId': owner_oid.upper(), 'reason': 'Local automated test'}, 'POST')
    request = api('managed/entraOwnerRequest/' + process['_id'])
    assert request['servicePrincipalId'] == principal['_id']
    assert request['newOwnerId'] == owner['_id']
    assert request['status'] == 'pending'
    assert 'Microsoft Graph | User.Read.All' in request['accessSummary']
    tasks = api('workflow/taskinstance?_queryId=filtered-query')['result']
    task = next(t for t in tasks if t['processInstanceId'] == process['_id'])
    task = api('workflow/taskinstance/' + task['_id'])
    assert task['variables']['accessSummary'] == request['accessSummary']
    assert task['variables']['grantedAccessJson'] == request['grantedAccessJson']
    task_definition = api('workflow/processdefinition/' + definition['_id'] + '/taskdefinition/' + task['taskDefinitionKey'])
    assert task_definition['formResourceKey'] == 'forms/servicePrincipalOwner.html'
    assert 'data-entra-owner-form' in task_definition['formGenerationTemplate']
    assert '{{variables.grantedAccessJson}}' in task_definition['formGenerationTemplate']
    assert any('accessSummary' in prop for prop in task['formProperties'])
    print('PASS: snapshot and readable review form reach the live owner task')
    png = api('workflow/processinstance/' + process['_id'] + '?_fields=/diagram&_mimeType=image/png', binary=True)
    assert png.startswith(b'\x89PNG\r\n\x1a\n'), 'Instance diagram is not a PNG'
    Path('/tmp/owner-workflow-active.png').write_bytes(png)
    assert not api('managed/entraServicePrincipal/' + principal['_id'] + '?_fields=*,governanceOwner').get('governanceOwner')
    print('PASS: external Entra IDs resolve to local records; nomination waits for approval')
    print('PASS: definition and active-step diagram endpoints return PNGs; version', definition['version'])
finally:
    if process:
        api('workflow/processinstance/' + process['_id'], method='DELETE')
        api('managed/entraOwnerRequest/' + process['_id'], method='DELETE')
    if principal:
        api('managed/entraServicePrincipal/' + principal['_id'], method='DELETE')
    if owner:
        api('managed/user/' + owner['_id'], method='DELETE')
