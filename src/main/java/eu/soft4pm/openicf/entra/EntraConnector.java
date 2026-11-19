// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.ArrayList;
import java.util.List;
import org.identityconnectors.framework.common.exceptions.ConfigurationException;
import org.identityconnectors.framework.common.exceptions.ConnectorException;
import org.identityconnectors.framework.common.objects.*;
import org.identityconnectors.framework.common.objects.filter.Filter;
import org.identityconnectors.framework.common.objects.filter.FilterTranslator;
import org.identityconnectors.framework.spi.*;
import org.identityconnectors.framework.spi.operations.*;

/** Inventory and service-principal blocking through the standard OpenICF SPI. */
@ConnectorClass(displayNameKey="connector.display", configurationClass=EntraConfiguration.class)
public final class EntraConnector implements Connector, SchemaOp, SearchOp<Filter>, TestOp, ScriptOnResourceOp, UpdateOp {
    private EntraConfiguration configuration;
    private CloudClient cloud;

    @Override public void init(Configuration value) {
        EntraConfiguration config = (EntraConfiguration)value;
        config.validate(); configuration = config; cloud = new CloudClient(config);
    }
    // Allows exercising the actual connector SPI with an offline server.
    void init(EntraConfiguration config, CloudClient client) {
        config.validate(); configuration = config; cloud = client;
    }
    @Override public Configuration getConfiguration() { return configuration; }
    @Override public void dispose() { if (cloud != null) cloud.close(); cloud = null; configuration = null; }

    /** Deliberately narrow write surface: disabling a service principal only. */
    @Override public Uid update(ObjectClass objectClass, Uid uid,
            java.util.Set<Attribute> attributes, OperationOptions options) {
        requireInitialized();
        if (ResourceType.of(objectClass) != ResourceType.SERVICE_PRINCIPAL)
            throw new UnsupportedOperationException("Only servicePrincipal can be updated");
        if (uid == null || !uid.getUidValue().matches("(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"))
            throw new IllegalArgumentException("Service principal UID must be an object UUID");
        if (attributes == null || attributes.size() != 1)
            throw new IllegalArgumentException("Only accountEnabled=false is supported");
        Attribute attribute = attributes.iterator().next();
        if (attribute == null || !"accountEnabled".equals(attribute.getName())
                || attribute.getValue() == null || attribute.getValue().size() != 1
                || !Boolean.FALSE.equals(attribute.getValue().get(0)))
            throw new IllegalArgumentException("Only accountEnabled=false is supported");
        cloud.disableServicePrincipal(uid.getUidValue());
        return uid;
    }

    /** Fixed read-only action used by OpenIDM after OIDC validation. No script evaluation. */
    @Override public Object runScriptOnResource(ScriptContext context, OperationOptions options) {
        requireInitialized();
        if (!"entra".equals(context.getScriptLanguage()) || !"isGroupMember".equals(context.getScriptText()))
            throw new UnsupportedOperationException("Only the isGroupMember read action is supported");
        String group = membershipId(context.getScriptArguments().get("groupId"));
        String user = membershipId(context.getScriptArguments().get("userId"));
        boolean[] found = {false};
        // No OData cast/filter: this endpoint also includes nested group membership
        // and does not require the advanced-query eventual-consistency index.
        cloud.each(CloudClient.Api.GRAPH, "groups/" + group + "/transitiveMembers", member -> {
            found[0] = user.equalsIgnoreCase(requiredId(member));
            return !found[0];
        });
        return found[0];
    }
    private static String membershipId(Object value) {
        if (!(value instanceof String text) || !text.matches("(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"))
            throw new IllegalArgumentException("Membership check requires UUID groupId and userId");
        return java.util.UUID.fromString(text).toString();
    }

