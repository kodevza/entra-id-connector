# SPDX-License-Identifier: CDDL-1.1
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from install_permissions import merge


class PermissionsInstallTest(unittest.TestCase):
    def test_merges_existing_configuration_and_is_idempotent(self):
        managed = json.loads((ROOT / 'managed-entra.example.json').read_text())
        managed['objects'].append(json.loads((ROOT / 'workflow/managed.json').read_text())['requestObject'])
        principal = next(o for o in managed['objects'] if o['name'] == 'entraServicePrincipal')
        principal['schema']['properties']['governanceOwner'] = {'type':'relationship', 'resourceCollection':[{'path':'managed/user'}]}
        principal['schema']['properties'].pop('grantedAccessJson')
        principal['schema']['order'].remove('grantedAccessJson')
        configs = {'managed': managed,
                   'sync': json.loads((ROOT / 'sync-entra.example.json').read_text()),
                   'provisioner.openicf/entra': json.loads((ROOT / 'provisioner.openicf-entra.example.json').read_text())}
        configs['provisioner.openicf/entra']['configurationProperties']['customSetting'] = 'keep'
        original = copy.deepcopy(configs)
        result = merge(configs)
        self.assertEqual(original, configs)
        self.assertEqual(result, merge(result))
        self.assertEqual('keep', result['provisioner.openicf/entra']['configurationProperties']['customSetting'])
        principal = next(o for o in result['managed']['objects'] if o['name'] == 'entraServicePrincipal')
        self.assertIn('grantedAccessJson', principal['schema']['properties'])
        self.assertEqual(['relationship','null'], principal['schema']['properties']['governanceOwner']['type'])
        self.assertEqual([{'path':'managed/user'}], principal['schema']['properties']['governanceOwner']['resourceCollection'])
        self.assertIn('nativeType', result['provisioner.openicf/entra']['objectTypes']['servicePrincipal']['properties']['grantedAccessJson'])


if __name__ == '__main__':
    unittest.main()
