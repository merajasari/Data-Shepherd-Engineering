import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.crypto_v2.phase4 import (
    rebalance_dates,
    simulate_strategy,
    summarize_path,
    target_weights,
)


class CryptoV2Phase4Tests(unittest.TestCase):
    def _day(self):
        return pd.DataFrame({
            "product_id": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
            "predicted_score": [10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
        })

    def test_target_weights_are_long_only_and_equal_weight(self):
        day = self._day()
        for variant, expected_n in [
            ("top_3_equal_weight", 3),
            ("top_5_equal_weight", 5),
            ("top_quintile_equal_weight", 2),
            ("equal_weight_universe", 10),
        ]:
            w = target_weights(day, variant)
            self.assertEqual(len(w), expected_n)
            self.assertAlmostEqual(sum(w.values()), 1.0)
            self.assertTrue(all(v >= 0 for v in w.values()))

    def test_btc_benchmark_and_cash(self):
        day = self._day().copy()
        day.loc[len(day)] = ["BTC-USD", 100]
        self.assertEqual(target_weights(day, "btc_benchmark"), {"BTC-USD": 1.0})
        self.assertEqual(target_weights(day, "cash"), {})

    def test_rebalance_schedule_is_calendar_based(self):
        dates = pd.to_datetime([
            "2026-01-01", "2026-01-02", "2026-01-08", "2026-01-09", "2026-01-15"
        ], utc=True)
        got = list(rebalance_dates(dates, 7))
        self.assertEqual(got, [dates[0], dates[2], dates[4]])

    def test_completed_candle_signal_does_not_receive_same_day_return(self):
        dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"], utc=True)
        predictions = pd.DataFrame({
            "timestamp_utc": [dates[0], dates[0], dates[1], dates[1], dates[2], dates[2]],
            "product_id": ["A", "B"] * 3,
            "predicted_score": [2.0, 1.0] * 3,
            "fold_id": ["dev_01"] * 6,
            "split": ["development"] * 6,
            "model_id": ["hist_gradient_boosting"] * 6,
            "horizon_days": [7] * 6,
        })
        panel = pd.DataFrame({
            "timestamp_utc": [dates[0], dates[0], dates[1], dates[1], dates[2], dates[2]],
            "product_id": ["A", "B"] * 3,
            "return_1d": [0.50, 0.0, 0.10, 0.0, 0.0, 0.0],
        })
        path = simulate_strategy(predictions, panel, "hist_gradient_boosting", "top_3_equal_weight", 0.0)
        # Initial signal is observed after the first completed candle, so the +50% first-day A return is not captured.
        self.assertAlmostEqual(path.iloc[0]["equity"], 1.0)
        # Next day's +10% A return is earned while A and B are held equally.
        self.assertAlmostEqual(path.iloc[1]["equity"], 1.05)

    def test_costs_reduce_equity(self):
        dates = pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True)
        predictions = pd.DataFrame({
            "timestamp_utc": [dates[0], dates[0], dates[1], dates[1]],
            "product_id": ["A", "B"] * 2,
            "predicted_score": [2.0, 1.0] * 2,
            "fold_id": ["dev_01"] * 4,
            "split": ["development"] * 4,
            "model_id": ["hist_gradient_boosting"] * 4,
            "horizon_days": [7] * 4,
        })
        panel = pd.DataFrame({
            "timestamp_utc": [dates[0], dates[0], dates[1], dates[1]],
            "product_id": ["A", "B"] * 2,
            "return_1d": [0.0, 0.0, 0.0, 0.0],
        })
        zero = simulate_strategy(predictions, panel, "hist_gradient_boosting", "top_3_equal_weight", 0.0)
        costly = simulate_strategy(predictions, panel, "hist_gradient_boosting", "top_3_equal_weight", 50.0)
        self.assertLess(costly.iloc[-1]["equity"], zero.iloc[-1]["equity"])
        self.assertGreater(costly["transaction_cost"].sum(), 0.0)


if __name__ == "__main__":
    unittest.main()
