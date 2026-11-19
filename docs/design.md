# Connector design and upstream conventions

## Why a separate OpenICF bundle

OpenIDM's provisioning boundary is OpenICF, not a new REST endpoint inside
OpenIDM. The upstream connectors implement the OpenICF SPI, provide an annotated
configuration bean and ship an OSGi JAR with `ConnectorBundle-FrameworkVersion`,
`ConnectorBundle-Name` and `ConnectorBundle-Version`. A
`conf/provisioner.openicf-<name>.json` instance selects it through `connectorRef`.
Generic UI support comes from the SPI configuration metadata and
the exported schema; custom UI templates are optional.

This standalone POM mirrors the upstream manifest convention using Felix's
Maven Bundle Plugin without inheriting an unreleased upstream parent. It pins
OpenICF 2.0.4, the framework shipped in the locally running OpenIDM 7.1.2. The
minimum connector SPI compatibility header remains 1.5, as in upstream's bundle
parent; the Java runtime requirement is independently Java 17. This is not a
claim that every historical OpenICF deployment is supported.

## Host-provided dependencies

Jackson Databind is explicitly Maven `provided`, together with its transitive
Core/Annotations dependencies. The connector contains no nested dependency JARs,
and does not inline Jackson classes. Required OSGi imports for Jackson packages
use version range `[2.18,3)`; optional imports would hide a missing runtime
dependency, so they are not used. The server tested here supplies Jackson 2.18.6.

This requires installing the connector in OpenIDM's `bundle/` directory and
selecting the OSGi `connectorHostRef` returned by `availableConnectors`. OpenIDM
normally recommends the isolated `connectors/` mode; that classloader does not
automatically see arbitrary OSGi bundles. We intentionally use supported OSGi
mode to satisfy the preference for shared server dependencies without copying
Jackson into `lib/`, changing boot delegation, or modifying OpenIDM source.

The packaged-JAR tests simulate host-provided dependencies on their classpath
and verify the thin artifact. The host Groovy probe separately initializes the
connector, checks all 13 schema types, parses JSON, and asserts that Jackson's
class is supplied by the server's `com.fasterxml.jackson.core.jackson-databind`
bundle. It never calls the cloud or saves tenant configuration.

The repository's legacy `samples/scriptedazure` demonstrates the alternative
scripted connector standard, but targets Azure AD Graph. A native Java bundle
provides a standalone artifact, typed configuration and independent tests for
modern Microsoft Graph and Azure ARM APIs.

## Relationships and governance

Identity classes and assignment/ownership edges are separate object types.
Microsoft Graph and ARM use different audiences, permissions and pagination
fields, so the transport keeps their token caches and URL boundaries separate.
No Graph error is converted into an empty collection, which would be dangerous
for authoritative reconciliation. Query consumers can cancel traversal. Local
filter evaluation preserves ICF semantics at the cost of full scans.
OpenIDM's data browser supplies page sizes and offsets even though cloud APIs
have their own pagination. Client paging is therefore implemented separately:
zero-based offsets (matching the upstream CSV connector), filtering before
offset/limit, one matching lookahead to detect more results, and opaque
object-class-bound continuation cookies. This rescans the collection on each
client page; it provides browsing, not snapshot isolation. Sorting remains
unsupported. Default offset zero is accepted for ordinary unpaged REST queries.

Complex permission definitions are lossless JSON-valued string attributes to
avoid losing nested actions, conditions or scope semantics in a flat ICF schema.
An evaluator above the connector can join these documents to grants and apply
its own rules. The connector does not claim to compute effective authorization.

The Graph v1.0 `/groups/{id}/members` documented service-principal omission is
handled by excluding service principals from that traversal and supplementing
from `/servicePrincipals/{id}/memberOf`, retaining only group relationships.
This also avoids duplicate service-principal membership IDs if Microsoft fixes
the forward endpoint. No beta endpoint is needed.

## Primary sources checked

- [OpenIDM external resource configuration](https://doc.openidentityplatform.org/openidm/integrators-guide/chap-resource-conf)
- [OpenICF repository and connector architecture](https://github.com/OpenIdentityPlatform/OpenICF)
- [Upstream Java connector POM](https://github.com/OpenIdentityPlatform/OpenICF/blob/master/OpenICF-csvfile-connector/pom.xml)
- [Upstream connector bundle manifest conventions](https://github.com/OpenIdentityPlatform/OpenICF/blob/master/OpenICF-java-framework/bundles-parent/pom.xml)
- [OpenIDM scripted bundle generator and generic UI](https://github.com/OpenIdentityPlatform/OpenIDM/tree/master/custom-scripted-connector-bundler)
- [Client credentials flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
- [Graph paging](https://learn.microsoft.com/en-us/graph/paging)
- [Group members and known omission](https://learn.microsoft.com/en-us/graph/api/group-list-members?view=graph-rest-1.0)
- [Service principal memberOf](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list-memberof?view=graph-rest-1.0)
- [App role assignments](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list-approleassignedto?view=graph-rest-1.0)
- [Delegated consent grants](https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-list?view=graph-rest-1.0)
- [Entra role assignments](https://learn.microsoft.com/en-us/graph/api/rbacapplication-list-roleassignments?view=graph-rest-1.0)
- [Azure role assignments](https://learn.microsoft.com/en-us/rest/api/authorization/role-assignments/list-for-subscription?view=rest-authorization-2022-04-01)
- [Azure role definitions](https://learn.microsoft.com/en-us/rest/api/authorization/role-definitions/list?view=rest-authorization-2022-04-01)
