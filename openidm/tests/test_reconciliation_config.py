# SPDX-License-Identifier: CDDL-1.1
import json
from pathlib import Path
import unittest

from test_identity_config import TENANT, config


class ReconciliationConfigTest(unittest.TestCase):
    def test_inventory_mappings_serialize_record_processing(self):
        example = Path(__file__).resolve().parents[1] / 'sync-entra.example.json'
        mappings = json.loads(example.read_text(encoding='utf-8'))['mappings']

        self.assertTrue(mappings, 'The example must include inventory mappings')
        for mapping in mappings:
            with self.subTest(mapping=mapping['name']):
                self.assertEqual(mapping.get('taskThreads'), 1)

    def test_account_mapping_serializes_record_processing(self):
        mapping = config.build_mapping(TENANT)

        self.assertEqual(mapping.get('taskThreads'), 1)
