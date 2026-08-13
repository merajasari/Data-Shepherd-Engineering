import unittest

import numpy as np
import pandas as pd

from ml.v5.phase2 import (
    MODEL_IDS,
    _daily_metric,
    summarize_predictions,
)


class V5Phase2Tests(unittest.TestCase):
    def test_registered_models_are_frozen(self):
        self.assertEqual(
            MODEL_IDS,
            (
                "hist_gradient_boosting",
                "ridge",
                "momentum_20d",
                "equal_score",
                "random_score",
            ),
        )

    def test_daily_metric_rewards_correct_ranking(self):
        g = pd.DataFrame(
            {
                "actual_relative_return_5d": [-0.04, -0.02, 0.01, 0.03, 0.08],
                "predicted_score": [-4.0, -2.0, 1.0, 3.0, 8.0],
            }
        )
        out = _daily_metric(g)
        self.assertGreater(out["ic"], 0.99)
        self.assertAlmostEqual(out["top_5_relative_return"], g["actual_relative_return_5d"].mean())
        self.assertGreater(out["top_minus_bottom_spread"], 0)

    def test_equal_score_has_nan_ic(self):
        g = pd.DataFrame(
            {
                "actual_relative_return_5d": [-0.02, 0.00, 0.01, 0.03],
                "predicted_score": [0.0, 0.0, 0.0, 0.0],
            }
        )
        out = _daily_metric(g)
        self.assertTrue(np.isnan(out["ic"]))

    def test_summary_supports_cross_sectional_metrics(self):
        predictions = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
                    utc=True,
                ),
                "symbol": list("ABCD") * 2,
                "actual_relative_return_5d": [-0.03, -0.01, 0.02, 0.05, -0.02, 0.00, 0.01, 0.04],
                "predicted_score": [-0.02, -0.01, 0.03, 0.06, -0.01, 0.01, 0.02, 0.05],
                "fold_id": ["dev_01"] * 8,
                "split": ["development"] * 8,
                "model_id": ["ridge"] * 8,
                "horizon_days": [5] * 8,
            }
        )

        daily = (
            predictions.groupby(
                ["horizon_days", "model_id", "split", "fold_id", "timestamp_utc"],
                observed=True,
            )
            .apply(_daily_metric, include_groups=False)
            .reset_index()
        )
        out = summarize_predictions(predictions, daily)

        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["day_count"], 2)
        self.assertEqual(out.iloc[0]["fold_count"], 1)
        self.assertGreater(out.iloc[0]["mean_ic"], 0.9)
        self.assertGreater(out.iloc[0]["top_minus_bottom_spread"], 0)
        self.assertGreater(out.iloc[0]["directional_sign_accuracy"], 0.5)


if __name__ == "__main__":
    unittest.main()
