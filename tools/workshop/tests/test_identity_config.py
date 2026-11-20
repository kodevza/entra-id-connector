# SPDX-License-Identifier: CDDL-1.1
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location('identity_config', pathlib.Path(__file__).parents[1] / 'identity_config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
TENANT = '655ccf7b-6f5b-4110-86e3-45c4b8ffc39a'

class IdentityConfigTest(unittest.TestCase):
    def test_preprovisioning_is_a_source_reconciliation_not_login(self):
        mapping = config.build_mapping(TENANT)
        self.assertEqual('system/entra/__ACCOUNT__', mapping['source'])
        self.assertEqual('managed/user', mapping['target'])
        props = {p['target']: p for p in mapping['properties']}
        self.assertIn('entraObjectId', props)
        self.assertEqual(TENANT, props['entraTenantId']['default'])
        self.assertNotIn('password', props)
        self.assertNotIn('authzRoles', props)
        self.assertIn('accountStatus', props)
        self.assertIn('entraOidcSubject', props['userName']['condition']['source'])
        self.assertIn('target.userName', props['userName']['condition']['source'])
        for prop in props.values():
            if 'transform' in prop:
                self.assertEqual('', prop.get('source'), 'Full-object transforms must bind the source root')
        self.assertIn('CREATE', [p['action'] for p in mapping['policies']])
        self.assertIn('entraObjectId', mapping['correlationQuery']['source'])
    def test_schema_merge_preserves_customizations_and_adds_owner(self):
        managed = {'objects':[{'name':'user','schema':{'properties':{'custom':{'type':'string'}},'order':['custom']}},
            {'name':'entraServicePrincipal','schema':{'properties':{},'order':[]}}]}
        config.extend_managed(managed)
        config.extend_managed(managed)
        self.assertIn('custom', managed['objects'][0]['schema']['properties'])
        fields = managed['objects'][0]['schema']['properties']
        self.assertTrue(fields['entraObjectId']['isProtected'])
        for name in ('entraOidcSubject', 'entraOidcClientId', 'entraWorkflowAliases'):
            self.assertTrue(fields[name]['isProtected'])
            self.assertFalse(fields[name]['userEditable'])
        owner = managed['objects'][1]['schema']['properties']['governanceOwner']
        self.assertEqual('managed/user', owner['resourceCollection'][0]['path'])
        self.assertEqual(1, managed['objects'][1]['schema']['order'].count('governanceOwner'))
    def test_existing_request_schema_gains_common_fields_without_losing_custom_fields(self):
        managed = {'objects':[{'name':'user','schema':{'properties':{}}},
            {'name':'entraOwnerRequest','schema':{'properties':{'custom':{'type':'string'}},'order':['custom']}}]}
        config.extend_managed(managed)
        config.extend_managed(managed)
        schema = next(o['schema'] for o in managed['objects'] if o['name']=='entraOwnerRequest')
        self.assertIn('custom', schema['properties'])
        for name in ('subject','source','tenantId','processId','processType','recordType','reviewer'):
            self.assertTrue(schema['properties'][name]['isProtected'])
            self.assertFalse(schema['properties'][name]['userEditable'])
            self.assertEqual(schema['order'].count(name), 1)

    def test_oidc_uses_tenant_specific_native_validation_and_postvalidation_hook(self):
        module = config.build_auth_module(TENANT, 'client', 'secret', '00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000003')
        self.assertEqual('OPENID_CONNECT',module['name'])
        self.assertEqual('00000000-0000-0000-0000-000000000003',module['properties']['entraAdminGroupId'])
        self.assertEqual('00000000-0000-0000-0000-000000000002',module['properties']['entraAccessGroupId'])
        self.assertEqual('authToken',module['properties']['openIdConnectHeader'])
        self.assertIn(TENANT,module['properties']['resolvers'][0]['well-known'])
        self.assertEqual('entra/populateContext.js',module['properties']['augmentSecurityContext']['file'])


class MembershipActionTest(unittest.TestCase):
    def test_membership_action_is_fixed_and_read_only(self):
        action = config.build_membership_action()
        self.assertEqual('isGroupMember', action['scriptId'])
        self.assertEqual('entra', action['actions'][0]['actionType'])
        self.assertEqual('isGroupMember', action['actions'][0]['actionSource'])

if __name__ == '__main__': unittest.main()
