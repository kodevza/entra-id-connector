// SPDX-License-Identifier: CDDL-1.1
import { h, Fragment, type TargetedKeyboardEvent } from 'preact';
import { useState, useId } from 'preact/hooks';

import type { ReviewData } from './types';

interface Permission {
    kind: string;
    grantId?: string;
    resourceName?: string;
    resourceId?: string;
    permission?: string;
    description?: string;
    consentType?: string;
    principalId?: string;
    directoryScopeId?: string;
    appScopeId?: string;
}

interface Snapshot {
    collectedAt?: string;
    coverage?: string;
    permissions: Permission[];
}

interface Candidate {
    objectId: string;
    label?: string;
    confidence?: string;
    state: string;
}

interface Evidence {
    candidate?: string;
    candidateType?: string;
    signal?: string;
    confidence?: string;
    relationship?: string;
    evidenceType?: string;
    evidenceId?: string;
    evidenceSource?: string;
    evidenceValue?: string;
    reason?: string;
}

const kinds: Readonly<Record<string, string>> = { application: 'Application permissions', delegated: 'Delegated permissions', directoryRole: 'Directory roles' };

function readRows<T>(value?: string): T[] {
    if (!value) return [];
    try {
        const rows = JSON.parse(value);
        return Array.isArray(rows) ? rows.filter(row => row && typeof row === 'object') : [];
    } catch {
        return [];
    }
}

function OwnerEvidence({ rows, id }: { rows: Evidence[]; id: string }) {
    const [query, setQuery] = useState('');
    const [subscription, setSubscription] = useState('');
    const [role, setRole] = useState('');
    const filters = [
        { name: 'Search evidence', value: query, update: setQuery },
        { name: 'Subscription ID', value: subscription, update: setSubscription },
        { name: 'Role', value: role, update: setRole }
    ];
    const includes = (value: string, filter: string) => value.toLowerCase().includes(filter.trim().toLowerCase());
    const visible = rows.map(row => ({
        row,
        subscriptionId: [row.evidenceSource, row.evidenceId].map(scope =>
            /(?:^|\/)subscriptions\/([^/]+)(?:\/|$)/i.exec(scope || '')?.[1]).find(Boolean) || '',
        roleName: row.signal === 'RBAC' ||
            row.reason === 'This principal has Azure RBAC on the same scope as the inspected service principal.'
            ? row.evidenceValue || '' : ''
    })).filter(({ row, subscriptionId, roleName }) =>
        includes(Object.values(row).join(' '), query) &&
        includes(subscriptionId, subscription) && includes(roleName, role));

    return <>
        <div class="eor-tools">
            {filters.map(({ name, value, update }, index) => <label key={name} htmlFor={id + '-filter-' + index}>{name}
                <input id={id + '-filter-' + index} type="search" value={value} onInput={event => update(event.currentTarget.value)} />
            </label>)}
        </div>
        <p class="eor-result" role="status">{visible.length} of {rows.length} evidence rows</p>
        {visible.length ? <div class="eor-table-wrap"><table class="eor-evidence">
            <caption class="eor-sr-only">OwnerLens evidence</caption>
            <thead><tr><th scope="col">Candidate</th><th scope="col">Signal</th><th scope="col">Subscription ID</th>
                <th scope="col">Role</th><th scope="col">Evidence details</th></tr></thead>
            <tbody>{visible.map(({ row, subscriptionId, roleName }, index) => <tr key={index}>
                <td><strong>{row.candidate}</strong><small>{row.candidateType}</small></td>
                <td><strong>{row.signal}</strong><small>{[row.confidence, row.relationship, row.evidenceType].filter(Boolean).join(' · ')}</small></td>
                <td class="eor-mono">{subscriptionId || '—'}</td>
                <td>{roleName || '—'}</td>
                <td>{!roleName && <strong>{row.evidenceValue}</strong>}<small>{row.reason}</small>
                    <small class="eor-mono">{row.evidenceId || row.evidenceSource}</small>
                    {row.evidenceId && row.evidenceSource && row.evidenceSource !== row.evidenceId &&
                        <small class="eor-mono">{row.evidenceSource}</small>}</td>
            </tr>)}</tbody>
        </table></div> : <p class="eor-empty">{rows.length ? 'No evidence matches your filters.' : 'No OwnerLens evidence was provided.'}</p>}
    </>;
}

