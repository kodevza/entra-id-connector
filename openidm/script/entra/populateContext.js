// SPDX-License-Identifier: CDDL-1.1
/*global httpRequest, security, properties, java */
(function () {
    // This hook runs after the native OPENID_CONNECT module has verified the JWS.
    // Decoding here extracts oid/tid; it is never a substitute for signature verification.
    var token = String(httpRequest.getHeaders().getFirst('authToken'));
    var payload = new java.lang.String(java.util.Base64.getUrlDecoder().decode(token.split('.')[1]), 'UTF-8');
    var mapped = require('entra/identity').mapClaims(JSON.parse(String(payload)), security, properties);
    return require('auth/customAuthz').setProtectedAttributes(mapped);
}());
