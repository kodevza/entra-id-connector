#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Upgrade the default embedded H2 Activiti schema in a stopped OpenIDM container."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

HOME = '/opt/openidm'
DATABASE = f'{HOME}/db/activiti/database'
MIGRATION = Path(__file__).resolve().parents[2] / 'openidm/workflow/widen-h2-variable-text.sql'

RUN_MIGRATION = r'''
set -eu
if [ ! -f "$1.mv.db" ]; then
    echo "Embedded Activiti H2 database missing from mounted storage: $1.mv.db" >&2
    exit 1
fi
set -- "$@" /opt/openidm/bundle/com.h2database.h2-*.jar
if [ "$#" -ne 2 ] || [ ! -f "$2" ]; then
    echo "Expected exactly one OpenIDM H2 bundle in /opt/openidm/bundle" >&2
    exit 1
fi
umask 077
exec java -cp "$2" org.h2.tools.RunScript -url "jdbc:h2:file:$1;IFEXISTS=TRUE" \
    -user sa -script /dev/stdin
'''


def install_storage(container):
    inspection = json.loads(subprocess.check_output(['docker', 'container', 'inspect', container]))[0]
    if inspection['State']['Status'] not in ('created', 'exited'):
        raise ValueError(f'Stop {container} before migrating its embedded H2 workflow database')
    if not any(
        mount['RW'] and (
            DATABASE == mount['Destination'].rstrip('/')
            or DATABASE.startswith(mount['Destination'].rstrip('/') + '/')
        )
        for mount in inspection['Mounts']
    ):
        raise ValueError('The embedded H2 workflow database must be on writable mounted storage')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = f'{DATABASE}-before-entra-{stamp}.zip'
    sql = f"BACKUP TO '{backup}';\n" + MIGRATION.read_text()
    print(f'H2 backup path: {backup}', flush=True)
    command = [
        'docker', 'run', '--rm', '-i', '--network', 'none',
        '--volumes-from', inspection['Id'], '--entrypoint', 'sh',
    ]
    if inspection['Config']['User']:
        command.extend(['--user', inspection['Config']['User']])
    subprocess.run(
        [*command, inspection['Image'], '-c', RUN_MIGRATION, 'migrate', DATABASE],
        input=sql, text=True, check=True,
    )
    print('Embedded H2 workflow text columns upgraded.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='openidm')
    args = parser.parse_args()
    try:
        install_storage(args.container)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
