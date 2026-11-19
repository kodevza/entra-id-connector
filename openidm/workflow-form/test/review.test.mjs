// SPDX-License-Identifier: CDDL-1.1
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
const archive = fileURLToPath(new URL('../../../target/workflow/servicePrincipalOwner.bar', import.meta.url));
const template = execFileSync('python3', ['-c',
    'import sys, zipfile; sys.stdout.buffer.write(zipfile.ZipFile(sys.argv[1]).read("forms/servicePrincipalOwner.html"))',
    archive], { encoding: 'utf8' });
const snapshot = {
    collectedAt: '2026-11-18T12:00:00Z', coverage: 'Direct Entra grants', permissions: [
        { kind: 'application', grantId: '1', resourceName: 'Microsoft Graph', permission: 'User.Read.All', description: 'Read users' },
        { kind: 'delegated', grantId: '2', resourceName: 'Microsoft Graph', permission: 'Mail.Read', consentType: 'Principal', principalId: 'user-id' },
        { kind: 'directoryRole', grantId: '3', permission: 'Directory Readers', directoryScopeId: '/' }
    ]
};
function mount(overrides = {}) {
    const variables = { subject: 'principal-id', principalLabel: 'Example app', ownerLabel: 'Example Owner', source: 'entra',
        grantedAccessJson: JSON.stringify(snapshot), ...overrides };
    const escaped = value => String(value ?? '').replace(/[&<>]/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;'
    })[character]);
    const html = template.replace(/{{variables\.(\w+)}}/g, (_, field) => escaped(variables[field]));
    const dom = new JSDOM('<!DOCTYPE html><form id="host"></form>', { runScripts: 'dangerously', url: 'http://localhost/' });
    dom.window.document.getElementById('host').innerHTML = html;
    for (const script of dom.window.document.querySelectorAll('script')) dom.window.eval(script.textContent);
    return dom;
}
const tick = () => new Promise(resolve => setTimeout(resolve, 5));

