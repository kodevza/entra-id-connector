// SPDX-License-Identifier: CDDL-1.1
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const template = fs.readFileSync(path.join(__dirname, '../ui/templates/common/NavigationTemplate.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
function render(attributes, original = 'technical-login') {
    let text = original;
    const initial = attributes && {...attributes};
    vm.runInNewContext(script, {
        document: {querySelector(selector) {
            assert.equal(selector, '#mainNavHolder #user_name');
            return {set textContent(value) { text = value; }};
        }},
        require(deps, callback) {
            assert.deepEqual(Array.from(deps), ['org/forgerock/commons/ui/common/main/Configuration']);
            callback({loggedUser: attributes ? {get(key) { return attributes[key]; }} : null});
        }
    });
    assert.deepEqual(attributes, initial);
    return text;
}
test('menu displays profile name while retaining the authentication identifier', () => {
    assert.equal(render({displayName: ' Konrad Zawadka ', userName: 'immutable-sub'}), 'Konrad Zawadka');
    assert.equal(render({givenName: 'Ada', sn: 'Lovelace'}), 'Ada Lovelace');
    assert.equal(render({givenName: ' Ada ', sn: null}), 'Ada');
    assert.equal(render({displayName: ' ', entraUserPrincipalName: 'ada@example.org'}), 'ada@example.org');
});
test('local admin and anonymous navigation retain their original labels', () => {
    assert.equal(render({userName: 'openidm-admin'}, 'openidm-admin'), 'openidm-admin');
    assert.equal(render(null, 'guest'), 'guest');
});
test('directory HTML is passed only to the text setter', () => {
    assert.equal(render({displayName: '<img src=x onerror=alert(1)>&'}), '<img src=x onerror=alert(1)>&');
});
