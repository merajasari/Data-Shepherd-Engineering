import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from ml.news_intelligence.gdelt_consolidate import _normalized_url, run


class GdeltConsolidationV2Test(unittest.TestCase):
    @staticmethod
    def _fake_to_parquet(frame, path, index=False):
        Path(path).write_text(frame.to_json(orient="records", date_format="iso"))

    @staticmethod
    def _row(date, url, assets):
        return {
            "DATE": date,
            "SourceCommonName": "example.com",
            "DocumentIdentifier": url,
            "V2Organizations": "Bitcoin Foundation",
            "V2Tone": "-5.0,1,2",
            "asset_ids": json.dumps(assets),
        }

    def test_url_identity_removes_tracking_parameters(self):
        first = _normalized_url("HTTPS://Example.com/story/?utm_source=x&a=1#section")
        second = _normalized_url("https://example.com/story?a=1")
        self.assertEqual(first, second)

    def test_cross_month_reobservation_is_removed_and_combined_archive_written(self):
        with tempfile.TemporaryDirectory() as root:
            raw, output = Path(root, "raw"), Path(root, "canonical")
            raw.mkdir()
            pd.DataFrame([
                self._row(20250101120000, "https://example.com/story?utm_source=one", ["BTC-USD"])
            ]).to_csv(raw / "gdelt_gkg_2025_01.csv", index=False)
            pd.DataFrame([
                self._row(20250201120000, "https://example.com/story?utm_source=two", ["BTC-USD"])
            ]).to_csv(raw / "gdelt_gkg_2025_02.csv", index=False)
            with patch.object(pd.DataFrame, "to_parquet", self._fake_to_parquet):
                manifest = run(raw, output)
            self.assertEqual(manifest["raw_rows"], 2)
            self.assertEqual(manifest["canonical_rows"], 1)
            self.assertEqual(manifest["duplicate_rows_removed"], 1)
            self.assertTrue((output / "canonical_news.parquet").exists())
            self.assertFalse(manifest["safety"]["dashboard_modified"])


if __name__ == "__main__":
    unittest.main()
