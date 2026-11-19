// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import org.identityconnectors.common.security.GuardedString;
import org.identityconnectors.framework.common.exceptions.*;
import org.identityconnectors.framework.common.objects.*;
import org.identityconnectors.framework.common.objects.filter.FilterBuilder;
import org.junit.jupiter.api.*;
import static org.junit.jupiter.api.Assertions.*;

class EntraConnectorTest {
    static final String ID = "00000000-0000-0000-0000-000000000001";
    HttpServer server;
    String base;
    EntraConfiguration config;
    CloudClient cloud;
    EntraConnector connector;
    Map<String, java.util.function.Consumer<HttpExchange>> routes;
    List<String> requests;
    List<String> tokenForms;
    AtomicInteger tokenCount;

    @BeforeEach void start() throws IOException {
        routes = new ConcurrentHashMap<>(); requests = new CopyOnWriteArrayList<>();
        tokenForms = new CopyOnWriteArrayList<>(); tokenCount = new AtomicInteger();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            requests.add(exchange.getRequestURI().toString());
            if (exchange.getRequestURI().getPath().equals("/token")) {
                tokenForms.add(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
                respond(exchange, 200, "{\"access_token\":\"token-" + tokenCount.incrementAndGet() + "\",\"expires_in\":3600}");
                return;
            }
            if (!Set.of("GET", "PATCH").contains(exchange.getRequestMethod())) { respond(exchange, 405, "{}"); return; }
            if (exchange.getRequestHeaders().getFirst("Authorization") == null) { respond(exchange, 401, "{}"); return; }
            var route = routes.get(exchange.getRequestURI().getPath());
            if (route == null) respond(exchange, 500, "{\"error\":\"missing test fixture\"}");
            else route.accept(exchange);
        });
        server.start(); base = "http://127.0.0.1:" + server.getAddress().getPort();
        config = new EntraConfiguration(); config.setTenantId(ID); config.setClientId(ID);
        config.setClientSecret(new GuardedString("secret +&=".toCharArray())); config.setMaxRetries(1);
        cloud = new CloudClient(config, URI.create(base + "/token"), URI.create(base + "/graph/"), URI.create(base + "/"));
        connector = new EntraConnector(); connector.init(config, cloud);
    }
    @AfterEach void stop() { connector.dispose(); server.stop(0); }
    void route(String path, String json) { routes.put(path, e -> respond(e, 200, json)); }
    static void respond(HttpExchange exchange, int status, String json) {
        try {
            byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes); exchange.close();
        } catch (IOException e) { throw new RuntimeException(e); }
    }
    List<ConnectorObject> read(String type) {
        List<ConnectorObject> objects = new ArrayList<>();
        connector.executeQuery(new ObjectClass(type), null, objects::add, new OperationOptions(Map.of()));
        return objects;
    }
    ScriptContext membershipCheck(String group, String user) {
        return new ScriptContextBuilder("entra", "isGroupMember")
                .addScriptArgument("groupId", group).addScriptArgument("userId", user).build();
    }
    @Test void servicePrincipalIncludesResolvedOutgoingPermissionsAndFreshEmptySnapshots() throws Exception {
        route("/graph/servicePrincipals", """
            {"value":[{"id":"client","displayName":"Client"},{"id":"api","displayName":"Microsoft Graph","appId":"graph-app",
            "appRoles":[{"id":"role","value":"User.Read.All","description":"Read all users"}],
            "oauth2PermissionScopes":[{"value":"Mail.Read","adminConsentDescription":"Read mail"}]}]}
            """);
        route("/graph/oauth2PermissionGrants", """
            {"value":[{"id":"d1","clientId":"client","resourceId":"api","consentType":"Principal","principalId":"user","scope":"Mail.Read Files.Read"},
            {"id":"other","clientId":"other","resourceId":"api","scope":"Wrong.Permission"}]}
            """);
        route("/graph/roleManagement/directory/roleAssignments", """
            {"value":[{"id":"r1","principalId":"client","roleDefinitionId":"admin","directoryScopeId":"/"}]}
            """);
        route("/graph/roleManagement/directory/roleDefinitions", """
            {"value":[{"id":"admin","displayName":"Directory Readers"}]}
            """);
        route("/graph/servicePrincipals/client/appRoleAssignments", "{\"value\":[],\"@odata.nextLink\":\"" + base + "/graph/accessPage2\"}");
        route("/graph/accessPage2", """
            {"value":[{"id":"a1","resourceId":"api","appRoleId":"role"},{"id":"a2","resourceId":"missing","appRoleId":"unknown"}]}
            """);
        route("/graph/servicePrincipals/api/appRoleAssignments", "{\"value\":[]}");
        var objects = read("servicePrincipal");
        String json = AttributeUtil.getSingleValue(objects.get(0).getAttributeByName("grantedAccessJson")).toString();
        var snapshot = CloudClient.JSON.readTree(json);
        assertEquals(5, snapshot.path("permissions").size());
        assertEquals("User.Read.All", snapshot.path("permissions").get(0).path("permission").asText());
        assertEquals("Microsoft Graph", snapshot.path("permissions").get(0).path("resourceName").asText());
        assertTrue(json.contains("Unresolved app role: unknown"));
        assertTrue(json.contains("Directory Readers"));
        assertTrue(json.contains("user"));
        assertFalse(json.contains("Wrong.Permission"));
        assertFalse(snapshot.path("collectedAt").asText().isBlank());
        assertEquals(0, CloudClient.JSON.readTree(AttributeUtil.getSingleValue(objects.get(1).getAttributeByName("grantedAccessJson")).toString()).path("permissions").size());
        route("/graph/servicePrincipals/client/appRoleAssignments", "{\"value\":[]}");
        route("/graph/oauth2PermissionGrants", "{\"value\":[]}");
        route("/graph/roleManagement/directory/roleAssignments", "{\"value\":[]}");
        assertEquals(0, CloudClient.JSON.readTree(AttributeUtil.getSingleValue(read("servicePrincipal").get(0).getAttributeByName("grantedAccessJson")).toString()).path("permissions").size());
        routes.put("/graph/oauth2PermissionGrants", e -> respond(e, 403, "{}"));
        assertThrows(PermissionDeniedException.class, () -> read("servicePrincipal"));
    }
    @Test void checksLiveGroupMembershipAcrossPages() {
        String group = "00000000-0000-0000-0000-000000000002";
        route("/graph/groups/" + group + "/transitiveMembers", "{\"value\":[],\"@odata.nextLink\":\"" + base + "/graph/members2\"}");
        route("/graph/members2", "{\"value\":[{\"id\":\"" + ID + "\"}]}");
        assertEquals(Boolean.TRUE, connector.runScriptOnResource(membershipCheck(group, ID), null));
        assertEquals(Boolean.FALSE, connector.runScriptOnResource(membershipCheck(group, group), null));
    }
    @Test void membershipLookupFailsClosedOnGraphError() {
        String group = "00000000-0000-0000-0000-000000000002";
        routes.put("/graph/groups/" + group + "/transitiveMembers", e -> respond(e, 403, "{}"));
        assertThrows(PermissionDeniedException.class, () -> connector.runScriptOnResource(membershipCheck(group, ID), null));
    }
    @Test void membershipLookupRejectsArbitraryScriptsAndInvalidIdsBeforeNetworkAccess() {
        assertThrows(IllegalArgumentException.class, () -> connector.runScriptOnResource(membershipCheck("../users", ID), null));
        assertThrows(UnsupportedOperationException.class, () -> connector.runScriptOnResource(new ScriptContextBuilder("groovy", "anything").build(), null));
        assertTrue(requests.isEmpty());
    }
    @Test void schemaAdvertisesOnlyServicePrincipalEnabledAsUpdateable() {
        Schema schema = connector.schema();
        assertEquals(13, schema.getObjectClassInfo().size());
        schema.getObjectClassInfo().forEach(type -> type.getAttributeInfo().forEach(attr -> {
            assertFalse(attr.isCreateable());
            assertEquals(type.getType().equals("servicePrincipal") && attr.getName().equals("accountEnabled"), attr.isUpdateable());
        }));
    }
    @Test void disablesServicePrincipalWithExactPatchAndEmptyResponse() {
        routes.put("/graph/servicePrincipals/" + ID, e -> {
            assertEquals("PATCH", e.getRequestMethod());
            assertEquals("application/json", e.getRequestHeaders().getFirst("Content-Type"));
            try {
                assertEquals("{\"accountEnabled\":false}", new String(e.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
                e.sendResponseHeaders(204, -1); e.close();
            } catch (IOException ex) { throw new RuntimeException(ex); }
        });
        assertEquals(new Uid(ID), connector.update(new ObjectClass("servicePrincipal"), new Uid(ID),
                Set.of(AttributeBuilder.build("accountEnabled", false)), null));
        assertEquals(List.of("/token", "/graph/servicePrincipals/" + ID), requests);
    }
    @Test void disableRefreshesRejectedTokenAndRetriesThrottling() {
        AtomicInteger calls = new AtomicInteger();
        List<String> bodies = new CopyOnWriteArrayList<>();
        routes.put("/graph/servicePrincipals/" + ID, e -> {
            try { bodies.add(new String(e.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)); }
            catch (IOException ex) { throw new RuntimeException(ex); }
            int call = calls.incrementAndGet();
            if (call == 1) respond(e, 401, "{}");
            else if (call == 2) {
                e.getResponseHeaders().add("Retry-After", "0"); respond(e, 429, "{}");
            } else {
                try { e.sendResponseHeaders(204, -1); e.close(); }
                catch (IOException ex) { throw new RuntimeException(ex); }
            }
        });
        connector.update(new ObjectClass("servicePrincipal"), new Uid(ID),
                Set.of(AttributeBuilder.build("accountEnabled", false)), null);
        assertEquals(3, calls.get());
        assertEquals(2, tokenCount.get());
        assertEquals(Collections.nCopies(3, "{\"accountEnabled\":false}"), bodies);
    }
    @Test void rejectsOtherWritesBeforeNetworkAccess() {
        var type = new ObjectClass("servicePrincipal");
        var disable = Set.of(AttributeBuilder.build("accountEnabled", false));
        assertThrows(UnsupportedOperationException.class, () -> connector.update(ObjectClass.ACCOUNT, new Uid(ID), disable, null));
        for (String id : List.of("../users", "not-an-id", ID + "?x=y"))
            assertThrows(IllegalArgumentException.class, () -> connector.update(type, new Uid(id), disable, null));
        for (Set<Attribute> attrs : List.of(Set.<Attribute>of(),
                Set.of(AttributeBuilder.build("accountEnabled", true)),
                Set.of(AttributeBuilder.build("accountEnabled", "false")),
                Set.of(AttributeBuilder.build("accountEnabled")),
                Set.of(AttributeBuilder.build("accountEnabled", false, true)),
                Set.of(AttributeBuilder.build("displayName", "new")),
                Set.of(AttributeBuilder.build("accountEnabled", false), AttributeBuilder.build("displayName", "new"))))
            assertThrows(IllegalArgumentException.class, () -> connector.update(type, new Uid(ID), attrs, null));
        assertTrue(requests.isEmpty());
    }
    @Test void disablePropagatesErrorsAndBoundsRetries() {
        var type = new ObjectClass("servicePrincipal");
        var attrs = Set.of(AttributeBuilder.build("accountEnabled", false));
        for (int status : List.of(403, 404, 400, 429, 503, 401)) {
            AtomicInteger calls = new AtomicInteger();
            routes.put("/graph/servicePrincipals/" + ID, e -> {
                calls.incrementAndGet();
                e.getResponseHeaders().add("Retry-After", "0");
                respond(e, status, "{}");
            });
            Class<? extends RuntimeException> expected = switch (status) {
                case 403 -> PermissionDeniedException.class;
                case 404 -> UnknownUidException.class;
                case 429, 503 -> RetryableException.class;
                case 401 -> InvalidCredentialException.class;
                default -> ConnectorException.class;
            };
            assertThrows(expected, () -> connector.update(type, new Uid(ID), attrs, null));
            assertEquals(Set.of(401, 429, 503).contains(status) ? 2 : 1, calls.get());
        }
    }
    @Test void streamsPagesAndCachesCorrectlyEncodedGraphToken() {
        route("/graph/users", "{\"value\":[{\"id\":\"u1\",\"displayName\":\"Same\",\"accountEnabled\":true}],\"@odata.nextLink\":\"" + base + "/graph/page2?$skiptoken=a%2Bb\"}");
        route("/graph/page2", "{\"value\":[{\"id\":\"u2\",\"displayName\":\"Same\"}]}");
        var objects = read("__ACCOUNT__");
        assertEquals(List.of("u1", "u2"), objects.stream().map(o -> o.getUid().getUidValue()).toList());
        assertEquals("u1", objects.get(0).getName().getNameValue());
        assertEquals(Boolean.TRUE, AttributeUtil.getSingleValue(objects.get(0).getAttributeByName("accountEnabled")));
        assertTrue(requests.contains("/graph/page2?$skiptoken=a%2Bb"));
        assertEquals(1, tokenCount.get());
        assertTrue(tokenForms.get(0).contains("client_secret=secret+%2B%26%3D"));
        assertTrue(tokenForms.get(0).contains("scope=https%3A%2F%2Fgraph.microsoft.com%2F.default"));
    }
    @Test void includesProfileFieldsForPreprovisionedOpenidmUsers() {
        route("/graph/users", "{\"value\":[{\"id\":\"u1\",\"givenName\":\"Ada\",\"surname\":\"Lovelace\",\"userPrincipalName\":\"ada@example.org\",\"accountEnabled\":true}]}");
        var user = read("__ACCOUNT__").get(0);
        assertEquals("Ada", AttributeUtil.getSingleValue(user.getAttributeByName("givenName")));
        assertEquals("Lovelace", AttributeUtil.getSingleValue(user.getAttributeByName("surname")));
        assertTrue(requests.stream().anyMatch(p -> p.contains("givenName") && p.contains("surname")));
        var attributes = connector.schema().findObjectClassInfo(ObjectClass.ACCOUNT.getObjectClassValue()).getAttributeInfo();
        assertTrue(attributes.stream().anyMatch(a -> a.getName().equals("givenName")));
        assertTrue(attributes.stream().anyMatch(a -> a.getName().equals("surname")));
    }
    @Test void consumerCancellationDoesNotFetchNextPage() {
        route("/graph/users", "{\"value\":[{\"id\":\"u1\"}],\"@odata.nextLink\":\"" + base + "/graph/notFetched\"}");
        connector.executeQuery(ObjectClass.ACCOUNT, null, object -> false, null);
        assertFalse(requests.contains("/graph/notFetched"));
    }
    @Test void appliesIcfFiltersWithoutInterpolatingOdata() {
        route("/graph/users", "{\"value\":[{\"id\":\"u1\"},{\"id\":\"u2\"}]}");
        List<ConnectorObject> found = new ArrayList<>();
        var filter = FilterBuilder.equalTo(new Uid("u2"));
        var translated = connector.createFilterTranslator(ObjectClass.ACCOUNT, null).translate(filter);
        connector.executeQuery(ObjectClass.ACCOUNT, translated.get(0), found::add, null);
        assertEquals("u2", found.get(0).getUid().getUidValue()); assertEquals(1, found.size());
    }
    @Test void preservesComplexApplicationPermissions() {
        route("/graph/applications", "{\"value\":[{\"id\":\"a1\",\"appId\":\"client1\",\"requiredResourceAccess\":[{\"resourceAppId\":\"graph\",\"resourceAccess\":[{\"id\":\"p1\",\"type\":\"Role\"}]}]}]}");
        var app = read("application").get(0);
        String json = (String)AttributeUtil.getSingleValue(app.getAttributeByName("requiredResourceAccessJson"));
        assertTrue(json.contains("resourceAccess")); assertTrue(json.contains("p1"));
    }
    @Test void groupMembershipCombinesUsersNestedGroupsAndInverseServicePrincipals() {
        route("/graph/groups", "{\"value\":[{\"id\":\"g1\"}]}");
        route("/graph/groups/g1/members", "{\"value\":[{\"id\":\"u1\",\"@odata.type\":\"#microsoft.graph.user\"},{\"id\":\"g2\",\"@odata.type\":\"#microsoft.graph.group\"},{\"id\":\"s1\",\"@odata.type\":\"#microsoft.graph.servicePrincipal\"}]}");
        route("/graph/servicePrincipals", "{\"value\":[{\"id\":\"s1\"}]}");
        route("/graph/servicePrincipals/s1/memberOf", "{\"value\":[{\"id\":\"role1\",\"@odata.type\":\"#microsoft.graph.directoryRole\"}],\"@odata.nextLink\":\"" + base + "/graph/spGroups\"}");
        route("/graph/spGroups", "{\"value\":[{\"id\":\"g1\",\"@odata.type\":\"#microsoft.graph.group\"}]}");
        assertEquals(List.of("g1:u1", "g1:g2", "g1:s1"), read("groupMembership").stream().map(o -> o.getUid().getUidValue()).toList());
    }
    @Test void streamsAppAssignmentsForAllResourcePrincipals() {
        route("/graph/servicePrincipals", "{\"value\":[{\"id\":\"r1\"}],\"@odata.nextLink\":\"" + base + "/graph/resources2\"}");
        route("/graph/resources2", "{\"value\":[{\"id\":\"r2\"}]}");
        route("/graph/servicePrincipals/r1/appRoleAssignedTo", "{\"value\":[{\"id\":\"grant1\",\"principalId\":\"s1\",\"principalType\":\"ServicePrincipal\",\"appRoleId\":\"role1\",\"resourceId\":\"r1\"}]}");
        route("/graph/servicePrincipals/r2/appRoleAssignedTo", "{\"value\":[{\"id\":\"grant2\",\"principalId\":\"u1\",\"principalType\":\"User\"}]}");
        assertEquals(2, read("appRoleAssignment").size());
    }
    @Test void azureUsesSeparateTokenAudienceAndFlattensProperties() {
        config.setSubscriptionIds(new String[]{ID});
        route("/graph/users", "{\"value\":[]}"); read("__ACCOUNT__");
        String path = "/subscriptions/" + ID + "/providers/Microsoft.Authorization/roleAssignments";
        route(path, "{\"value\":[{\"id\":\"/subscriptions/" + ID + "/providers/Microsoft.Authorization/roleAssignments/r1\",\"properties\":{\"principalId\":\"s1\",\"scope\":\"/subscriptions/" + ID + "\",\"condition\":\"expression\"}}],\"nextLink\":\"" + base + path + "/page2?api-version=2022-04-01\"}");
        route(path + "/page2", "{\"value\":[]}");
        var object = read("azureRoleAssignment").get(0);
        assertEquals("s1", AttributeUtil.getSingleValue(object.getAttributeByName("principalId")));
        assertEquals("expression", AttributeUtil.getSingleValue(object.getAttributeByName("condition")));
        assertEquals(ID, AttributeUtil.getSingleValue(object.getAttributeByName("subscriptionId")));
        assertEquals(2, tokenCount.get());
        assertTrue(tokenForms.get(1).contains("scope=https%3A%2F%2Fmanagement.azure.com%2F.default"));
    }
    @Test void unconfiguredAzureFailsInsteadOfReturningEmptyInventory() {
        assertThrows(ConfigurationException.class, () -> read("azureRoleAssignment"));
    }
    @Test void forbiddenFailsInsteadOfReturningEmptyInventoryOrLeakingResponse() {
        routes.put("/graph/users", e -> respond(e, 403, "{\"secret\":\"do-not-log\"}"));
        var error = assertThrows(PermissionDeniedException.class, () -> read("__ACCOUNT__"));
        assertFalse(error.toString().contains("do-not-log"));
    }
    @Test void retries429UsingRetryAfter() {
        AtomicInteger calls = new AtomicInteger();
        routes.put("/graph/users", e -> {
            if (calls.incrementAndGet() == 1) { e.getResponseHeaders().add("Retry-After", "0"); respond(e, 429, "{}"); }
            else respond(e, 200, "{\"value\":[{\"id\":\"u1\"}]}");
        });
        assertEquals(1, read("__ACCOUNT__").size()); assertEquals(2, calls.get());
    }
    @Test void honorsLongRetryAfterWithoutSleepingOrRetryingEarly() {
        routes.put("/graph/users", e -> { e.getResponseHeaders().add("Retry-After", "120"); respond(e, 429, "{}"); });
        assertThrows(RetryableException.class, () -> read("__ACCOUNT__"));
        assertEquals(1, requests.stream().filter(p -> p.startsWith("/graph/users")).count());
    }
    @Test void refreshesRejectedTokenOnlyOnce() {
        routes.put("/graph/users", e -> respond(e, 401, "{}"));
        assertThrows(InvalidCredentialException.class, () -> read("__ACCOUNT__"));
        assertEquals(2, tokenCount.get());
    }
    @Test void rejectsExternalPaginationBeforeSendingToken() {
        route("/graph/users", "{\"value\":[],\"@odata.nextLink\":\"https://example.org/steal\"}");
        assertThrows(ConnectorException.class, () -> read("__ACCOUNT__"));
        assertEquals(2, requests.size());
    }
    @Test void rejectsRepeatedPaginationAndMalformedCollections() {
        route("/graph/users", "{\"value\":[],\"@odata.nextLink\":\"" + base + "/graph/users\"}");
        assertThrows(ConnectorException.class, () -> read("__ACCOUNT__"));
        route("/graph/users", "{}");
        assertThrows(ConnectorException.class, () -> read("__ACCOUNT__"));
    }
    @Test void missingIdsAbortInventory() {
        route("/graph/users", "{\"value\":[{\"displayName\":\"missing ID\"}]}");
        assertThrows(ConnectorException.class, () -> read("__ACCOUNT__"));
    }
    static final class Page implements org.identityconnectors.framework.spi.SearchResultsHandler {
        final List<ConnectorObject> objects = new ArrayList<>();
        SearchResult result;
        @Override public boolean handle(ConnectorObject object) { objects.add(object); return true; }
        @Override public void handleResult(SearchResult value) { result = value; }
    }
    @Test void openIdmClientPagingReturnsContinuationAcrossGraphPages() {
        route("/graph/users", "{\"value\":[{\"id\":\"u1\"},{\"id\":\"u2\"}],\"@odata.nextLink\":\"" + base + "/graph/page2\"}");
        route("/graph/page2", "{\"value\":[{\"id\":\"u3\"}]}");
        Page first = new Page();
        connector.executeQuery(ObjectClass.ACCOUNT, null, first,
                new OperationOptions(Map.of(OperationOptions.OP_PAGE_SIZE, 2, OperationOptions.OP_PAGED_RESULTS_OFFSET, 0)));
        assertEquals(List.of("u1", "u2"), first.objects.stream().map(o -> o.getUid().getUidValue()).toList());
        assertNotNull(first.result); assertNotNull(first.result.getPagedResultsCookie());
        Page second = new Page();
        connector.executeQuery(ObjectClass.ACCOUNT, null, second,
                new OperationOptions(Map.of(OperationOptions.OP_PAGE_SIZE, 2, OperationOptions.OP_PAGED_RESULTS_COOKIE, first.result.getPagedResultsCookie())));
        assertEquals(List.of("u3"), second.objects.stream().map(o -> o.getUid().getUidValue()).toList());
        assertNotNull(second.result); assertNull(second.result.getPagedResultsCookie());
    }
    @Test void zeroOffsetWithoutPageSizeDoesNotBreakDefaultOpenIdmQueries() {
        route("/graph/users", "{\"value\":[{\"id\":\"u1\"}]}");
        Page page = new Page();
        connector.executeQuery(ObjectClass.ACCOUNT, null, page,
                new OperationOptions(Map.of(OperationOptions.OP_PAGED_RESULTS_OFFSET, 0)));
        assertEquals(1, page.objects.size());
        assertNull(page.result.getPagedResultsCookie());
    }
    @Test void pagingOffsetAppliesAfterFilteringAndDetectsExactLastPage() {
        route("/graph/users", "{\"value\":[{\"id\":\"u0\",\"userType\":\"Guest\"},{\"id\":\"u1\",\"userType\":\"Member\"},{\"id\":\"u2\",\"userType\":\"Member\"}]}");
        Page page = new Page();
        connector.executeQuery(ObjectClass.ACCOUNT, FilterBuilder.equalTo(AttributeBuilder.build("userType", "Member")), page,
                new OperationOptions(Map.of(OperationOptions.OP_PAGE_SIZE, 1, OperationOptions.OP_PAGED_RESULTS_OFFSET, 1)));
        assertEquals(List.of("u2"), page.objects.stream().map(o -> o.getUid().getUidValue()).toList());
        assertNull(page.result.getPagedResultsCookie());
    }
    @Test void membershipPagingContinuesIntoInverseServicePrincipalRelationships() {
        route("/graph/groups", "{\"value\":[{\"id\":\"g1\"}]}");
        route("/graph/groups/g1/members", "{\"value\":[{\"id\":\"u1\",\"@odata.type\":\"#microsoft.graph.user\"}]}");
        route("/graph/servicePrincipals", "{\"value\":[{\"id\":\"s1\"}]}");
        route("/graph/servicePrincipals/s1/memberOf", "{\"value\":[{\"id\":\"g1\",\"@odata.type\":\"#microsoft.graph.group\"}]}");
        Page first = new Page();
        connector.executeQuery(new ObjectClass("groupMembership"), null, first,
                new OperationOptions(Map.of(OperationOptions.OP_PAGE_SIZE, 1)));
        assertEquals("g1:u1", first.objects.get(0).getUid().getUidValue());
        assertNotNull(first.result.getPagedResultsCookie());
        Page second = new Page();
        connector.executeQuery(new ObjectClass("groupMembership"), null, second,
                new OperationOptions(Map.of(OperationOptions.OP_PAGE_SIZE, 1, OperationOptions.OP_PAGED_RESULTS_COOKIE, first.result.getPagedResultsCookie())));
        assertEquals("g1:s1", second.objects.get(0).getUid().getUidValue());
        assertNull(second.result.getPagedResultsCookie());
    }
    @Test void malformedOrWrongObjectClassCookiesAreRejectedBeforeNetworkAccess() {
        for (String cookie : List.of("invalid!", java.util.Base64.getUrlEncoder().encodeToString("v1\n__GROUP__\n1".getBytes(StandardCharsets.UTF_8)))) {
            assertThrows(IllegalArgumentException.class, () -> connector.executeQuery(ObjectClass.ACCOUNT, null,
                    new Page(), new OperationOptions(Map.of(OperationOptions.OP_PAGED_RESULTS_COOKIE, cookie))));
        }
        assertTrue(requests.isEmpty());
    }
    @Test void validatesConfigurationBeforeAnyNetworkRequest() {
        config.setTenantId("../common");
        assertThrows(ConfigurationException.class, config::validate); assertTrue(requests.isEmpty());
    }
    @Test void directoryDefinitionsExpandInheritanceAndKeepPermissionDocuments() {
        route("/graph/roleManagement/directory/roleDefinitions", "{\"value\":[{\"id\":\"role1\",\"rolePermissions\":[{\"allowedResourceActions\":[\"read\"]}],\"inheritsPermissionsFrom\":[{\"id\":\"role0\"}]}]}");
        var role = read("directoryRoleDefinition").get(0);
        assertTrue(requests.contains("/graph/roleManagement/directory/roleDefinitions?$expand=inheritsPermissionsFrom"));
        assertTrue(AttributeUtil.getSingleValue(role.getAttributeByName("inheritsPermissionsFromJson")).toString().contains("role0"));
    }
    @Test void emptyNullAndNonObjectResponsesAbortInventory() {
        for (String response : List.of("", "null", "[]", "not-json")) {
            route("/graph/users", response);
            assertThrows(ConnectorException.class, () -> read("__ACCOUNT__"));
        }
    }
    @Test void paginationCannotTraverseOutOfGraphApiPath() {
        route("/graph/users", "{\"value\":[],\"@odata.nextLink\":\"" + base + "/graph/%2e%2e/token\"}");
        assertThrows(ConnectorException.class, () -> read("__ACCOUNT__"));
        assertEquals(2, requests.size());
    }
    @Test void azurePaginationCannotReadAnotherSubscription() {
        config.setSubscriptionIds(new String[]{ID});
        String path = "/subscriptions/" + ID + "/providers/Microsoft.Authorization/roleDefinitions";
        route(path, "{\"value\":[],\"nextLink\":\"" + base + "/subscriptions/00000000-0000-0000-0000-000000000002/providers/Microsoft.Authorization/roleDefinitions\"}");
        assertThrows(ConnectorException.class, () -> read("azureRoleDefinition"));
        assertEquals(2, requests.size());
    }
}
