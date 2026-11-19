// SPDX-License-Identifier: CDDL-1.1
// Runs the exact BPMN Groovy scripts with a fake router, not tenant data.
import org.activiti.engine.impl.identity.Authentication

def model = new XmlSlurper().parse(new File(args[0]))
model.declareNamespace(activiti:'http://activiti.org/bpmn')
def scripts = [:]
model.process.scriptTask.each { scripts[it.@id.text()] = it.script.text() }
def principalId = '00000000-0000-0000-0000-000000000001'
def ownerId = '00000000-0000-0000-0000-000000000002'
def principalObjectId = '10000000-0000-0000-0000-000000000001'
def ownerObjectId = '10000000-0000-0000-0000-000000000002'
def fixture = { Closure mutate = {}, List evidence = null ->
    def db = [:], events = [], variables = [decision:'accept', newOwnerId:ownerObjectId], connector = [fail:false]
    db['managed/entraServicePrincipal/' + principalId] = [_id:principalId, _rev:'1', sourceId:principalObjectId, tenantId:'tenant', displayName:'Test application', grantedAccessJson:groovy.json.JsonOutput.toJson([collectedAt:'2026-11-18T12:00:00Z',coverage:'Direct Entra grants',permissions:[[kind:'application',resourceName:'Microsoft Graph',permission:'User.Read.All',description:'Read users']]])]
    db['managed/user/' + ownerId] = [_id:ownerId, userName:'owner', accountStatus:'active', entraObjectId:ownerObjectId, entraTenantId:'tenant']
    mutate(db)
    if (evidence != null) {
        variables.remove('newOwnerId')
        variables.ownerEvidenceJson = groovy.json.JsonOutput.toJson([servicePrincipalId:principalObjectId, ownerCandidates:evidence])
    }
    def router = new Expando()
    router.read = { String p, Map params = null, List fields = null ->
        assert db.containsKey(p)
        // Native relationships are returned only when explicitly requested.
        fields?.contains('governanceOwner') ? db[p] : db[p].findAll { k,v -> k != 'governanceOwner' }
    }
    router.query = { String collection, Map params ->
        def records = db.findAll { k,v -> k.startsWith(collection + '/') }.values().findAll { record ->
            def clauses = params._queryFilter.split(' and ')
            clauses.every { clause ->
                def parts = clause.split(' eq ', 2)
                record[parts[0]] == new groovy.json.JsonSlurper().parseText(parts[1])
            }
        }
        [result:records as List]
    }
    router.create = { String collection, String id, Map body ->
        db[collection + '/' + id] = body + [_id:id, _rev:'1']; events << ['create',collection]; db[collection+'/'+id]
    }
    router.patch = { String p, String rev, List patches ->
        if (p.startsWith('system/')) {
            assert p == 'system/entra/servicePrincipal/' + principalObjectId
            assert rev == null
            assert patches == [[operation:'replace', field:'/accountEnabled', value:false]]
            if (connector.fail) { throw new IllegalStateException('Connector unavailable') }
            events << ['block',p]
            return [_id:principalObjectId, accountEnabled:false]
        }
        assert db[p]._rev == rev
        patches.each { db[p][it.field.substring(1)] = it.value }
        events << ['patch',p]; db[p]
    }
    def execution = new Expando(getProcessInstanceId:{'process-id'},
        setVariable:{String name, value -> variables[name]=value},getVariable:{String name -> variables[name]})
    def bindings = new Binding([openidm:router,execution:execution,servicePrincipalId:principalObjectId,newOwnerId:ownerObjectId,reason:'Testing'])
    def shell = new GroovyShell(this.class.classLoader,bindings)
    Authentication.setAuthenticatedUserId('requester')
    shell.evaluate(scripts.prepare)
    assert !db['managed/entraServicePrincipal/'+principalId].governanceOwner
    assert variables.ownerAssignee == 'owner'
    assert variables.subject == principalObjectId
    assert variables.source == 'entra'
    def history = db['managed/entraOwnerRequest/process-id']
    assert history.grantedAccessJson == db['managed/entraServicePrincipal/' + principalId].grantedAccessJson
    assert variables.accessSummary.contains('Microsoft Graph | User.Read.All')
    assert variables.accessSummary.contains('2026-11-18T12:00:00Z')
    assert variables.grantedAccessJson == history.grantedAccessJson
    assert !variables.containsKey('_formGenerationTemplate')
    assert model.process.userTask.@'activiti:formKey'.text() == 'forms/servicePrincipalOwner.html'
    assert history.subject == principalObjectId
    assert history.subject != principalId
    assert history.source == 'entra'
    assert history.subjectType == 'servicePrincipal'
    assert history.processType == 'servicePrincipalOwner'
    assert history.processId == 'process-id'
    assert history.recordType == 'ownership_assignment'
    assert history.reviewer == 'owner'
    assert history.requester == 'requester'
    assert db['managed/entraOwnerRequest/process-id'].servicePrincipalId == principalId
    assert db['managed/entraOwnerRequest/process-id'].newOwnerId == ownerId
    [db:db, events:events, variables:variables, shell:shell, connector:connector]
}
def apply = { f, String actor -> Authentication.setAuthenticatedUserId(actor); f.shell.evaluate(scripts.apply) }
def reject = { f, String actor ->
    try { apply(f, actor); assert false : 'Expected rejection' }
    catch (IllegalArgumentException | IllegalStateException expected) { }
}
def accepted = fixture()
// Arbitrary task-completion variables cannot redirect an approved assignment.
accepted.variables.newOwnerId = 'attacker'
accepted.variables.subject = 'attacker'
accepted.variables.accessSummary = 'No access'
accepted.variables.grantedAccessJson = '{}'
apply(accepted, 'owner')
assert accepted.db['managed/entraServicePrincipal/'+principalId].governanceOwner._ref == 'managed/user/'+ownerId
assert accepted.db['managed/entraOwnerRequest/process-id'].status == 'accepted'
assert accepted.db['managed/entraOwnerRequest/process-id'].accessSummary.contains('User.Read.All')
assert accepted.db['managed/entraOwnerRequest/process-id'].subject == principalObjectId
assert accepted.db['managed/entraOwnerRequest/process-id'].decidedBy == 'owner'
assert accepted.db['managed/entraOwnerRequest/process-id'].decidedAt
println 'PASS: acceptance, pre-login owner and immutable request'
def declined = fixture(); declined.variables.decision='reject'; apply(declined,'owner')
assert !declined.db['managed/entraServicePrincipal/'+principalId].governanceOwner
assert declined.db['managed/entraOwnerRequest/process-id'].status == 'rejected'
assert declined.events.findAll { it[0] == 'block' } == [['block','system/entra/servicePrincipal/'+principalObjectId]]
assert declined.events.findIndexOf { it[0] == 'block' } < declined.events.findIndexOf { it == ['patch','managed/entraOwnerRequest/process-id'] }
assert !accepted.events.any { it[0] == 'block' }
println 'PASS: rejection blocks the authoritative service principal through the connector'
def failedBlock = fixture(); failedBlock.variables.decision='reject'; failedBlock.connector.fail=true
reject(failedBlock, 'owner')
assert failedBlock.db['managed/entraOwnerRequest/process-id'].status == 'pending'
assert !failedBlock.db['managed/entraOwnerRequest/process-id'].decidedAt
failedBlock.connector.fail=false
failedBlock.variables.subject='attacker'; failedBlock.variables.servicePrincipalId='attacker'
apply(failedBlock, 'owner')
assert failedBlock.db['managed/entraOwnerRequest/process-id'].status == 'rejected'
println 'PASS: failed block leaves request pending and retry uses the stored subject'
def unauthorizedReject = fixture(); unauthorizedReject.variables.decision='reject'
reject(unauthorizedReject, 'another-user')
assert !unauthorizedReject.events.any { it[0] == 'block' }
println 'PASS: unauthorized rejection cannot block a service principal'
def unauthorized = fixture(); reject(unauthorized,'another-user')
assert !unauthorized.db['managed/entraServicePrincipal/'+principalId].governanceOwner
println 'PASS: another user cannot approve'
def inactive = fixture();inactive.db['managed/user/'+ownerId].accountStatus='inactive';reject(inactive,'owner')
println 'PASS: inactive owner cannot be assigned'
def stale = fixture();stale.db['managed/entraServicePrincipal/'+principalId].governanceOwner=[_ref:'managed/user/another'];reject(stale,'owner')
println 'PASS: concurrent owner change is preserved'
def missing = fixture();missing.variables.decision=null;reject(missing,'owner')
println 'PASS: explicit decision is required'
def invalidPreparation = { Closure mutate ->
    try { fixture(mutate); assert false : 'Expected invalid nomination to fail' }
    catch (IllegalArgumentException expected) {
        assert expected.message.startsWith('[workflow-message]')
        assert expected.message.endsWith('[/workflow-message]')
        assert expected.message.contains("Object ID") || expected.message.contains("active")
    }
}
invalidPreparation { db -> db['managed/user/'+ownerId].entraTenantId = 'another-tenant' }
invalidPreparation { db -> db['managed/user/'+ownerId].accountStatus = 'inactive' }
invalidPreparation { db -> db['managed/user/'+ownerId].entraObjectId = 'another-object' }
invalidPreparation { db -> db['managed/entraServicePrincipal/'+principalId].sourceId = 'another-object' }
invalidPreparation { db -> db['managed/user/duplicate'] = db['managed/user/'+ownerId] + [_id:'duplicate'] }
invalidPreparation { db -> db['managed/entraServicePrincipal/duplicate'] = db['managed/entraServicePrincipal/'+principalId] + [_id:'duplicate'] }
def otherTenant = fixture { db -> db['managed/user/other-tenant'] = db['managed/user/'+ownerId] + [_id:'other-tenant', entraTenantId:'another-tenant'] }
apply(otherTenant, 'owner')
println 'PASS: unknown, inactive, ambiguous and cross-tenant IDs fail; owner lookup is tenant-scoped'
def otherId = '00000000-0000-0000-0000-000000000003'
def otherObjectId = '10000000-0000-0000-0000-000000000003'
def thirdId = '00000000-0000-0000-0000-000000000004'
def thirdObjectId = '10000000-0000-0000-0000-000000000004'
def addCandidates = { db ->
    db['managed/user/'+otherId] = [_id:otherId, userName:'second', accountStatus:'active',
        entraObjectId:otherObjectId, entraTenantId:'tenant', entraUserPrincipalName:'second@example.test']
    db['managed/user/'+thirdId] = [_id:thirdId, userName:'third', accountStatus:'active',
        entraObjectId:thirdObjectId, entraTenantId:'tenant']
}
def rows = [
    [candidate:thirdObjectId, candidateType:'ActivityCaller', confidence:'LOW'],
    [candidate:'second@example.test', candidateType:'User', confidence:'MED', reason:'RBAC signal'],
    [candidate:'Owner display name', candidateType:'User', confidence:'HIGH',
        evidenceType:'Ownership Metadata', evidenceValue:ownerObjectId],
    [candidate:ownerObjectId, candidateType:'User', confidence:'LOW']]
