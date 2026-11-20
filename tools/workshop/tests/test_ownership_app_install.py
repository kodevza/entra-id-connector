# SPDX-License-Identifier: CDDL-1.1
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'install_ownership_app.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class OwnershipAppMigrationTest(unittest.TestCase):
    def setUp(self):
        self.app = f'{installer.HOME}/ui/selfservice/extension/{installer.APP}'
        self.files = {self.app: b"legacy app"}
        for ui, backup in (('admin', 1), ('selfservice', 3)):
            root = f'{installer.HOME}/ui/{ui}/'
            self.files[root + 'extension/' + installer.NAV] = (
                installer.LINK + installer.MENU_ANCHOR + '\nreporting registration\n' + installer.WORKFLOW_INSTALL + '\n'
            ).encode()
            self.files[root + 'default/index.html'] = b'urlArgs: "v=original&ownerSearch=abcdef"'
            self.files[root + 'default/' + installer.MODULE + 'StartProcessView.js'] = b'legacy OwnerLookup'
            self.files[root + 'default/' + installer.MODULE + 'OwnerLookup.js'] = b'legacy lookup'
            self.files[root + 'extension/' + installer.EXTENSION + 'install.js'] = b'legacy loader'
            self.files[f'/backup/{backup}-StartProcessView.js'] = b'original module'

    def test_migration_preserves_other_extensions_and_is_repeatable(self):
        changes = installer.plan(self.files.get, '/backup')
        for path, (_, new) in changes.items():
            if new is None:
                del self.files[path]
            else:
                self.files[path] = new
        self.assertFalse(installer.plan(self.files.get))
        self.assertNotIn(self.app, self.files)
        for ui in ('admin', 'selfservice'):
            root = f'{installer.HOME}/ui/{ui}/'
            nav = self.files[root + 'extension/' + installer.NAV]
            self.assertNotIn(b'data-entra-ownership-link', nav)
            self.assertIn(b'reporting registration', nav)
            self.assertNotIn(b'entraWorkflow', nav)
            self.assertEqual(b'urlArgs: "v=original"', self.files[root + 'default/index.html'])

    def test_legacy_overlay_requires_an_original_view(self):
        with self.assertRaisesRegex(ValueError, '--restore-from'):
            installer.plan(self.files.get)
