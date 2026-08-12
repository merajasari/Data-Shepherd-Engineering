import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ml.crypto_v2.historical_inventory import build_inventory, run_inventory


class CryptoV2HistoricalInventoryTests(unittest.TestCase):
    def _write_source(self, root, provider, product, dates):
        d = Path(root) / provider / "daily" / product
        d.mkdir(parents=True, exist_ok=True)
        rows = []
        for i, date in enumerate(dates):
            close = 100.0 + i
            rows.append({
                "product_id": product,
                "provider": provider,
                "granularity": "daily",
                "timestamp_utc": pd.Timestamp(date, tz="UTC").isoformat(),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 10.0 + i,
            })
        frame = pd.DataFrame(rows)
        frame.to_csv(d / "candles.csv", index=False)
        meta = {
            "product_id": product,
            "provider": provider,
            "granularity": "daily",
            "requested_start_utc": pd.Timestamp(dates[0], tz="UTC").isoformat(),
            "requested_end_utc_exclusive": (pd.Timestamp(dates[-1], tz="UTC") + pd.Timedelta(days=1)).isoformat(),
            "first_available_utc": pd.Timestamp(dates[0], tz="UTC").isoformat(),
            "last_available_utc": pd.Timestamp(dates[-1], tz="UTC").isoformat(),
            "row_count": len(frame),
            "ingested_at_utc": "2026-08-12T00:00:00+00:00",
        }
        (d / "metadata.json").write_text(json.dumps(meta) + "\n", encoding="utf-8")

    def test_inventory_reports_gap_without_filling(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_source(tmp, "provider_a", "BTC-USD", [
                "2020-01-01", "2020-01-02", "2020-01-04"
            ])
            inventory, gaps = build_inventory(tmp)
            self.assertEqual(len(inventory), 1)
            row = inventory.iloc[0]
            self.assertEqual(int(row["row_count"]), 3)
            self.assertEqual(int(row["expected_calendar_days"]), 4)
            self.assertEqual(int(row["missing_days"]), 1)
            self.assertAlmostEqual(float(row["coverage_fraction"]), 0.75)
            self.assertEqual(len(gaps), 1)
            self.assertEqual(int(gaps.iloc[0]["missing_intervals"]), 1)

    def test_inventory_keeps_provider_series_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dates = ["2020-01-01", "2020-01-02"]
            self._write_source(tmp, "provider_a", "BTC-USD", dates)
            self._write_source(tmp, "provider_b", "BTC-USD", dates)
            inventory, _ = build_inventory(tmp)
            self.assertEqual(len(inventory), 2)
            self.assertEqual(set(inventory["provider"]), {"provider_a", "provider_b"})
            self.assertEqual(inventory["product_id"].nunique(), 1)

    def test_run_inventory_writes_reproducible_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            self._write_source(tmp, "provider_a", "ETH-USD", [
                "2020-01-01", "2020-01-02", "2020-01-03"
            ])
            manifest, inventory, gaps = run_inventory(tmp, out)
            self.assertEqual(manifest["research_version"], "crypto_v2")
            self.assertEqual(manifest["provider_count"], 1)
            self.assertEqual(manifest["asset_count"], 1)
            self.assertEqual(manifest["total_rows"], 3)
            self.assertEqual(len(inventory), 1)
            self.assertEqual(len(gaps), 0)
            self.assertTrue((Path(out) / "source_inventory.csv").exists())
            self.assertTrue((Path(out) / "gap_inventory.csv").exists())
            self.assertTrue((Path(out) / "baseline_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
