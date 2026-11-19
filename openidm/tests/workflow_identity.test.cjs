// SPDX-License-Identifier: CDDL-1.1
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const tenant = '655ccf7b-6f5b-4110-86e3-45c4b8ffc39a';
const oid = '711939c0-9cbf-47bb-baa0-850d8baa281f';
const legacy = 'entra.' + tenant + '.' + oid;
function fixture(overrides = {}) {
    const user = {_id:'local-id', _rev:'1', userName:legacy, entraTenantId:tenant, entraObjectId:oid, ...overrides};
    const request = {_id:'process', _rev:'1', newOwnerId:user._id, newOwnerUserName:legacy, status:'pending'};
    const task = {_id:'task', _rev:1, assignee:legacy, processDefinitionId:'servicePrincipalOwner:4:208', processInstanceId:'process'};
    const writes = [];
    let collision = false, failTaskOnce = false;
    const api = {
        query(resource, params) {
            if (resource === 'managed/user') return {result: collision ? [{_id:'other'}] : []};
            if (resource === 'managed/entraOwnerRequest') return {result: request.status === 'pending' ? [request] : []};
            if (resource === 'workflow/taskinstance') {
                return {result: task.assignee === params.assignee ? [task] : []};
            }
            throw new Error(resource);
        },
        read(resource) {
            if (resource === 'managed/user/local-id') return user;
            if (resource === 'managed/entraOwnerRequest/process') return request;
            if (resource === 'workflow/taskinstance/task') return task;
            throw new Error(resource);
        },
        patch(resource, rev, patches) {
            const record = this.read(resource);
            assert.equal(rev, record._rev);
            for (const p of patches) record[p.field.slice(1)] = JSON.parse(JSON.stringify(p.value));
            record._rev = String(Number(record._rev) + 1);
            writes.push({resource, patches});
            return record;
        },
        update(resource, rev, data) {
            assert.equal(typeof rev, 'string', 'Script API requires string task revisions');
            if (failTaskOnce) {failTaskOnce = false; throw new Error('Temporary task failure');}
            const record = this.read(resource);
            Object.assign(record, data);
            writes.push({resource, data});
            return record;
        }
    };
    const exports = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../script/entra/workflowIdentity.js'), 'utf8'), {exports, openidm:api, JSON});
    return {user, task, request, writes,
        bind: (subject='native-sub') => exports.bindSubject(user, {tid:tenant,oid,sub:subject,aud:'client'}),
        collide: () => {collision = true;}, fail: () => {failTaskOnce = true;}};
}
test('binds a verified subject and migrates a pending ownership task without changing IDs or completing it', () => {
    const f = fixture();
    f.bind();
    assert.equal(f.user._id, 'local-id');
    assert.equal(f.user.userName, 'native-sub');
    assert.equal(f.user.entraOidcClientId, 'client');
    assert.equal(f.request.newOwnerId, 'local-id');
    assert.equal(f.request.newOwnerUserName, 'native-sub');
    assert.equal(f.request.status, 'pending');
    assert.equal(f.task.assignee, 'native-sub');
    assert.ok(f.user.entraWorkflowAliases.includes(legacy));
});
test('repeated login is idempotent and preserves completed history', () => {
    const f = fixture(); f.request.status = 'accepted'; f.task.assignee = null;
    f.bind(); const count = f.writes.length; f.bind();
    assert.equal(f.writes.length, count);
    assert.equal(f.request.newOwnerUserName, legacy);
});
test('fails before writes when the subject collides with another local login', () => {
    const f = fixture(); f.collide();
    assert.throws(() => f.bind(), e => e.code === 409);
    assert.equal(f.writes.length, 0);
});
test('can retry after a partial task migration', () => {
    const f = fixture(); f.fail();
    assert.throws(() => f.bind(), /Temporary task failure/);
    assert.ok(f.user.entraWorkflowAliases.includes(legacy));
    f.bind();
    assert.equal(f.task.assignee, 'native-sub');
    assert.equal(f.request.newOwnerUserName, 'native-sub');
});
test('a changed login app subject keeps previous aliases for outstanding tasks', () => {
    const f = fixture({userName:'old-sub', entraOidcSubject:'old-sub', entraOidcClientId:'old-client'});
    f.task.assignee = 'old-sub'; f.request.newOwnerUserName = 'old-sub';
    f.bind();
    assert.equal(f.task.assignee, 'native-sub');
    assert.ok(f.user.entraWorkflowAliases.includes('old-sub'));
});
test('does not take over a task whose owner differs from the authoritative request', () => {
    const f = fixture(); f.request.newOwnerId = 'someone-else';
    assert.throws(() => f.bind(), e => e.code === 409);
    assert.equal(f.task.assignee, legacy);
});
