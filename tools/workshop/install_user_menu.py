#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Install the Entra navigation and Self-Service dashboard templates as UI extensions.

No API credentials or OpenIDM source checkout are needed. Known legacy display-name
bundle patches are removed; other bundle modules and workflow changes are retained.
"""
import argparse
import datetime
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

HELPER = 'org/forgerock/openidm/ui/common/util/UserDisplayName'
MODEL = 'org/forgerock/openidm/ui/common/UserModel'
MARKER = '<!-- Entra integration extension:'
ASSETS = Path(__file__).resolve().parents[2] / 'openidm/ui'
NAVIGATION = 'templates/common/NavigationTemplate.html'
DASHBOARD = 'templates/workflow/tasks/TasksDashboardTemplate.html'
REPORTING_LOADER = ('\n<!-- Governance CSV export -->\n'
                    '<script>require(["org/forgerock/openidm/ui/common/workflow/GovernanceReport"], '
                    'function (install) { install(); });</script>\n')


def merge_navigation(existing, stock, template):
    if existing is None:
        return template
    base = existing.removesuffix(REPORTING_LOADER)
    if MARKER not in base and (base == existing or base.rstrip() != stock.rstrip()):
        raise ValueError('Existing custom UI navigation template needs manual merge')
    return template + existing[len(base):]



def remove_legacy_patch(bundle):
    """Undo only the previous, unminified named-module patch; fail on other forms."""
    if HELPER not in bundle:
        return bundle
    start = bundle.index('define("' + MODEL + '"')
    following = re.search(r',\s*define\("', bundle[start + 1:])
    if not following:
        raise ValueError('Unknown UserModel module boundary; refusing to modify bundle')
    end = start + 1 + following.start()
    model = bundle[start:end]
    for pattern in (r',\s*"' + re.escape(HELPER) + '"',
                    r',\s*UserDisplayName(?=\s*\))',
                    r'\s*UserDisplayName\.register\(\);'):
        model, count = re.subn(pattern, '', model)
        if count != 1:
            raise ValueError('Unknown legacy UserModel patch; refusing to modify bundle')
    bundle = bundle[:start] + model + bundle[end:]
    start = bundle.index('define("' + HELPER + '"')
    end = bundle.find('\n});', start)
    if end < 0:
        raise ValueError('Unknown legacy helper boundary; refusing to modify bundle')
    bundle = bundle[:start] + bundle[end + len('\n});'):]
    if HELPER in bundle:
        raise ValueError('Unexpected remaining legacy helper reference')
    return bundle


def version_ui_assets(index, version):
    def replace(match):
        args = re.sub(r'&(?:entraDashboard|entraUi)=[^&"\']*', '', match.group(2))
        return match.group(1) + args + '&entraUi=' + version + match.group(3)

    updated, count = re.subn(r'(urlArgs\s*:\s*["\'])([^"\']*)(["\'])', replace, index)
    if count != 1:
        raise ValueError('Expected exactly one RequireJS urlArgs in UI index.html')
    return updated


def install(container='openidm', check=False):
    def docker(*args, **kwargs):
        return subprocess.run(['docker', *args], check=True, **kwargs)
    changes = []
    with tempfile.TemporaryDirectory(prefix='entra-user-menu-') as directory:
        local = Path(directory)
        def read(remote):
            exists = subprocess.run(['docker', 'exec', container, 'test', '-f', remote],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if exists.returncode == 1:
                return None
            exists.check_returncode()
            target = local / 'read'
            docker('cp', container + ':' + remote, str(target), stdout=subprocess.DEVNULL)
            return target.read_text()
        # Validate every change before writing any deployment files.
        for ui in ('admin', 'selfservice'):
            base = '/opt/openidm/ui/' + ui + '/'
            templates = (NAVIGATION, DASHBOARD) if ui == 'selfservice' else (NAVIGATION,)
            for relative in templates:
                extension = base + 'extension/' + relative
                old = read(extension)
                template = (ASSETS / relative).read_text()
                if relative == NAVIGATION and old is not None:
                    template = merge_navigation(old, read(base + 'default/' + relative) or '', template)
                elif old is not None and MARKER not in old:
                    raise ValueError('Existing custom UI template needs manual merge: ' + extension)
                if old != template:
                    changes.append((extension, old, template))
            for relative in ('main.js', NAVIGATION):
                remote = base + 'default/' + relative
                old = read(remote)
                if old is None:
                    raise ValueError('Missing default UI file: ' + remote)
                new = (remove_legacy_patch(old) if relative == 'main.js' else
                       old.replace('{{idmDisplayName user.username}}', '{{user.username}}'))
                if new != old:
                    changes.append((remote, old, new))
            index_path = base + 'extension/index.html'
            previous = read(index_path)
            index = previous if previous is not None else read(base + 'default/index.html')
            if index is None:
                raise ValueError('Missing default UI index.html: ' + base + 'default/index.html')
            version = hashlib.sha256(b'\0'.join((ASSETS / relative).read_bytes() for relative in templates)).hexdigest()[:16]
            updated = version_ui_assets(index, version)
            if updated != previous:
                changes.append((index_path, previous, updated))
        for remote, _, _ in changes:
            print(('Would update: ' if check else 'Updating: ') + remote)
        if check or not changes:
            print('Entra UI extension check complete.' if check else 'Entra UI extensions already installed.')
            return
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = '/opt/openidm/identity-backups/user-menu-' + stamp
        docker('exec', container, 'mkdir', '-p', backup)
        docker('exec', container, 'chmod', '700', backup)
        manifest = []
        for index, (remote, old, new) in enumerate(changes):
            if old is not None:
                target = local / ('backup-' + str(index))
                target.write_text(old)
                docker('cp', str(target), container + ':' + backup + '/' + str(index), stdout=subprocess.DEVNULL)
            manifest.append({'path': remote, 'backup': str(index) if old is not None else None})
        import json
        manifest_path = local / 'manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        docker('cp', str(manifest_path), container + ':' + backup + '/manifest.json', stdout=subprocess.DEVNULL)
        for index, (remote, _, new) in enumerate(changes):
            target = local / ('new-' + str(index))
            target.write_text(new)
            docker('exec', container, 'mkdir', '-p', str(Path(remote).parent))
            docker('cp', str(target), container + ':' + remote, stdout=subprocess.DEVNULL)
        print('Installed Entra UI extensions. Backup: ' + backup)
        print('Hard-refresh both UIs to replace cached templates and bundles.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--check', action='store_true', help='Validate and show changes without writing')
    args = parser.parse_args()
    install(args.container, args.check)