function OwnerReview({ data, snapshot, invalid = false, readOnly = false }: {
    data: ReviewData;
    snapshot: Snapshot | null;
    invalid?: boolean;
    readOnly?: boolean;
}) {
    const [query, setQuery] = useState('');
    const [kind, setKind] = useState('all');
    const [decision, setDecision] = useState(data.decision || '');
    const [tab, setTab] = useState(0);
    const id = useId();
    const tabs = ['Request', 'Evidence'];
    function navigateTabs(event: TargetedKeyboardEvent<HTMLDivElement>) {
        const destinations: Record<string, number | undefined> = { ArrowLeft: 1 - tab, ArrowRight: 1 - tab, Home: 0, End: 1 };
        const next = destinations[event.key];
        if (next === undefined) return;
        event.preventDefault();
        setTab(next);
        event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next].focus();
    }
    const rankedReview = Boolean(data.ownerCandidatesJson);
    const candidates = readRows<Candidate>(data.ownerCandidatesJson);
    const evidence = readRows<Evidence>(data.ownerEvidenceJson);
    const available = candidates.filter(candidate => candidate.state === 'available');
    const states: Readonly<Record<string, string>> = { current: 'Current reviewer', reviewed: 'Already reviewed', available: 'Awaiting review', unavailable: 'Unavailable' };
    const permissions = snapshot?.permissions || [];
    const visible = permissions.filter(permission => (kind === 'all' || permission.kind === kind) &&
        [permission.resourceName, permission.permission, permission.description, permission.principalId,
            permission.directoryScopeId, permission.appScopeId].filter(Boolean).join(' ').toLowerCase().includes(query.toLowerCase()));
    return <section class="entra-owner-review" aria-label="Ownership review">
        <header><span class="eor-eyebrow">ENTRA GOVERNANCE</span><h2>Review service principal access</h2>
            <p>Review the granted permissions before accepting responsibility for this service principal.</p></header>
        <div class="eor-tabs" role="tablist" aria-label="Review details" onKeyDown={navigateTabs}>
            {tabs.map((label, index) => <button key={label} type="button" role="tab" id={id + '-tab-' + index}
                aria-controls={id + '-panel-' + index} aria-selected={tab === index} tabIndex={tab === index ? 0 : -1}
                onClick={() => setTab(index)}>{label}</button>)}
        </div>
        <div role="tabpanel" id={id + '-panel-0'} aria-labelledby={id + '-tab-0'} hidden={tab !== 0} tabIndex={0}>
            <dl class="eor-details">
                <div><dt>Service principal</dt><dd>{data.principalLabel || data.subject}</dd></div>
                <div><dt>Nominated owner</dt><dd>{data.ownerLabel}</dd></div>
                <div><dt>Entra Object ID</dt><dd class="eor-mono">{data.subject}</dd></div>
                <div><dt>Data source</dt><dd>{data.source || 'entra'}</dd></div>
            </dl>
            <section aria-label="Granted permissions">
                <div class="eor-heading"><h3>Granted permissions <span class="eor-count">{permissions.length}</span></h3>
                    {snapshot?.collectedAt && <p>Collected: <time dateTime={snapshot.collectedAt}>{snapshot.collectedAt}</time></p>}</div>
                <p class="eor-note">{snapshot?.coverage || 'Only the access captured in the inventory snapshot is shown.'}</p>
                <p class="eor-note">Delegated permissions require a signed-in user; they are not application-only access. This snapshot is from when the request was started.</p>
                {!snapshot && data.accessSummary && <p class="eor-note">{data.accessSummary}</p>}
                {!snapshot ? <p role="status" class="eor-warning">{invalid ? 'The permissions snapshot could not be read.' : 'Permissions have not been collected.'} Ask an administrator to reconcile the service principal before reviewing access.</p> : <>
                    <div class="eor-tools">
                        <label htmlFor={`${id}-search`}>Search permissions<input id={`${id}-search`} type="search" value={query}
                            placeholder="API, permission, scope or user" onInput={event => setQuery(event.currentTarget.value)} /></label>
                        <label htmlFor={`${id}-kind`}>Permission type<select id={`${id}-kind`} value={kind} onChange={event => setKind(event.currentTarget.value)}>
                            <option value="all">All types</option>{Object.entries(kinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                    </div>
                    <p class="eor-result" role="status">{visible.length} of {permissions.length} permissions</p>
                    {visible.length ? <div class="eor-table-wrap"><table><caption class="eor-sr-only">Granted access captured for this ownership request</caption>
                        <thead><tr><th>API / resource</th><th>Permission</th><th>Type and scope</th></tr></thead>
                        <tbody>{visible.map((permission, index) => <tr key={`${permission.grantId}-${permission.permission}-${index}`}>
                            <td><strong>{permission.resourceName || (permission.kind === 'directoryRole' ? 'Microsoft Entra directory' : permission.resourceId || 'Unresolved resource')}</strong>
                                {permission.resourceId && <small class="eor-mono">{permission.resourceId}</small>}</td>
                            <td><strong class="eor-permission">{permission.permission}</strong>{permission.description && <small>{permission.description}</small>}</td>
                            <td><span class={`eor-tag eor-${permission.kind}`}>{kinds[permission.kind] || permission.kind}</span>
                                {permission.kind === 'delegated' && <small>{permission.consentType === 'AllPrincipals' ? 'Tenant-wide user consent' : `User consent (${permission.consentType || 'unspecified'})`}
                                    {permission.principalId && <span class="eor-mono">User: {permission.principalId}</span>}</small>}
                                {permission.kind === 'directoryRole' && <small class="eor-mono">Scope: {permission.directoryScopeId || permission.appScopeId || 'Unspecified'}</small>}</td>
                        </tr>)}</tbody></table></div> : <p class="eor-empty">{permissions.length ? 'No permissions match your filters.' : 'No direct Entra grants were found in the collected scope.'}</p>}
                </>}
            </section>
            {rankedReview && <section aria-label="OwnerLens suggestions">
                <h3>OwnerLens candidates</h3>
                <div class="eor-table-wrap"><table>
                    <thead><tr><th scope="col">Rank</th><th scope="col">Candidate</th><th scope="col">Confidence</th><th scope="col">Review status</th></tr></thead>
                    <tbody>{candidates.map((candidate, index) => <tr key={candidate.objectId}>
                        <td>{index + 1}</td><td><strong>{candidate.label}</strong><small class="eor-mono">{candidate.objectId}</small></td>
                        <td>{candidate.confidence}</td><td>{states[candidate.state]}</td>
                    </tr>)}</tbody>
                </table></div>
            </section>}
        </div>
        <div role="tabpanel" id={id + '-panel-1'} aria-labelledby={id + '-tab-1'} hidden={tab !== 1} tabIndex={0}>
            <OwnerEvidence rows={evidence} id={id} />
        </div>
        {!readOnly && <section class="eor-decision" aria-label="Ownership decision">
            <h3>Your decision</h3><label htmlFor={`${id}-decision`}>Accept ownership?</label>
            <select id={`${id}-decision`} name="decision" required value={decision} onChange={event => setDecision(event.currentTarget.value)}>
                <option value="">Choose a decision</option><option value="accept">Accept ownership</option><option value="reject">{rankedReview ? 'Decline ownership' : 'Reject and block service principal'}</option>
                {available.length > 0 && <option value="forward">Forward to another candidate</option>}
            </select>
            {decision === 'forward' && <label htmlFor={`${id}-forward`}>Forward to
                <select id={`${id}-forward`} name="forwardOwnerObjectId" required>
                    <option value="">Choose a candidate</option>
                    {available.map(candidate => <option key={candidate.objectId} value={candidate.objectId}>{candidate.label} ({candidate.confidence})</option>)}
                </select>
            </label>}
            {decision === 'reject' && rankedReview ? <p class="eor-note" role="status">{
                available.length ? 'The next eligible candidate will receive a review task.' : 'The request will close without an owner assignment.'
            }</p> : decision === 'forward' ? <p class="eor-note">The selected candidate will receive a review task.</p> : decision === 'reject' ? <p class="eor-warning" role="status">Rejecting this request will block the service principal in Entra. Existing tokens may remain usable until they expire.</p> : <p class="eor-note">Accepting assigns you as the governance owner in OpenIDM. Complete the task to submit your decision.</p>}
        </section>}
    </section>;
}

export function Review({ data, readOnly }: { data: ReviewData; readOnly?: boolean }) {
    let snapshot: Snapshot | null = null;
    let invalid = false;
    if (data.grantedAccessJson) {
        try {
            snapshot = JSON.parse(data.grantedAccessJson);
            if (!snapshot || !Array.isArray(snapshot.permissions) || snapshot.permissions.some(p => !p || typeof p !== 'object' || Array.isArray(p))) {
                throw new Error('Invalid snapshot');
            }
        } catch {
            snapshot = null;
            invalid = true;
        }
    }
    return <OwnerReview data={data} snapshot={snapshot} invalid={invalid} readOnly={readOnly} />;
}
