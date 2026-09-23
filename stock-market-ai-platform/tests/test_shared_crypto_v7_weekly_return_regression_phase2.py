import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v7_weekly_return_regression import phase2


class SharedCryptoV7Phase2Test(unittest.TestCase):
    def test_folds_are_chronological_and_purged_by_full_week(self):
        timestamps = pd.Series(pd.date_range(
            "2021-01-01T00:00:00Z", periods=1800, freq="24h"
        ))
        timestamps = timestamps[timestamps < phase2.HOLDOUT].reset_index(drop=True)
        folds = phase2.make_folds(timestamps)
        self.assertGreaterEqual(len(folds), 1)
        for fold in folds:
            train = timestamps[fold["train"]]
            validation = timestamps[fold["validation"]]
            self.assertEqual(fold["train_end"], fold["start"] - phase2.PURGE)
            self.assertLess(train.max(), fold["train_end"])
            self.assertGreaterEqual(validation.min(), fold["start"])
            self.assertLess(validation.max(), fold["end"])
            self.assertLess(validation.max(), phase2.HOLDOUT)

    def test_sleeve_rule_uses_larger_positive_prediction_or_cash(self):
        sleeves = phase2.choose_sleeve(
            np.array([0.03, -0.01, 0.02, 0.00]),
            np.array([0.01, -0.02, 0.04, 0.00]),
        )
        self.assertEqual(sleeves.tolist(), ["BTC", "CASH", "ALT", "CASH"])

    def test_regression_metrics_report_improvement_against_train_mean(self):
        actual = np.array([0.10, -0.10, 0.05, -0.05])
        predicted = np.array([0.09, -0.08, 0.04, -0.04])
        baseline = np.zeros(4)
        metrics = phase2._regression_metrics(actual, predicted, baseline)
        self.assertGreater(metrics["mae_improvement_vs_train_mean"], 0.0)
        self.assertEqual(metrics["sign_accuracy"], 1.0)
        self.assertGreater(metrics["spearman"], 0.9)

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({"timestamp_utc": [phase2.HOLDOUT]})
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase2.validate_pre_holdout(frame, "test")

    def test_only_hgb_is_primary_and_ridge_is_diagnostic(self):
        models = phase2.model_candidates()
        self.assertEqual(
            set(models),
            {phase2.PRIMARY_MODEL, phase2.DIAGNOSTIC_MODEL},
        )
        self.assertEqual(
            models[phase2.PRIMARY_MODEL].named_steps["model"].loss,
            "absolute_error",
        )


if __name__ == "__main__":
    unittest.main()