    @Override public Schema schema() {
        SchemaBuilder schema = new SchemaBuilder(EntraConnector.class);
        for (ResourceType type : ResourceType.values()) {
            ObjectClassInfoBuilder object = new ObjectClassInfoBuilder().setType(type.objectClass);
            object.addAttributeInfo(readOnly(Name.NAME, String.class, false));
            object.addAttributeInfo(readOnly("objectType", String.class, false));
            for (ResourceType.Field field : type.fields)
                object.addAttributeInfo(new AttributeInfoBuilder(field.attribute(), field.javaType())
                        .setCreateable(false)
                        .setUpdateable(type == ResourceType.SERVICE_PRINCIPAL && field.attribute().equals("accountEnabled"))
                        .setMultiValued(field.kind().equals("multi")).build());
            ObjectClassInfo info = object.build();
            schema.defineObjectClass(info);
            if (type != ResourceType.SERVICE_PRINCIPAL)
                schema.removeSupportedObjectClass(UpdateOp.class, info);
        }
        schema.defineOperationOption(OperationOptionInfoBuilder.buildPageSize(), SearchOp.class);
        schema.defineOperationOption(OperationOptionInfoBuilder.buildPagedResultsOffset(), SearchOp.class);
        schema.defineOperationOption(OperationOptionInfoBuilder.buildPagedResultsCookie(), SearchOp.class);
        return schema.build();
    }
    private static AttributeInfo readOnly(String name, Class<?> type, boolean multi) {
        return new AttributeInfoBuilder(name, type).setCreateable(false).setUpdateable(false)
                .setMultiValued(multi).build();
    }

    @Override public FilterTranslator<Filter> createFilterTranslator(ObjectClass type, OperationOptions options) {
        ResourceType.of(type);
        // Local evaluation preserves the full ICF filter semantics (no unsafe OData interpolation).
        return filter -> filter == null ? java.util.Collections.singletonList(null) : List.of(filter);
    }
    @Override public void executeQuery(ObjectClass objectClass, Filter filter, ResultsHandler handler, OperationOptions options) {
        ResourceType type = ResourceType.of(objectClass);
        requireInitialized();
        if (options != null && options.getSortKeys() != null && options.getSortKeys().length > 0)
            throw new UnsupportedOperationException("Client sorting is not supported");
        ClientPage page = new ClientPage(type, options);
        java.util.function.Predicate<JsonNode> consume = node -> {
            ConnectorObject object = convert(type, node);
            return filter != null && !filter.accept(object) || page.handle(object, handler);
        };
        boolean complete = true;
        if (type == ResourceType.SERVICE_PRINCIPAL) {
            complete = new GrantedAccess(cloud).each(consume);
        } else if (type.azure()) {
            String[] subscriptions = configuration.getSubscriptionIds();
            if (subscriptions.length == 0) throw new ConfigurationException("Azure RBAC inventory requires subscriptionIds; it is not an empty inventory");
            for (String subscription : subscriptions) {
                complete = cloud.each(CloudClient.Api.ARM, "subscriptions/" + subscription
                        + "/providers/Microsoft.Authorization/" + type.path + "?api-version=2022-04-01", node -> {
                    ObjectNode flattened = node.deepCopy();
                    JsonNode properties = flattened.remove("properties");
                    if (properties != null && properties.isObject()) flattened.setAll((ObjectNode)properties);
                    flattened.put("subscriptionId", subscription);
                    return consume.test(flattened);
                });
                if (!complete) break;
            }
        } else if (type.child != null) {
            complete = cloud.each(CloudClient.Api.GRAPH, type.path + "?$select=id", parent -> {
                String source = requiredId(parent);
                return cloud.each(CloudClient.Api.GRAPH, type.path + "/" + CloudClient.encode(source) + "/" + type.child, child -> {
                    if (type == ResourceType.GROUP_MEMBERSHIP && "#microsoft.graph.servicePrincipal".equals(child.path("@odata.type").asText())) return true;
                    ObjectNode enriched = child.deepCopy();
                    if (type.edge()) {
                        String target = requiredId(child);
                        enriched.put("id", source + ":" + target).put("sourceId", source).put("targetId", target)
                                .put("targetType", child.path("@odata.type").asText("#microsoft.graph.directoryObject"));
                    }
                    return consume.test(enriched);
                });
            });
        } else complete = cloud.each(CloudClient.Api.GRAPH, type.collection(), consume);
        if (type == ResourceType.GROUP_MEMBERSHIP && complete) {
            // Graph v1.0 group/members omits service principals. Read their inverse relationship.
            complete = cloud.each(CloudClient.Api.GRAPH, "servicePrincipals?$select=id", principal -> {
                String target = requiredId(principal);
                return cloud.each(CloudClient.Api.GRAPH, "servicePrincipals/" + CloudClient.encode(target) + "/memberOf", group -> {
                    if (!"#microsoft.graph.group".equals(group.path("@odata.type").asText())) return true;
                    String source = requiredId(group);
                    ObjectNode edge = CloudClient.JSON.createObjectNode().put("id", source + ":" + target)
                            .put("sourceId", source).put("targetId", target).put("targetType", "#microsoft.graph.servicePrincipal");
                    return consume.test(edge);
                });
            });
        }
        if (handler instanceof SearchResultsHandler results && !page.cancelled)
            results.handleResult(new SearchResult(page.cookie(), SearchResult.NO_COUNT));
    }