def routed = fixture(addCandidates, rows)
def request = routed.db['managed/entraOwnerRequest/process-id']
def parser = new groovy.json.JsonSlurper()
assert parser.parseText(request.ownerCandidatesJson)*.id == [ownerId, otherId, thirdId]
assert parser.parseText(request.ownerEvidenceJson).size() == 4
routed.variables.decision = 'forward'
routed.variables.forwardOwnerObjectId = 'attacker'
reject(routed, 'owner')
assert request.status == 'pending'
routed.variables.forwardOwnerObjectId = thirdObjectId
routed.variables.ownerCandidatesJson = '[]'
routed.variables.ownerEvidenceJson = '[]'
apply(routed, 'owner')
assert routed.variables.routeToNextOwner && routed.variables.ownerAssignee == 'third'
assert routed.variables.decision == null
assert routed.variables.ownerEvidenceJson == request.ownerEvidenceJson
routed.variables.decision = 'forward'
routed.variables.forwardOwnerObjectId = ownerObjectId
reject(routed, 'third')
routed.db['managed/user/'+otherId].userName = 'second-oidc-subject'
routed.variables.decision = 'reject'
apply(routed, 'third')
assert routed.variables.routeToNextOwner && routed.variables.ownerAssignee == 'second-oidc-subject'
routed.variables.decision = 'reject'
apply(routed, 'second-oidc-subject')
assert routed.variables.routeToNextOwner == false
assert request.status == 'exhausted'
assert parser.parseText(request.ownerReviewHistoryJson)*.actor == ['owner', 'third', 'second-oidc-subject']
assert !routed.events.any { it[0] == 'block' }
assert !routed.db['managed/entraServicePrincipal/'+principalId].governanceOwner
println 'PASS: evidence ranking, forwarding, fallback to original ranking and exhaustion'

