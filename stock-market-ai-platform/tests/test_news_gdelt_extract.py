import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import pandas as pd

from ml.news_intelligence.gdelt_extract import execute, load_approved_plan


CSV = "DATE,SourceCommonName,DocumentIdentifier,V2Organizations,V2Tone,asset_ids\n" \
      '20250101120000,example.com,https://example.com/bitcoin,Bitcoin,-1.0,"[""BTC-USD""]"\n'


class GdeltExtractionTest(unittest.TestCase):
    def _inputs(self, root):
        sql = Path(root, "sql"); sql.mkdir()
        Path(sql, "gdelt_gkg_2025_01.sql").write_text("SELECT 1")
        estimates = Path(root, "estimates.csv")
        pd.DataFrame([{"query_file":"gdelt_gkg_2025_01.sql",
                       "estimated_bytes":1024}]).to_csv(estimates, index=False)
        return sql, estimates

    def test_budget_guard_refuses_plan(self):
        with tempfile.TemporaryDirectory() as root:
            sql, estimates = self._inputs(root)
            with self.assertRaisesRegex(ValueError, "exceeds safety budget"):
                load_approved_plan(sql, estimates, max_total_bytes=100)

    def test_executes_with_per_query_cap_and_resumes(self):
        with tempfile.TemporaryDirectory() as root:
            sql, estimates = self._inputs(root)
            raw = Path(root, "raw")
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout=CSV, stderr="")
            budget = 2 * 1024 ** 2
            first = execute("project", sql, estimates, raw, budget, runner, lambda _: None)
            second = execute("project", sql, estimates, raw, budget, runner, lambda _: None)
            self.assertEqual(first["downloaded_queries"], 1)
            self.assertEqual(second["reused_queries"], 1)
            self.assertEqual(len(calls), 1)
            self.assertIn("--maximum_bytes_billed=1048576", calls[0])
            self.assertTrue(Path(root, "extraction_manifest.json").exists())

    def test_failure_includes_stdout_diagnostic(self):
        with tempfile.TemporaryDirectory() as root:
            sql, estimates = self._inputs(root)
            def runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 1,
                    stdout="BigQuery rejected the request", stderr="")
            with self.assertRaisesRegex(RuntimeError, "BigQuery rejected the request"):
                execute("project", sql, estimates, Path(root, "raw"), 2 * 1024 ** 2,
                        runner, lambda _: None)


if __name__ == "__main__":
    unittest.main()
