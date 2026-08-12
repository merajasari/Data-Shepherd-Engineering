import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from ml.crypto_v2.reconciliation import build_overlap_diagnostics, run_reconciliation


class CryptoV2ReconciliationTests(unittest.TestCase):
    def write_source(self, root, provider, closes):
        product = "BTC-USD"
        folder = Path(root) / provider / "daily" / product
        folder.mkdir(parents=True, exist_ok=True)
        start = pd.Timestamp("2020-01-01", tz="UTC")
        rows = []
        for index, close in enumerate(closes):
            timestamp = start + pd.Timedelta(days=index)
            rows.append({
                "product_id": product,
                "provider": provider,
                "granularity": "daily",
                "timestamp_utc": timestamp.isoformat(),
                "open": float(close),
                "high": float(close) + 1.0,
                "low": float(close) - 1.0,
                "close": float(close),
                "volume": 10.0 + index,
            })
        frame = pd.DataFrame(rows)
        frame.to_csv(folder / "candles.csv", index=False)
        metadata = {
            "product_id": product,
            "provider": provider,
            "granularity": "daily",
            "requested_start_utc": start.isoformat(),
            "requested_end_utc_exclusive": (start + pd.Timedelta(days=len(closes))).isoformat(),
            "first_available_utc": start.isoformat(),
            "last_available_utc": (start + pd.Timedelta(days=len(closes) - 1)).isoformat(),
            "row_count": len(frame),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata) + "\n", encoding="utf-8")

    def test_single_provider_produces_no_pair(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_source(root, "provider_a", [100, 101, 102])
            self.assertEqual(len(build_overlap_diagnostics(root)), 0)

    def test_two_providers_are_compared(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_source(root, "provider_a", [100, 101, 102])
            self.write_source(root, "provider_b", [100, 102, 102])
            result = build_overlap_diagnostics(root)
            self.assertEqual(len(result), 1)
            self.assertEqual(int(result.iloc[0]["overlap_count"]), 3)
            self.assertGreater(float(result.iloc[0]["close_max_abs_diff_bps"]), 0.0)

    def test_stage_does_not_select_a_source(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as output:
            self.write_source(root, "provider_a", [100, 101])
            self.write_source(root, "provider_b", [100, 101])
            manifest, result = run_reconciliation(root, output)
            self.assertFalse(manifest["canonical_source_selected"])
            self.assertEqual(len(result), 1)
            self.assertTrue((Path(output) / "reconciliation_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
