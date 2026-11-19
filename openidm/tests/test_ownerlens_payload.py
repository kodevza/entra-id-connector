# SPDX-License-Identifier: CDDL-1.1
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ownerlens_payload import build_payload


class OwnerLensPayloadTest(unittest.TestCase):
    def test_converts_the_ownerlens_report_without_losing_candidate_evidence(self):
        principal = '10000000-0000-0000-0000-000000000001'
        row = {'candidate': 'reviewer@example.test', 'candidateType': 'User', 'confidence': 'MED',
               'evidenceId': '/scope', 'reason': 'Shared role'}
        report = {'enterpriseApplication': {'objectId': principal}, 'ownerCandidates': [row],
                  'azure': {'activityEvidence': ['unrelated details']}}
        payload = build_payload(report, 'servicePrincipalOwner:1:123', 'Review')
        self.assertEqual(payload['servicePrincipalId'], principal)
        self.assertEqual(payload['_processDefinitionId'], 'servicePrincipalOwner:1:123')
        self.assertNotIn('newOwnerId', payload)
        self.assertEqual(json.loads(payload['ownerEvidenceJson']),
                         {'servicePrincipalId': principal, 'ownerCandidates': [row]})
