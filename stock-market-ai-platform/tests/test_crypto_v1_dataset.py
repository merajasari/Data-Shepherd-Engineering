"""Data-quality and leakage contracts for Crypto V1 Phase 2."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from ml.crypto_v1.prepare_dataset import (
    REQUIRED_FEATURES, add_features_and_eligibility, add_targets, build_gold_panel,
    build_silver,
)
from ml.crypto_v1.validation import BronzeValidationError, validate_bronze


class BronzeValidationTests(unittest.TestCase):
    def _write_bronze(self, rows, start="2024-01-01T00:00:00+00:00",
                      end="2024-01-06T00:00:00+00:00", metadata_updates=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        product_dir = Path(temporary.name) / "coinbase_exchange" / "daily" / "BTC-USD"
        product_dir.mkdir(parents=True)
        frame = pd.DataFrame(rows)
        frame.to_csv(product_dir / "candles.csv", index=False)
        metadata = {
            "product_id": "BTC-USD", "provider": "coinbase_exchange", "granularity": "daily",
            "requested_start_utc": start, "requested_end_utc_exclusive": end,
            "first_available_utc": rows[0]["timestamp_utc"] if rows else None,
            "last_available_utc": rows[-1]["timestamp_utc"] if rows else None,
            "row_count": len(rows), "ingested_at_utc": "2024-01-07T00:00:00+00:00",
        }
        metadata.update(metadata_updates or {})
        (product_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        return Path(temporary.name), product_dir

    @staticmethod
    def _rows(days=(1, 2, 3)):
        return [{
            "product_id": "BTC-USD", "provider": "coinbase_exchange", "granularity": "daily",
            "timestamp_utc": f"2024-01-{day:02d}T00:00:00+00:00",
            "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100,
        } for day in days]

    def test_valid_data_and_gap_are_reported_without_synthesis(self):
        _, product_dir = self._write_bronze(self._rows((1, 2, 4)))
        frame, report = validate_bronze(product_dir / "candles.csv")
        self.assertEqual(len(frame), 3)
        self.assertEqual(report.gap_count, 1)
        self.assertEqual(report.missing_interval_count, 1)
        self.assertNotIn(pd.Timestamp("2024-01-03", tz="UTC"), set(frame["timestamp_utc"]))

    def test_duplicate_timestamp_fails(self):
        rows = self._rows((1, 2, 2))
        _, product_dir = self._write_bronze(rows)
        with self.assertRaisesRegex(BronzeValidationError, "Duplicate"):
            validate_bronze(product_dir / "candles.csv")

    def test_order_ohlc_and_metadata_corruption_fail(self):
        cases = []
        unordered = self._rows((2, 1)); cases.append((unordered, {}, "ordered"))
        invalid_ohlc = self._rows(); invalid_ohlc[1]["low"] = 13; cases.append((invalid_ohlc, {}, "OHLC"))
        negative = self._rows(); negative[1]["volume"] = -1; cases.append((negative, {}, "non-negative"))
        cases.append((self._rows(), {"row_count": 99}, "row_count"))
        for rows, updates, message in cases:
            with self.subTest(message=message):
                _, product_dir = self._write_bronze(rows, metadata_updates=updates)
                with self.assertRaisesRegex(BronzeValidationError, message):
                    validate_bronze(product_dir / "candles.csv")

    def test_non_utc_timestamp_fails(self):
        rows = self._rows(); rows[0]["timestamp_utc"] = "2024-01-01T01:00:00+01:00"
        _, product_dir = self._write_bronze(rows)
        with self.assertRaisesRegex(BronzeValidationError, "must be UTC"):
            validate_bronze(product_dir / "candles.csv")

    def test_silver_is_parquet_sorted_and_unique(self):
        root, _ = self._write_bronze(self._rows())
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        paths, reports = build_silver(root, Path(temporary.name))
        silver = pd.read_parquet(paths[0])
        self.assertEqual(len(reports), 1)
        self.assertTrue(silver["timestamp_utc"].is_monotonic_increasing)
        self.assertFalse(silver.duplicated(["product_id", "timestamp_utc"]).any())
        self.assertTrue(pd.api.types.is_float_dtype(silver["close"]))


def synthetic_gold(days=140, asset_start=0, asset_volume=2_000_000.0, gap_day=None):
    timestamps = pd.date_range("2023-01-01", periods=days, tz="UTC")
    rows = []
    for product, start, base, daily_growth, volume in (
        ("BTC-USD", 0, 100.0, 0.001, 30_000.0),
        ("ETH-USD", asset_start, 20.0, 0.002, asset_volume),
        ("SOL-USD", 0, 10.0, 0.003, 50_000.0),
    ):
        for index, timestamp in enumerate(timestamps[start:], start=start):
            if product == "ETH-USD" and index == gap_day:
                continue
            close = base * (1 + daily_growth) ** index
            rows.append({
                "product_id": product, "timestamp_utc": timestamp,
                "open": close * .99, "high": close * 1.01, "low": close * .98,
                "close": close, "volume": volume, "provider": "coinbase_exchange",
                "granularity": "daily",
            })
    return build_gold_panel(pd.DataFrame(rows), completed_before_utc="2025-01-01")


class PanelContractTests(unittest.TestCase):
    def test_gold_keeps_differing_histories_and_does_not_invent_gap(self):
        gold = synthetic_gold(asset_start=40, gap_day=80)
        eth = gold[gold["product_id"] == "ETH-USD"]
        self.assertEqual(eth["first_available_timestamp"].nunique(), 1)
        self.assertEqual(eth["first_available_timestamp"].iloc[0], pd.Timestamp("2023-02-10", tz="UTC"))
        self.assertFalse((eth["timestamp_utc"] == pd.Timestamp("2023-03-22", tz="UTC")).any())
        self.assertIn("BTC-USD", set(gold["product_id"]))

    def test_new_listing_and_liquidity_threshold_are_point_in_time(self):
        panel = add_features_and_eligibility(synthetic_gold(asset_start=40))
        eth = panel[panel["product_id"] == "ETH-USD"].reset_index(drop=True)
        self.assertFalse(eth.loc[58, "is_eligible"])
        self.assertEqual(eth.loc[58, "eligibility_reason"], "insufficient_history")
        self.assertTrue(eth.loc[59, "is_eligible"])
        sol = panel[panel["product_id"] == "SOL-USD"]
        self.assertFalse(sol.iloc[-1]["meets_liquidity_threshold"])
        self.assertEqual(sol.iloc[-1]["eligibility_reason"], "below_liquidity_threshold")

    def test_gap_invalidates_trailing_window_without_filling(self):
        panel = add_features_and_eligibility(synthetic_gold(gap_day=100))
        eth = panel[panel["product_id"] == "ETH-USD"].set_index("timestamp_utc")
        after_gap = eth.loc[pd.Timestamp("2023-04-12", tz="UTC")]
        self.assertTrue(pd.isna(after_gap["return_3d"]))
        self.assertFalse(after_gap["has_required_trailing_windows"])

    def test_btc_relative_feature_is_asset_minus_btc(self):
        panel = add_features_and_eligibility(synthetic_gold())
        row = panel[(panel["product_id"] == "ETH-USD")].iloc[-1]
        expected = row["return_7d"] - row["btc_return_7d"]
        self.assertAlmostEqual(row["btc_relative_return_7d"], expected)

    def test_targets_exact_endpoint_ranks_and_top_flags(self):
        panel = add_targets(add_features_and_eligibility(synthetic_gold()))
        date = pd.Timestamp("2023-04-15", tz="UTC")
        rows = panel[(panel["timestamp_utc"] == date) & panel["is_eligible"]]
        eth = rows[rows["product_id"] == "ETH-USD"].iloc[0]
        expected_asset = (1.002 ** 3) - 1
        expected_btc = (1.001 ** 3) - 1
        self.assertAlmostEqual(eth["forward_return_3d"], expected_asset)
        self.assertAlmostEqual(eth["forward_return_relative_to_btc_3d"], expected_asset - expected_btc)
        self.assertEqual(eth["target_endpoint_utc_3d"], date + pd.Timedelta(days=3))
        self.assertEqual(eth["target_percentile_rank_3d"], 1.0)
        self.assertTrue(eth["target_top_3_3d"])

    def test_future_mutation_cannot_change_past_features_or_eligibility(self):
        """Purpose-built look-ahead trap: drastically rewrite all later candles."""
        gold = synthetic_gold()
        decision = pd.Timestamp("2023-04-15", tz="UTC")
        baseline = add_features_and_eligibility(gold)
        mutated = gold.copy()
        future = mutated["timestamp_utc"] > decision
        mutated.loc[future, "close"] *= 1000
        mutated.loc[future, "high"] *= 1000
        mutated.loc[future, "open"] *= 1000
        mutated.loc[future, "low"] *= 1000
        mutated.loc[future, "dollar_volume"] = mutated.loc[future, "close"] * mutated.loc[future, "volume"]
        changed = add_features_and_eligibility(mutated)
        keys = (baseline["timestamp_utc"] == decision) & (baseline["product_id"] == "ETH-USD")
        keys_changed = (changed["timestamp_utc"] == decision) & (changed["product_id"] == "ETH-USD")
        columns = list(REQUIRED_FEATURES) + ["is_eligible", "trailing_median_dollar_volume_30d"]
        pd.testing.assert_series_equal(
            baseline.loc[keys, columns].iloc[0], changed.loc[keys_changed, columns].iloc[0],
            check_names=False,
        )

    def test_targets_are_not_feature_inputs_and_incomplete_targets_remain_missing(self):
        panel = add_features_and_eligibility(synthetic_gold())
        self.assertFalse(any(name.startswith("target_") or name.startswith("forward_")
                             for name in REQUIRED_FEATURES))
        labeled = add_targets(panel)
        last = labeled[labeled["product_id"] == "ETH-USD"].iloc[-1]
        self.assertTrue(pd.isna(last["forward_return_1d"]))
        self.assertTrue(pd.isna(last["target_top_3_1d"]))


if __name__ == "__main__":
    unittest.main()
