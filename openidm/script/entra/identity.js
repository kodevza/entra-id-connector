// SPDX-License-Identifier: CDDL-1.1
/*global exports, openidm */
// Called ONLY after OPENID_CONNECT has verified the token signature against Entra JWKS.
(function () {
    exports.rejectLocalAuth = function (security) {
        var user = openidm.read(security.authorization.component + '/' + security.authorization.id);
        if (user && user.entraObjectId) {
            throw {code: 401, message: 'Use Microsoft Entra ID to sign in'};
        }
        return security;
    };
    exports.authorizeClaims = function (claims, security, properties) {
        function denied() { throw {code: 401, message: 'Entra identity is not authorized'}; }
        var guid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        if (claims.tid !== properties.entraTenantId || !guid.test(claims.oid || '') ||
                claims.aud !== properties.entraClientId ||
                claims.iss !== 'https://login.microsoftonline.com/' + properties.entraTenantId + '/v2.0' ||
                !claims.sub || claims.sub !== security.authenticationId ||
                typeof claims.exp !== 'number' || claims.exp <= Date.now() / 1000 ||
                (claims.nbf && claims.nbf > Date.now() / 1000)) {
            denied();
        }
        var result = openidm.query('managed/user', {
            _queryFilter: '/entraTenantId eq ' + JSON.stringify(claims.tid) +
                ' and /entraObjectId eq ' + JSON.stringify(claims.oid)
        }, ['*', 'authzRoles']).result;
        if (result.length !== 1 || result[0].accountStatus !== 'active') { denied(); }
        if (!guid.test(properties.entraAccessGroupId || '') || !guid.test(properties.entraAdminGroupId || '')) {
            throw {code:503, message:'Entra access groups are not configured'};
        }
        function isMember(groupId) {
            var membership;
            try {
                membership = openidm.action('system/entra', 'script', {
                    groupId: groupId, userId: claims.oid
                }, {scriptId:'isGroupMember', scriptExecuteMode:'resource'});
            } catch (error) {
                throw {code:503, message:'Unable to verify Entra group membership'};
            }
            // Provisioner errors may be returned with HTTP 200 and an error entry.
            if (!membership || !membership.actions || membership.actions.length !== 1 ||
                    membership.actions[0].error || typeof membership.actions[0].result !== 'boolean') {
                throw {code:503, message:'Unable to verify Entra group membership'};
            }
            return membership.actions[0].result;
        }
        var administrator = isMember(properties.entraAdminGroupId);
        if (!administrator && !isMember(properties.entraAccessGroupId)) {
            throw {code:403, message:'Access requires membership in iam or iam-admins'};
        }
        var user = result[0], roles = ['openidm-authorized'];
        if (administrator) { roles.push('openidm-admin'); }
        (user.authzRoles || []).forEach(function (role) {
            var name = String(role._ref).split('/').pop();
            if (name !== 'openidm-admin' && roles.indexOf(name) === -1) { roles.push(name); }
        });
        return {user:user, roles:roles};
    };
    exports.mapClaims = function (claims, security, properties) {
        var authorized = exports.authorizeClaims(claims, security, properties),
            user = authorized.user, roles = authorized.roles;
        // Keep the principal chosen by native OIDC and CAF unchanged. Bind its
        // verified subject to the preprovisioned account after all access checks.
        require('entra/workflowIdentity').bindSubject(user, claims);
        security.authorization = {id: user._id, component: 'managed/user',
            moduleId: security.authorization.moduleId, provider: 'entra', roles: roles};
        return security;
    };
}());
