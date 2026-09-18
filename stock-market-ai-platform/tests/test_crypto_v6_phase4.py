import unittest

import numpy as np
import pandas as pd

from ml.crypto_v6.phase2 import FEATURE_SET_V5, FEATURE_SET_V6
from ml.crypto_v6.phase4 import (
    _safe_correlation,
    feature_coverage,
    fold_portfolio_diagnostics,
    paired_fold_deltas,
    redundancy_table,
    target_associations,
)


class CryptoV6Phase4DiagnosticsTest(unittest.TestCase):
    def test_coverage_and_target_associations_handle_constant_features(self):
        frame = pd.DataFrame({
            "news_a": [0.0, 0.0, 1.0, 2.0],
            "news_b": [0.0, 0.0, 0.0, 0.0],
            "target": [0.0, 1.0, 2.0, 3.0],
        })
        coverage = feature_coverage(frame, "ranking", ("news_a", "news_b"))
        constant = coverage.set_index("feature").loc["news_b"]
        self.assertEqual(constant["zero_fraction"], 1.0)
        associations = target_associations(
            frame, "ranking", ("news_a", "news_b"), ("target",)
        ).set_index("feature")
        self.assertGreater(associations.loc["news_a", "spearman"], 0.0)
        self.assertTrue(np.isnan(associations.loc["news_b", "pearson"]))
        self.assertTrue(np.isnan(_safe_correlation(frame["news_b"], frame["target"])))

    def test_redundancy_reports_only_high_absolute_pairs(self):
        frame = pd.DataFrame({
            "a": [0, 1, 2, 3],
            "b": [0, 2, 4, 6],
            "c": [0, 1, 0, 1],
        })
        result = redundancy_table(frame, "allocation", ("a", "b", "c"), 0.80)
        pairs = {(row.feature_left, row.feature_right) for row in result.itertuples()}
        self.assertIn(("a", "b"), pairs)
        self.assertNotIn(("a", "c"), pairs)

    def test_fold_diagnostics_preserve_paired_clock_and_calculate_delta(self):
        times = pd.to_datetime(["2025-01-01T00:00:00Z", "2025-01-04T00:00:00Z"])
        periods = []
        predictions = []
        for feature_set, returns in (
            (FEATURE_SET_V5, (0.01, 0.01)),
            (FEATURE_SET_V6, (0.02, 0.02)),
        ):
            for timestamp, net_return in zip(times, returns):
                periods.append({
                    "feature_set": feature_set,
                    "timestamp_utc": timestamp,
                    "model_id": "ridge",
                    "horizon_days": 3,
                    "top_n": 3,
                    "cost_bps_round_trip": 25.0,
                    "net_return": net_return,
                    "turnover": 0.1,
                })
                predictions.append({
                    "feature_set": feature_set,
                    "timestamp_utc": timestamp,
                    "model_id": "ridge",
                    "horizon_days": 3,
                    "fold_id": "dev_01",
                })
        metrics = fold_portfolio_diagnostics(
            pd.DataFrame(periods), pd.DataFrame(predictions)
        )
        deltas = paired_fold_deltas(metrics)
        self.assertEqual(len(metrics), 2)
        self.assertEqual(len(deltas), 1)
        self.assertGreater(deltas.iloc[0]["v6_minus_v5_ending_equity"], 0.0)

    def test_missing_fold_pair_fails_closed(self):
        frame = pd.DataFrame([{
            "feature_set": FEATURE_SET_V5,
            "fold_id": "dev_01",
            "ending_equity": 1.0,
            "cumulative_return": 0.0,
            "sharpe": 0.0,
            "maximum_drawdown": 0.0,
            "total_turnover": 0.0,
        }])
        with self.assertRaisesRegex(RuntimeError, "Missing paired fold"):
            paired_fold_deltas(frame)


if __name__ == "__main__":
    unittest.main()
