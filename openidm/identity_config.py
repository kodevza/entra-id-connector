# SPDX-License-Identifier: CDDL-1.1
"""Configuration builders for Entra preprovisioning, native OIDC and local governance."""
import copy
import json
import uuid

MAPPING = 'systemEntraAccount_managedUser'


def build_mapping(tenant):
    tenant = str(uuid.UUID(tenant))
    def transform(target, expression):
        return {'source':'', 'target': target, 'transform': {'type': 'groovy', 'source': '// Entra identity ' + target + '\nreturn ' + expression}}
    literal = json.dumps(tenant)
    mapping = {
        'name': MAPPING, 'source': 'system/entra/__ACCOUNT__', 'target': 'managed/user',
        'sourceQuery': {'_queryFilter':'true'}, 'sourceQueryFullEntry': True,
        'taskThreads': 1, 'runTargetPhase': True,
        'targetQuery': {'_queryFilter':'/entraTenantId eq ' + json.dumps(tenant)},
        'correlationQuery': {'type':'groovy','source':
            '// Entra immutable identity correlation\nreturn [_queryFilter: "entraObjectId eq " + groovy.json.JsonOutput.toJson(source._id) + " and entraTenantId eq " + groovy.json.JsonOutput.toJson(' + literal + ')]'},
        'properties': [
            {'source':'_id','target':'entraObjectId'},
            {'target':'entraTenantId','default':tenant},
            transform('userName', "'entra.' + " + literal + " + '.' + source._id"),
            {'source':'userPrincipalName','target':'entraUserPrincipalName'},
            transform('givenName', "source.givenName ?: source.displayName ?: source._id"),
            transform('sn', "source.surname ?: '(Entra)'"),
            transform('mail', "source.mail ?: source.userPrincipalName ?: (source._id + '@entra.invalid')"),
            transform('displayName', "source.displayName ?: source.userPrincipalName ?: source._id"),
            transform('accountStatus', "source.accountEnabled == true ? 'active' : 'inactive'")
        ],
        'policies': [{'situation':s, 'action':a} for s,a in [
            ('CONFIRMED','UPDATE'),('FOUND','UPDATE'),('ABSENT','CREATE'),('MISSING','CREATE'),
            ('AMBIGUOUS','EXCEPTION'),('FOUND_ALREADY_LINKED','EXCEPTION'),
            ('SOURCE_MISSING',{'type':'text/javascript','file':'entra/missingSource.js','tenantId':tenant}),('UNQUALIFIED','IGNORE'),('UNASSIGNED','IGNORE')]]
    }

    # A first login binds the native OIDC subject. Graph must never overwrite
    # that technical login with the pre-login placeholder on subsequent imports.
    next(p for p in mapping['properties'] if p['target'] == 'userName')['condition'] = {
        'type':'text/javascript',
        'source':'!(target.entraOidcSubject && target.userName === target.entraOidcSubject)'}
    return mapping


def extend_managed(managed):
    for obj in managed['objects']:
        schema = obj['schema']
        additions = {}
        if obj['name'] == 'user':
            for field,title in [('entraTenantId','Entra tenant ID'),('entraObjectId','Entra object ID'),
                                ('entraUserPrincipalName','Entra UPN'),('displayName','Display name'),
                                ('entraOidcSubject','Verified Entra OIDC subject'),('entraOidcClientId','Entra OIDC client ID')]:
                additions[field] = {'type':'string','title':title,'viewable':True,'searchable':True,
                    'userEditable':False, 'isProtected':True}
            additions['entraWorkflowAliases'] = {'type':'array','items':{'type':'string'},
                'title':'Previous Entra workflow logins','viewable':False,'userEditable':False,'isProtected':True}
        elif obj['name'] == 'entraServicePrincipal':
            additions['governanceOwner'] = {'type':['relationship','null'],'title':'Governance owner (OpenIDM)',
                'description':'Local accountable owner, assigned only after acceptance in OpenIDM.',
                'viewable':True,'userEditable':False,'isProtected':True,'validate':True,'returnByDefault':True,
                'properties':{'_ref':{'type':'string'},'_refProperties':{'type':'object','properties':{'_id':{'type':'string'}}}},
                'resourceCollection':[{'path':'managed/user','label':'User',
                    'query':{'queryFilter':'/accountStatus eq "active"','fields':['userName','displayName','entraUserPrincipalName'],
                        'sortKeys':['displayName']}}]}
        for name,definition in additions.items():
            schema['properties'].setdefault(name,definition)
            if name == 'governanceOwner':
                if schema['properties'][name].get('type') == 'relationship':
                    schema['properties'][name]['type'] = ['relationship', 'null']
                schema['properties'][name].setdefault('returnByDefault', True)
            if name not in schema.setdefault('order',[]): schema['order'].append(name)
    # The workflow schema is shared by fresh installs and upgrades. Preserve custom fields.
    from pathlib import Path
    request_definition = json.loads((Path(__file__).parent / 'workflow/managed.json').read_text())['requestObject']
    existing = next((o for o in managed['objects'] if o['name'] == 'entraOwnerRequest'), None)
    if existing is None:
        managed['objects'].append(copy.deepcopy(request_definition))
    else:
        schema = existing['schema']
        for name, definition in request_definition['schema']['properties'].items():
            schema['properties'].setdefault(name, copy.deepcopy(definition))
            if name not in schema.setdefault('order', []):
                schema['order'].append(name)
    return managed


def build_auth_module(tenant, client, secret, access_group_id, admin_group_id):
    tenant = str(uuid.UUID(tenant))
    base = 'https://login.microsoftonline.com/' + tenant + '/v2.0'
    return {'name':'OPENID_CONNECT','enabled':True,'properties':{
        'openIdConnectHeader':'authToken', 'entraTenantId':tenant,'entraClientId':client,
        'entraAccessGroupId':str(uuid.UUID(access_group_id)),
        'entraAdminGroupId':str(uuid.UUID(admin_group_id)),
        'defaultUserRoles':[],
        'augmentSecurityContext':{'type':'text/javascript','file':'entra/populateContext.js'},
        'resolvers':[{'name':'entra','type':'OPENID_CONNECT','enabled':True,
            'well-known':base + '/.well-known/openid-configuration',
            'issuer':base,'client_id':client,'client_secret':secret,
            'authorization_endpoint':'https://login.microsoftonline.com/' + tenant + '/oauth2/v2.0/authorize',
            'token_endpoint':'https://login.microsoftonline.com/' + tenant + '/oauth2/v2.0/token',
            'end_session_endpoint':'https://login.microsoftonline.com/' + tenant + '/oauth2/v2.0/logout',
            'scope':['openid','profile','email'], 'authenticationId':'sub',
            'icon':'<button class="btn btn-lg btn-default btn-block btn-social-provider"><span>{{action}} Microsoft Entra ID</span></button>'}]}}


def merge_named(items, item, key='name'):
    result = copy.deepcopy(items)
    for i, old in enumerate(result):
        if old.get(key) == item[key]:
            result[i] = item
            break
    else: result.append(item)
    return result


def build_membership_action():
    return {'scriptId':'isGroupMember','actions':[{
        'systemType':r'^eu\.soft4pm\.openicf\.entra\.EntraConnector$',
        'actionType':'entra','actionSource':'isGroupMember'}]}
