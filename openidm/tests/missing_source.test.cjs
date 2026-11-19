// SPDX-License-Identifier: CDDL-1.1
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function run(user) {
  const patches=[];
  const result=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../script/entra/missingSource.js'),'utf8'), {
    tenantId:'tenant',recon:{actionParam:{targetId:'local-id'}},
    openidm:{read(p){assert.equal(p,'managed/user/local-id');return user;},patch(...args){patches.push(args);}}
  });
  return {result,patches};
}
test('missing source disables the linked account, preserving owner relationships',()=>{
  const r=run({_rev:'1',entraTenantId:'tenant',entraObjectId:'object',accountStatus:'active'});
  assert.equal(r.result,'IGNORE'); assert.equal(r.patches.length,1);
  assert.equal(r.patches[0][2][0].value,'inactive');
});
test('missing-source policy cannot disable an account from another tenant',()=>{
  assert.throws(()=>run({_rev:'1',entraTenantId:'another',accountStatus:'active'}));
});
