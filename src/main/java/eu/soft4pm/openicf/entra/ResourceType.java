// SPDX-License-Identifier: CDDL-1.1
package eu.soft4pm.openicf.entra;

import java.util.Arrays;
import java.util.List;
import org.identityconnectors.framework.common.objects.ObjectClass;

/** Explicit schema: complex permission documents remain lossless JSON strings. */
enum ResourceType {
    USER("__ACCOUNT__", "users", null, "displayName,givenName,surname,userPrincipalName,mail,userType,accountEnabled:boolean"),
    GROUP("__GROUP__", "groups", null, "displayName,description,mail,mailNickname,securityEnabled:boolean,mailEnabled:boolean,groupTypes:multi,isAssignableToRole:boolean"),
    APPLICATION("application", "applications", null, "displayName,appId,signInAudience,identifierUris:multi,appRoles:json,api:json,requiredResourceAccess:json"),
    SERVICE_PRINCIPAL("servicePrincipal", "servicePrincipals", null, "displayName,appId,servicePrincipalType,accountEnabled:boolean,appOwnerOrganizationId,servicePrincipalNames:multi,appRoles:json,oauth2PermissionScopes:json,tags:multi,grantedAccess:json"),
    GROUP_MEMBERSHIP("groupMembership", "groups", "members", "sourceId,targetId,targetType"),
    APPLICATION_OWNER("applicationOwner", "applications", "owners", "sourceId,targetId,targetType"),
    SERVICE_PRINCIPAL_OWNER("servicePrincipalOwner", "servicePrincipals", "owners", "sourceId,targetId,targetType"),
    APP_ROLE_ASSIGNMENT("appRoleAssignment", "servicePrincipals", "appRoleAssignedTo", "appRoleId,principalId,principalType,principalDisplayName,resourceId,resourceDisplayName,createdDateTime"),
    OAUTH_GRANT("oauth2PermissionGrant", "oauth2PermissionGrants", null, "clientId,consentType,principalId,resourceId,scope"),
    DIRECTORY_ROLE_ASSIGNMENT("directoryRoleAssignment", "roleManagement/directory/roleAssignments", null, "principalId,roleDefinitionId,directoryScopeId,appScopeId"),
    DIRECTORY_ROLE_DEFINITION("directoryRoleDefinition", "roleManagement/directory/roleDefinitions", null, "displayName,description,templateId,isBuiltIn:boolean,isEnabled:boolean,rolePermissions:json,inheritsPermissionsFrom:json"),
    AZURE_ROLE_ASSIGNMENT("azureRoleAssignment", "roleAssignments", null, "subscriptionId,principalId,principalType,roleDefinitionId,scope,condition,conditionVersion,description,delegatedManagedIdentityResourceId"),
    AZURE_ROLE_DEFINITION("azureRoleDefinition", "roleDefinitions", null, "subscriptionId,roleName,description,type,permissions:json,assignableScopes:multi");

    record Field(String source, String kind) {
        String attribute() { return source + (kind.equals("json") ? "Json" : ""); }
        Class<?> javaType() { return kind.equals("boolean") ? Boolean.class : String.class; }
    }
    final String objectClass;
    final String path;
    final String child;
    final List<Field> fields;
    ResourceType(String objectClass, String path, String child, String fields) {
        this.objectClass = objectClass; this.path = path; this.child = child;
        this.fields = Arrays.stream(fields.split(",")).map(s -> {
            String[] parts = s.split(":"); return new Field(parts[0], parts.length == 1 ? "string" : parts[1]);
        }).toList();
    }
    boolean azure() { return this == AZURE_ROLE_ASSIGNMENT || this == AZURE_ROLE_DEFINITION; }
    boolean edge() { return this == GROUP_MEMBERSHIP || this == APPLICATION_OWNER || this == SERVICE_PRINCIPAL_OWNER; }
    String collection() {
        if (child != null || azure()) return path;
        if (this == DIRECTORY_ROLE_ASSIGNMENT) return path;
        if (this == DIRECTORY_ROLE_DEFINITION) return path + "?$expand=inheritsPermissionsFrom";
        return path + "?$select=id," + String.join(",", fields.stream().filter(f -> !f.source().equals("grantedAccess")).map(Field::source).toList());
    }
    static ResourceType of(ObjectClass objectClass) {
        return Arrays.stream(values()).filter(t -> t.objectClass.equals(objectClass.getObjectClassValue()))
                .findFirst().orElseThrow(() -> new UnsupportedOperationException("Unsupported object class: " + objectClass.getObjectClassValue()));
    }
}
