// SPDX-License-Identifier: CDDL-1.1
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const tenant = '655ccf7b-6f5b-4110-86e3-45c4b8ffc39a';
const oid = '711939c0-9cbf-47bb-baa0-850d8baa281f';
function run(overrides = {}, users, access = {}) {
  const user = {_id: 'local-id', _rev:'1', userName: 'entra.' + tenant + '.' + oid,
    entraTenantId: tenant, entraObjectId: oid, accountStatus: 'active', authzRoles: []};
  const claims = {tid: tenant, oid, sub: 'pairwise-sub', aud: 'client',
    iss: 'https://login.microsoftonline.com/' + tenant + '/v2.0', exp: Date.now()/1000 + 300, ...overrides};
  const exports = {};
  const calls = [];
  const openidm = {action(resource, action, content, params) {
    assert.equal(resource, 'system/entra'); assert.equal(action, 'script');
    assert.equal(params.scriptId, 'isGroupMember'); assert.equal(params.scriptExecuteMode, 'resource');
    assert.ok(['00000000-0000-0000-0000-000000000002','00000000-0000-0000-0000-000000000003'].includes(content.groupId)); assert.equal(content.userId, oid);
    if (access.error) throw new Error('Graph unavailable');
    return access.response || {actions:[{result:content.groupId.endsWith('0003') ? access.admin === true : access.member !== false}]};
  },query(collection, query, fields) {
    if (collection === 'managed/user' && query._queryFilter.includes('entraObjectId')) {
      return {result: users === undefined ? [user] : users};
    }
    calls.push({collection, query});
    return {result: []};
  }, patch(resource, rev, patches) { calls.push({resource, patches}); return {}; },
    update(resource, rev, data) { calls.push({resource, data}); return {}; }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../script/entra/identity.js'), 'utf8'), {exports, openidm, Date, JSON, require(name) {
    assert.equal(name, 'entra/workflowIdentity');
    const helper = {};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../script/entra/workflowIdentity.js'), 'utf8'), {exports:helper, openidm, JSON});
    return helper;
  }});
  const security = {authorization: {moduleId: 'OpenIDConnect'}};
  Object.defineProperty(security, 'authenticationId', {get() {return 'pairwise-sub';},
    set() {throw new Error('The OIDC principal must remain unchanged');}});
  const mapped = exports.mapClaims(claims, security,
    {entraTenantId: tenant, entraClientId: 'client', entraAccessGroupId: access.missingGroup ? undefined : '00000000-0000-0000-0000-000000000002', entraAdminGroupId: '00000000-0000-0000-0000-000000000003'});
  mapped.testCalls = calls;
  return mapped;
}
test('first login binds the preprovisioned account without rewriting the native OIDC principal', () => {
  const security = run();
  assert.equal(security.authorization.id, 'local-id');
  assert.equal(security.authorization.component, 'managed/user');
  assert.equal(security.authenticationId, 'pairwise-sub');
  const update = security.testCalls.find(call => call.resource === 'managed/user/local-id');
  assert.ok(update);
  assert.ok(update.patches.some(p => p.field === '/userName' && p.value === 'pairwise-sub'));
  assert.ok(update.patches.some(p => p.field === '/entraOidcSubject' && p.value === 'pairwise-sub'));
  assert.ok(update.patches.some(p => p.field === '/entraOidcClientId' && p.value === 'client'));
  assert.deepEqual(Array.from(security.authorization.roles), ['openidm-authorized']);
});
for (const claims of [{tid: 'other'}, {aud:'other'}, {iss:'https://evil.invalid'}, {exp:0}, {oid:'bad" or true'}, {sub:'another'}]) {
  test('rejects invalid identity ' + JSON.stringify(claims), () => assert.throws(() => run(claims), e => e.code === 401));
}
test('does not create a user on first login', () => assert.throws(() => run({}, []), e => e.code === 401));
test('rejects inactive account', () => assert.throws(() => run({}, [{accountStatus:'inactive'}]), e => e.code === 401));
test('rejects ambiguous identity', () => assert.throws(() => run({}, [{}, {}]), e => e.code === 401));

test('Entra account cannot authenticate using a local password', () => {
  const exports = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../script/entra/identity.js'), 'utf8'), {
    exports, openidm: {read() {return {entraObjectId: oid};}}
  });
  assert.throws(() => exports.rejectLocalAuth({authorization:{id:'local-id', component:'managed/user'}}), e => e.code === 401);
});

test('denies a nonmember even when an active synchronized account exists', () => {
  assert.throws(() => run({}, undefined, {member:false}), e => e.code === 403);
});
test('ignores group claims when the live lookup says nonmember', () => {
  assert.throws(() => run({groups:['00000000-0000-0000-0000-000000000002']}, undefined, {member:false}), e => e.code === 403);
});
test('denies when Graph is unavailable', () => {
  assert.throws(() => run({}, undefined, {error:true}), e => e.code === 503);
});
test('denies malformed or failed connector responses', () => {
  for (const response of [{}, {actions:[]}, {actions:[{error:'forbidden'}]}, {actions:[{result:'true'}]}]) {
    assert.throws(() => run({}, undefined, {response}), e => e.code === 503 || e.code === 403);
  }
});
test('denies when the configured access group is absent', () => {
  assert.throws(() => run({}, undefined, {missingGroup:true}), e => e.code === 503);
});

test('iam-admins grants admin access even without iam membership', () => {
  assert.deepEqual(Array.from(run({},undefined,{admin:true,member:false}).authorization.roles), ['openidm-authorized','openidm-admin']);
});
test('a stale local admin grant does not bypass iam-admins membership', () => {
  const user={_id:'local-id', userName:'entra.' + tenant + '.' + oid,entraTenantId:tenant,entraObjectId:oid,accountStatus:'active',authzRoles:[{_ref:'repo/internal/role/openidm-admin'}]};
  assert.deepEqual(Array.from(run({},[user],{admin:false}).authorization.roles), ['openidm-authorized']);
});
