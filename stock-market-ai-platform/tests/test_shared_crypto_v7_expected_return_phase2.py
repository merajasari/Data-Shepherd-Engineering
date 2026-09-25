import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor

from ml.shared_crypto_v7_expected_return import phase2


class SharedCryptoV7Phase2Test(unittest.TestCase):
    def test_folds_are_chronological_and_purged_by_full_72h_horizon(self):
        timestamps = pd.Series(pd.date_range(
            "2021-01-01T00:00:00Z",
            periods=1900,
            freq="24h",
        ))
        timestamps = timestamps[
            timestamps < phase2.HOLDOUT
        ].reset_index(drop=True)

        folds = phase2.make_folds(timestamps)
        self.assertGreaterEqual(len(folds), 1)
        self.assertLessEqual(len(folds), phase2.MAX_FOLDS)

        for fold in folds:
            train = timestamps[fold["train"]]
            validation = timestamps[fold["validation"]]
            self.assertEqual(
                fold["train_end"],
                fold["start"] - phase2.PURGE,
            )
            self.assertLess(
                train.max(),
                fold["train_end"],
            )
            self.assertGreaterEqual(
                validation.min(),
                fold["start"],
            )
            self.assertLess(
                validation.max(),
                fold["end"],
            )
            self.assertLess(
                validation.max(),
                phase2.HOLDOUT,
            )

    def test_only_preregistered_primary_and_diagnostic_families_exist(self):
        models = phase2.model_candidates()
        self.assertEqual(
            set(models),
            {
                phase2.PRIMARY_MODEL,
                phase2.DIAGNOSTIC_MODEL,
            },
        )
        self.assertEqual(
            phase2.PRIMARY_MODEL,
            "hist_gradient_boosting_regressor",
        )
        self.assertEqual(
            phase2.DIAGNOSTIC_MODEL,
            "ridge_regression_diagnostic",
        )
        self.assertEqual(
            phase2.TARGETS,
            (
                "btc_net_entry_return_72h",
                "alt_net_entry_return_72h",
            ),
        )

    def test_regression_metrics_reward_perfect_predictions(self):
        actual = pd.Series([-0.02, 0.01, 0.03, -0.01])
        predicted = actual.to_numpy(copy=True)
        metrics = phase2.regression_metrics(
            actual,
            predicted,
            baseline_prediction=0.0,
        )
        self.assertAlmostEqual(metrics["mae"], 0.0)
        self.assertAlmostEqual(metrics["rmse"], 0.0)
        self.assertAlmostEqual(metrics["r2"], 1.0)
        self.assertAlmostEqual(metrics["pearson_correlation"], 1.0)
        self.assertAlmostEqual(metrics["sign_accuracy"], 1.0)
        self.assertGreater(
            metrics["mae_improvement_vs_train_mean"],
            0.0,
        )
        self.assertGreater(
            metrics["rmse_improvement_vs_train_mean"],
            0.0,
        )

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({
            "timestamp_utc": [phase2.HOLDOUT],
        })
        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase2.validate_pre_holdout(frame, "test")

    def test_walk_forward_fits_targets_independently(self):
        timestamps = pd.date_range(
            "2023-01-01T00:00:00Z",
            periods=1000,
            freq="24h",
        )
        trend = np.linspace(-0.04, 0.05, len(timestamps))
        data = pd.DataFrame({
            "timestamp_utc": timestamps,
            "x": np.sin(np.arange(len(timestamps)) / 20.0),
            "btc_forward_return_72h": trend + 0.002,
            "alt_forward_return_72h": trend * 1.4 - 0.001,
            "btc_net_entry_return_72h": trend,
            "alt_net_entry_return_72h": trend * 1.4 - 0.0035,
            "alt_basket_assets": ["A|B|C|D|E"] * len(timestamps),
            "oracle_best_sleeve_net25_72h": ["BTC"] * len(timestamps),
        })
        data = data[data["timestamp_utc"] < phase2.HOLDOUT].reset_index(
            drop=True
        )

        dummy_models = {
            phase2.PRIMARY_MODEL: DummyRegressor(strategy="mean"),
            phase2.DIAGNOSTIC_MODEL: DummyRegressor(strategy="median"),
        }
        with patch.object(
            phase2,
            "model_candidates",
            return_value=dummy_models,
        ):
            predictions, metrics = phase2.walk_forward(
                data,
                ["x"],
            )

        self.assertFalse(predictions.empty)
        self.assertFalse(metrics.empty)
        self.assertEqual(
            set(metrics["target"]),
            set(phase2.TARGETS),
        )
        self.assertEqual(
            set(metrics["model_id"]),
            set(dummy_models),
        )
        for target in phase2.TARGETS:
            for model_id in dummy_models:
                self.assertIn(
                    f"predicted_{target}_{model_id}",
                    predictions.columns,
                )
        self.assertTrue(
            (
                pd.to_datetime(
                    predictions["timestamp_utc"],
                    utc=True,
                )
                < phase2.HOLDOUT
            ).all()
        )


if __name__ == "__main__":
    unittest.main()
