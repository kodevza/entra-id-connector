// SPDX-License-Identifier: CDDL-1.1
// Run as an OpenIDM admin via POST /openidm/script?_action=eval.
// Local schema/serialization checks only; never calls Entra or Azure.
import org.osgi.framework.FrameworkUtil
import org.forgerock.openidm.script.ScriptExecutor
import org.identityconnectors.common.security.GuardedString

def context = FrameworkUtil.getBundle(ScriptExecutor.class).bundleContext
def bundle = context.bundles.find { it.symbolicName == 'eu.soft4pm.openicf.entra-id-connector' }
assert bundle != null : 'Connector OSGi bundle missing'
assert bundle.state == 32 : 'Connector OSGi bundle is not ACTIVE'
def config = bundle.loadClass('eu.soft4pm.openicf.entra.EntraConfiguration').getDeclaredConstructor().newInstance()
config.tenantId = '00000000-0000-0000-0000-000000000001'
config.clientId = '00000000-0000-0000-0000-000000000001'
config.clientSecret = new GuardedString('offline-test-only'.toCharArray())
def connector = bundle.loadClass('eu.soft4pm.openicf.entra.EntraConnector').getDeclaredConstructor().newInstance()
try {
    connector.init(config)
    assert connector.schema().objectClassInfo.size() == 13
    def jsonClass = bundle.loadClass('com.fasterxml.jackson.databind.ObjectMapper')
    def provider = FrameworkUtil.getBundle(jsonClass)
    assert provider != null
    assert provider.symbolicName == 'com.fasterxml.jackson.core.jackson-databind'
    def mapper = jsonClass.getDeclaredConstructor().newInstance()
    assert mapper.readTree('{"ok":true}').get('ok').asBoolean()
    return [connector: bundle.symbolicName, connectorState: bundle.state,
            objectTypes: connector.schema().objectClassInfo.size(),
            jacksonProvider: provider.symbolicName, jacksonVersion: provider.version.toString(),
            jsonRoundTrip: true]
} finally {
    connector.dispose()
    config.clientSecret.dispose()
}
