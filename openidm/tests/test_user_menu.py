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


class UIAssetVersionTest(unittest.TestCase):
    def test_versions_the_dashboard_template_and_preserves_other_extensions(self):
        index = 'var require = {urlArgs: "v=7.1.2&reporting=abc"};'
        updated = menu.version_ui_assets(index, '123')
        self.assertEqual('var require = {urlArgs: "v=7.1.2&reporting=abc&entraUi=123"};', updated)
        self.assertEqual(updated, menu.version_ui_assets(updated, '123'))
        self.assertEqual(updated.replace('=123', '=456'), menu.version_ui_assets(updated, '456'))


class NavigationTemplateTest(unittest.TestCase):
    def test_reporting_navigation_can_be_upgraded_repeatedly(self):
        stock = '<nav>Stock navigation</nav>\n'
        entra = stock + menu.MARKER + ' profile -->\n<script>profile();</script>\n'
        reporting = ('\n<!-- Governance CSV export -->\n'
                     '<script>require(["org/forgerock/openidm/ui/common/workflow/GovernanceReport"], '
                     'function (install) { install(); });</script>\n')
        self.assertEqual(entra + reporting, menu.merge_navigation(stock + reporting, stock, entra))
        self.assertEqual(entra + reporting, menu.merge_navigation(entra + reporting, stock, entra))
        with self.assertRaises(ValueError):
            menu.merge_navigation('<nav>Custom</nav>' + reporting, stock, entra)

    def test_retired_ownership_link_is_absent(self):
        template = (Path(menu.__file__).parent / 'ui' / menu.NAVIGATION).read_text()
        self.assertNotIn('/entra-ownership.html', template)
