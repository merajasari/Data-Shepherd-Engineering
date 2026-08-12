"""Static and pagination contracts for isolated Crypto V1."""

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ml.crypto_v1.config import (
    BENCHMARK_PRODUCT, CRYPTO_UNIVERSE, FORWARD_HORIZONS_DAYS,
    TOP_COUNTS, ALLOW_LEVERAGE,
)
from ml.crypto_v1.providers.coinbase import CoinbaseExchangeProvider
from ml.crypto_v1.prepare_dataset import (
    REQUIRED_FEATURES, build_horizon_research_panel,
)


class FakeCoinbase(CoinbaseExchangeProvider):
    def __init__(self):
        super().__init__(pause_seconds=0)
        self.calls = []

    def _request_json(self, path, params):
        self.calls.append((path, params))
        start = datetime.fromisoformat(params["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(params["end"].replace("Z", "+00:00"))
        rows = []
        cursor = start
        while cursor <= end:  # exercise boundary filtering/deduplication
            rows.append([int(cursor.timestamp()), 1, 3, 2, 2.5, 10])
            cursor += timedelta(days=1)
        return list(reversed(rows))


class CryptoV1ContractTests(unittest.TestCase):
    def test_universe_and_benchmark(self):
        self.assertGreaterEqual(len(CRYPTO_UNIVERSE), 20)
        self.assertLessEqual(len(CRYPTO_UNIVERSE), 30)
        self.assertEqual(len(CRYPTO_UNIVERSE), len(set(CRYPTO_UNIVERSE)))
        self.assertIn("BTC-USD", CRYPTO_UNIVERSE)
        self.assertIn("ETH-USD", CRYPTO_UNIVERSE)
        self.assertEqual(BENCHMARK_PRODUCT, "BTC-USD")
        self.assertTrue(all(pair.endswith("-USD") for pair in CRYPTO_UNIVERSE))

    def test_research_contract(self):
        self.assertEqual(FORWARD_HORIZONS_DAYS, (1, 3, 7))
        self.assertEqual(TOP_COUNTS, (3, 5))
        self.assertFalse(ALLOW_LEVERAGE)

    def test_daily_pagination_is_sorted_unique_and_end_exclusive(self):
        provider = FakeCoinbase()
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=650)
        candles = provider.get_candles("BTC-USD", start, end, "daily")
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(len(candles), 650)
        self.assertEqual(candles[0].timestamp_utc, start)
        self.assertEqual(candles[-1].timestamp_utc, end - timedelta(days=1))


    def test_horizon_panels_recompute_ranks_after_xrp_boundary_filter(self):
        """XRP may remain in short horizons when its 7d endpoint is absent."""
        dates = pd.date_range("2021-01-14", "2021-01-19", tz="UTC")
        products = [
            "BTC-USD", "ETH-USD", "XRP-USD", "LTC-USD", "BCH-USD", "XLM-USD",
        ]
        rows = []
        for timestamp in dates:
            for index, product in enumerate(products):
                row = {
                    "product_id": product,
                    "timestamp_utc": timestamp,
                    "is_eligible": True,
                    "forward_return_relative_to_btc_1d": index / 100,
                    "forward_return_relative_to_btc_3d": index / 50,
                    "forward_return_relative_to_btc_7d": index / 25,
                }
                row.update({feature: 1.0 for feature in REQUIRED_FEATURES})
                rows.append(row)
        labeled = pd.DataFrame(rows)
        xrp = labeled["product_id"].eq("XRP-USD")
        cutoffs = {
            1: pd.Timestamp("2021-01-19", tz="UTC"),
            3: pd.Timestamp("2021-01-17", tz="UTC"),
            7: pd.Timestamp("2021-01-13", tz="UTC"),
        }
        for horizon, cutoff in cutoffs.items():
            labeled.loc[xrp & labeled["timestamp_utc"].ge(cutoff),
                        f"forward_return_relative_to_btc_{horizon}d"] = np.nan

        for horizon in FORWARD_HORIZONS_DAYS:
            panel = build_horizon_research_panel(labeled, horizon)
            target = f"forward_return_relative_to_btc_{horizon}d"
            expected_sizes = labeled[labeled[target].notna()].groupby(
                "timestamp_utc").size()
            self.assertTrue(panel.groupby("timestamp_utc").size().equals(
                expected_sizes))
            sizes = panel.groupby("timestamp_utc").size()
            self.assertTrue(panel.groupby("timestamp_utc")[
                f"target_top_3_{horizon}d"].sum().equals(
                    sizes.clip(upper=3).astype("Int64")))
            self.assertTrue(panel.groupby("timestamp_utc")[
                f"target_top_5_{horizon}d"].sum().equals(
                    sizes.clip(upper=5).astype("Int64")))
            expected_xrp_dates = set(dates[dates < cutoffs[horizon]])
            actual_xrp_dates = set(panel.loc[
                panel["product_id"].eq("XRP-USD"), "timestamp_utc"])
            self.assertEqual(actual_xrp_dates, expected_xrp_dates)
            self.assertFalse(
                panel.duplicated(["product_id", "timestamp_utc"]).any())
            keys = panel[["product_id", "timestamp_utc"]]
            self.assertTrue(keys.reset_index(drop=True).equals(
                keys.sort_values(
                    ["timestamp_utc", "product_id"]).reset_index(drop=True)))

    def test_required_features_exclude_all_targets(self):
        self.assertFalse(any(
            feature.startswith(("target_", "forward_"))
            for feature in REQUIRED_FEATURES
        ))


if __name__ == "__main__":
    unittest.main()
