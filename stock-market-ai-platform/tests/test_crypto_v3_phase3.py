import unittest

import pandas as pd

from ml.crypto_v3.phase3 import (
    CLASSIFIER_THRESHOLD,
    HORIZON_DAYS,
    RANK_MODEL_ID,
    rebalance_dates,
    selected_products,
    target_weights,
)


class CryptoV3Phase3Tests(unittest.TestCase):
    def sample_day(self):
        return pd.DataFrame({
            "timestamp_utc": [pd.Timestamp("2026-01-01", tz="UTC")] * 6,
            "product_id": ["A", "B", "C", "D", "E", "F"],
            "fold_id": ["dev_01"] * 6,
            "split": ["development"] * 6,
            "predicted_positive_probability": [0.80, 0.70, 0.60, 0.51, 0.50, 0.20],
            "predicted_risk_adjusted_return_7d": [0.10, 0.30, -0.10, 0.20, 0.50, 0.40],
            "passes_classifier_gate": [True, True, True, True, False, False],
        })

    def test_preregistered_threshold_and_ranker(self):
        self.assertEqual(CLASSIFIER_THRESHOLD, 0.50)
        self.assertEqual(RANK_MODEL_ID, "ridge")

    def test_selected_products_gate_then_rank(self):
        day = self.sample_day()
        self.assertEqual(selected_products(day, "gated_top_3"), ["B", "D", "A"])
        self.assertEqual(selected_products(day, "gated_top_5"), ["B", "D", "A", "C"])
        self.assertEqual(selected_products(day, "gated_top_quintile"), ["B"])

    def test_no_passing_assets_means_cash(self):
        day = self.sample_day().copy()
        day["passes_classifier_gate"] = False
        self.assertEqual(selected_products(day, "gated_top_3"), [])
        self.assertEqual(target_weights(day, "gated_top_3"), {})

    def test_equal_weight_universe_uses_all_non_btc_assets(self):
        day = self.sample_day()
        weights = target_weights(day, "equal_weight_non_btc_universe")
        self.assertEqual(set(weights), set(day["product_id"]))
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_rebalance_schedule_is_seven_days(self):
        dates = pd.date_range("2026-01-01", periods=22, freq="D", tz="UTC")
        schedule = rebalance_dates(dates)
        self.assertEqual(HORIZON_DAYS, 7)
        self.assertEqual(list(schedule[:4]), [
            pd.Timestamp("2026-01-01", tz="UTC"),
            pd.Timestamp("2026-01-08", tz="UTC"),
            pd.Timestamp("2026-01-15", tz="UTC"),
            pd.Timestamp("2026-01-22", tz="UTC"),
        ])


if __name__ == "__main__":
    unittest.main()
