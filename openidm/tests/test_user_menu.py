# SPDX-License-Identifier: CDDL-1.1
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('install_user_menu', Path(__file__).parents[1] / 'install_user_menu.py')
menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(menu)


class LegacyMenuMigrationTest(unittest.TestCase):
    def test_removes_only_known_patch_and_retains_other_modules(self):
        helper = 'define("' + menu.HELPER + '", [], function () {\n    return {};\n});\n'
        original = 'define("' + menu.MODEL + '", ["jquery"], function ($) {\n    var model;\n    return model;\n})'
        patched = original.replace('["jquery"]', '["jquery",\n "' + menu.HELPER + '"]').replace('function ($)', 'function ($, UserDisplayName)').replace('    return model;', '    UserDisplayName.register();\n    return model;')
        suffix = ',define("workflow/untouched", [], function () {return "unchanged";});'
        polyfill = 'function unrelatedPolyfill() {}\n'
        result = menu.remove_legacy_patch(helper + polyfill + patched + suffix)
        self.assertEqual('\n' + polyfill + original + suffix, result)
        self.assertEqual(result, menu.remove_legacy_patch(result))

    def test_unrecognized_patch_fails_without_guessing(self):
        with self.assertRaises(ValueError):
            menu.remove_legacy_patch('define("' + menu.MODEL + '", ["' + menu.HELPER + '"],function(){}),define("other",[],function(){});')

    def test_stock_bundle_is_unchanged(self):
        self.assertEqual('stock', menu.remove_legacy_patch('stock'))
