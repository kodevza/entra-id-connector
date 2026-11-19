#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Install the read-only ownership form search endpoint, with backups."""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8081/openidm')
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--home', default='/opt/openidm')
    parser.add_argument('--username', default='openidm-admin')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    password = os.environ.get('OPENIDM_PASSWORD') or getpass.getpass('OpenIDM admin password: ')
    headers = {'X-OpenIDM-Username': args.username, 'X-OpenIDM-Password': password, 'Content-Type': 'application/json'}

    def api(path, data=None):
        req = urllib.request.Request(args.url.rstrip('/') + '/' + path, headers=headers,
            data=json.dumps(data).encode() if data is not None else None, method='PUT' if data is not None else 'GET')
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def docker(*command):
        return subprocess.check_output(['docker', *command])

    access_path = args.home + '/script/access.js'
    access = docker('exec', args.container, 'cat', access_path).decode()
    if 'httpAccessConfig' not in access:
        raise ValueError('Unsupported access.js: expected httpAccessConfig')
    api('config/process/access')
    try:
        old_endpoint = api('config/endpoint/ownerLookup')
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        old_endpoint = None
    if args.check:
        print('Owner search prerequisites OK. Endpoint installed:', old_endpoint is not None)
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = args.home + '/workflow-backups/owner-search-' + stamp
    docker('exec', args.container, 'mkdir', '-p', backup)
    docker('exec', args.container, 'chmod', '700', backup)
    docker('exec', args.container, 'cp', access_path, backup + '/access.js')
    subprocess.run(['docker', 'exec', '-i', args.container, 'sh', '-c', 'umask 077; cat > "$1"',
                    'backup', backup + '/endpoint-ownerLookup.json'], input=json.dumps(old_endpoint).encode(), check=True)
    target = args.home + '/script/workflow/ownerLookup.js'
    if subprocess.run(['docker', 'exec', args.container, 'test', '-f', target]).returncode == 0:
        docker('exec', args.container, 'cp', target, backup + '/ownerLookup.js')
    docker('exec', args.container, 'mkdir', '-p', str(Path(target).parent))
    docker('cp', str(ROOT / 'script/ownerLookup.js'), args.container + ':' + target)
    marker = '// Governance ownership form lookup'
    if marker not in access:
        access += '\n' + marker + '\nhttpAccessConfig.configs.push(' + json.dumps({
            'pattern': 'endpoint/ownerLookup', 'roles': 'openidm-authorized,openidm-admin',
            'methods': 'read', 'actions': '*'}) + ');\n'
        subprocess.run(['docker', 'exec', '-i', args.container, 'sh', '-c', 'cat > "$1"', 'access', access_path],
                       input=access.encode(), check=True)
    api('config/endpoint/ownerLookup', {'type': 'text/javascript', 'file': 'workflow/ownerLookup.js'})
    print('Installed owner search. Backup:', backup)


if __name__ == '__main__':
    main()
