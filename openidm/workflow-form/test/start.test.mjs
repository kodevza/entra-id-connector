// SPDX-License-Identifier: CDDL-1.1
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { setTimeout } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

const archive = fileURLToPath(new URL('../../../target/workflow/servicePrincipalOwner.bar', import.meta.url));
const template = execFileSync('python3', ['-c',
    'import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read("forms/servicePrincipalOwnerStart.html"))',
    archive], { encoding: 'utf8' });
const definitionId = 'servicePrincipalOwner:7:selected';

for (const method of ['manual', 'ownerlens']) {
    test(`the archived start form submits the ${method} nomination from the host form`, async t => {
        const payloads = [];
        const dom = new JSDOM('<form><div id="processContent"></div><input type="submit" name="startProcessButton"></form>',
            { runScripts: 'dangerously', url: 'http://localhost/' });
        t.after(() => dom.window.close());
        const { document, Event } = dom.window;
        const host = document.querySelector('form');
        host.querySelector('#processContent').innerHTML = template.replace('{{_id}}', definitionId);
        dom.window.fetch = async (url, options) => {
            assert.equal(options.credentials, 'same-origin');
            if (url.pathname === '/openidm/endpoint/ownerLookup') {
                if (url.searchParams.get('kind') === 'owner') {
                    assert.equal(url.searchParams.get('principalId'), 'principal-oid');
                    return Response.json({ result: [{ id: 'owner-oid', label: 'Example owner' }] });
                }
                return Response.json({ result: [{ id: 'principal-oid', label: 'Example app' }] });
            }
            assert.equal(url.pathname, '/openidm/workflow/processinstance');
            assert.equal(url.searchParams.get('_action'), 'create');
            assert.equal(options.method, 'POST');
            payloads.push(JSON.parse(options.body));
            return payloads.length === 1 ? Response.json({ message: 'Try again' }, { status: 409 })
                : Response.json({ _id: 'started-instance' });
        };
        dom.window.eval(host.querySelector('script').textContent);
        assert.equal(document.forms.length, 1);
        assert.equal(host.querySelector('input[name="startProcessButton"]').disabled, true);
        function input(selector, value, type = 'input') {
            const element = host.querySelector(selector);
            element.value = value;
            element.dispatchEvent(new Event(type, { bubbles: true }));
        }
        async function find(selector, content) {
            for (let attempt = 0; attempt < 100; attempt++) {
                const match = [...host.querySelectorAll(selector)].find(el => el.textContent.includes(content));
                if (match) return match;
                await setTimeout(10);
            }
            assert.fail(`Missing ${content} in ${host.querySelector('[data-mount]').textContent}`);
        }
        input('input[type=search]', 'Example');
        (await find('button', 'Example app')).click();
        if (method === 'manual') {
            await find('label', 'Proposed owner');
            input('input[type=search]', 'Example');
            (await find('button', 'Example owner')).click();
        } else {
            input('select', 'ownerlens', 'change');
            await find('label', 'OwnerLens evidence JSON');
            input('textarea[rows="6"]', '{"evidence":[]}');
        }
        input('textarea[rows="3"]', '  Ownership request  ');
        const start = await find('button', 'Start request');
        await setTimeout(5);
        start.click();
        await find('[role=alert]', 'Try again');
        start.click();
        await find('[role=status]', 'started-instance');
        const fields = method === 'manual' ? { newOwnerId: 'owner-oid' } : { ownerEvidenceJson: '{"evidence":[]}' };
        assert.deepEqual(payloads, Array(2).fill({
            _processDefinitionId: definitionId, servicePrincipalId: 'principal-oid', reason: 'Ownership request', ...fields
        }));
    });
}
