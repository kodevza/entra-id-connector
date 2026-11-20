// SPDX-License-Identifier: CDDL-1.1
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Script } from 'node:vm';

const directory = process.env.WORKFLOW_TEST_COVERAGE === '1' ? 'workflow-coverage' : 'workflow';
const output = new URL(`../../../target/${directory}/`, import.meta.url);

export function readForm(name) {
    const archive = fileURLToPath(new URL('servicePrincipalOwner.bar', output));
    return execFileSync('python3', ['-c',
        'import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]))',
        archive, `forms/${name}`], { encoding: 'utf8' });
}

export function runFormScript(dom, host, entry) {
    // V8 uses this filename to find the source map for the script extracted from the BAR.
    const filename = fileURLToPath(new URL(`${entry}.js`, output));
    const script = new Script(host.querySelector('script').textContent, { filename });
    script.runInContext(dom.getInternalVMContext());
}