test('the BAR form mounts from escaped task variables', () => {
    const dom = mount();
    const doc = dom.window.document;
    assert.equal(doc.querySelectorAll('tbody tr').length, 3);
    assert.doesNotMatch(doc.querySelector('[data-mount]').textContent, /form is loading/);
    assert.match(doc.body.textContent, /Example app/);
    assert.match(doc.body.textContent, /User.Read.All/);
    assert.match(doc.body.textContent, /User: user-id/);
    assert.match(doc.body.textContent, /Scope: \//);
    assert.equal(doc.querySelector('select[name="decision"]').value, '');
    dom.window.close();
});

test('filters the grant list, reports no matches, and submits only a deliberate decision', async () => {
    const dom = mount();
    const doc = dom.window.document;
    const input = doc.querySelector('input[type="search"]');
    input.value = 'mail'; input.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    await tick();
    assert.equal(doc.querySelectorAll('tbody tr').length, 1);
    assert.match(doc.querySelector('tbody').textContent, /Mail.Read/);
    const kind = doc.querySelector('[id$="-kind"]');
    kind.value = 'application';
    kind.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    await tick();
    assert.match(doc.body.textContent, /No permissions match/);
    kind.value = 'all';
    kind.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    input.value = 'no match'; input.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    await tick();
    assert.match(doc.body.textContent, /No permissions match/);
    const decision = doc.querySelector('select[name="decision"]');
    assert.equal(decision.required, true);
    decision.value = 'reject'; decision.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    await tick();
    assert.match(doc.querySelector('.eor-decision').textContent, /will block the service principal/);
    assert.equal(decision.value, 'reject');
    assert.deepEqual([...doc.querySelectorAll('[name]')].map(element => element.name), ['decision']);
    dom.window.close();
});

test('distinguishes missing, malformed and successfully collected empty permission snapshots', () => {
    for (const [value, message] of [['', 'have not been collected'], ['bad json', 'could not be read'],
        [JSON.stringify({ permissions: [] }), 'No direct Entra grants']]) {
        const dom = mount({ grantedAccessJson: value });
        assert.match(dom.window.document.querySelector('.entra-owner-review').textContent, new RegExp(message));
        dom.window.close();
    }
});

test('directory values stay text across both HTML and Preact boundaries', () => {
    const attack = '</textarea><img src=x onerror="window.pwned=true"><script>window.pwned=true</script>';
    const dom = mount({ principalLabel: attack, grantedAccessJson: JSON.stringify({ permissions: [{ kind: 'application', permission: attack, description: attack }] }) });
    assert.equal(dom.window.pwned, undefined);
    assert.equal(dom.window.document.querySelectorAll('img').length, 0);
    assert.match(dom.window.document.querySelector('.entra-owner-review').textContent, /<img src=x/);
    dom.window.close();
});

test('shows OwnerLens evidence and submits a forward decision for an unreviewed candidate', async () => {
    const evidence = '</textarea><img src=x onerror="window.pwned=true">';
    const dom = mount({
        ownerEvidenceJson: JSON.stringify([
            { candidate: 'Second owner', signal: 'RBAC', evidenceSource: '/subscriptions/sub-123/resourceGroups/test',
                evidenceValue: 'Reader', reason: evidence },
            { candidate: 'Third owner', signal: 'RBAC', evidenceId: '/subscriptions/sub-123', evidenceValue: 'Contributor' },
            { candidate: 'Second owner', signal: 'Activity', evidenceId: '/subscriptions/sub-456', evidenceValue: 'Read logs' },
            { candidate: 'Fourth owner', signal: 'RBAC', evidenceId: '/subscriptions/sub-456', evidenceValue: 'Reader' }
        ]),
        ownerCandidatesJson: JSON.stringify([
            { objectId: 'current-id', label: 'Current owner', confidence: 'HIGH', state: 'current' },
            { objectId: 'second-id', label: 'Second owner', confidence: 'MED', state: 'available' },
            { objectId: 'reviewed-id', label: 'Previous owner', confidence: 'LOW', state: 'reviewed' }
        ])
    });
    const doc = dom.window.document;
    const suggestions = doc.querySelector('[aria-label="OwnerLens suggestions"]');
    assert.equal(suggestions.querySelectorAll('table').length, 1);
    assert.match(suggestions.textContent, /Already reviewed/);
    const [requestTab, evidenceTab] = doc.querySelectorAll('[role="tab"]');
    const requestPanel = doc.getElementById(requestTab.getAttribute('aria-controls'));
    const evidencePanel = doc.getElementById(evidenceTab.getAttribute('aria-controls'));
    assert.equal(requestPanel.hidden, false);
    assert.equal(evidencePanel.hidden, true);
    assert.ok(!requestPanel.textContent.includes(evidence));

    requestTab.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    await tick();
    assert.equal(doc.activeElement, evidenceTab);
    assert.equal(evidenceTab.getAttribute('aria-selected'), 'true');
    assert.equal(requestPanel.hidden, true);
    assert.equal(evidencePanel.hidden, false);
    assert.ok(evidencePanel.textContent.includes(evidence));
    assert.deepEqual([...evidencePanel.querySelectorAll('tbody tr:first-child td')].slice(2, 4)
        .map(cell => cell.textContent), ['sub-123', 'Reader']);

    const [search, subscription, role] = evidencePanel.querySelectorAll('input');
    for (const [input, value] of [[subscription, 'SUB-123'], [role, 'reader']]) {
        input.value = value;
        input.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    }
    await tick();
    assert.equal(evidencePanel.querySelectorAll('tbody tr').length, 1);
    search.value = 'not found';
    search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    await tick();
    assert.match(evidencePanel.textContent, /No evidence matches/);
    requestTab.click();
    await tick();
    evidenceTab.click();
    await tick();
    assert.equal(search.value, 'not found');
    assert.equal(doc.querySelector('img'), null);
    const decision = doc.querySelector('[name="decision"]');
    assert.equal(decision.querySelector('[value="reject"]').textContent, 'Decline ownership');
    decision.value = 'forward';
    decision.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    await tick();
    const target = doc.querySelector('[name="forwardOwnerObjectId"]');
    assert.equal(target.required, true);
    assert.deepEqual([...target.options].map(option => option.value), ['', 'second-id']);
    target.value = 'second-id';
    assert.deepEqual(Object.fromEntries(new dom.window.FormData(doc.getElementById('host'))), {
        decision: 'forward', forwardOwnerObjectId: 'second-id'
    });
    decision.value = 'reject';
    decision.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    await tick();
    assert.equal(doc.querySelector('[name="forwardOwnerObjectId"]'), null);
    assert.deepEqual(Object.fromEntries(new dom.window.FormData(doc.getElementById('host'))), {
        decision: 'reject'
    });
    assert.match(doc.querySelector('.eor-decision').textContent, /next eligible candidate/);
    dom.window.close();
});
