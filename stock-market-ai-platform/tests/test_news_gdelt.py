import subprocess
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.news_intelligence.gdelt import build_query, canonicalize_export, estimate_queries


class GdeltAcquisitionTest(unittest.TestCase):
    def test_query_is_partition_pruned_and_asset_filtered(self):
        sql = build_query("2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z",
                          {"BTC-USD": ("bitcoin",), "ETH-USD": ("ethereum",)})
        self.assertIn("gkg_partitioned", sql)
        self.assertIn("_PARTITIONTIME >=", sql)
        self.assertIn("_PARTITIONTIME <", sql)
        self.assertIn("ARRAY_LENGTH(asset_ids) > 0", sql)

    def test_export_uses_observation_time_and_valid_vectors(self):
        raw = pd.DataFrame([{
            "DATE": 20250101123000, "SourceCommonName": "example.com",
            "DocumentIdentifier": "https://example.com/bitcoin-story",
            "V2Organizations": "Bitcoin Foundation",
            "V2Tone": "-5.0,1,2,3",
            "asset_ids": '["BTC-USD"]',
        }])
        result = canonicalize_export(raw, "2025-01-02T00:00:00Z")
        self.assertEqual(result.iloc[0]["asset_ids"], ["BTC-USD"])
        self.assertEqual(result.iloc[0]["timestamp_semantics"],
                         "gdelt_first_observed_not_publisher_timestamp")
        self.assertEqual(len(result.iloc[0]["embedding"]), 256)
        self.assertLess(result.iloc[0]["sentiment"], 0)

    def test_estimator_aggregates_dry_runs_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            for month in ("2025_01", "2025_02"):
                Path(directory, f"gdelt_gkg_{month}.sql").write_text("SELECT 1")
            calls = []
            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0,
                    stdout="running this query will process 1024 bytes of data.", stderr="")
            estimates, summary = estimate_queries(directory, "example-project", runner)
            self.assertEqual(summary["query_count"], 2)
            self.assertEqual(summary["total_estimated_bytes"], 2048)
            self.assertTrue(all("--dry_run" in call[0] for call in calls))
            self.assertEqual(len(estimates), 2)


if __name__ == "__main__":
    unittest.main()
