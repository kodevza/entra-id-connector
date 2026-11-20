#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Merge service-principal permission inventory and deploy the owner review form.

Install the rebuilt connector JAR and restart OpenIDM before running this script.
Existing process instances retain their original form and historical snapshot.
"""
import argparse
import copy
import datetime
import getpass
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from install_workflow_bar import install_bar, validate_archive, ARCHIVE

ROOT = Path(__file__).resolve().parents[2] / 'openidm'


def merge(configs):
    result = copy.deepcopy(configs)
    example = json.loads((ROOT / 'provisioner.openicf-entra.example.json').read_text())
    result['provisioner.openicf/entra']['objectTypes']['servicePrincipal']['properties']['grantedAccessJson'] = example['objectTypes']['servicePrincipal']['properties']['grantedAccessJson']
    principal = next(o for o in result['managed']['objects'] if o['name'] == 'entraServicePrincipal')['schema']
    schema = next(o for o in json.loads((ROOT / 'managed-entra.example.json').read_text())['objects'] if o['name'] == 'entraServicePrincipal')['schema']
    owner = principal['properties'].get('governanceOwner', {})
    if owner.get('type') == 'relationship':
        owner['type'] = ['relationship', 'null']
    principal['properties'].setdefault('grantedAccessJson', schema['properties']['grantedAccessJson'])
    if 'grantedAccessJson' not in principal.setdefault('order', []):
        principal['order'].append('grantedAccessJson')
    request = next(o for o in result['managed']['objects'] if o['name'] == 'entraOwnerRequest')['schema']
    asset = json.loads((ROOT / 'workflow/managed.json').read_text())['requestObject']['schema']
    for name in ('grantedAccessJson', 'accessSummary', 'ownerEvidenceJson',
                 'ownerCandidatesJson', 'ownerReviewHistoryJson'):
        request['properties'].setdefault(name, asset['properties'][name])
        if name not in request.setdefault('order', []):
            request['order'].append(name)
    mappings = [m for m in result['sync']['mappings'] if m['source'] == 'system/entra/servicePrincipal' and m['target'] == 'managed/entraServicePrincipal']
    if len(mappings) != 1:
        raise ValueError('Expected exactly one service-principal inventory mapping')
    mapping = mappings[0]
    if not any(p['target'] == 'grantedAccessJson' for p in mapping['properties']):
        mapping['properties'].append({'source': 'grantedAccessJson', 'target': 'grantedAccessJson'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8081/openidm')
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--username', default='openidm-admin')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    password = os.environ.get('OPENIDM_PASSWORD') or getpass.getpass('OpenIDM admin password: ')
    headers = {'X-OpenIDM-Username': args.username, 'X-OpenIDM-Password': password, 'Content-Type': 'application/json'}

    def api(path, data=None, method=None):
        req = urllib.request.Request(args.url.rstrip('/') + '/' + path, headers=headers,
            data=json.dumps(data).encode() if data is not None else None,
            method=method or ('PUT' if data is not None else 'GET'))
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)

    def docker(*command):
        return subprocess.check_output(['docker', *command])

    configs = {name: api('config/' + name) for name in ('managed', 'sync', 'provisioner.openicf/entra')}
    merged = merge(configs)
    validate_archive(ARCHIVE)
    changed = [name for name in configs if configs[name] != merged[name]]
    print('Configurations to update:', ', '.join(changed) or 'none')
    if args.check:
        install_bar(api, args.container, check=True)
        return
    backup = '/opt/openidm/identity-backups/permissions-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    docker('exec', args.container, 'mkdir', '-m', '700', '-p', backup)
    for name in configs:
        filename = name.replace('/', '-') + '.json'
        subprocess.run(['docker', 'exec', '-i', args.container, 'sh', '-c', 'umask 077; cat > "$1"', 'backup', backup + '/' + filename], input=json.dumps(configs[name]).encode(), check=True)
    for name in changed:
        api('config/' + name, merged[name])
    install_bar(api, args.container)
    print('Backup:', backup)
    print('Reconcile service principals before starting new ownership requests.')


if __name__ == '__main__':
    main()
