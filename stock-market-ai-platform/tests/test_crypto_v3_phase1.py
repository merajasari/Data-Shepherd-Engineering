import unittest

import pandas as pd

from ml.crypto_v3.phase1 import (
    BENCHMARK_PRODUCT,
    MIN_NON_BTC_ASSETS,
    TARGET_POSITIVE,
    TARGET_RISK_ADJUSTED,
    VOLATILITY_DENOMINATOR_FLOOR,
    build_dataset,
)
from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES


class CryptoV3Phase1Tests(unittest.TestCase):
    def sample_source(self):
        rows = []
        dates = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
        products = [BENCHMARK_PRODUCT] + [f"ALT{i}-USD" for i in range(1, 12)]
        for ts in dates:
            for i, product in enumerate(products):
                row = {
                    "timestamp_utc": ts,
                    "product_id": product,
                    "return_1d": 0.01,
                    "realized_volatility_30d": 0.20 if i % 2 else 0.05,
                    "forward_return_7d": 0.04 if i % 3 else -0.02,
                    "target_endpoint_utc_7d": ts + pd.Timedelta(days=7),
                    "btc_return_7d": 0.01,
                    "btc_return_30d": 0.02,
                    "btc_realized_volatility_30d": 0.5,
                    "btc_regime": "sample",
                    "source_provider": "coinbase_exchange",
                    "source_granularity": "daily",
                }
                for j, feature in enumerate(REQUIRED_FEATURES):
                    row.setdefault(feature, 0.10 + j * 0.001)
                row["realized_volatility_30d"] = 0.20 if i % 2 else 0.05
                rows.append(row)
        return pd.DataFrame(rows)

    def test_btc_is_excluded_and_breadth_is_non_btc(self):
        out = build_dataset(self.sample_source())
        self.assertFalse((out["product_id"] == BENCHMARK_PRODUCT).any())
        self.assertGreaterEqual(out["eligible_non_btc_asset_count"].min(), MIN_NON_BTC_ASSETS)
        self.assertEqual(out["product_id"].nunique(), 11)

    def test_positive_target_matches_absolute_return_sign(self):
        out = build_dataset(self.sample_source())
        expected = out["forward_return_7d"] > 0
        self.assertTrue((out[TARGET_POSITIVE] == expected).all())

    def test_risk_adjusted_target_uses_fixed_volatility_floor(self):
        out = build_dataset(self.sample_source())
        low_vol = out[out["realized_volatility_30d"] < VOLATILITY_DENOMINATOR_FLOOR].iloc[0]
        expected = low_vol["forward_return_7d"] / VOLATILITY_DENOMINATOR_FLOOR
        self.assertAlmostEqual(low_vol[TARGET_RISK_ADJUSTED], expected)

    def test_rejects_insufficient_non_btc_breadth(self):
        source = self.sample_source()
        keep = [BENCHMARK_PRODUCT] + [f"ALT{i}-USD" for i in range(1, 9)]
        source = source[source["product_id"].isin(keep)].copy()
        out = build_dataset(source)
        self.assertTrue(out.empty)


if __name__ == "__main__":
    unittest.main()
