// SPDX-License-Identifier: CDDL-1.1
// Browser-side search over OpenIDM's existing managed-resource REST API.
// Authorization and data visibility MUST be enforced by OpenIDM, never here.
import { api } from './api';
import type { QueryResult, SearchItem } from './types';

type Principal = { sourceId?: string; displayName?: string; appId?: string; tenantId?: string };
type Owner = { entraObjectId?: string; displayName?: string; givenName?: string; sn?: string;
    userName?: string; mail?: string };

const PAGE_SIZE = 20;
const MAX_LENGTH = 200;
const PRINCIPAL_PATH = 'managed/entraServicePrincipal';
const OWNER_PATH = 'managed/user';

// ForgeRock query-filter literals use JSON string escaping, including control characters.
const literal = (value: string) => JSON.stringify(value);

function searchTerm(query: string): string | null {
    const term = query.trim();
    if (term.length < 2) return null;
    if (term.length > MAX_LENGTH) throw new Error('Search is too long');
    return literal(term);
}

async function records<T>(path: string, filter: string, fields: string[], signal: AbortSignal, pageSize = PAGE_SIZE): Promise<T[]> {
    const response = await api<QueryResult<T>>(path, {
        query: { _queryFilter: filter, _pageSize: pageSize, _fields: fields.join(',') }, signal
    });
    if (!Array.isArray(response.result)) throw new Error('Invalid OpenIDM search response');
    return response.result;
}

export async function searchPrincipals(query: string, signal: AbortSignal): Promise<SearchItem[]> {
    const term = searchTerm(query);
    if (!term) return [];
    const filter = `(displayName co ${term} or sourceId sw ${term} or appId sw ${term}) and sourceId pr and tenantId pr`;
    const principals = await records<Principal>(PRINCIPAL_PATH, filter,
        ['sourceId', 'displayName', 'appId', 'tenantId'], signal);
    return principals.filter(p => typeof p.sourceId === 'string' && !!p.sourceId &&
        typeof p.tenantId === 'string' && !!p.tenantId).map(p => ({
        id: p.sourceId!,
        label: `${p.displayName || p.sourceId}${p.appId ? ` — ${p.appId}` : ''} (${p.sourceId})`
    }));
}

export async function searchOwners(query: string, signal: AbortSignal, principalId: string): Promise<SearchItem[]> {
    const term = searchTerm(query);
    if (!term) return [];
    if (!principalId) throw new Error('Select a synchronized service principal first');
    // Resolve the tenant from OpenIDM rather than trusting the browser's selected item.
    // The BPMN independently validates principal/owner IDs and tenant on submission.
    const matches = await records<Principal>(PRINCIPAL_PATH, `sourceId eq ${literal(principalId)}`,
        ['tenantId'], signal, 2);
    if (matches.length !== 1 || typeof matches[0].tenantId !== 'string' || !matches[0].tenantId) {
        throw new Error('Select a synchronized service principal first');
    }
    const tenant = literal(matches[0].tenantId);
    const filter = `accountStatus eq "active" and entraObjectId pr and entraTenantId eq ${tenant} ` +
        `and (displayName co ${term} or givenName co ${term} or sn co ${term} ` +
        `or userName co ${term} or mail co ${term} or entraObjectId sw ${term})`;
    const owners = await records<Owner>(OWNER_PATH, filter,
        ['entraObjectId', 'displayName', 'givenName', 'sn', 'userName', 'mail'], signal);
    return owners.filter(o => typeof o.entraObjectId === 'string' && !!o.entraObjectId).map(o => {
        const id = o.entraObjectId!;
        const name = o.displayName || [o.givenName, o.sn].filter(Boolean).join(' ') || o.userName || id;
        const detail = o.mail || o.userName;
        return { id, label: `${name}${detail ? ` — ${detail}` : ''} (${id})` };
    });
}
