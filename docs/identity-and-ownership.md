# Entra sign-in, preprovisioned accounts and local ownership

The inventory collection `managed/entraUser` is separate from the authenticating
accounts in `managed/user`. The companion configuration creates **every Entra user
in OpenIDM during reconciliation**, without waiting for an interactive sign-in.
It never imports passwords. An administrator can nominate any active synchronized
user as a service principal's governance owner before that user's first login.

Account correlation uses `(entraTenantId, entraObjectId)`. Before first sign-in,
`userName` is generated as `entra.<tenant UUID>.<object UUID>`. After verified
sign-in it becomes the login application's native OIDC `sub`. This technical login
stays stable when names, UPN or email change; the local account `_id` never changes. Display name, given name, surname, UPN, mail and enabled status are updated
from Entra. Missing names/mail use safe fallbacks because OpenIDM requires those
fields. Repeated reconciliation updates the existing accounts and preserves local
roles and ownership references. No reverse mapping or write operation is added to
the cloud connector.

## Sign-in

A dedicated **single-tenant Web** app registration supplies the Entra client ID
and secret. Register the actual UI callback URLs, including `oauthReturn.html`:

- `http://localhost:8081/oauthReturn.html`
- `http://localhost:8081/admin/oauthReturn.html`

The local deployment also registers the equivalent `127.0.0.1` URLs. Additional
origins/ports need their own registered URLs. The authorization-code flow requests
`openid profile email`; implicit grants are disabled. The app does not need the
inventory connector's application permissions or Azure RBAC rights.

OpenIDM's native `OPENID_CONNECT` module verifies the JWS with Entra discovery/JWKS.
Only after that verification, `entra/populateContext.js` extracts the claims and
`entra/identity.js` enforces the expected issuer, tenant, audience, expiry and
subject. It resolves `oid` to the **existing** active `managed/user`, installs that
account's local roles, and binds the verified subject used by Activiti. It never
rewrites `security.authenticationId` or creates an account at login. A missing, ambiguous or inactive account is denied.
Directory roles are not automatically converted into OpenIDM admin roles.

