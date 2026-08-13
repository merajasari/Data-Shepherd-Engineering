import unittest

import pandas as pd

from ml.v5.prepare_dataset import (
    add_forward_returns,
    build_manifest,
    validate_panel,
)


class V5PrepareDatasetTests(unittest.TestCase):
    def test_forward_returns_include_endpoint_timestamp(self):
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range(
                    "2026-01-01", periods=5, freq="D", tz="UTC"
                ),
                "close": [100.0, 101.0, 102.0, 103.0, 104.0],
            }
        )

        out = add_forward_returns(df, "stock", horizons=(2,))

        self.assertEqual(
            out.loc[0, "target_endpoint_utc_2d"],
            pd.Timestamp("2026-01-03", tz="UTC"),
        )
        self.assertAlmostEqual(
            out.loc[0, "forward_stock_return_2d"], 0.02
        )
        self.assertTrue(pd.isna(out.loc[4, "forward_stock_return_2d"]))

    def test_validate_panel_rejects_spy_as_candidate(self):
        panel = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-01-01", "2026-01-01"], utc=True
                ),
                "symbol": ["AAPL", "SPY"],
                "forward_relative_return_5d": [0.01, 0.0],
                "forward_relative_return_10d": [0.02, 0.0],
                "forward_relative_return_20d": [0.03, 0.0],
                "is_labeled_5d": [True, True],
                "is_labeled_10d": [True, True],
                "is_labeled_20d": [True, True],
            }
        )

        with self.assertRaisesRegex(ValueError, "SPY appears"):
            validate_panel(panel, expected_symbols=("AAPL", "SPY"))

    def test_validate_panel_rejects_duplicate_timestamp_symbol(self):
        panel = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-01-01", "2026-01-01"], utc=True
                ),
                "symbol": ["AAPL", "AAPL"],
                "forward_relative_return_5d": [0.01, 0.02],
                "forward_relative_return_10d": [0.01, 0.02],
                "forward_relative_return_20d": [0.01, 0.02],
                "is_labeled_5d": [True, True],
                "is_labeled_10d": [True, True],
                "is_labeled_20d": [True, True],
            }
        )

        with self.assertRaisesRegex(ValueError, "Duplicate timestamp/symbol"):
            validate_panel(panel, expected_symbols=("AAPL",))

    def test_manifest_preserves_short_history(self):
        ts = pd.to_datetime(
            [
                "2026-01-01",
                "2026-01-02",
                "2026-01-01",
            ],
            utc=True,
        )
        panel = pd.DataFrame(
            {
                "timestamp_utc": ts,
                "symbol": ["AAPL", "AAPL", "PLTR"],
                "feature_complete": [True, True, False],
                "is_labeled_5d": [True, False, False],
                "is_labeled_10d": [True, False, False],
                "is_labeled_20d": [True, False, False],
            }
        ).sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)

        manifest = build_manifest(panel)
        by_symbol = {x["symbol"]: x for x in manifest["symbols"]}

        self.assertEqual(by_symbol["AAPL"]["rows"], 2)
        self.assertEqual(by_symbol["PLTR"]["rows"], 1)
        self.assertEqual(by_symbol["PLTR"]["feature_complete_rows"], 0)
        self.assertFalse(manifest["benchmark_is_investable"])


if __name__ == "__main__":
    unittest.main()
