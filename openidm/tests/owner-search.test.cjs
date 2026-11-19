// SPDX-License-Identifier: CDDL-1.1
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'script/ownerLookup.js'), 'utf8');
function lookup(params, options = {}) {
    const calls = [];
    const result = vm.runInNewContext(source, {
        request: {method: options.method || 'read', additionalParameters: params},
        context: {security: {authorization: {roles: options.roles || ['openidm-authorized']}}},
        openidm: {query(resource, query, fields) {
            calls.push({resource, query, fields});
            if (resource === 'managed/entraServicePrincipal' && params.kind === 'owner') {
                return {result: options.principals || [{tenantId: 'tenant-a'}]};
            }
            return {result: [{sourceId: 'external-principal', entraObjectId: 'external-user',
                _id: 'local-record', displayName: '<Example>', mail: 'user@example.test', password: 'secret'}]};
        }}
    });
    return {result, calls};
}
test('lookup returns only external IDs and labels, with bounded results', () => {
    const {result, calls} = lookup({kind: 'principal', q: 'example'});
    assert.deepEqual(Object.keys(result.result[0]).sort(), ['id', 'label']);
    assert.equal(result.result[0].id, 'external-principal');
    assert.equal(calls[0].query._pageSize, 20);
    assert.match(calls[0].query._queryFilter, /displayName co/);
    assert.match(calls[0].query._queryFilter, /appId sw/);
    assert.ok(!calls[0].fields.includes('password'));
});
test('owner is active and synchronized in the selected principal tenant', () => {
    const {calls, result} = lookup({kind: 'owner', q: 'example', principalId: 'app-object-id'});
    assert.equal(calls[0].query._queryFilter, 'sourceId eq "app-object-id"');
    assert.equal(calls[0].query._pageSize, 2);
    assert.match(calls[1].query._queryFilter, /accountStatus eq "active" and entraObjectId pr and entraTenantId eq "tenant-a"/);
    assert.match(calls[1].query._queryFilter, /userName co/);
    assert.match(calls[1].query._queryFilter, /mail co/);
    assert.equal(result.result[0].id, 'external-user');
});
test('owner lookup rejects missing or ambiguous principals', () => {
    for (const principals of [[], [{tenantId:'a'}, {tenantId:'b'}], [{}]]) {
        assert.throws(() => lookup({kind:'owner', q:'test'}, {principals}), e => e.code === 400);
    }
});
test('query and principal ID are escaped as filter literals', () => {
    const injection = '" or true or userName eq "\\';
    const {calls} = lookup({kind:'owner', q: injection, principalId: injection});
    const escaped = injection.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    assert.equal(calls[0].query._queryFilter, 'sourceId eq "' + escaped + '"');
    assert.ok(calls[1].query._queryFilter.includes('userName co "' + escaped + '"'));
});
test('short searches avoid reads and invalid requests are rejected', () => {
    assert.equal(lookup({kind:'principal', q:'x'}).calls.length, 0);
    assert.throws(() => lookup({kind:'other', q:'ab'}), e => e.code === 400);
    assert.throws(() => lookup({kind:'principal', q:'x'.repeat(201)}), e => e.code === 400);
    assert.throws(() => lookup({kind:'principal', q:'ab'}, {roles:[]}), e => e.code === 403);
    assert.throws(() => lookup({kind:'principal', q:'ab'}, {method:'create'}), e => e.code === 405);
});
