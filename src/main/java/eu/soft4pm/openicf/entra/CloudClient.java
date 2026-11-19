// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;
import org.identityconnectors.framework.common.exceptions.*;

/** Small, bounded HTTP transport with separate Graph and ARM token audiences. */
final class CloudClient {
    static final ObjectMapper JSON = new ObjectMapper();
    enum Api { GRAPH, ARM }
    private record Token(String value, Instant expires) { }
    private final EntraConfiguration config;
    private final URI tokenEndpoint;
    private final URI graph;
    private final URI arm;
    private final HttpClient http;
    private final Map<Api, Token> tokens = new HashMap<>();

    CloudClient(EntraConfiguration config) {
        this(config, URI.create("https://login.microsoftonline.com/" + config.getTenantId() + "/oauth2/v2.0/token"),
                URI.create("https://graph.microsoft.com/v1.0/"), URI.create("https://management.azure.com/"));
    }
    // Package-private endpoint injection for offline HTTP contract tests only.
    CloudClient(EntraConfiguration config, URI tokenEndpoint, URI graph, URI arm) {
        this.config = config; this.tokenEndpoint = tokenEndpoint; this.graph = graph; this.arm = arm;
        http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(config.getRequestTimeoutSeconds()))
                .followRedirects(HttpClient.Redirect.NEVER).build();
    }

    /** Returns false when a consumer cancels; pages and objects are streamed. */
    boolean each(Api api, String path, Predicate<JsonNode> consumer) {
        URI next = base(api).resolve(path);
        Set<URI> visited = new HashSet<>();
        while (next != null) {
            if (!visited.add(next)) throw new ConnectorException("Repeated pagination link; inventory aborted");
            JsonNode page = get(api, next);
            JsonNode values = page.get("value");
            if (values == null || !values.isArray()) throw new ConnectorException("Invalid cloud collection response");
            for (JsonNode value : values) if (!consumer.test(value)) return false;
            JsonNode link = page.get(api == Api.GRAPH ? "@odata.nextLink" : "nextLink");
            next = link == null || link.isNull() || link.asText().isBlank() ? null : URI.create(link.asText());
        }
        return true;
    }

    JsonNode get(Api api, URI uri) {
        validateTarget(api, uri);
        boolean refreshed = false;
        int retries = 0;
        while (true) {
            HttpResponse<String> response = send(HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(config.getRequestTimeoutSeconds()))
                    .header("Authorization", "Bearer " + token(api))
                    .header("Accept", "application/json").GET().build());
            int status = response.statusCode();
            if (status == 401 && !refreshed) {
                synchronized (tokens) { tokens.remove(api); }
                refreshed = true;
                continue;
            }
            if (transientStatus(status)) {
                if (retries >= config.getMaxRetries()) throw RetryableException.wrap("Cloud API temporarily unavailable (HTTP " + status + ")", (Throwable)null);
                pause(response, retries++);
                continue;
            }
            checkStatus(status);
            return parse(response.body());
        }
    }

    /** Idempotent PATCH; a 204 intentionally has no JSON response body. */
    void disableServicePrincipal(String objectId) {
        URI uri = graph.resolve("servicePrincipals/" + encode(objectId));
        validateTarget(Api.GRAPH, uri);
        boolean refreshed = false;
        int retries = 0;
        while (true) {
            HttpResponse<String> response = send(HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(config.getRequestTimeoutSeconds()))
                    .header("Authorization", "Bearer " + token(Api.GRAPH))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .method("PATCH", HttpRequest.BodyPublishers.ofString("{\"accountEnabled\":false}"))
                    .build());
            int status = response.statusCode();
            if (status == 401 && !refreshed) {
                synchronized (tokens) { tokens.remove(Api.GRAPH); }
                refreshed = true;
                continue;
            }
            if (transientStatus(status)) {
                if (retries >= config.getMaxRetries())
                    throw RetryableException.wrap("Cloud API temporarily unavailable (HTTP " + status + ")", (Throwable)null);
                pause(response, retries++);
                continue;
            }
            checkStatus(status);
            if (status != 204) throw new ConnectorException("Unexpected service principal update response (HTTP " + status + ")");
            return;
        }
    }

    private String token(Api api) {
        synchronized (tokens) {
            Token cached = tokens.get(api);
            if (cached != null && cached.expires().isAfter(Instant.now().plusSeconds(30))) return cached.value();
            String[] form = new String[1];
            config.getClientSecret().access(chars -> form[0] = "grant_type=client_credentials&client_id="
                    + encode(config.getClientId()) + "&client_secret=" + encode(new String(chars))
                    + "&scope=" + encode(api == Api.GRAPH ? "https://graph.microsoft.com/.default" : "https://management.azure.com/.default"));
            HttpRequest request = HttpRequest.newBuilder(tokenEndpoint)
                    .timeout(Duration.ofSeconds(config.getRequestTimeoutSeconds()))
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(form[0])).build();
            form[0] = null;
            HttpResponse<String> response;
            int retries = 0;
            do {
                response = send(request);
                if (!transientStatus(response.statusCode())) break;
                if (retries >= config.getMaxRetries()) throw RetryableException.wrap("Token endpoint temporarily unavailable", (Throwable)null);
                pause(response, retries++);
            } while (true);
            if (response.statusCode() != 200) throw new InvalidCredentialException("Token request failed (HTTP " + response.statusCode() + "); check tenant, client ID and secret");
            JsonNode json = parse(response.body());
            String value = json.path("access_token").asText();
            long expires = json.path("expires_in").asLong(0);
            if (value.isBlank() || expires <= 0) throw new InvalidCredentialException("Token response lacks access_token or expires_in");
            tokens.put(api, new Token(value, Instant.now().plusSeconds(Math.min(expires, 86400))));
            return value;
        }
    }

    private void validateTarget(Api api, URI uri) {
        URI expected = base(api);
        if (!uri.isAbsolute() || !expected.getScheme().equalsIgnoreCase(uri.getScheme())
                || !expected.getHost().equalsIgnoreCase(uri.getHost()) || expected.getPort() != uri.getPort()
                || uri.getUserInfo() != null || uri.getFragment() != null
                || java.util.Arrays.stream(uri.getPath().split("/")).anyMatch(p -> p.equals(".") || p.equals(".."))
                || uri.getPath().contains("\\")
                || !uri.normalize().getPath().startsWith(expected.getPath()))
            throw new ConnectorException("Untrusted cloud pagination URL rejected");
        if (api == Api.ARM) {
            boolean allowed = false;
            for (String id : config.getSubscriptionIds())
                if (uri.getPath().toLowerCase(java.util.Locale.ROOT).startsWith("/subscriptions/" + id.toLowerCase(java.util.Locale.ROOT) + "/")) allowed = true;
            if (!allowed) throw new ConnectorException("Azure pagination URL is outside configured subscriptions");
        }
    }
    private URI base(Api api) { return api == Api.GRAPH ? graph : arm; }
    private static boolean transientStatus(int status) { return status == 429 || status == 500 || status == 502 || status == 503 || status == 504; }
    private static void checkStatus(int status) {
        if (status >= 200 && status < 300) return;
        if (status == 401) throw new InvalidCredentialException("Cloud API rejected credentials (HTTP 401)");
        if (status == 403) throw new PermissionDeniedException("Cloud API denied access (HTTP 403); verify Graph consent or Azure RBAC on the requested subscription");
        if (status == 404) throw new UnknownUidException("Cloud resource no longer exists (HTTP 404); inventory aborted, retry reconciliation");
        throw new ConnectorException("Cloud API request failed (HTTP " + status + ")");
    }
    private static HttpResponse<String> sendWith(HttpClient client, HttpRequest request) throws IOException, InterruptedException {
        return client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }
    private HttpResponse<String> send(HttpRequest request) {
        try { return sendWith(http, request); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new ConnectorIOException("Cloud request interrupted"); }
        catch (IOException e) { throw new ConnectorIOException("Cloud request failed; check connectivity and TLS"); }
    }
    private static JsonNode parse(String body) {
        try {
            JsonNode parsed = JSON.readTree(body);
            if (parsed == null || !parsed.isObject()) throw new ConnectorException("Cloud endpoint returned no JSON object");
            return parsed;
        }
        catch (IOException e) { throw new ConnectorException("Invalid JSON from cloud endpoint"); }
    }
    private static void pause(HttpResponse<?> response, int attempt) {
        long seconds = Math.min(1L << attempt, 30);
        String header = response.headers().firstValue("Retry-After").orElse(null);
        if (header != null) {
            try { seconds = Long.parseLong(header); }
            catch (NumberFormatException e) {
                try { seconds = Math.max(0, Duration.between(Instant.now(), ZonedDateTime.parse(header, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant()).getSeconds()); }
                catch (RuntimeException ignored) { /* use bounded exponential delay */ }
            }
        }
        if (seconds > 30) throw RetryableException.wrap("Cloud API requested a longer retry delay; retry the operation later", (Throwable)null);
        try { Thread.sleep(Math.max(0, seconds) * 1000); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new ConnectorIOException("Cloud retry interrupted"); }
    }
    static String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
    void close() { synchronized (tokens) { tokens.clear(); } }
}
