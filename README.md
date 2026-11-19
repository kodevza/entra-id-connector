# Microsoft Entra ID Governance Connector

[OpenICF](https://github.com/OpenIdentityPlatform/OpenICF) connector for
[OpenIDM](https://github.com/OpenIdentityPlatform/OpenIDM). Inventories Microsoft
Entra identities, relationships, consent grants, directory roles and Azure RBAC,
and supports explicitly disabling service principals.
This is an independent connector, not an official Microsoft or Open Identity
Platform product. Version 0.1.0 is an initial implementation, validated against
one live tenant and two Azure subscriptions. See [validation](docs/validation.md)
for tested behavior and limits.

## OpenIDM integration

This follows the native OpenICF Java connector model: `@ConnectorClass`,
`AbstractConfiguration`, `SchemaOp`, `SearchOp<Filter>`, `UpdateOp` and `TestOp`. The JAR has
the standard `ConnectorBundle-*` and OSGi manifest headers. Jackson and OpenICF
are `provided` dependencies, supplied by OpenIDM rather than embedded in the JAR.
Required OSGi package imports wire Jackson to the server's implementation.
OpenIDM itself needs no source changes. Its generic connector UI
reads configuration metadata, including the confidential `GuardedString` secret.
See [design decisions and sources](docs/design.md).

## Sign-in and preprovisioned governance accounts

The optional [Entra identity and ownership companion](docs/identity-and-ownership.md)
adds native Entra OIDC login, scheduled user synchronization into `managed/user`,
a live `iam` group gate enforced by OpenIDM, and an owner acceptance workflow. Users exist and can be nominated as owners
before their first login; no password synchronization or cloud writes are added.

## Inventory

| OpenIDM object type | Data |
| --- | --- |
| `account` | Users, UPN, user type, enabled status |
| `group` | Groups, group types, role-assignable flag |
| `application` | App registrations, requested resource access, exposed API definitions and app roles |
| `servicePrincipal` | Enterprise apps / managed identities, application IDs, exposed app roles/OAuth scopes and resolved direct granted-access snapshots |
| `groupMembership` | Direct group memberships, including service principals via inverse `memberOf` |
| `applicationOwner`, `servicePrincipalOwner` | Ownership edges: `sourceId` → `targetId` |
| `appRoleAssignment` | App roles / application permissions granted to users, groups and service principals |
| `oauth2PermissionGrant` | Delegated consent grants: client, resource, principal, consent type and scopes |
| `directoryRoleAssignment` | Active Entra directory role assignments, including directory/app scope |
| `directoryRoleDefinition` | Directory role definitions and permission documents |
| `azureRoleAssignment` | Azure RBAC assignments with principal, role, scope and ABAC condition |
| `azureRoleDefinition` | Azure role definitions, actions, data actions and assignable scopes |

`__UID__` and `__NAME__` use immutable object IDs, not non-unique display names.
Edges use `sourceId:targetId`; Azure objects use their full ARM resource ID.
Complex permission structures are JSON strings (`appRolesJson`, `apiJson`,
`requiredResourceAccessJson`, `oauth2PermissionScopesJson`, `rolePermissionsJson`,
`permissionsJson`, `inheritsPermissionsFromJson`, `grantedAccessJson`). A `null` cloud field is omitted.

Requested permissions (`requiredResourceAccessJson`) are **not** evidence of
granted access. Resolve an assignment's `appRoleId` against the resource service
principal's `appRolesJson`. `oauth2PermissionGrant.clientId` and `resourceId` are
service principal **object IDs**, not application/client IDs. Directory and Azure
role assignments join `roleDefinitionId` to their respective definitions.
Group-derived access can be computed from membership edges; the connector does
not calculate effective permissions or evaluate ABAC conditions.

The connector also exposes a fixed read-only OpenICF resource action,
`isGroupMember` (`scriptLanguage=entra`). It validates UUID arguments and reads
transitive group membership through Graph for the OpenIDM login gate. Arbitrary
scripts remain unsupported. Service-principal reconciliation also resolves directly granted API permissions and active directory roles into `grantedAccessJson`, which new ownership workflows copy into the owner review and request history. See [granted-access installation and coverage](docs/identity-and-ownership.md#granted-access-in-ownership-reviews).

The only cloud resource write is the service-principal
blocking operation below.

## Build and verify

Requires Java 17+ and Maven 3.9+, or Docker:

```sh
mvn clean verify
# or from this directory:
docker run --rm -v "$PWD:/work" -w /work \
  -v openidm-entra-maven-cache:/root/.m2 \
  maven:3.9.11-eclipse-temurin-17 mvn -B -ntp clean verify
```

Artifact: `target/entra-id-connector-0.1.0.jar`.
Tests use an offline HTTP server for Graph and ARM; an integration test loads the
actual packaged JAR through OpenICF, with host dependencies on the test classpath,
and checks discovery, configuration, schema, confidential properties and supported
operations. A packaging test prevents dependency JARs or Jackson/JUnit classes
from being included. No real tenant is contacted. An additional
[host probe](src/test/resources/host-runtime-probe.groovy) verifies the actual
Jackson OSGi provider and JSON parsing in a running OpenIDM; it performs no cloud
requests. See [local validation](docs/validation.md).

## Install locally

This thin JAR requires OSGi installation in OpenIDM's `bundle/` directory:

```sh
docker cp target/entra-id-connector-0.1.0.jar \
  openidm:/opt/openidm/bundle/eu.soft4pm.openicf.entra-id-connector-0.1.0.jar
```

Restart OpenIDM after installing the JAR, during a suitable maintenance window
(`docker restart openidm` locally), so the new bundle is installed and started.
When upgrading from the earlier self-contained variant, move its old JAR out of
`connectors/` before restarting to prevent duplicate connector choices. The local
previous artifact is retained under `/opt/openidm/connector-backups/`.
For this workspace the admin UI is <http://localhost:8081/admin/>. Go to
**Configure → Connectors → New Connector** and select **Microsoft Entra ID Governance**.
Enter a name such as `entra` (no extra hyphens), tenant ID, client ID, client
secret and optionally Azure subscription IDs. Use **Test** and save.
The standard UI generates the provisioner configuration and object types from
the connector's schema. Use the UI confidential field for the secret; never
commit a populated provisioner file. This repository includes an unconfigured
[example](openidm/provisioner.openicf-entra.example.json) for manual deployments.
The selected `connectorRef` must include the OSGi `connectorHostRef` returned by
`availableConnectors` (on OpenIDM 7.1.2:
`osgi:service/org.identityconnectors.framework.api.ConnectorInfoManager`).

OpenIDM normally recommends isolated local connectors in `connectors/`. This
project deliberately uses its supported OSGi mode to share the host's Jackson
instead of shipping duplicate libraries. A JAR placed only in `connectors/`
cannot rely on packages from the server's OSGi bundles. Do not add Jackson to
`lib/` or use global classloader/boot-delegation workarounds.

The current build compiles against Jackson 2.18.6 and requires exported Jackson
packages in `[2.18,3)`. Verify the host's library version when upgrading OpenIDM;
missing or incompatible imports prevent the bundle from resolving. This version
targets OpenIDM's OSGi environment, not a standalone remote connector server.

The bundle is reusable on compatible hosts without rebuilding OpenIDM. Copying into an existing
container survives stop/start but not container replacement; include the JAR in
a derived image or mount a dedicated file for a durable deployment.

### TLS trust

Java HTTP uses OpenIDM's configured trust context. Some OpenIDM distributions
ship an old `security/truststore` that lacks the CA roots used by Microsoft.
If TLS fails with `PKIX path building failed`, update the host truststore with
the verified root CA certificates from the supported JRE truststore. The local
deployment required DigiCert Global Root G2 and Microsoft RSA Root Certificate
Authority 2017; a backup was retained before import. Do not import an arbitrary
server leaf certificate or disable TLS/hostname validation. This is host
configuration, not a change to connector trust or HTTP behavior.

## Entra and Azure configuration

Use a single-tenant app registration and **application** Graph permissions with
administrator consent. A full inventory uses these read permissions:

| Permission | Purpose |
| --- | --- |
| `User.Read.All` | Users |
| `Group.Read.All` | Group metadata and memberships |
| `Application.Read.All` | Apps, service principals, owners, app role assignments |
| `Directory.Read.All` | Global delegated OAuth consent grants |
| `RoleManagement.Read.Directory` | Directory role definitions and assignments |
| `Member.Read.Hidden` | Required if hidden group memberships must be included |

Some permissions overlap with `Directory.Read.All`; the table lists each
collection's read requirements so a deployment that inventories a subset can
choose its own permission policy. `Test` checks every collection, so a reduced
permission deployment must query only its allowed object types and cannot use
the full test as a subset-only readiness check. Lack of permission fails the
operation rather than returning an empty authoritative inventory.

For Azure RBAC, give the same service principal a role with
`Microsoft.Authorization/roleAssignments/read` and
`Microsoft.Authorization/roleDefinitions/read` on each configured subscription
(a suitable custom role or the built-in Reader role). Graph consent does not
grant Azure access. A separate client-credentials token is requested for
`https://management.azure.com/.default`. Empty `subscriptionIds` disables Azure
checks in `Test`; explicitly querying Azure types then fails with a configuration
error, rather than claiming there are no assignments.

Inventory uses GET. The only resource write is a PATCH setting a service
principal's `accountEnabled` to `false`. Create, delete, other updates,
authentication of end users and LiveSync/delta synchronization are unsupported.

## Block a service principal

The native OpenICF `UpdateOp` accepts exactly one Boolean attribute:
`servicePrincipal.accountEnabled=false`. It sends
`PATCH /v1.0/servicePrincipals/{object-id}` with `{"accountEnabled":false}`.
Use the service principal **object ID**, not its application/client ID.
Re-enabling, changing other attributes, and updating other object types are rejected
before any HTTP request. The schema advertises Update only for servicePrincipal.

Grant the connector app `Application.ReadWrite.All` application permission with
administrator consent to block arbitrary service principals. Read-only installations
can retain their existing permissions; blocking then fails with an explicit 403.
See [Microsoft Graph update permissions](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-update?view=graph-rest-1.0).
Protect the OpenIDM system resource update endpoint with the appropriate admin
access policy. Existing import mappings remain one-way inventory mappings.

After installing the updated bundle, refresh the provisioner's schema if necessary
so `servicePrincipal.accountEnabled` is updateable. With the example provisioner,
an authorized OpenIDM REST request is:

```http
PATCH /openidm/system/entra/servicePrincipal/<SERVICE_PRINCIPAL_OBJECT_UUID>
Content-Type: application/json

[{"operation":"replace","field":"/accountEnabled","value":false}]
```

A successful Graph 204 confirms acceptance of the disable operation. It blocks
new token issuance once Entra enforces the changed account state; this is not a
guaranteed zero-latency cutoff. Read back `accountEnabled` and inspect Entra service
principal sign-in logs to verify the result. Transport timeouts can leave the
outcome unknown; retrying this same disable operation is idempotent. HTTP 401
refreshes the connector token once; throttling and transient server errors use
bounded retries. No successful result is returned for Graph errors.

### Existing tokens and CAE

Already-issued access tokens can remain usable until expiry when the application
or resource does not support Continuous Access Evaluation (CAE). Disabling a
service principal is itself a supported CAE revocation event; no separate
revoke-sessions call is made. The connector cannot enable CAE in the target app
by changing a directory property, and does not claim to invalidate all its tokens.

For workload identity CAE, the target application must opt in by including this
`claims` value in its own token requests and handle 401 claims challenges:

```json
{"access_token":{"xms_cc":{"values":["cp1"]}}}
```

Microsoft currently documents support for Microsoft Graph resources and single-tenant
LOB service principals registered in the tenant. Third-party SaaS, multitenant
applications and managed identities are outside that support. Workload Identities
Premium is required to create or modify Conditional Access policies targeting
service principals; applicable policies must target the principal directly.
Check the CAE field in Entra service principal sign-in logs for the affected app.
Declaring `cp1` on the connector's own token requests would only affect the
connector, not the principal being blocked, so this operation does not do that.
See [Microsoft workload identity CAE prerequisites and behavior](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-continuous-access-evaluation-workload).

## Reconciliation into OpenIDM

The connector exposes remote data; importing it into OpenIDM also requires
managed object schemas and synchronization mappings. Example merge fragments:

- [Managed governance collections](openidm/managed-entra.example.json) — merge
  `objects` into `conf/managed.json`, preserving existing definitions.
- [OrientDB classes and indexes](openidm/repo.orientdb-entra.example.json) — merge
  `dbStructure.orientdbClass` into `conf/repo.orientdb.json` when using OrientDB.
  Classes must exist before correlation queries can run. Other repository
  implementations need their own corresponding storage configuration.
- [Import mappings](openidm/sync-entra.example.json) — replace
  `REPLACE_WITH_TENANT_UUID` and merge `mappings` into `conf/sync.json`.

All 13 mappings read `system/entra/<type>` and write dedicated `managed/entra*`
collections. No reverse mappings or cloud writes are configured. Policies create
new objects and update linked/correlated objects; missing or unqualified source
objects are ignored instead of deleted. There is no automatic schedule.

The examples use the native `sourceQueryFullEntry: true` optimization so that
reconciliation reads a complete source collection once, rather than making an
expensive connector UID lookup for every record. `runTargetPhase` is false;
these are inventory imports, not an authoritative deletion workflow.

Managed `sourceId` stores the connector object's immutable UID; together with
`tenantId` it is indexed uniquely and used for correlation. For relationship
collections, the source connector's parent `sourceId` is mapped to managed
`parentId`, while `targetId` retains the member/owner ID. Thus a relationship's
managed `sourceId` is `parentId:targetId`; multiple owners or members of a parent
remain distinct. Optional cloud attributes allow null values in managed schemas.
`collectedAt` records the last collection timestamp. Source references remain
IDs; these examples do not compute effective access or materialize native
managed relationship graphs.

The Entra mappings use `taskThreads: 1` to serialize record processing within
each reconciliation. On OpenIDM 7.1.2, concurrent records can access a Groovy
script while its first compilation is still running and fail with
`Script status is 8`. The single worker also applies after an IDM restart.
For existing Entra deployments, add this setting to the installed mappings in
`sync.json`. Then trigger a mapping with:

```text
POST /openidm/recon?_action=recon&mapping=systemEntraUser_managedEntraUser
GET  /openidm/recon/<returned-run-id>
```

Check `statusSummary.FAILURE` as well as the overall run state: this OpenIDM
runtime can report `SUCCESS` while individual records have failed. Collection
counts and relationship identifiers should also be verified after import.

## Coverage and limits

- Public Azure cloud only; tenant and subscription IDs must be UUIDs.
- Azure RBAC uses the subscription-level role assignment and definition list
  APIs (2022-04-01), following `nextLink`. Inventory is limited to configured
  subscriptions and what those APIs return to the caller. Tenant/management
  group-wide enumeration is not implemented.
- Active role assignments are inventoried. PIM eligibility and scheduling,
  deny assignments, access packages, Conditional Access, Azure resource-specific
  ACLs, Azure AD B2C, and beta-only agent APIs are outside this release.
- Objects returned by Graph are preserved with `objectType`; the connector does
  not label every service principal as an AI agent. Agent discovery/classification
  needs an explicit policy and, where applicable, dedicated agent APIs.
- No automatic group expansion, effective-access calculation or inference that
  requested permissions have been consented. No snapshot consistency guarantee;
  Graph changes and eventual consistency can affect reconciliation.
- Server pagination is streamed for both APIs and nested collections. Arbitrary
  ICF filters are evaluated locally; UID reads can require a full collection scan.
  Client page size, zero-based offsets and opaque continuation cookies support
  OpenIDM's data browser. Pages are evaluated after filtering and resume by
  rescanning from the beginning, following the upstream CSV connector convention;
  this is not a stable snapshot if directory contents change between requests.
  Sorting is not advertised and is rejected. Large tenant performance needs
  validation before production use.
- Permission failures, missing objects during a traversal, malformed responses,
  cyclic pagination and exhausted retries abort the operation. Callers must
  discard partial results when a query fails; never apply destructive
  reconciliation policies to an unsuccessful run.
- Tokens are cached per audience and refreshed once after a 401. Transient
  429/500/502/503/504 responses use bounded retries and `Retry-After`; waits above
  30 seconds return a retryable error. HTTP redirects and pagination URLs outside
  the expected API origin/path (and configured Azure subscriptions) are rejected.
- The implementation currently supports a client secret; certificate/federated
  credentials and managed-identity authentication are future extensions.

## Publishing

This directory is an independent Git repository, ready to be reviewed and hosted
as a separate GitHub project. The Maven namespace is `eu.soft4pm.openicf`; the
repository name/owner can be chosen before publishing. CI builds and tests on
pull requests and pushes, and uploads the JAR as a workflow artifact. It does not
publish releases, create cloud applications, or grant permissions automatically.

Licensed under CDDL 1.1; see [LICENSE.md](LICENSE.md). Dependency licensing is
listed in [NOTICE.md](NOTICE.md).

### Entra ownership workflow forms

The connector provides custom OpenIDM workflow forms for starting service
principal ownership requests and completing the assigned reviews.
See [deployment and migration](openidm/WORKFLOW_UI.md) and
[build and tests](openidm/workflow-form/README.md).
