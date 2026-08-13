import unittest

import numpy as np
import pandas as pd

from ml.crypto_v2.phase6 import (
    MARKET_FEATURES,
    MARKET_GATE_THRESHOLD,
    build_market_frame,
    selected_products,
)


class CryptoV2Phase6Tests(unittest.TestCase):
    def _panel(self):
        rows = []
        dates = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
        for ts in dates:
            for i, product in enumerate(["BTC-USD", "ETH-USD", "SOL-USD"]):
                rows.append({
                    "timestamp_utc": ts,
                    "product_id": product,
                    "return_1d": 0.01 * (i + 1),
                    "return_7d": 0.02 * (i + 1),
                    "return_30d": 0.03 * (i + 1),
                    "realized_volatility_30d": 0.4 + 0.1 * i,
                    "drawdown_from_high_30d": -0.1 * i,
                    "btc_relative_return_7d": 0.01 * i,
                    "btc_return_7d": 0.02,
                    "btc_return_14d": 0.03,
                    "btc_return_30d": 0.04,
                    "btc_realized_volatility_14d": 0.5,
                    "btc_realized_volatility_30d": 0.6,
                    "btc_close_to_sma_30": 0.05,
                    "forward_return_7d": [-0.01, 0.02, 0.05][i],
                    "target_endpoint_utc_7d": ts + pd.Timedelta(days=7),
                })
        return pd.DataFrame(rows)

    def test_market_frame_is_one_row_per_timestamp(self):
        frame = build_market_frame(self._panel())
        self.assertEqual(len(frame), 3)
        self.assertFalse(frame.duplicated(["timestamp_utc"]).any())
        self.assertEqual(frame["eligible_asset_count"].tolist(), [3, 3, 3])

    def test_market_target_is_equal_weight_universe_mean(self):
        frame = build_market_frame(self._panel())
        expected = np.mean([-0.01, 0.02, 0.05])
        self.assertTrue(np.allclose(frame["actual_market_forward_return_7d"], expected))

    def test_market_features_are_predecision_only_and_present(self):
        frame = build_market_frame(self._panel())
        self.assertTrue(set(MARKET_FEATURES).issubset(frame.columns))
        self.assertFalse(frame[list(MARKET_FEATURES)].isna().any().any())
        self.assertEqual(MARKET_GATE_THRESHOLD, 0.0)

    def test_risk_off_selects_cash(self):
        day = pd.DataFrame({
            "product_id": ["BTC-USD", "ETH-USD", "SOL-USD"],
            "predicted_score": [0.1, 0.3, 0.2],
            "market_risk_on": [False, False, False],
        })
        self.assertEqual(selected_products(day, "market_gated_top_3"), [])

    def test_risk_on_uses_frozen_rank_score_order(self):
        day = pd.DataFrame({
            "product_id": ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD"],
            "predicted_score": [0.1, 0.4, 0.3, 0.2],
            "market_risk_on": [True, True, True, True],
        })
        self.assertEqual(
            selected_products(day, "market_gated_top_3"),
            ["ETH-USD", "SOL-USD", "ADA-USD"],
        )


if __name__ == "__main__":
    unittest.main()
