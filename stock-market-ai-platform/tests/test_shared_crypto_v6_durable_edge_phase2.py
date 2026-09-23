import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v6_durable_edge import phase2


class FakeProbabilityModel:
    classes_ = np.array(["ALT", "BTC", "CASH"], dtype=object)

    def predict_proba(self, features):
        return np.tile(np.array([[0.20, 0.70, 0.10]]), (len(features), 1))


class SharedCryptoV6Phase2Test(unittest.TestCase):
    def test_folds_are_chronological_and_purged_by_full_target_horizon(self):
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

    def test_probability_columns_follow_frozen_class_order(self):
        probabilities = phase2._ordered_probabilities(
            FakeProbabilityModel(), pd.DataFrame({"x": [1, 2]})
        )
        self.assertTrue(np.allclose(probabilities[0], [0.20, 0.70, 0.10]))
        self.assertEqual(tuple(phase2.CLASSES), ("ALT", "BTC", "CASH"))

    def test_multiclass_brier_is_zero_for_perfect_probabilities(self):
        actual = pd.Series(["ALT", "BTC", "CASH"])
        probabilities = np.eye(3)
        self.assertAlmostEqual(
            phase2._multiclass_brier(actual, probabilities), 0.0
        )

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({"timestamp_utc": [phase2.HOLDOUT]})
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase2.validate_pre_holdout(frame, "test")

    def test_only_hgb_is_primary_and_logistic_is_diagnostic(self):
        models = phase2.model_candidates()
        self.assertEqual(
            set(models),
            {
                "hist_gradient_boosting_classifier",
                "multinomial_logistic_regression_diagnostic",
            },
        )


if __name__ == "__main__":
    unittest.main()
