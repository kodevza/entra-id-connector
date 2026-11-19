// SPDX-License-Identifier: CDDL-1.1
/*global recon, tenantId, openidm */
// SOURCE_MISSING is evaluated for a linked target after a successful source scan.
(function () {
    var id = recon.actionParam.targetId;
    if (!id || String(id).indexOf('/') !== -1) { throw new Error('Invalid missing-source target'); }
    var path = 'managed/user/' + id, user = openidm.read(path);
    if (!user || user.entraTenantId !== tenantId || !user.entraObjectId) {
        throw new Error('Missing-source target does not belong to the configured Entra tenant');
    }
    if (user.accountStatus !== 'inactive') {
        openidm.patch(path, user._rev, [{operation:'replace',field:'/accountStatus',value:'inactive'}]);
    }
    // Keep the account and its governance relationships; never delete the user.
    return 'IGNORE';
}());
