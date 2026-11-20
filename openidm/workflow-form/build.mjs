// SPDX-License-Identifier: CDDL-1.1
import { build } from 'esbuild';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { execFileSync } from 'node:child_process';
const root = dirname(fileURLToPath(import.meta.url));
const coverage = process.argv.includes('--coverage');
const output = resolve(root, '../../target', coverage ? 'workflow-coverage' : 'workflow');
await mkdir(output, { recursive: true });
async function bundle(entry) {
    const outfile = resolve(output, entry.replace(/\.tsx$/, '.js'));
    const result = await build({ entryPoints: [resolve(root, 'src', entry)], bundle: true, write: false,
        minify: !coverage, outfile, sourcemap: coverage ? 'inline' : false, format: 'iife', target: ['es2020'], jsxFactory: 'h', jsxFragment: 'Fragment', legalComments: 'none' });
    const script = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
    if (coverage) await writeFile(outfile, script);
    return script;
}
const [js, start, reviewStyles, startStyles] = await Promise.all([
    bundle('bar.tsx'), bundle('start-bar.tsx'), readFile(resolve(root, 'src/review.css'), 'utf8'),
    readFile(resolve(root, 'src/start.css'), 'utf8')
]);
await writeFile(resolve(output, 'servicePrincipalOwnerStart.html'), `<div data-entra-owner-start data-definition-id="{{_id}}">
<style>${startStyles}</style>
<div data-mount><p role="status">The ownership form is loading.</p></div>
<script>${start}</script>
</div>
`);
const fields = ['subject', 'source', 'principalLabel', 'ownerLabel', 'grantedAccessJson', 'accessSummary', 'decision', 'ownerEvidenceJson', 'ownerCandidatesJson'];
const html = `<!-- Connector-owned Preact owner review. Deployed with its BPMN in one BAR. -->
<div data-entra-owner-form>
${fields.map(name => `<textarea hidden aria-hidden="true" data-field="${name}">{{variables.${name}}}</textarea>`).join('\n')}
<style>${reviewStyles}</style>
<div data-mount><p role="alert">The ownership form is loading. If it does not appear, reload the page before completing this task.</p></div>
<script>${js}</script>
</div>\n`;
await writeFile(resolve(output, 'servicePrincipalOwner.html'), html);
execFileSync('python3', [resolve(root, 'pack.py'), output], { stdio: 'inherit' });
console.log(`Preact form: ${Buffer.byteLength(html)} bytes (including styles and runtime)`);
