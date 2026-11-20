// SPDX-License-Identifier: CDDL-1.1
import { h } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
import { startOwnership } from './api';
import { searchPrincipals, searchOwners } from './owner-lookup';

import type { SearchItem } from './types';

interface SearchPickerProps {
    label: string;
    search: (query: string, signal: AbortSignal) => Promise<SearchItem[]>;
    selection: SearchItem | null;
    choose: (item: SearchItem | null) => void;
}

export function SearchPicker({ label, search, selection, choose }: SearchPickerProps) {
    const [query, setQuery] = useState('');
    const [result, setResult] = useState<{ query?: string; items?: SearchItem[]; error?: string }>({});
    useEffect(() => {
        const value = query.trim();
        if (selection || value.length < 2) return;
        const controller = new AbortController();
        const timer = setTimeout(async () => {
            try {
                const items = await search(value, controller.signal);
                if (!controller.signal.aborted) setResult({ query, items });
            } catch (error) {
                if (!controller.signal.aborted) setResult({ query, error: error instanceof Error ? error.message : String(error) });
            }
        }, 250);
        return () => {
            clearTimeout(timer);
            controller.abort();
        };
    }, [query, search, selection]);

    if (selection) return <div class="selection"><strong>{label}</strong><span>{selection.label}</span>
        <button class="btn btn-default" type="button" onClick={() => { setQuery(''); setResult({}); choose(null); }}>Change</button></div>;

    const show = query.trim().length >= 2;
    return <div class="selection"><label>{label}<input class="form-control" type="search" value={query} maxLength={200}
        onInput={event => { setResult({}); setQuery(event.currentTarget.value); }} placeholder="Enter at least two characters" /></label>
        {show && (result.query !== query ? <p role="status">Searching…</p> : result.error
            ? <p role="alert">{result.error}</p> : result.items?.length
                ? <ul class="results">{result.items.map(item => <li key={item.id}>
                    <button class="btn btn-default" type="button" onClick={() => choose(item)}>{item.label}</button>
                </li>)}</ul> : <p role="status">No matches.</p>)}
    </div>;
}

export function Start({ definitionId }: { definitionId: string }) {
    const [principal, setPrincipal] = useState<SearchItem | null>(null);
    const [owner, setOwner] = useState<SearchItem | null>(null);
    const [reason, setReason] = useState('');
    const [evidence, setEvidence] = useState('');
    const [mode, setMode] = useState('manual');
    const [state, setState] = useState<{ busy?: boolean; error?: string; started?: string }>({});
    const searchOwner = useCallback((q: string, signal: AbortSignal) => searchOwners(q, signal, principal?.id ?? ''), [principal?.id]);
    async function submit() {
        if (state.busy || !principal || (mode === 'manual' && !owner)) return;
        if (!reason.trim() || (mode === 'ownerlens' && !evidence.trim())) {
            setState({ error: 'Enter a reason and provide evidence when using OwnerLens.' });
            return;
        }
        const nomination = mode === 'manual'
            ? owner && { newOwnerId: owner.id } : { ownerEvidenceJson: evidence.trim() };
        if (!nomination) return;
        setState({ busy: true });
        try {
            const result = await startOwnership({ servicePrincipalId: principal.id, reason: reason.trim(), ...nomination }, definitionId);
            setState({ started: result._id || result.id });
        } catch (error) {
            setState({ error: error instanceof Error ? error.message : String(error) });
        }
    }
    if (state.started) return <div role="status">Request submitted. Process ID {state.started}</div>;
    return <div class="stack">
        <fieldset class="stack" disabled={state.busy}>
            <SearchPicker label="Service principal" search={searchPrincipals} selection={principal}
                choose={item => { setPrincipal(item); setOwner(null); }} />
            <label>Nomination method<select class="form-control" value={mode} onChange={event => setMode(event.currentTarget.value)}>
                <option value="manual">Manual nomination</option><option value="ownerlens">OwnerLens evidence</option>
            </select></label>
            {mode === 'manual' && principal && <SearchPicker key={principal.id} label="Proposed owner" search={searchOwner}
                selection={owner} choose={setOwner} />}
            {mode === 'ownerlens' && <label>OwnerLens evidence JSON<textarea class="form-control" value={evidence}
                onInput={event => setEvidence(event.currentTarget.value)} required rows={6} /></label>}
            <label>Reason<textarea class="form-control" value={reason}
                onInput={event => setReason(event.currentTarget.value)} required rows={3} /></label>
            <button type="button" class="btn btn-primary" onClick={submit}
                disabled={!principal || (mode === 'manual' && !owner)}>Start request</button>
        </fieldset>
        {state.error && <p role="alert">{state.error}</p>}
    </div>;
}