    /** Offset-based browsing follows the upstream CSV connector convention (zero-based offset). */
    private static final class ClientPage {
        private final ResourceType type;
        private final int offset;
        private final int limit;
        private long seen;
        private int delivered;
        private boolean more;
        private boolean cancelled;
        ClientPage(ResourceType type, OperationOptions options) {
            this.type = type;
            int start = options == null || options.getPagedResultsOffset() == null ? 0 : options.getPagedResultsOffset();
            limit = options == null || options.getPageSize() == null ? 0 : options.getPageSize();
            if (limit < 0 || start < 0) throw new IllegalArgumentException("Page size and offset cannot be negative");
            if (options != null && options.getPagedResultsCookie() != null) {
                try {
                    String decoded = new String(java.util.Base64.getUrlDecoder().decode(options.getPagedResultsCookie()), java.nio.charset.StandardCharsets.UTF_8);
                    String[] fields = decoded.split("\\n", -1);
                    if (fields.length != 3 || !fields[0].equals("v1") || !fields[1].equals(type.objectClass)) throw new IllegalArgumentException();
                    start = Integer.parseInt(fields[2]);
                    if (start < 0) throw new IllegalArgumentException();
                } catch (IllegalArgumentException e) { throw new IllegalArgumentException("Invalid continuation cookie"); }
            }
            if ((long)start + limit > Integer.MAX_VALUE) throw new IllegalArgumentException("Paging offset is too large");
            offset = start;
        }
        boolean handle(ConnectorObject object, ResultsHandler handler) {
            if (seen++ < offset) return true;
            // A single matching lookahead distinguishes the last page from a page with more results.
            if (limit > 0 && delivered == limit) { more = true; return false; }
            delivered++;
            if (!handler.handle(object)) { cancelled = true; return false; }
            return true;
        }
        String cookie() {
            if (!more) return null;
            String value = "v1\n" + type.objectClass + "\n" + (offset + delivered);
            return java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
    }

    private static ConnectorObject convert(ResourceType type, JsonNode node) {
        String id = requiredId(node);
        // Object ID is unique and stable; display names are neither. This also keeps __NAME__ reads unambiguous.
        ConnectorObjectBuilder object = new ConnectorObjectBuilder().setObjectClass(new ObjectClass(type.objectClass)).setUid(id).setName(id);
        object.addAttribute("objectType", node.path("@odata.type").asText(type.objectClass));
        for (ResourceType.Field field : type.fields) {
            JsonNode value = node.get(field.source());
            if (value == null || value.isNull()) continue;
            switch (field.kind()) {
                case "json" -> object.addAttribute(field.attribute(), value.toString());
                case "boolean" -> {
                    if (!value.isBoolean()) throw new ConnectorException("Invalid boolean cloud attribute");
                    object.addAttribute(field.attribute(), value.booleanValue());
                }
                case "multi" -> {
                    if (!value.isArray()) throw new ConnectorException("Invalid multi-valued cloud attribute");
                    List<String> values = new ArrayList<>(); value.forEach(item -> values.add(item.asText()));
                    object.addAttribute(field.attribute(), values);
                }
                default -> object.addAttribute(field.attribute(), value.asText());
            }
        }
        return object.build();
    }
    private static String requiredId(JsonNode node) {
        String id = node.path("id").asText();
        if (id.isBlank()) throw new ConnectorException("Cloud object has no ID; inventory aborted");
        return id;
    }
    private void requireInitialized() {
        if (cloud == null) throw new IllegalStateException("Connector is not initialized");
    }
    @Override public void test() {
        requireInitialized();
        // Verify every configured collection, not just token acquisition. No 403 is converted into an empty result.
        for (ResourceType type : ResourceType.values()) {
            if (type.azure() && configuration.getSubscriptionIds().length == 0) continue;
            executeQuery(new ObjectClass(type.objectClass), null, object -> false, new OperationOptions(java.util.Map.of()));
        }
    }
}
