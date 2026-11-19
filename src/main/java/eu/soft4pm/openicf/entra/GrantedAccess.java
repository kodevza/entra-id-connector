// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import java.time.Instant;
import java.util.*;
import java.util.function.Predicate;

/** A fresh, direct-grant snapshot per service-principal search; never a consent inference. */
final class GrantedAccess {
    private final CloudClient cloud;
    GrantedAccess(CloudClient cloud) { this.cloud = cloud; }

    private List<JsonNode> list(String path) {
        List<JsonNode> result = new ArrayList<>();
        cloud.each(CloudClient.Api.GRAPH, path, node -> { result.add(node); return true; });
        return result;
    }
    private static Map<String, JsonNode> index(List<JsonNode> nodes) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        nodes.forEach(n -> result.put(n.path("id").asText(), n));
        return result;
    }
    private static Map<String, List<JsonNode>> group(List<JsonNode> nodes, String field) {
        Map<String, List<JsonNode>> result = new HashMap<>();
        nodes.forEach(n -> result.computeIfAbsent(n.path(field).asText(), key -> new ArrayList<>()).add(n));
        return result;
    }
    boolean each(Predicate<JsonNode> consume) {
        Map<String, JsonNode> principals = index(list(ResourceType.SERVICE_PRINCIPAL.collection()));
        if (principals.isEmpty()) return true;
        // Resolve definitions once per inventory, including every upstream page.
        Map<String, List<JsonNode>> delegated = group(list(ResourceType.OAUTH_GRANT.collection()), "clientId");
        Map<String, List<JsonNode>> directory = group(list(ResourceType.DIRECTORY_ROLE_ASSIGNMENT.collection()), "principalId");
        Map<String, JsonNode> definitions = index(list(ResourceType.DIRECTORY_ROLE_DEFINITION.collection()));
        for (var entry : principals.entrySet()) {
            String id = entry.getKey();
            ObjectNode snapshot = CloudClient.JSON.createObjectNode();
            snapshot.put("coverage", "Direct Entra API grants and active directory roles; excludes group-derived access, PIM eligibility, Azure RBAC and resource-specific ACLs.");
            ArrayNode permissions = snapshot.putArray("permissions");
            for (JsonNode grant : list("servicePrincipals/" + CloudClient.encode(id) + "/appRoleAssignments")) {
                ObjectNode item = permission(permissions, "application", grant);
                JsonNode resource = principals.get(grant.path("resourceId").asText());
                resource(item, resource, grant);
                String roleId = grant.path("appRoleId").asText();
                item.put("permissionId", roleId);
                JsonNode definition = find(resource, "appRoles", "id", roleId);
                if (definition != null) {
                    item.put("permission", definition.path("value").asText(roleId));
                    item.put("displayName", definition.path("displayName").asText());
                    item.put("description", definition.path("description").asText());
                } else item.put("permission", roleId.equals("00000000-0000-0000-0000-000000000000")
                        ? "Default access (no specific app role)" : "Unresolved app role: " + roleId);
            }
            for (JsonNode grant : delegated.getOrDefault(id, List.of())) {
                for (String scope : grant.path("scope").asText().trim().split("\\s+")) {
                    if (scope.isEmpty()) continue;
                    ObjectNode item = permission(permissions, "delegated", grant);
                    JsonNode resource = principals.get(grant.path("resourceId").asText());
                    resource(item, resource, grant);
                    item.put("permission", scope);
                    item.set("consentType", grant.path("consentType"));
                    item.set("principalId", grant.path("principalId"));
                    JsonNode definition = find(resource, "oauth2PermissionScopes", "value", scope);
                    if (definition != null) item.put("description", definition.path("adminConsentDescription").asText());
                }
            }
            for (JsonNode grant : directory.getOrDefault(id, List.of())) {
                ObjectNode item = permission(permissions, "directoryRole", grant);
                String roleId = grant.path("roleDefinitionId").asText();
                JsonNode definition = definitions.get(roleId);
                item.put("permissionId", roleId);
                item.put("permission", definition == null ? "Unresolved directory role: " + roleId : definition.path("displayName").asText(roleId));
                item.set("directoryScopeId", grant.path("directoryScopeId"));
                item.set("appScopeId", grant.path("appScopeId"));
                if (definition != null) item.set("rolePermissions", definition.path("rolePermissions"));
            }
            snapshot.put("collectedAt", Instant.now().toString());
            ObjectNode enriched = entry.getValue().deepCopy();
            enriched.set("grantedAccess", snapshot);
            if (!consume.test(enriched)) return false;
        }
        return true;
    }
    private static ObjectNode permission(ArrayNode permissions, String kind, JsonNode grant) {
        ObjectNode item = permissions.addObject().put("kind", kind);
        item.set("grantId", grant.path("id"));
        return item;
    }
    private static void resource(ObjectNode item, JsonNode resource, JsonNode grant) {
        String id = grant.path("resourceId").asText();
        item.put("resourceId", id);
        item.put("resourceName", resource == null ? grant.path("resourceDisplayName").asText(id) : resource.path("displayName").asText(id));
        if (resource != null) item.set("resourceAppId", resource.path("appId"));
    }
    private static JsonNode find(JsonNode resource, String collection, String field, String value) {
        if (resource != null) for (JsonNode definition : resource.path(collection))
            if (definition.path(field).asText().equals(value)) return definition;
        return null;
    }
}
