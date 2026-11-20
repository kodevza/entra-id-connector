#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Retire the legacy ownerLookup endpoint after deploying the direct-query Preact form.

Default is a read-only check. --apply backs up changes before removing the endpoint,
its deployed script and the exact access.js rule created by install_owner_search.py.
"""
import argparse
import datetime
import getpass
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

MARKER = '// Governance ownership form lookup'
RULE = re.compile(r'\n?' + re.escape(MARKER) + r'\r?\nhttpAccessConfig\.configs\.push\((\{[^\r\n]*\})\);\r?\n?')
EXPECTED_RULE = {'pattern': 'endpoint/ownerLookup', 'roles': 'openidm-authorized,openidm-admin',
                 'methods': 'read', 'actions': '*'}


def without_legacy_rule(source):
    matches = list(RULE.finditer(source))
    if not matches:
        if MARKER in source:
            raise ValueError('Customized legacy access rule: review access.js manually')
        return source, False
    if len(matches) != 1 or json.loads(matches[0].group(1)) != EXPECTED_RULE:
        raise ValueError('Unexpected legacy access rule: review access.js manually')
    return source[:matches[0].start()] + source[matches[0].end():], True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8081/openidm')
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--home', default='/opt/openidm')
    parser.add_argument('--username', default='openidm-admin')
    parser.add_argument('--check', action='store_true', help='Inspect only (default)')
    parser.add_argument('--apply', action='store_true', help='Remove the legacy endpoint after backup')
    args = parser.parse_args()
    if args.check and args.apply:
        parser.error('Use either --check or --apply')
    password = os.environ.get('OPENIDM_PASSWORD') or getpass.getpass('OpenIDM admin password: ')
    headers = {'X-OpenIDM-Username': args.username, 'X-OpenIDM-Password': password,
               'Content-Type': 'application/json'}

    def api(path, method='GET'):
        req = urllib.request.Request(args.url.rstrip('/') + '/' + path, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()
                return json.loads(content) if content else None
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def docker(*command, input=None):
        return subprocess.run(['docker', *command], check=True, input=input,
                              stdout=subprocess.PIPE).stdout

    endpoint = api('config/endpoint/ownerLookup')
    if endpoint is not None and (endpoint.get('file') != 'workflow/ownerLookup.js' or
                                 endpoint.get('type') != 'text/javascript'):
        raise ValueError('Unexpected endpoint definition: refusing to remove customized endpoint')
    access_path = args.home + '/script/access.js'
    source = docker('exec', args.container, 'cat', access_path).decode()
    updated, has_rule = without_legacy_rule(source)
    script = args.home + '/script/workflow/ownerLookup.js'
    has_script = subprocess.run(['docker', 'exec', args.container, 'test', '-f', script],
                                stdout=subprocess.DEVNULL).returncode == 0
    print(f'Legacy endpoint: {endpoint is not None}; access rule: {has_rule}; script: {has_script}')
    if not args.apply or not (endpoint is not None or has_rule or has_script):
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = args.home + '/workflow-backups/owner-search-retired-' + stamp
    docker('exec', args.container, 'mkdir', '-p', backup)
    docker('exec', args.container, 'chmod', '700', backup)
    docker('exec', args.container, 'cp', access_path, backup + '/access.js')
    if endpoint is not None:
        docker('exec', '-i', args.container, 'sh', '-c', 'umask 077; cat > "$1"',
               'backup', backup + '/endpoint-ownerLookup.json', input=json.dumps(endpoint).encode())
    if has_script:
        docker('exec', args.container, 'cp', script, backup + '/ownerLookup.js')
    if endpoint is not None:
        api('config/endpoint/ownerLookup', method='DELETE')
    if has_rule:
        docker('exec', '-i', args.container, 'sh', '-c',
               'set -e; temp="$1.owner-new-$$"; cat > "$temp"; chmod 644 "$temp"; mv "$temp" "$1"',
               'edit', access_path, input=updated.encode())
    if has_script:
        docker('exec', args.container, 'rm', '-f', script)
    print('Legacy owner lookup removed. Backup:', backup)
    print('If OpenIDM caches access.js, restart OpenIDM before testing the access rules.')


if __name__ == '__main__':
    main()
