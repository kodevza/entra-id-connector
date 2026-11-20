# Microsoft Entra ID Governance Connector

An independent OpenICF connector for OpenIDM that inventories Microsoft Entra ID and Azure RBAC. It reads users, groups, apps, managed identities, memberships, owners, consent grants and role assignments. It can also disable a service principal on request.

Version 0.1.0 was validated against one live tenant and two Azure subscriptions. See the [validation report](docs/validation.md) for results.

## Set up the connector

### 1. Configure access in Entra and Azure

Create a single-tenant Entra app registration with a client secret. Grant administrator consent for the Microsoft Graph **application permissions** you need.

| Permission | Used for |
| --- | --- |
| `User.Read.All` | Users |
| `Group.Read.All` | Groups and memberships |
| `Application.Read.All` | App registrations, service principals, owners and app role assignments |
| `Directory.Read.All` | Delegated OAuth consent grants across the tenant |
| `RoleManagement.Read.Directory` | Directory role definitions and assignments |
| `Member.Read.Hidden` | Hidden group memberships, if needed |

Some permissions overlap with `Directory.Read.All`. OpenIDM's **Test** checks every inventory collection, so verify individual object types if you grant access to only a subset. A permission error fails the query.

To inventory Azure RBAC, grant the same service principal **Reader** or a custom role with `Microsoft.Authorization/roleAssignments/read` and `Microsoft.Authorization/roleDefinitions/read` on each configured subscription. Leave `subscriptionIds` empty to skip Azure checks. Queries for Azure object types then return a configuration error.

### 2. Build the JAR

Use Java 17+ and Maven 3.9+, or run Maven in Docker from the repository root.

```sh
mvn clean verify
```

```sh
docker run --rm -v "$PWD:/work" -w /work \
  -v openidm-entra-maven-cache:/root/.m2 \
  maven:3.9.11-eclipse-temurin-17 mvn -B -ntp clean verify
```

Both commands produce `target/entra-id-connector-0.1.0.jar` and run offline connector and bundle tests.

### 3. Install in OpenIDM

1. Copy the JAR into OpenIDM's `bundle/` directory. The bundle uses OpenIDM's OpenICF and Jackson packages and requires exported Jackson packages in `[2.18,3)`.

   ```sh
   docker cp target/entra-id-connector-0.1.0.jar \
     openidm:/opt/openidm/bundle/eu.soft4pm.openicf.entra-id-connector-0.1.0.jar
   ```

