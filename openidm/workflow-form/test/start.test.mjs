// SPDX-License-Identifier: CDDL-1.1
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout } from 'node:timers/promises';
import { JSDOM } from 'jsdom';
import { readForm, runFormScript } from './archive.mjs';

const template = readForm('servicePrincipalOwnerStart.html');
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
            if (url.pathname === '/openidm/managed/entraServicePrincipal') {
                assert.equal(options.method, 'GET');
                const filter = url.searchParams.get('_queryFilter');
                assert.equal(url.searchParams.get('_pageSize'), filter.startsWith('sourceId eq ') ? '2' : '20');
                if (filter.startsWith('sourceId eq ')) {
                    assert.equal(filter, 'sourceId eq "principal-oid"');
                    assert.equal(url.searchParams.get('_fields'), 'tenantId');
                    return Response.json({ result: [{ tenantId: 'tenant-a' }] });
                }
                assert.match(filter, /displayName co "Example"/);
                assert.match(filter, /sourceId sw "Example"/);
                assert.equal(url.searchParams.get('_fields'), 'sourceId,displayName,appId,tenantId');
                return Response.json({ result: [{ sourceId: 'principal-oid', tenantId: 'tenant-a', displayName: 'Example app' }] });
            }
            if (url.pathname === '/openidm/managed/user') {
                assert.match(url.searchParams.get('_queryFilter'), /accountStatus eq "active" and entraObjectId pr and entraTenantId eq "tenant-a"/);
                assert.match(url.searchParams.get('_queryFilter'), /mail co "Example"/);
                assert.equal(url.searchParams.get('_pageSize'), '20');
                assert.equal(url.searchParams.get('_fields'), 'entraObjectId,displayName,givenName,sn,userName,mail');
                return Response.json({ result: [{ entraObjectId: 'owner-oid', displayName: 'Example owner' }] });
            }
            assert.equal(url.pathname, '/openidm/workflow/processinstance');
            assert.equal(url.searchParams.get('_action'), 'create');
            assert.equal(options.method, 'POST');
            payloads.push(JSON.parse(options.body));
            return payloads.length === 1 ? Response.json({ message: 'Try again' }, { status: 409 })
                : Response.json({ _id: 'started-instance' });
        };
        runFormScript(dom, host, 'start-bar');
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

test('search rejects a denied managed-resource read instead of silently showing no matches', async t => {
    const dom = new JSDOM('<form><div id="processContent"></div><input type="submit" name="startProcessButton"></form>',
        { runScripts: 'dangerously', url: 'http://localhost/' });
    t.after(() => dom.window.close());
    const { document, Event } = dom.window;
    const host = document.querySelector('form');
    host.querySelector('#processContent').innerHTML = template.replace('{{_id}}', definitionId);
    dom.window.fetch = async (url, options) => {
        assert.equal(url.pathname, '/openidm/managed/entraServicePrincipal');
        assert.equal(options.method, 'GET');
        return Response.json({ message: 'Forbidden' }, { status: 403 });
    };
    dom.window.eval(host.querySelector('script').textContent);
    const input = host.querySelector('input[type=search]');
    input.value = 'Example';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    for (let attempt = 0; attempt < 100; attempt++) {
        if (host.querySelector('[role=alert]')?.textContent.includes('Forbidden')) break;
        await setTimeout(10);
    }
    assert.match(host.querySelector('[role=alert]')?.textContent || '', /Forbidden/);
    assert.equal(host.querySelector('input[name=startProcessButton]').disabled, true);
});

test('query values are escaped before inclusion in the managed-resource filter', async t => {
    const dom = new JSDOM('<form><div id="processContent"></div><input type="submit" name="startProcessButton"></form>',
        { runScripts: 'dangerously', url: 'http://localhost/' });
    t.after(() => dom.window.close());
    const { document, Event } = dom.window;
    const host = document.querySelector('form');
    host.querySelector('#processContent').innerHTML = template.replace('{{_id}}', definitionId);
    const injection = '" or true or userName eq "\\';
    let seen = false;
    dom.window.fetch = async (url) => {
        assert.equal(url.pathname, '/openidm/managed/entraServicePrincipal');
        const literal = JSON.stringify(injection);
        assert.equal(url.searchParams.get('_queryFilter'),
            `(displayName co ${literal} or sourceId sw ${literal} or appId sw ${literal}) and sourceId pr and tenantId pr`);
        seen = true;
        return Response.json({ result: [] });
    };
    dom.window.eval(host.querySelector('script').textContent);
    const input = host.querySelector('input[type=search]');
    input.value = injection;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    for (let attempt = 0; attempt < 100 && !seen; attempt++) await setTimeout(10);
    assert.ok(seen);
});
