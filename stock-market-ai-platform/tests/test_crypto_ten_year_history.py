import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.crypto_ten_year_history import (
    clip_canonical_window, coverage_report, stage_existing_coinbase, validate_canonical,
)


class TenYearHistoryTest(unittest.TestCase):
    def test_clips_combined_provider_rows_to_registered_clock(self):
        frame = pd.DataFrame({
            "product_id": ["BTC-USD"] * 3,
            "timestamp_utc": pd.to_datetime(
                ["2016-09-14", "2016-09-15", "2026-09-16"], utc=True),
            "source_provider": ["kraken_exchange", "kraken_exchange", "coinbase_exchange"],
        })
        clipped = clip_canonical_window(frame, "2016-09-15", "2026-09-16")
        self.assertEqual(len(clipped), 1)
        self.assertEqual(str(clipped.iloc[0]["timestamp_utc"]), "2016-09-15 00:00:00+00:00")

    def test_stages_existing_coinbase_without_touching_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "existing" / "coinbase_exchange" / "daily" / "BTC-USD"
            source.mkdir(parents=True)
            (source / "candles.csv").write_text("observed\n", encoding="utf-8")
            count = stage_existing_coinbase(root / "existing", root / "isolated")
            self.assertEqual(count, 1)
            self.assertEqual((source / "candles.csv").read_text(), "observed\n")
            self.assertEqual((root / "isolated" / "coinbase_exchange" / "daily" /
                              "BTC-USD" / "candles.csv").read_text(), "observed\n")

    def test_coverage_preserves_real_asset_start_dates(self):
        frame = pd.DataFrame({
            "product_id": ["BTC-USD", "BTC-USD", "NEW-USD"],
            "timestamp_utc": pd.to_datetime(["2016-09-15", "2016-09-17", "2024-01-01"], utc=True),
            "open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
            "close": [1, 2, 3], "volume": [1, 1, 1],
        })
        report = coverage_report(frame, ("BTC-USD", "NEW-USD", "MISSING-USD"))
        btc = report.set_index("product_id").loc["BTC-USD"]
        self.assertEqual(btc["observed_days"], 2)
        self.assertEqual(btc["missing_calendar_days"], 1)
        self.assertTrue(report.set_index("product_id").loc["NEW-USD", "first_available_utc"].startswith("2024-01-01"))
        self.assertEqual(report.set_index("product_id").loc["MISSING-USD", "observed_days"], 0)
        validate_canonical(frame, "2016-09-15", "2026-09-16")

    def test_validation_rejects_synthetic_or_invalid_prices(self):
        frame = pd.DataFrame({"product_id": ["BTC-USD"],
            "timestamp_utc": pd.to_datetime(["2016-09-15"], utc=True),
            "open": [0], "high": [1], "low": [1], "close": [1], "volume": [1]})
        with self.assertRaises(ValueError):
            validate_canonical(frame, "2016-09-15", "2026-09-16")


if __name__ == "__main__":
    unittest.main()
