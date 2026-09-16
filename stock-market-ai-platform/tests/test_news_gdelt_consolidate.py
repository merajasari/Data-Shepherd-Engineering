import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ml.news_intelligence.gdelt_consolidate import run


class GdeltConsolidationTest(unittest.TestCase):
    def _write(self, root, month, rows):
        path = Path(root, f"gdelt_gkg_{month}.csv")
        pd.DataFrame(rows).to_csv(path, index=False)

    def _row(self, date, url, assets):
        return {
            "DATE": date, "SourceCommonName": "example.com",
            "DocumentIdentifier": url, "V2Organizations": "Bitcoin Foundation",
            "V2Tone": "-5.0,1,2", "asset_ids": json.dumps(assets),
        }

    def test_merges_month_duplicates_and_removes_later_reobservations(self):
        with tempfile.TemporaryDirectory() as root:
            raw, output = Path(root, "raw"), Path(root, "canonical")
            raw.mkdir()
            repeated = self._row(20250101120000, "https://example.com/story", ["BTC-USD"])
            self._write(raw, "2025_01", [
                repeated,
                self._row(20250101120000, "https://example.com/story", ["ETH-USD"]),
            ])
            self._write(raw, "2025_02", [repeated])
            manifest = run(raw, output)
            january = pd.read_parquet(output / "news_2025_01.parquet")
            february = pd.read_parquet(output / "news_2025_02.parquet")
            self.assertEqual(manifest["raw_rows"], 3)
            self.assertEqual(manifest["canonical_rows"], 1)
            self.assertEqual(manifest["duplicate_rows_removed"], 2)
            self.assertEqual(list(january.iloc[0]["asset_ids"]), ["BTC-USD", "ETH-USD"])
            self.assertTrue(february.empty)
            self.assertEqual(january.iloc[0]["available_at_utc"],
                             pd.Timestamp("2025-01-01T12:00:00Z"))

    def test_missing_required_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            raw, output = Path(root, "raw"), Path(root, "canonical")
            raw.mkdir()
            pd.DataFrame([{"DATE": 20250101120000}]).to_csv(
                raw / "gdelt_gkg_2025_01.csv", index=False)
            with self.assertRaisesRegex(ValueError, "missing columns"):
                run(raw, output)


if __name__ == "__main__":
    unittest.main()
