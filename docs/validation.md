# Local validation — 2026-11-16

`mvn -B -ntp clean verify` using Maven 3.9.11 / Temurin Java 17 in Docker: passed.

- `eu.soft4pm.openicf.entra.EntraConnectorTest`: 26 tests, 0 failures, 0 errors.
- `eu.soft4pm.openicf.entra.BundleIT`: 2 tests, 0 failures, 0 errors.

Artifact: 29044 bytes.
SHA-256: `b3f19320defd4126a79e185829ae2c6fe496d0e4f210324ec5a87dd99d846e26`.
No nested dependency JARs or inlined Jackson/JUnit classes are packaged. Jackson
Databind is `provided`; OSGi imports Jackson packages in `[2.18,3)`.

## Runtime and registration

Installed as an OSGi bundle in the local OpenIDM 7.1.2 / OpenICF 2.0.4 container:
`/opt/openidm/bundle/eu.soft4pm.openicf.entra-id-connector-0.1.0.jar`.
The earlier self-contained JAR is backed up outside discovery under
`/opt/openidm/connector-backups/`.

The host probe initialized the actual connector, validated all 13 schema types,
parsed JSON and confirmed that Jackson came from the server's
`com.fasterxml.jackson.core.jackson-databind` bundle, version 2.18.6.
`availableConnectors` returned the OSGi connector reference;
`createCoreConfig` returned its six configuration properties.

A live instance named `entra` was subsequently registered through
`createFullConfig` and `config/provisioner.openicf/entra`. Its configuration and
13 object types survived a container restart. OpenIDM stores `clientSecret` as
a `$crypto` encrypted value. Plain credentials and deployment-specific records
are kept only in Git-ignored local files; no credentials are included here.

## Live cloud checks

The full native connector test passed with Graph application read permissions
and Azure RBAC access on two configured subscriptions. Azure access uses a
custom role containing only `Microsoft.Authorization/roleAssignments/read` and
`Microsoft.Authorization/roleDefinitions/read`. A third visible subscription
could not be authorized because the operator received HTTP 403, and was excluded
from the connector configuration. Tenant-wide Entra reads remain enabled.

Authenticated REST queries through OpenIDM returned successful non-empty pages
for all 13 configured object types (two objects per sample page). Applications
and service principals were also checked with continuation cookies: second
pages returned two objects each with no IDs duplicated from the first pages.
A full inventory import was subsequently completed using native OpenIDM reconciliation, as described below. Effective access was not calculated.
The UI uses these same resource query endpoints; no visual browser validation
is claimed.

The original host truststore lacked Microsoft's CA roots, causing a Java TLS
`PKIX path building failed` error. After backing up the truststore, DigiCert
Global Root G2 and Microsoft RSA Root Certificate Authority 2017 were imported
from the container JRE's trusted CA store. Live Graph and ARM requests then
passed with TLS and hostname verification enabled.

## Paging regression

Live OpenIDM queries exposed that the first connector implementation rejected
`_pageSize` and the default zero offset. Two regression tests were added before
the fix. The focused Maven run failed with two `UnsupportedOperationException`
errors (red). After implementing client paging, the same run passed (green).
Additional tests cover filtering before offset, exact last pages, continuation
into inverse service-principal memberships and invalid cookies.

Focused command:

```sh
mvn -B -ntp '-Dtest=EntraConnectorTest#openIdmClientPagingReturnsContinuationAcrossGraphPages+zeroOffsetWithoutPageSizeDoesNotBreakDefaultOpenIdmQueries' test
```

The final full `clean verify` run passed, followed by live paged REST queries
against the redeployed artifact. Client paging follows upstream CSV connector
zero-based offsets and rescans between pages; it is not a consistent snapshot.
PIM eligibility, effective access, and the other documented exclusions remain
outside the connector's coverage. No GitHub publication was performed.


## Native reconciliation import

Dedicated managed governance collections and 13 one-way import mappings were
added through the native `config/managed` and `config/sync` APIs, preserving the
existing user/role/assignment definitions. Corresponding OrientDB classes and
indexes were merged into `config/repo.orientdb`; new repository classes must
exist before a correlation query can search them. Generic merge fragments are
included under `openidm/`; populated configurations, backups and run IDs are
kept only in Git-ignored local files.

Every mapping reads a `system/entra/*` source and writes a `managed/entra*`
target. Full source entries are queried once per mapping. The target phase is
disabled and no deletion policy or reverse mapping is configured.

The initial runs exposed three configuration issues, resolved before declaring
the import successful: first-use script registry initialization (handled by
precompiling the mapping scripts), optional cloud values requiring nullable
managed property types, and relationship parent IDs colliding with the managed
snapshot identity. Relationship parent references now map to `parentId`, while
managed `sourceId` preserves the connector's full immutable relationship UID.

Latest runs for all 13 mappings finished with `state: SUCCESS` and
`statusSummary.FAILURE: 0`. For each collection, the managed record count matched
the source total. `(tenantId, sourceId)` pairs were unique, and every membership
and ownership record satisfied `sourceId == parentId + ':' + targetId`.
Tenant-specific counts and run identifiers are recorded in
`openidm/entra.reconciliation-summary.local.json`, which is excluded from Git.
No effective-access computation, cloud mutation or automatic schedule was added.

## Identity and ownership companion — 2026-11-16

- Connector profile-field regression reproduced first, then fixed: 27 unit tests
  and 2 packaged-bundle integration tests pass (`mvn verify` in the Maven Docker image).
- 13 JavaScript checks and 3 configuration-builder checks pass. They cover
  immutable account mapping, claim restrictions, no login-time creation,
  inactive/ambiguous users, local-password rejection and missing-source handling.
