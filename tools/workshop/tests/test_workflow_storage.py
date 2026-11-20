# SPDX-License-Identifier: CDDL-1.1
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


H2_JAR = os.environ.get('OPENIDM_TEST_H2_JAR')
TABLES = ('ACT_RU_VARIABLE', 'ACT_HI_VARINST', 'ACT_HI_DETAIL')


@unittest.skipUnless(H2_JAR, 'Set OPENIDM_TEST_H2_JAR to run against H2')
class WorkflowStorageTest(unittest.TestCase):
    def test_existing_h2_workflow_database_accepts_long_variable_values(self):
        migration = Path(__file__).resolve().parents[3] / 'openidm/workflow/widen-h2-variable-text.sql'
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'test.sql'
            url = f'jdbc:h2:file:{directory}/workflow'

            def run(sql):
                script.write_text(sql)
                return subprocess.run(
                    ['java', '-cp', H2_JAR, 'org.h2.tools.RunScript', '-url', url,
                     '-user', 'sa', '-script', str(script), '-showResults'],
                    capture_output=True, text=True)

            setup = ''.join(
                f"CREATE TABLE {table} (TEXT_ VARCHAR(4000), TEXT2_ VARCHAR(4000));"
                f"INSERT INTO {table} VALUES ('existing', 'value');"
                for table in TABLES)
            self.assertEqual(0, run(setup).returncode)
            insert = ''.join(
                f"INSERT INTO {table} VALUES (REPEAT('a', 18963), REPEAT('b', 250000));"
                for table in TABLES)
            self.assertIn('Value too long', run(insert).stderr)
            sql = migration.read_text()
            for _ in range(2):
                result = run(sql)
                self.assertEqual(0, result.returncode, result.stderr)
            result = run(insert)
            self.assertEqual(0, result.returncode, result.stderr)
            for table in TABLES:
                result = run(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE (TEXT_ = 'existing' AND TEXT2_ = 'value') OR "
                    f"(LENGTH(TEXT_) = 18963 AND LENGTH(TEXT2_) = 250000);")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn('--> 2', result.stdout)