This explicit mapping is needed because Entra's OIDC `sub` is application-specific
and cannot be precomputed from the Graph inventory. Microsoft recommends stable
`tid`/`oid` for this association: [claims validation](https://learn.microsoft.com/en-us/entra/identity-platform/claims-validation)
and [ID token claims](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference).

OpenIDM 7.1.2's native module always uses `sub` as the authenticated Java principal.
Changing `authenticationId` in an augmentation script alone does not change that
principal: CAF restores `sub` when constructing the request and JWT session. The
connector integration therefore keeps native authentication intact. After all
claim, active-account and live group checks pass, `entra/workflowIdentity.js`:

- Binds protected `entraOidcSubject` and `entraOidcClientId` to the existing account
  and updates its technical `userName` to the verified subject.
- Keeps previous technical names in protected `entraWorkflowAliases`, so a partial
  task update can be retried by signing in again.
- Updates only pending ownership requests for that account and its assigned
  `servicePrincipalOwner` tasks. It never completes tasks or modifies finished
  request history, candidate groups or other workflows.
- Rejects username collisions and inconsistent task/request ownership.

The username mapping condition preserves a bound subject during reconciliation.
Before a nominee's first login, tasks use the placeholder username; their first
authorized login moves them to `sub`, making them visible in stock Self Service.
Existing process versions continue working because their stored owner username,
task assignee and managed username agree. No OpenIDM core patch is required.
Subject binding writes only local OpenIDM records, never Microsoft Graph.
An application/client change may produce a new `sub`; a verified login updates
the binding and outstanding ownership tasks, retaining previous aliases.

The installer also adds a guard to `MANAGED_USER`: synchronized Entra accounts
cannot use a local password, including one set later by a reset operation. The
existing internal administrator login remains available.

## Access group: iam

Entra authenticates the identity; OpenIDM grants access only to members of the
static Entra security group **`iam`**, or the administrator group **`iam-admins`**. There is no group assignment to the
Enterprise Application, no SCIM provisioning and no P1/P2 requirement for those
features. Manage the group's membership in Entra. The deployed group object ID is
stored as `entraAccessGroupId`, with the administrator group as `entraAdminGroupId`, in the OpenIDM OIDC module; renaming another group
to `iam` does not grant access.

After validating the ID token and resolving the active managed account, OpenIDM
invokes the connector's fixed `isGroupMember` resource action. The connector uses
its existing app-only Graph credentials to read `/groups/<id>/transitiveMembers`,
including nested membership, following pagination. It does not evaluate arbitrary
scripts or use membership values supplied by the browser. The connector needs a
Graph group-membership read permission with admin consent, independent of the
login app's scopes. Existing inventory permissions can supply that access.

The check happens during a fresh Entra authentication and has no positive
membership cache. Nonmembers are denied. Missing configuration, connector/API
errors, missing groups or malformed responses also deny access. Group changes
are subject to Graph replication; they do not wait for the 15-minute account
reconciliation. Existing OpenIDM JWT sessions follow their configured expiry.
The separate local administrator login remains available.

All directory users continue to be synchronized and can be nominated as owners.
A nominee must join `iam` or `iam-admins` to sign in and accept their task.
Membership in `iam` grants ordinary `openidm-authorized` access. Live membership
in `iam-admins` additionally grants `openidm-admin`, without requiring membership
in `iam`. Locally stored `openidm-admin` grants are ignored for Entra logins, so
removal from the administrator group takes effect on fresh authentication. Both groups are initially empty; the user maintains their members.

## Workflow storage prerequisite

For the default embedded H2 Activiti database, run the connector's storage
installer before deploying the ownership workflow or starting reviews on an
existing deployment. For a fresh instance, start OpenIDM once so Activiti can
initialize its tables. Then run these steps from the connector checkout:

```sh
docker stop openidm
python3 tools/workshop/install_workflow_storage.py --container openidm
docker start openidm
```

The installer uses the OpenIDM image and its H2 bundle in a temporary container.
It requires the stopped instance's initialized database on writable mounted
storage at `/opt/openidm/db/activiti/database.mv.db`. It saves a timestamped H2
backup ZIP alongside the database before widening both text columns in the
runtime variable and history tables. Existing rows remain readable and the
migration can be rerun. Wait for it to succeed before starting OpenIDM.

The columns retain their JDBC string type and use H2's default `VARCHAR`
capacity in place of the Activiti schema's 4,000-character cap. OwnerLens
still validates the evidence size at the workflow boundary. The installer
targets the default embedded H2 layout and unprefixed tables. For an external
Activiti data source or custom schema, have the database administrator apply
the equivalent change for that database before deploying the workflow.

## Install/update

Prepare [workflow storage](#workflow-storage-prerequisite), then build and
install the connector JAR as described in the main README. The update
adds `givenName` and `surname` to the account schema. Restart OpenIDM after changing
the JAR, then install its companion configuration:

```sh
python3 tools/workshop/install_identity.py \
  --tenant YOUR_TENANT_UUID \
  --client-id YOUR_LOGIN_APP_CLIENT_ID \
  --access-group-id YOUR_IAM_GROUP_OBJECT_ID \
  --admin-group-id YOUR_IAM_ADMINS_GROUP_OBJECT_ID
```

The installer prompts for the OpenIDM admin password and the login client secret,
or reads `OPENIDM_PASSWORD` and `ENTRA_CLIENT_SECRET` from the environment. Never
commit populated authentication/provisioner files. It merges the existing managed,
provisioner, synchronization and authentication configuration, copies scripts and
deploys the BPMN/custom-form BAR, and creates an OrientDB class for request history. It assumes
the local connector is named `entra`, the container is `openidm`, and the existing
inventory collections have been installed. Override `--url` or `--container` as
needed. A custom file-based `MANAGED_USER` augmentation hook needs the guard
composed into that hook manually.

For an existing installation, update only the subject binding without supplying
the login client secret again:

```sh
python3 tools/workshop/install_workflow_identity.py --check
python3 tools/workshop/install_workflow_identity.py
```

This preserves the provider configuration, roles and existing mappings. It adds
protected binding fields and the username condition, installs the hooks, and
reloads authentication. Sign out of OpenIDM and sign in through Microsoft to
replace an older JWT session. Pending task IDs and account IDs are preserved.
The script stores configuration and hook backups under
`/opt/openidm/identity-backups/native-subject-<UTC timestamp>/`.

Backups are stored inside `/opt/openidm/identity-backups/<UTC timestamp>/`. The
JSON views are persisted asynchronously; wait for the installer to finish before
restarting. Container replacement still requires mounting/preserving OpenIDM's
configuration, scripts, workflow and repository or including them in an image.

Start the first reconciliation with the admin API:

```text
POST /openidm/recon?_action=recon&mapping=systemEntraAccount_managedUser
GET  /openidm/recon/<returned-id>
```

Check `statusSummary.FAILURE == 0`, not just `state == SUCCESS`. A schedule runs
this mapping every 15 minutes with concurrent executions disabled. Disabled Entra
users become inactive. After a successful source scan, linked accounts whose
source no longer exists are also disabled; accounts and owner references are
retained. This affects subsequent authentication. Existing OpenIDM sessions follow
the configured JWT/session expiry; it does not revoke every issued session token.

## Ownership process

Open **Admin → Manage → Processes → Definitions** and start
**Service principal — assign governance owner**. Supply the service principal's
Entra **Object ID** (Enterprise applications, not Application/client ID), the new
owner's Entra user **Object ID**, and a reason. These are resolved through
`entraServicePrincipal.sourceId` and `user.entraObjectId` in the same tenant;
unknown or ambiguous matches fail. Local OpenIDM record IDs remain internal. The user can be
selected from the synchronized users even if they have never signed in. The
current stock start form takes IDs; it does not contain a searchable user picker.
The resulting `governanceOwner` relationship uses the native user resource picker
and resolves to the preprovisioned managed account.

The BPMN includes diagram geometry for every step and transition, so the admin
UI can show both the definition and the active approval step. Select the latest
definition when starting a process; historical definitions keep their original
forms and diagrams.

The nominated user signs in through Entra and accepts or rejects the task. Only
that user can decide; an administrator cannot complete it on their behalf.
Acceptance writes `managed/entraServicePrincipal/<id>/governanceOwner` as a
relationship to `managed/user/<id>`. Rejection of a manual nomination leaves ownership unchanged and blocks the service principal through
`system/entra/servicePrincipal/<Entra Object ID>` with `accountEnabled=false`.
The decision form explicitly labels this consequence. The connector must have
`Application.ReadWrite.All` with admin consent and an updateable provisioner
`accountEnabled` property (see the connector README). A connector failure leaves
the task pending and does not record a completed rejection; the owner can retry.
A cloud write cannot be rolled back with the local workflow transaction: if the
local history write fails after blocking, retrying the same disable is idempotent.
Acceptance never re-enables a blocked principal. Only newly started instances use
the blocking behavior after you deploy the updated definition. See the
[workflow deployment procedure](../openidm/WORKFLOW_UI.md#install).
Already running instances retain their original definition. This is
a local governance assignment and does **not** change Microsoft Graph owners.
Imported Graph ownership remains in `entraServicePrincipalOwner`.

An [OwnerLens Lite review](../openidm/workflow-form/README.md#ownerlens-lite-review)
uses a ranked list of candidates and an evidence table. Each reviewer can accept,
decline, or forward to another candidate. Declines advance through the original
ranking until a reviewer accepts or the list is exhausted.

The authoritative pending request is saved in `managed/entraOwnerRequest` under
the engine's process ID, separately from client-writable workflow variables.
History records the requester, reason, decision, actor and timestamps. Acceptance
rechecks the account status/tenant and preserves a concurrent ownership change.
Administrator permissions control access to request history.

Validation messages are defined in the BPMN script and enclosed in
`[workflow-message]...[/workflow-message]`. The UI extracts this text from Activiti
exception wrappers and renders it as plain text, preserving form input. Other
failures show generic guidance. The unchanged OpenIDM resource returns HTTP 500
for script failures, including these validation failures; failed starts roll back.

## Validation

```sh
mvn verify
node --test openidm/tests/*.test.cjs
python3 -m unittest discover -s tools/workshop/tests -p 'test_*.py'
# Exact BPMN scripts, mocked router, no cloud writes:
docker cp openidm/tests/owner_workflow.groovy openidm:/tmp/entra-owner-workflow-test.groovy
docker exec openidm java -cp '/opt/openidm/bundle/*' groovy.ui.GroovyMain \
  /tmp/entra-owner-workflow-test.groovy /opt/openidm/workflow/servicePrincipalOwner.bpmn20.xml
# Disposable OpenIDM and mock OAuth/Graph with no external network:
python3 tools/workshop/tests/offline_reconciliation.py
# Disposable local records; Entra object IDs and both UI diagram endpoints:
python3 tools/workshop/tests/live_owner_workflow.py
# Native subject binding, stock Self Service aggregation and local task acceptance:
python3 tools/workshop/tests/live_workflow_identity.py
```

The local integration check verifies stable account IDs and missing-source
deactivation using one temporary local account/link, then cleans that fixture.
It only reads the cloud. A full interactive sign-in, including MFA and the return
to OpenIDM, must also be checked with an actual user's Entra session.

## Navigation and Self-Service dashboard

The connector's OpenIDM configuration includes a navigation template extension
for both Admin and Self Service. The menu shows `displayName`, then given name
and surname, then Entra UPN, then the original username. Directory values are
inserted with jQuery `text()`, so HTML is displayed as text. No authentication
identifier, managed record ID, workflow assignment or relationship is changed.

The connector also installs a Self-Service dashboard template that hides the
Notifications panel and gives tasks and processes the full row. The dashboard
still fetches notifications in the background.

The full identity installer installs both extensions automatically. To update an
existing integration, run from the connector checkout with OpenIDM running:

```sh
python3 tools/workshop/install_user_menu.py --check
python3 tools/workshop/install_user_menu.py
```

The installer uses Docker, requires no API password and writes to these paths under `/opt/openidm/ui/`:

- `{admin,selfservice}/extension/templates/common/NavigationTemplate.html`
- `selfservice/extension/templates/workflow/tasks/TasksDashboardTemplate.html`
- `{admin,selfservice}/extension/index.html` to version cached UI assets while preserving existing RequireJS parameters

The navigation template uses the existing RequireJS modules to read the managed user profile;
it does not replace OpenIDM JavaScript modules or require an OpenIDM UI build.

For migration from the earlier implementation, the installer removes only the
known `UserDisplayName` patch from existing default bundles and resets the old
template helper call. Unrelated workflow changes are preserved. All affected
files are backed up under `/opt/openidm/identity-backups/user-menu-<timestamp>/`,
with a manifest mapping backup filenames to their original paths. An existing
custom template at either extension path requires a manual merge; the installer stops before
writing files in that case. Repeat installation is a no-op.

Hard-refresh both UIs after installation. Role changes still require logout and
a new Entra login to refresh the OpenIDM session.

## Common workflow history contract

New owner-assignment instances keep the existing searchable start form and write
`subject` as the service principal's Entra Object ID, separately from the local
`servicePrincipalId` used for assignment. Their approval form shows **Subject**,
**Data source** and **Subject name**. The server resolves these from inventory;
submitted task variables cannot redirect the stored request or its subject.

The request also stores `subjectName`, `subjectType=servicePrincipal`,
`source=entra`, `tenantId`, `processId`, `processType=servicePrincipalOwner`,
`recordType=ownership_assignment` and `reviewer`, alongside the existing requester,
reason, status and decision timestamps/actor. These common fields allow the
[reporting companion](../../openidm-reporting/README.md) to include different
workflow collections in one history table and CSV. An ownership assignment is
not labeled as a recertification.

Deploy the latest workflow definition before installing the reporting companion.
See the [workflow deployment procedure](../openidm/WORKFLOW_UI.md#install).
Both the host workflow installer and identity
schema builder add the new properties to existing request schemas while retaining
custom properties. Existing process definitions, running instances and historical
records keep their original behavior/data; the upgrade does not reconstruct
missing past subject metadata. Use the latest definition for new requests.

## Granted access in ownership reviews

Service-principal reconciliation now stores `grantedAccessJson`: a fresh snapshot
of directly granted application permissions, delegated OAuth consent and active
Entra directory roles. Resource service-principal IDs are resolved to API names;
app-role IDs resolve against the resource's `appRoles`, and delegated scopes
retain the consent type and user Object ID for per-user consent. Requested API
permissions and the service principal's own exposed roles are not treated as
access grants. Unknown resource/role definitions retain IDs and explicit unresolved
labels. Every search reads current Graph data and replaces empty snapshots too,
so revoked grants disappear after a successful reconciliation.

Graph pagination is followed for every collection. Resource and directory-role
definitions and delegated grants are fetched once per search; outgoing app-role
assignments are read per service principal. This adds Graph calls and directory
role/consent read requirements to service-principal reconciliation. An API failure
aborts the search rather than producing a successful empty permissions snapshot.
Check record failures as well as the overall reconciliation state.

New ownership requests copy the snapshot into protected request history and show
a multiline, escaped review form with API/permission names, descriptions, consent
and directory scopes, plus collection time. No additional owner privileges are
needed to read the task. Task-completion values do not overwrite the stored
snapshot. Missing inventory is explicitly shown as not collected, rather than
claiming no access. The snapshot describes what was imported when the request
started; it is not a live effective-access calculation.

Coverage excludes group-derived permissions, PIM eligibility, Azure RBAC,
resource-specific ACLs and Conditional Access. Delegated consent requires a user
context and does not imply application-only access. Existing instances keep their
previous form and data.

Upgrade an existing installation after building the connector:

```sh
# Back up the installed JAR, then install the newly built JAR as in the README.
# Restart OpenIDM to load the bundle before installing configuration.
npm ci --prefix openidm/workflow-form
npm run --prefix openidm/workflow-form build
python3 tools/workshop/install_permissions.py --check
python3 tools/workshop/install_permissions.py
```

The installer backs up configuration and the previous BPMN in the container,
merges the provisioner/schema/mapping fields and deploys the updated workflow.
It also makes the optional governance-owner relationship nullable, preserving its
relationship configuration; otherwise importing an unowned existing principal
can fail policy validation on `governanceOwner: null`.
Run `systemEntraServicePrincipal_managedEntraServicePrincipal` reconciliation,
check `statusSummary.FAILURE`, and start a new ownership request. Refresh the UI
if an old task form remains cached.

API references: [granted app roles](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list-approleassignments?view=graph-rest-1.0)
and [delegated consent](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list-oauth2permissiongrants?view=graph-rest-1.0).


The approval now uses a [custom Preact form packaged with BPMN in one BAR](../openidm/workflow-form/README.md). Build the BAR before using any ownership workflow installer. New instances load the form through the native Activiti `formKey`; legacy running instances retain their previous form.

### Offline reconciliation integration test

From the connector repository, run `python3 tools/workshop/tests/offline_reconciliation.py`.
It requires Docker, an OpenIDM image (`openidentityplatform/openidm:latest` by default),
and `python:3.12-alpine`. Maven packages a disposable copy of the connector with
loopback endpoints. If Maven is unavailable locally, load
`maven:3.9.11-eclipse-temurin-17` for the Docker build. Image pulls and dependency
downloads happen before the test runtime.

The test starts a fresh OpenIDM container with networking disabled. A Python
sidecar shares its loopback interface and serves synthetic OAuth and paginated
Graph responses. The test uses the actual connector, synchronization scripts,
managed objects and repository links. It checks the first and second reconciliation,
including mapped attributes, stable record IDs and duplicate prevention. It then
checks account preprovisioning, owner assignment and deactivation when a source
record is missing. Both containers are removed after the test. No tenant
credentials are required.
