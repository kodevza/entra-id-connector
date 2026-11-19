// SPDX-License-Identifier: CDDL-1.1
/*global exports, openidm */
// Invoke only after native JWS validation, account resolution and live group checks.
(function () {
    exports.bindSubject = function (user, claims) {
        function conflict(message) { throw {code:409, message:message}; }
        var canonical = 'entra.' + claims.tid + '.' + claims.oid,
            aliases = (user.entraWorkflowAliases || []).slice(),
            subject = claims.sub,
            requests, tasks = [], matches, i, j, task, record, current;
        if (user.entraTenantId !== claims.tid || user.entraObjectId !== claims.oid ||
                (user.userName !== canonical && user.userName !== user.entraOidcSubject)) {
            conflict('Entra workflow identity does not match the synchronized account');
        }
        // A subject is scoped to the configured issuer/client. Resolve the managed
        // account by tid/oid, never by an unverified browser-supplied username.
        matches = openidm.query('managed/user', {
            _queryFilter:'userName eq ' + JSON.stringify(subject)
        }).result;
        for (i = 0; i < matches.length; i++) {
            if (matches[i]._id !== user._id) { conflict('Entra subject conflicts with another local login'); }
        }
        [canonical, user.userName].forEach(function (name) {
            if (name !== subject && aliases.indexOf(name) === -1) { aliases.push(name); }
        });
        requests = openidm.query('managed/entraOwnerRequest', {
            _queryFilter:'newOwnerId eq ' + JSON.stringify(user._id) + ' and status eq "pending"'
        }).result;
        for (i = 0; i < requests.length; i++) {
            record = requests[i];
            if (record.newOwnerId !== user._id || record.status !== 'pending' ||
                    (record.newOwnerUserName !== subject && aliases.indexOf(record.newOwnerUserName) === -1)) {
                conflict('Pending ownership request has an inconsistent identity');
            }
        }
        // Preflight all tasks before changing anything. Only this integration's
        // ownership workflow is migrated; candidate groups and other workflows stay intact.
        for (i = 0; i < aliases.length; i++) {
            if (aliases[i] === subject) { continue; }
            matches = openidm.query('workflow/taskinstance', {_queryId:'filtered-query', assignee:aliases[i]}).result;
            for (j = 0; j < matches.length; j++) {
                task = matches[j];
                if (task.processDefinitionId.split(':')[0] !== 'servicePrincipalOwner') { continue; }
                record = openidm.read('managed/entraOwnerRequest/' + task.processInstanceId);
                if (record.newOwnerId !== user._id || record.status !== 'pending' ||
                        (record.newOwnerUserName !== subject && aliases.indexOf(record.newOwnerUserName) === -1)) {
                    conflict('Ownership task does not match the nominated account');
                }
                tasks.push(task);
            }
        }
        // Persist aliases atomically with the username so a failed task update can
        // be retried at the next login. Local IDs, roles, passwords and links are preserved.
        if (user.userName !== subject || user.entraOidcSubject !== subject ||
                user.entraOidcClientId !== claims.aud ||
                JSON.stringify(user.entraWorkflowAliases || []) !== JSON.stringify(aliases)) {
            user = openidm.patch('managed/user/' + user._id, user._rev, [
                {operation:'replace', field:'/userName', value:subject},
                {operation:'add', field:'/entraOidcSubject', value:subject},
                {operation:'add', field:'/entraOidcClientId', value:claims.aud},
                {operation:'add', field:'/entraWorkflowAliases', value:aliases}
            ]);
        }
        for (i = 0; i < requests.length; i++) {
            record = requests[i];
            if (record.newOwnerUserName !== subject) {
                openidm.patch('managed/entraOwnerRequest/' + record._id, record._rev, [
                    {operation:'replace', field:'/newOwnerUserName', value:subject}
                ]);
            }
        }
        for (i = 0; i < tasks.length; i++) {
            task = tasks[i];
            current = openidm.read('workflow/taskinstance/' + task._id);
            if (current.assignee === subject) { continue; }
            if (current.assignee !== task.assignee) { conflict('Ownership task was reassigned during sign-in; retry'); }
            openidm.update('workflow/taskinstance/' + task._id, String(current._rev), {assignee:subject});
        }
        return user;
    };
}());
