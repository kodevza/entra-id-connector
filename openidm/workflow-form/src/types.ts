// SPDX-License-Identifier: CDDL-1.1
export interface ReviewData {
    subject?: string;
    source?: string;
    principalLabel?: string;
    ownerLabel?: string;
    grantedAccessJson?: string;
    accessSummary?: string;
    decision?: string;
    ownerEvidenceJson?: string;
    ownerCandidatesJson?: string;
}

export interface SearchItem {
    id: string;
    label: string;
}

export interface QueryResult<T> {
    result: T[];
}
