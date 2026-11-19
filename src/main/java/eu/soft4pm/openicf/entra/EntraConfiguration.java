// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import java.util.UUID;
import org.identityconnectors.common.security.GuardedString;
import org.identityconnectors.framework.common.exceptions.ConfigurationException;
import org.identityconnectors.framework.spi.AbstractConfiguration;
import org.identityconnectors.framework.spi.ConfigurationProperty;

/** Standard OpenICF configuration; secrets are never stored as ordinary properties. */
public final class EntraConfiguration extends AbstractConfiguration {
    private String tenantId;
    private String clientId;
    private GuardedString clientSecret;
    private String[] subscriptionIds = new String[0];
    private int requestTimeoutSeconds = 30;
    private int maxRetries = 3;

    @ConfigurationProperty(order=1, required=true, displayMessageKey="tenant.display", helpMessageKey="tenant.help")
    public String getTenantId() { return tenantId; }
    public void setTenantId(String value) { tenantId = value; }
    @ConfigurationProperty(order=2, required=true, displayMessageKey="client.display", helpMessageKey="client.help")
    public String getClientId() { return clientId; }
    public void setClientId(String value) { clientId = value; }
    @ConfigurationProperty(order=3, required=true, confidential=true, displayMessageKey="secret.display", helpMessageKey="secret.help")
    public GuardedString getClientSecret() { return clientSecret; }
    public void setClientSecret(GuardedString value) { clientSecret = value; }
    @ConfigurationProperty(order=4, displayMessageKey="subscriptions.display", helpMessageKey="subscriptions.help")
    public String[] getSubscriptionIds() { return subscriptionIds.clone(); }
    public void setSubscriptionIds(String[] value) { subscriptionIds = value == null ? new String[0] : value.clone(); }
    @ConfigurationProperty(order=5, displayMessageKey="timeout.display", helpMessageKey="timeout.help")
    public int getRequestTimeoutSeconds() { return requestTimeoutSeconds; }
    public void setRequestTimeoutSeconds(int value) { requestTimeoutSeconds = value; }
    @ConfigurationProperty(order=6, displayMessageKey="retries.display", helpMessageKey="retries.help")
    public int getMaxRetries() { return maxRetries; }
    public void setMaxRetries(int value) { maxRetries = value; }

    @Override public void validate() {
        uuid(tenantId, "tenantId"); uuid(clientId, "clientId");
        if (clientSecret == null) throw new ConfigurationException("clientSecret is required");
        clientSecret.access(chars -> {
            if (chars.length == 0) throw new ConfigurationException("clientSecret is empty");
        });
        for (String id : subscriptionIds) uuid(id, "subscriptionIds");
        if (requestTimeoutSeconds < 1 || requestTimeoutSeconds > 300)
            throw new ConfigurationException("requestTimeoutSeconds must be 1..300");
        if (maxRetries < 0 || maxRetries > 5) throw new ConfigurationException("maxRetries must be 0..5");
    }
    private static void uuid(String value, String property) {
        try {
            if (value == null || !UUID.fromString(value).toString().equalsIgnoreCase(value)) throw new IllegalArgumentException();
        } catch (IllegalArgumentException e) { throw new ConfigurationException(property + " must contain UUIDs"); }
    }
}
