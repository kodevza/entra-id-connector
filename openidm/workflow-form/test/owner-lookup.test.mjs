// SPDX-License-Identifier: CDDL-1.1
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const source = readFileSync(new URL('../src/owner-lookup.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
}).outputText;

function lookup(queryApi) {
    const module = { exports: {} };
    vm.runInNewContext(compiled, {
        module, exports: module.exports,
        require: name => {
            assert.equal(name, './api');
            return { api: queryApi };
        }
    });
    return module.exports;
}

const signal = new AbortController().signal;

test('principal lookup returns only IDs and labels and requests limited fields', async () => {
    const calls = [];
    const search = lookup(async (path, options) => {
        calls.push({ path, options });
        return { result: [{ sourceId: 'app-oid', displayName: '<Example>', appId: 'client-id',
            tenantId: 'tenant-a', password: 'secret' }, { sourceId: 'bad', tenantId: '' }] };
    });
    const results = await search.searchPrincipals(' Example ', signal);
    assert.equal(JSON.stringify(results), JSON.stringify([{ id: 'app-oid', label: '<Example> — client-id (app-oid)' }]));
    assert.equal(calls[0].path, 'managed/entraServicePrincipal');
    assert.equal(calls[0].options.query._pageSize, 20);
    assert.equal(calls[0].options.query._fields, 'sourceId,displayName,appId,tenantId');
    assert.match(calls[0].options.query._queryFilter, /sourceId sw "Example"/);
    assert.equal(calls[0].options.signal, signal);
});

test('owner search resolves tenant from managed principal and only searches active users in that tenant', async () => {
    const calls = [];
    const search = lookup(async (path, options) => {
        calls.push({path, options});
        return path === 'managed/entraServicePrincipal'
            ? { result: [{ tenantId: 'tenant-a' }] }
            : { result: [{ entraObjectId: 'owner-oid', givenName: 'Test', sn: 'Person', mail: 'person@example.test',
                password: 'secret' }] };
    });
    const result = await search.searchOwners('test', signal, 'app-oid');
    assert.equal(JSON.stringify(result), JSON.stringify([{ id: 'owner-oid',
        label: 'Test Person — person@example.test (owner-oid)' }]));
    assert.equal(calls.length, 2);
    assert.equal(calls[0].options.query._queryFilter, 'sourceId eq "app-oid"');
    assert.equal(calls[0].options.query._pageSize, 2);
    assert.equal(calls[0].options.query._fields, 'tenantId');
    assert.equal(calls[1].path, 'managed/user');
    assert.equal(calls[1].options.query._pageSize, 20);
    assert.equal(calls[1].options.query._fields, 'entraObjectId,displayName,givenName,sn,userName,mail');
    assert.match(calls[1].options.query._queryFilter, /accountStatus eq "active" and entraObjectId pr and entraTenantId eq "tenant-a"/);
    assert.match(calls[1].options.query._queryFilter, /givenName co "test"/);
});

test('ambiguous or missing principals prevent owner lookup', async () => {
    for (const result of [[], [{ tenantId: 'a' }, { tenantId: 'b' }], [{}]]) {
        let calls = 0;
        const search = lookup(async () => { calls++; return { result }; });
        await assert.rejects(search.searchOwners('test', signal, 'app-oid'), /Select a synchronized/);
        assert.equal(calls, 1);
    }
});

test('query-filter literals escape quotes, slashes and control characters', async () => {
    const input = '" or true or userName eq "\\\n';
    const calls = [];
    const search = lookup(async (_, options) => {
        calls.push(options.query._queryFilter);
        return { result: [] };
    });
    await search.searchPrincipals(input, signal);
    const literal = JSON.stringify(input.trim());
    assert.equal(calls[0], `(displayName co ${literal} or sourceId sw ${literal} or appId sw ${literal}) and sourceId pr and tenantId pr`);
    assert.equal(await search.searchPrincipals('a', signal).then(r => r.length), 0);
    assert.equal(calls.length, 1);
    await assert.rejects(search.searchPrincipals('a'.repeat(201), signal), /Search is too long/);
});

test('malformed search responses are rejected rather than treated as empty', async () => {
    const search = lookup(async () => ({ error: 'broken' }));
    await assert.rejects(search.searchPrincipals('some', signal), /Invalid OpenIDM search response/);
});
