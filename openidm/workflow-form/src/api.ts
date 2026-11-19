// SPDX-License-Identifier: CDDL-1.1
interface RequestOptions {
    query?: Record<string, string | number>;
    method?: string;
    body?: object;
    signal?: AbortSignal;
}

type StartFields = { servicePrincipalId: string; reason: string } &
    ({ newOwnerId: string } | { ownerEvidenceJson: string });

export async function api<T>(path: string, { query, method = 'GET', body, signal }: RequestOptions = {}): Promise<T> {
    const url = new URL('/openidm/' + path, location.origin);
    if (query) url.search = new URLSearchParams(Object.entries(query).map(([key, value]) => [key, String(value)])).toString();
    const headers: Record<string, string> = { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' };
    try {
        const session = JSON.parse(sessionStorage.getItem('authDetails') ?? 'null');
        if (session?.provider === 'OPENAM' && session.authToken) {
            headers.provider = session.provider;
            headers.authToken = session.authToken;
        }
    } catch {
        // Cookie-based sessions are available even when browser storage is disabled.
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, {
        method, headers, signal, credentials: 'same-origin',
        body: body === undefined ? undefined : JSON.stringify(body)
    });
    const result = await response.json().catch(() => null);
    if (!response.ok || !result) {
        throw Object.assign(new Error(result?.message || 'OpenIDM request failed (' + response.status + ').'),
            { status: response.status });
    }
    return result;
}

export function startOwnership(fields: StartFields, definitionId: string) {
    return api<{ _id?: string; id?: string }>('workflow/processinstance', {
        query: { _action: 'create' }, method: 'POST', body: { ...fields, _processDefinitionId: definitionId }
    });
}