- All 4 live Entra users were preprovisioned into `managed/user`. Reconciliation
  creates no duplicates and finishes with `statusSummary.FAILURE == 0`.
- Live local fixtures verified storing a user who has never logged in as a native
  service-principal owner relationship, and disabling a linked user after its
  source is absent. Fixtures were removed; the 4 actual accounts remain.
- Six scenarios execute the actual BPMN Groovy scripts with a mocked router:
  acceptance, rejection, another actor, inactive owner, concurrent ownership change
  and missing decision. Tests explicitly model relationships being omitted unless
  requested in `_fields`.
- A real workflow instance routed its task to a preprovisioned user. Completion by
  the administrator was rejected because only the nominated owner may decide.
  The validation instance was canceled without assigning a real service principal.
- The native module rejects an unsigned ID token (HTTP 401). Both the mapping
  helper and full augmentation entry point were exercised in the running script
  engine. The browser renders the Entra sign-in button and redirects to the
  configured tenant's Microsoft sign-in page with the registered callback URL.
- Full interactive login/MFA and return to the OpenIDM UI are pending user testing.

A dedicated single-tenant registration, `OpenIDM Local Sign-in`, was created for
this deployment. Its current login credential expires **2027-05-15**. Rotate the
credential in Entra and OpenIDM before that date. The connector's inventory
credentials and permissions are independent of this login registration.

## Live iam group gate — 2026-11-17

Created the empty, static Entra security group `iam` with object ID
`5ca0d185-7e27-4f7c-b3ee-56f43e02bd57`. No members were added. OpenIDM's OIDC module
now requires live membership in this group; all directory accounts remain
preprovisioned independently. No group-based Enterprise Application assignment,
SCIM configuration, license change or Graph write operation was added to the
connector.

Regression tests failed before implementation. After implementation, 30 connector
unit tests, 2 packaged-bundle tests, 18 JavaScript checks and 4 configuration checks
pass. The new connector action is fixed to `isGroupMember`, rejects arbitrary
scripts and invalid IDs, handles pagination and propagates API failures.

The rebuilt connector and group gate were installed and verified after restarting
the container. Live tests confirmed:

- An existing active managed user outside `iam` is denied by the actual
  post-validation authorization hook (HTTP 403), even with a supplied groups claim.
- A failed group lookup is denied (HTTP 503).
- A known member of an existing test group is accepted by the same hook with
  test-only script bindings. Production configuration and memberships are unchanged.
- The deployed module continues to reference the immutable `iam` object ID.

Read-only live check (initial empty-group deployment; `OPENIDM_PASSWORD` required):

```sh
python3 openidm/tests/live_group_gate.py
```

This tests post-validation authorization, not an end-to-end interactive Entra/MFA
login. Group removal affects fresh authentication; issued OpenIDM sessions retain
their normal configured expiry. The local internal administrator login is retained.


## iam-admins and user menu label — 2026-11-17

Created empty static security group `iam-admins`, object ID
`5b551b6f-5267-43aa-bfb5-41504d44b851`. No group members were added. The installed
OIDC module checks it live and grants `openidm-admin` only on a positive result.
Administrators need not also belong to `iam`. Tests cover administrator-only
access, ordinary access, and dropping a stale locally stored admin grant.

Live post-validation probes verified ordinary access with the configured empty
admin group, and administrator access with a known existing group in test-only
bindings, including an inaccessible ordinary group to exercise admin-only access.
Production membership and group IDs were unchanged by probes.

Browser checks render the shared navigation with a display name and verify that
the underlying username stays unchanged. The helper also has four focused tests
for display name, name components, UPN, and internal/anonymous fallback.

## Entra IDs and process diagram — 2026-11-17

- Red: the exact BPMN script failed when given Entra IDs distinct from local IDs;
  a separate geometry assertion failed because BPMNDiagram was missing.
- Green: the mocked-router suite passes acceptance, rejection, authorization,
  inactive owner, concurrent assignment, explicit decision, missing/ambiguous
  object IDs, tenant scoping and complete diagram geometry checks.
- Deployed locally as `servicePrincipalOwner:3:204`; the previous BPMN was backed
  up under `/opt/openidm/identity-backups/owner-workflow-20261117T152236Z`.
- The live local check passed with disposable user/principal records whose Entra
  IDs differ from local IDs, including uppercase GUID input. The request resolved
  to the intended records and waited for owner approval. All fixtures were removed.
- Both diagram endpoints used by the UI returned valid PNGs. Visual inspection
  confirmed a red outline around the active acceptance step. Browser verification
  was unavailable because the browser access host could not be reached.
- No Microsoft Graph writes were performed. Existing workflow definitions and
  their history retain their original version; use version 3 for the new form.


## Native OIDC subject binding (2026-11-17)

The connector companion now preserves the native authenticated `sub` and binds
it to the existing managed account after verified claims and live membership
checks. It migrates that account's pending ownership requests and assigned tasks.
The earlier experimental OpenIDM authentication binary patch was removed; the
deployed authentication bundle matches its original backup.

Validation:

- Regression tests first failed when the old hook attempted to rewrite the
  native principal and when the subject-binding schema/mapping was absent.
- 26 JavaScript tests and 4 Python configuration tests passed.
- `live_workflow_identity.py` passed: idempotent binding, unchanged local IDs,
  stock Self Service task aggregation, mapping condition and standard task
  authorization/BPMN rejection using disposable local records.
- `live_identity.py` passed: reconciliation preserved existing IDs and bound
  subjects, ownership before first login, and missing-source deactivation.
  All fixtures were removed; the four original accounts remained.
- The user confirmed that the task appeared after fresh Microsoft sign-in.
  The original request was subsequently accepted under the native subject.
- The OpenIDM checkout's 20 existing Node UI regression tests passed.

No Graph writes or group membership changes were performed.