2. If upgrading from the older self-contained build, move its JAR out of `connectors/`. Restart OpenIDM during a maintenance window with `docker restart openidm` for the local Docker setup.
3. Open the [local OpenIDM admin UI](http://localhost:8081/admin/) and go to **Configure → Connectors → New Connector → Microsoft Entra ID Governance**.
4. Enter `entra` as the connector name, then provide the tenant ID, client ID, client secret and optional subscription IDs. Select **Test**, then save.

For manual deployment, start with the [example provisioner](openidm/provisioner.openicf-entra.example.json). Use the OSGi `connectorHostRef` returned by `availableConnectors`. On OpenIDM 7.1.2 the value is `osgi:service/org.identityconnectors.framework.api.ConnectorInfoManager`. Keep the configured client secret out of version control.

To retain the JAR when the container is replaced, include it in a derived image or mount it as a file. For `PKIX path building failed` errors, check the verified root CAs in the OpenIDM truststore. See [runtime validation](docs/validation.md#runtime-and-registration), [live cloud checks](docs/validation.md#live-cloud-checks) and [bundle design](docs/design.md#host-provided-dependencies).

## Inventory

| Object type | Data |
| --- | --- |
| `account`, `group` | Users and groups |
| `application`, `servicePrincipal` | App registrations, enterprise apps and managed identities |
| `groupMembership` | Direct memberships, including service principals |
| `applicationOwner`, `servicePrincipalOwner` | App registration and service principal owners |
| `appRoleAssignment`, `oauth2PermissionGrant` | App role grants and delegated OAuth consent |
| `directoryRoleAssignment`, `directoryRoleDefinition` | Active Entra role assignments and role definitions |
| `azureRoleAssignment`, `azureRoleDefinition` | Azure RBAC assignments and role definitions, including scopes and conditions |

`__UID__` and `__NAME__` use immutable IDs. Membership and ownership records use `sourceId:targetId`. Azure records use full ARM resource IDs. Complex permission fields are JSON strings, and cloud fields with null values are omitted.

Use assignments and consent grants to identify granted access. `requiredResourceAccessJson` records what an app requested. Resolve an assignment's `appRoleId` against the resource service principal's `appRolesJson`. In delegated grants, `clientId` and `resourceId` are service principal object IDs. Directory and Azure role assignments reference their definitions through `roleDefinitionId`.

Service principal inventory includes direct API grants and active directory roles in `grantedAccessJson`. See [granted access in ownership reviews](docs/identity-and-ownership.md#granted-access-in-ownership-reviews).

### Reconcile into managed objects

1. Merge `objects` from the [managed object example](openidm/managed-entra.example.json) into `conf/managed.json`.
2. For OrientDB, merge `dbStructure.orientdbClass` from the [repository example](openidm/repo.orientdb-entra.example.json) into `conf/repo.orientdb.json`. Set up equivalent storage if you use another repository.
3. Replace `REPLACE_WITH_TENANT_UUID` in the [mapping example](openidm/sync-entra.example.json) and merge `mappings` into `conf/sync.json`.
4. Start a reconciliation and check its record-level failure count.

   ```text
   POST /openidm/recon?_action=recon&mapping=systemEntraUser_managedEntraUser
   GET  /openidm/recon/<returned-run-id>
   ```

The 13 mappings import records from `system/entra/<type>` into `managed/entra*`. They correlate by `tenantId` and `sourceId`, create or update records and retain missing records. For membership and ownership records, managed `sourceId` contains the full relationship ID and `parentId` contains the source parent ID. Run mappings manually or configure a schedule.

Keep `taskThreads: 1` on Entra mappings to avoid Groovy compilation races on OpenIDM 7.1.2. The overall run can show `SUCCESS` even when some records failed, so also check `statusSummary.FAILURE`. Discard partial results from failed queries. See [reconciliation validation](docs/validation.md#native-reconciliation-import).

## Optional Entra sign-in and ownership reviews

The companion adds Entra OIDC sign-in, scheduled synchronization into `managed/user`, and a live `iam` group check in OpenIDM. Synchronized users can be nominated as owners before their first sign-in.

1. Prepare [workflow storage](docs/identity-and-ownership.md#workflow-storage-prerequisite) before deploying ownership recertification. Check the storage again after replacing the OpenIDM container or restoring or creating the workflow database.
2. Build the [workflow BAR](openidm/workflow-form/README.md#build-and-test).
3. Deploy it with the [identity installer](docs/identity-and-ownership.md#installupdate) for a new setup or the [permissions installer](docs/identity-and-ownership.md#granted-access-in-ownership-reviews) for an existing one.
4. Run `systemEntraServicePrincipal_managedEntraServicePrincipal` reconciliation, check `statusSummary.FAILURE` and follow the [OwnerLens Lite verification procedure](openidm/workflow-form/README.md#ownerlens-lite-review).

See the [workflow deployment guide](openidm/WORKFLOW_UI.md) for form and migration details.

## Disable a service principal

Disabling a service principal is the connector's only cloud write. To disable arbitrary service principals, grant the connector app the Microsoft Graph `Application.ReadWrite.All` application permission with administrator consent and restrict access to the OpenIDM update endpoint. See [Graph update permissions](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-update?view=graph-rest-1.0).

Refresh the provisioner schema if it predates this operation. Send an authorized request using the service principal's **object ID**.

```http
PATCH /openidm/system/entra/servicePrincipal/<SERVICE_PRINCIPAL_OBJECT_UUID>
Content-Type: application/json

[{"operation":"replace","field":"/accountEnabled","value":false}]
```

Read back `accountEnabled` and check Entra service principal sign-in logs to verify the result. You can safely retry the same request after a timeout. Disabling prevents new token issuance once Entra applies the change. Existing tokens can remain usable until expiry unless workload identity Continuous Access Evaluation applies. See [CAE prerequisites and behavior](https://learn.microsoft.com/en-us/entra/identity/conditional-access/concept-continuous-access-evaluation-workload).

## Supported scope

- Public Azure cloud with client-secret authentication. Tenant and subscription IDs must be UUIDs. Azure RBAC inventory covers the configured subscriptions.
- Role inventory covers active assignments. PIM eligibility, deny assignments, Conditional Access, access packages, effective-access calculation and ABAC condition evaluation are outside scope.
- Searches filter locally and page through Graph and ARM. Changes during a paged search can affect results. Large tenant performance still needs validation.
- Service principal disabling is the only supported update. Create, delete, end-user authentication through the connector, and LiveSync are unsupported. The companion handles sign-in through OpenIDM.

## Tools Workshop

The [workshop](tools/workshop/) contains the Python installers, OwnerLens payload helper, and workflow BAR packer. Its [tests directory](tools/workshop/tests/) contains the Python tests and reconciliation fixtures. Run the Python commands in this README from the repository root.

```sh
python3 -m unittest discover -s tools/workshop/tests -p 'test_*.py'
```

## Tests and licensing

- `mvn clean verify` runs connector and bundle tests and writes Java coverage to `target/site/jacoco/index.html`.
- `python3 tools/workshop/tests/offline_reconciliation.py` runs OpenIDM reconciliation in Docker against local Graph and OAuth fixtures.
- Run `npm ci` and `npm run test:coverage` in `openidm/workflow-form` for form integration tests. The report is at `target/coverage-typescript/index.html` from the repository root.

CI builds and tests the connector and uploads the JAR as a workflow artifact. See the [CDDL 1.1 license](LICENSE.md) and [dependency notices](NOTICE.md).
