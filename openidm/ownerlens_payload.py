#!/usr/bin/env python3
# SPDX-License-Identifier: CDDL-1.1
"""Convert an OwnerLens Lite JSON report to an OpenIDM process start payload."""
import argparse
import json
from pathlib import Path
from uuid import UUID


def build_payload(report, definition_id, reason):
    principal_id = str(UUID(report['enterpriseApplication']['objectId']))
    rows = report['ownerCandidates']
    if not isinstance(rows, list) or not rows or len(rows) > 500 or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Expected 1 to 500 OwnerLens candidate evidence rows')
    fields = ('candidate', 'candidateType', 'confidence', 'relationship', 'signal',
              'evidenceType', 'evidenceId', 'evidenceSource', 'evidenceValue', 'reason', 'candidateObjectId')
    evidence = json.dumps({
        'servicePrincipalId': principal_id,
        'ownerCandidates': [{field: row[field] for field in fields if isinstance(row.get(field), str)} for row in rows],
    }, ensure_ascii=False, separators=(',', ':'))
    if len(evidence.encode('utf-16-le')) // 2 > 250000:
        raise ValueError('OwnerLens evidence exceeds 250000 UTF-16 code units')
    if not reason.strip():
        raise ValueError('A reason is required')
    return {
        '_processDefinitionId': definition_id,
        'servicePrincipalId': principal_id,
        'ownerEvidenceJson': evidence,
        'reason': reason,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--definition-id', required=True)
    parser.add_argument('--reason', default='OwnerLens ownership review')
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding='utf-8-sig'))
        print(json.dumps(build_payload(report, args.definition_id, args.reason)))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
