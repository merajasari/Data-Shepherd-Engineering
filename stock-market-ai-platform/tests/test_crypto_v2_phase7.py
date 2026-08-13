import unittest

import numpy as np
import pandas as pd

from ml.crypto_v2.phase3 import MODEL_FEATURES
from ml.crypto_v2.phase7 import (
    BENCHMARK_PRODUCT,
    INVESTABLE_MIN_ASSETS,
    build_ex_btc_universe,
    rebalance_dates,
    target_products,
)


class CryptoV2Phase7Tests(unittest.TestCase):
    def sample_panel(self, asset_count=11, days=20):
        dates = pd.date_range("2025-01-01", periods=days, freq="D", tz="UTC")
        products = [BENCHMARK_PRODUCT] + [f"ALT{i:02d}-USD" for i in range(asset_count)]
        rows = []
        for ts in dates:
            for j, product in enumerate(products):
                row = {
                    "timestamp_utc": ts,
                    "product_id": product,
                    "return_1d": 0.001 * (j + 1),
                    "forward_return_relative_to_btc_7d": 0.002 * j,
                    "target_endpoint_utc_7d": ts + pd.Timedelta(days=7),
                }
                for i, col in enumerate(MODEL_FEATURES):
                    row[col] = 0.01 + i * 0.001 + j * 0.0001
                rows.append(row)
        return pd.DataFrame(rows)

    def test_ex_btc_universe_removes_btc(self):
        panel = self.sample_panel(asset_count=11)
        out = build_ex_btc_universe(panel)
        self.assertFalse((out["product_id"] == BENCHMARK_PRODUCT).any())
        self.assertEqual(out["product_id"].nunique(), 11)

    def test_breadth_is_applied_after_btc_exclusion(self):
        panel = self.sample_panel(asset_count=INVESTABLE_MIN_ASSETS - 1)
        out = build_ex_btc_universe(panel)
        self.assertTrue(out.empty)

    def test_target_products_never_selects_btc(self):
        day = pd.DataFrame({
            "product_id": ["ALT01-USD", "ALT02-USD", "ALT03-USD", "ALT04-USD", "ALT05-USD"],
            "predicted_score": [5, 4, 3, 2, 1],
        })
        selected = target_products(day, "ex_btc_top_3_equal_weight")
        self.assertEqual(selected, ["ALT01-USD", "ALT02-USD", "ALT03-USD"])
        self.assertNotIn(BENCHMARK_PRODUCT, selected)

    def test_rebalance_schedule_is_seven_calendar_days(self):
        dates = pd.date_range("2025-01-01", periods=22, freq="D", tz="UTC")
        schedule = rebalance_dates(dates)
        self.assertEqual(list(schedule[:4]), [
            pd.Timestamp("2025-01-01", tz="UTC"),
            pd.Timestamp("2025-01-08", tz="UTC"),
            pd.Timestamp("2025-01-15", tz="UTC"),
            pd.Timestamp("2025-01-22", tz="UTC"),
        ])


if __name__ == "__main__":
    unittest.main()
