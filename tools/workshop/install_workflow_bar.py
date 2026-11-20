#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Deploy the BPMN and bundled start and review forms together as one Activiti BAR."""
import argparse
import datetime
import getpass
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'target/workflow/servicePrincipalOwner.bar'
KEY = 'servicePrincipalOwner'


def validate_archive(archive):
    with zipfile.ZipFile(archive) as bar:
        if bar.read(KEY + '.bpmn20.xml') != (ROOT / 'openidm/workflow' / (KEY + '.bpmn20.xml')).read_bytes():
            raise ValueError('BAR is stale: rebuild with npm run build in openidm/workflow-form')
        form = bar.read('forms/servicePrincipalOwner.html').decode()
        if 'data-entra-owner-form' not in form or '{{variables.grantedAccessJson}}' not in form:
            raise ValueError('BAR does not contain the expected Preact review form')
        start = bar.read('forms/servicePrincipalOwnerStart.html').decode()
        if 'data-entra-owner-start' not in start or '{{_id}}' not in start:
            raise ValueError('BAR does not contain the expected ownership start form')
    return start, form


def install_bar(api, container='openidm', archive=ARCHIVE, check=False):
    archive = Path(archive)
    start, form = validate_archive(archive)
    workflow = api('config/workflow')
    if workflow.get('workflowDirectory') not in ('/opt/openidm/workflow', '&{launcher.project.location}/workflow'):
        raise ValueError('Custom workflow directory requires manual BAR installation')
    target = '/opt/openidm/workflow/' + KEY + '.bar'
    old = subprocess.run(['docker', 'exec', container, 'cat', target], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if old.returncode not in (0, 1):
        old.check_returncode()
    changed = old.returncode != 0 or old.stdout != archive.read_bytes()
    definitions = api('workflow/processdefinition?_queryId=filtered-query')['result']
    latest = max((d['version'] for d in definitions if d['key'] == KEY), default=0)
    print('BAR needs update:', changed)
    if check:
        return latest
    if changed:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = '/opt/openidm/workflow-backups/bar-' + stamp
        subprocess.check_call(['docker', 'exec', container, 'mkdir', '-m', '700', '-p', backup])
        if old.returncode == 0:
            subprocess.check_call(['docker', 'exec', container, 'cp', target, backup + '/' + KEY + '.bar'])
        # Keep legacy XML untouched: removing a watched deployment can affect
        # historical definitions/instances. All new installs use this BAR.
        subprocess.check_call(['docker', 'cp', str(archive), container + ':' + target])
        api('config/workflow', workflow, 'PUT')
        print('Backup:', backup)
    for _ in range(45):
        try:
            definitions = api('workflow/processdefinition?_queryId=filtered-query')['result']
            candidates = [d for d in definitions if d['key'] == KEY]
            current = max(candidates, key=lambda d: d['version']) if candidates else None
            if current and (not changed or current['version'] > latest):
                path = 'workflow/processdefinition/' + current['_id']
                definition = api(path)
                task = api(path + '/taskdefinition/acceptOwnership')
                if definition.get('formGenerationTemplate') == start and task.get('formGenerationTemplate') == form:
                    print('Installed BAR workflow version:', current['version'])
                    return current['version']
        except urllib.error.HTTPError as error:
            # Reconfiguring workflow temporarily unregisters the REST resources.
            if error.code not in (404, 503):
                raise
        time.sleep(1)
    raise RuntimeError('The latest workflow did not load the BAR form; inspect OpenIDM logs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8081/openidm')
    parser.add_argument('--container', default='openidm')
    parser.add_argument('--username', default='openidm-admin')
    parser.add_argument('--archive', type=Path, default=ARCHIVE)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    password = os.environ.get('OPENIDM_PASSWORD') or getpass.getpass('OpenIDM admin password: ')
    headers = {'X-OpenIDM-Username': args.username, 'X-OpenIDM-Password': password, 'Content-Type': 'application/json'}

    def api(path, data=None, method=None):
        req = urllib.request.Request(args.url.rstrip('/') + '/' + path, headers=headers, method=method,
            data=json.dumps(data).encode() if data is not None else None)
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    install_bar(api, args.container, args.archive, args.check)


if __name__ == '__main__':
    main()