def fallback = fixture(addCandidates, rows)
fallback.db['managed/user/'+otherId].accountStatus = 'inactive'
fallback.variables.decision = 'reject'
apply(fallback, 'owner')
assert fallback.variables.ownerAssignee == 'third'
fallback.variables.decision = 'accept'
apply(fallback, 'third')
assert fallback.db['managed/entraServicePrincipal/'+principalId].governanceOwner._ref == 'managed/user/'+thirdId
println 'PASS: fallback skips inactive users and assigns the accepting reviewer'
Authentication.setAuthenticatedUserId(null)

// Every element and transition must have diagram geometry for Activiti/UI.
def diagram = model.children().find { it.name() == 'BPMNDiagram' }
assert diagram, 'Missing BPMN diagram'
def plane = diagram.children().find { it.name() == 'BPMNPlane' }
def shapes = plane.children().findAll { it.name() == 'BPMNShape' }.collect { it.@bpmnElement.text() }
def edges = plane.children().findAll { it.name() == 'BPMNEdge' }.collect { it.@bpmnElement.text() }
model.process.children().findAll { it.name() in ['startEvent','endEvent','scriptTask','userTask'] }.each { assert it.@id.text() in shapes }
model.process.sequenceFlow.each { assert it.@id.text() in edges }
println 'PASS: diagram covers all steps and transitions'
