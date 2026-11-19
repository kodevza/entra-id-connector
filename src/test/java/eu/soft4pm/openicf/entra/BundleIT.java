// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import java.nio.file.Path;
import java.util.jar.JarFile;
import org.identityconnectors.common.security.GuardedString;
import org.identityconnectors.framework.api.*;
import org.identityconnectors.framework.api.operations.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

/** Loads the thin artifact through OpenICF with host dependencies on the test classpath. */
class BundleIT {
    @Test void bundleRequiresHostJacksonAndContainsNoDependencyJars() throws Exception {
        try (JarFile jar = new JarFile("target/entra-id-connector-0.1.0.jar")) {
            assertFalse(jar.stream().anyMatch(entry -> entry.getName().endsWith(".jar")));
            assertFalse(jar.stream().anyMatch(entry -> entry.getName().startsWith("com/fasterxml/")
                    || entry.getName().startsWith("org/junit/")));
            var manifest = jar.getManifest().getMainAttributes();
            assertNull(manifest.getValue("Embed-Dependency"));
            assertNull(manifest.getValue("Embedded-Artifacts"));
            String imports = manifest.getValue("Import-Package");
            assertTrue(imports.contains("com.fasterxml.jackson.databind;version=\"[2.18,3)\""));
            assertFalse(imports.contains("resolution:=optional"));
        }
    }
    @Test void packagedBundleIsDiscoverableAndExposesRestrictedUpdate() throws Exception {
        var factory = ConnectorInfoManagerFactory.getInstance();
        var manager = factory.getLocalManager(Path.of("target/entra-id-connector-0.1.0.jar").toUri().toURL());
        assertEquals(1, manager.getConnectorInfos().size());
        ConnectorInfo info = manager.getConnectorInfos().get(0);
        assertEquals("Microsoft Entra ID Governance", info.getConnectorDisplayName());
        assertEquals("eu.soft4pm.openicf.entra-id-connector", info.getConnectorKey().getBundleName());
        APIConfiguration api = info.createDefaultAPIConfiguration();
        var properties = api.getConfigurationProperties();
        assertTrue(properties.getProperty("clientSecret").isConfidential());
        assertTrue(properties.getProperty("clientSecret").isRequired());
        properties.setPropertyValue("tenantId", EntraConnectorTest.ID);
        properties.setPropertyValue("clientId", EntraConnectorTest.ID);
        properties.setPropertyValue("clientSecret", new GuardedString("test".toCharArray()));
        ConnectorFacade facade = ConnectorFacadeFactory.getInstance().newInstance(api);
        facade.validate();
        assertEquals(13, facade.schema().getObjectClassInfo().size());
        assertEquals(java.util.Set.of("servicePrincipal"), facade.schema()
                .getSupportedObjectClassesByOperation(UpdateApiOp.class).stream()
                .map(o -> o.getType()).collect(java.util.stream.Collectors.toSet()));
        assertTrue(facade.getSupportedOperations().contains(SearchApiOp.class));
        assertTrue(facade.getSupportedOperations().contains(GetApiOp.class));
        assertTrue(facade.getSupportedOperations().contains(ScriptOnResourceApiOp.class));
        assertFalse(facade.getSupportedOperations().contains(CreateApiOp.class));
        assertTrue(facade.getSupportedOperations().contains(UpdateApiOp.class));
        assertFalse(facade.getSupportedOperations().contains(DeleteApiOp.class));
        assertFalse(facade.getSupportedOperations().contains(SyncApiOp.class));
        ConnectorFacadeFactory.getInstance().dispose(); factory.clearLocalCache();
    }
}
