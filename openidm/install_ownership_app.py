#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Remove the standalone ownership UI and migrate legacy workflow overlays."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess

APP = 'entra-ownership.html'
HOME = '/opt/openidm'
NAV = 'templates/common/NavigationTemplate.html'
MODULE = 'org/forgerock/openidm/ui/common/workflow/processes/'
EXTENSION = 'org/forgerock/openidm/extension/entraWorkflow/'
WORKFLOW_INSTALL = (
    '<!-- Entra workflow extension -->\n'
    '<script>require(["' + EXTENSION + 'install"], function (install) { install(); });</script>'
)
MENU_ANCHOR = '            {{#if userBar.length}}'
LINK = ('            <ul class="nav navbar-nav">\n'
        '                <li><a href="/entra-ownership.html" data-entra-ownership-link>Entra ownership</a></li>\n'
        '            </ul>\n\n')


def update_navigation(nav):
    updated = nav.replace(WORKFLOW_INSTALL + '\n', '').replace(LINK, '')
    updated = re.sub(r'<!-- Entra ownership form layout --><link[^>]*>\n?', '', updated)
    if EXTENSION in updated:
        raise ValueError('Unexpected workflow loader in navigation template')
    if 'data-entra-ownership-link' in updated:
        raise ValueError('Customized Entra ownership link needs manual removal from navigation')
    updated = updated.replace('    "jquery",\n    "org/forgerock/commons/ui/common/main/Configuration"',
                              '    "org/forgerock/commons/ui/common/main/Configuration"')
    old_handler = '], function ($, Configuration) {\n    var user = Configuration.loggedUser;'
    updated = updated.replace(old_handler, '], function (Configuration) {\n    var user = Configuration.loggedUser;')
    updated = updated.replace(
        '    if (label) {\n        // text() treats directory values as plain text, including HTML characters.\n'
        '        $("#mainNavHolder #user_name").text(label);\n    }',
        '    var name = document.querySelector("#mainNavHolder #user_name");\n'
        '    if (name && label) {\n        name.textContent = label;\n    }')
    return updated


def plan(read, restore_from=None):
    changes = {}

    def change(path, new):
        old = read(path)
        if old != new:
            changes[path] = (old, new)

    change(f'{HOME}/ui/selfservice/extension/{APP}', None)
    for index, ui in ((1, 'admin'), (3, 'selfservice')):
        base = f'{HOME}/ui/{ui}/'
        nav = base + 'extension/' + NAV
        original = read(nav)
        if original is None:
            original = read(base + 'default/' + NAV)
        if original is None:
            raise ValueError(f'Missing navigation template for {ui}')
        updated_nav = update_navigation(original.decode()).encode()
        start = base + 'default/' + MODULE + 'StartProcessView.js'
        previous = read(start)
        if previous and b'OwnerLookup' in previous:
            if not restore_from:
                raise ValueError('Supply --restore-from with a pre-OwnerLookup backup directory')
            restored = read(f'{restore_from}/{index}-StartProcessView.js')
            if not restored or b'OwnerLookup' in restored:
                raise ValueError(f'Missing or customized original start view for {ui} in {restore_from}')
            change(start, restored)
        change(base + 'default/' + MODULE + 'OwnerLookup.js', None)
        for layer in ('default', 'extension'):
            index_path = base + layer + '/index.html'
            html = read(index_path)
            if html:
                change(index_path, re.sub(rb'&ownerSearch=[^&"\']*', b'', html))
        assets = ['install.js', 'common/StartProcessView.js', 'common/WorkflowDelegate.js',
                  'common/owner-review-layout.css', 'admin/TaskListView.js', 'admin/TaskInstanceView.js',
                  'admin/ProcessInstanceView.js', 'admin/WorkflowUtils.js']
        for asset in assets:
            change(base + 'extension/' + EXTENSION + asset, None)
        if original and WORKFLOW_INSTALL.encode() in original:
            for template in ('ProcessInstanceViewTemplate.html', 'TaskInstanceViewTemplate.html'):
                change(base + 'extension/templates/admin/workflow/' + template, None)
        if updated_nav != original:
            change(nav, updated_nav)
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--restore-from', help='Container path to the original owner-search installer backup')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()

    def docker(*command, **kwargs):
        return subprocess.run(['docker', *command], check=True, **kwargs)

    def read(path):
        result = subprocess.run(['docker', 'exec', args.container, 'test', '-f', path])
        if result.returncode == 1:
            return None
        result.check_returncode()
        return docker('exec', args.container, 'cat', path, stdout=subprocess.PIPE).stdout

    def write(path, data):
        docker('exec', '-i', args.container, 'sh', '-c',
               'set -e; tmp="$1.entra-new-$$"; cat > "$tmp"; chmod 644 "$tmp"; mv "$tmp" "$1"',
               'install', path, input=data)

    changes = plan(read, args.restore_from)
    if args.check or not changes:
        for path, (_, new) in changes.items():
            print('Would remove' if new is None else 'Would write', path)
        print(f'{len(changes)} ownership UI changes pending.')
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = f'{HOME}/workflow-backups/ownership-app-{stamp}'
    docker('exec', args.container, 'mkdir', '-m', '700', '-p', backup)
    manifest = {}
    for index, (path, (old, _)) in enumerate(changes.items()):
        saved = f'{backup}/{index}' if old is not None else None
        manifest[path] = saved
        if saved:
            docker('exec', args.container, 'cp', '-p', path, saved)
    write(backup + '/manifest.json', json.dumps(manifest, indent=2).encode())
    for path, (_, new) in changes.items():
        if new is None:
            docker('exec', args.container, 'rm', '-f', path)
        else:
            docker('exec', args.container, 'mkdir', '-p', str(Path(path).parent))
            write(path, new)
    print('Removed legacy ownership UI. Backup:', backup)


if __name__ == '__main__':
    main()
