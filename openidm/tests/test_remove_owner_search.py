# SPDX-License-Identifier: CDDL-1.1
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remove_owner_search import MARKER, without_legacy_rule


class RetireOwnerSearchTests(unittest.TestCase):
    def test_removes_only_installed_rule(self):
        other = "httpAccessConfig.configs.push({\"pattern\": \"managed/user\"});\n"
        rule = (MARKER + '\nhttpAccessConfig.configs.push(' +
                '{"pattern": "endpoint/ownerLookup", "roles": "openidm-authorized,openidm-admin", '
                '"methods": "read", "actions": "*"});\n')
        updated, changed = without_legacy_rule(other + '\n' + rule + 'console.log(1);\n')
        self.assertTrue(changed)
        self.assertEqual(other + 'console.log(1);\n', updated)
        self.assertEqual((updated, False), without_legacy_rule(updated))

    def test_unknown_rule_is_not_removed(self):
        with self.assertRaises(ValueError):
            without_legacy_rule(MARKER + '\nhttpAccessConfig.configs.push({"pattern":"*"});\n')
        with self.assertRaises(ValueError):
            without_legacy_rule(MARKER + '\n// another implementation\n')


if __name__ == '__main__':
    unittest.main()
