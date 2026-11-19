// SPDX-License-Identifier: CDDL-1.1
// Narrow, read-only lookup for the governance ownership start form.
(function () {
    if (request.method !== 'read') {
        throw {code: 405, message: 'Read only'};
    }
    var roles = context.security && context.security.authorization && context.security.authorization.roles || [];
    if (roles.indexOf('openidm-authorized') < 0 && roles.indexOf('openidm-admin') < 0) {
        throw {code: 403, message: 'Access denied'};
    }
    var params = request.additionalParameters || {}, query = String(params.q || '').trim(),
        kind = String(params.kind || ''), principalId = String(params.principalId || ''),
        fields, resource, filter, value, matches, principal;
    function literal(text) {
        return '"' + String(text).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    }
    if (kind !== 'principal' && kind !== 'owner') {
        throw {code: 400, message: 'Invalid lookup kind'};
    }
    if (query.length < 2) { return {result: []}; }
    if (query.length > 200) { throw {code: 400, message: 'Search is too long'}; }
    value = literal(query);
    if (kind === 'principal') {
        resource = 'managed/entraServicePrincipal';
        fields = ['sourceId', 'displayName', 'appId', 'tenantId'];
        filter = '(displayName co ' + value + ' or sourceId sw ' + value + ' or appId sw ' + value +
            ') and sourceId pr and tenantId pr';
    } else {
        matches = openidm.query('managed/entraServicePrincipal', {
            _queryFilter: 'sourceId eq ' + literal(principalId), _pageSize: 2
        }, ['tenantId']).result;
        if (matches.length !== 1 || !matches[0].tenantId) {
            throw {code: 400, message: 'Select a synchronized service principal first'};
        }
        principal = matches[0];
        resource = 'managed/user';
        fields = ['entraObjectId', 'displayName', 'givenName', 'sn', 'userName', 'mail'];
        filter = 'accountStatus eq "active" and entraObjectId pr and entraTenantId eq ' + literal(principal.tenantId) +
            ' and (displayName co ' + value + ' or givenName co ' + value + ' or sn co ' + value +
            ' or userName co ' + value + ' or mail co ' + value + ' or entraObjectId sw ' + value + ')';
    }
    var records = openidm.query(resource, {_queryFilter: filter, _pageSize: 20}, fields).result;
    return {result: records.map(function (record) {
        var id = kind === 'principal' ? record.sourceId : record.entraObjectId,
            name = record.displayName || [record.givenName, record.sn].filter(function (part) { return !!part; }).join(' ') || record.userName || id,
            detail = kind === 'principal' ? record.appId : record.mail || record.userName;
        return {id: id, label: name + (detail ? ' — ' + detail : '') + ' (' + id + ')'};
    })};
}());
