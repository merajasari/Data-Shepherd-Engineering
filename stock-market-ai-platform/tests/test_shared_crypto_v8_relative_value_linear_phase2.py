import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor

from ml.shared_crypto_v8_relative_value_linear import phase2


class SharedCryptoV8Phase2Test(unittest.TestCase):
    def test_folds_use_full_72h_purge(self):
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
        self.assertLessEqual(
            len(folds),
            phase2.MAX_FOLDS,
        )

        for fold in folds:
            train = timestamps[
                fold["train"]
            ]
            validation = timestamps[
                fold["validation"]
            ]
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

    def test_only_preregistered_ridge_family_is_used(self):
        pipeline = phase2.model_template()
        self.assertEqual(
            phase2.PRIMARY_MODEL,
            "ridge_regression",
        )
        self.assertEqual(
            phase2.RIDGE_ALPHA,
            10.0,
        )
        self.assertEqual(
            phase2.TARGETS,
            (
                "alt_excess_vs_btc_net25_72h",
                "cash_excess_vs_btc_net25_72h",
            ),
        )
        self.assertEqual(
            pipeline.named_steps[
                "model"
            ].alpha,
            10.0,
        )

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({
            "timestamp_utc": [
                phase2.HOLDOUT
            ],
        })
        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase2.validate_pre_holdout(
                frame,
                "test",
            )

    def test_walk_forward_fits_targets_independently(self):
        timestamps = pd.date_range(
            "2023-01-01T00:00:00Z",
            periods=1000,
            freq="24h",
        )
        x = np.linspace(
            -1.0,
            1.0,
            len(timestamps),
        )
        data = pd.DataFrame({
            "timestamp_utc": timestamps,
            "x": x,
            "btc_forward_return_72h": 0.01 * x,
            "alt_forward_return_72h": 0.02 * x,
            "alt_excess_vs_btc_net25_72h": 0.01 * x - 0.0025,
            "cash_excess_vs_btc_net25_72h": -0.01 * x - 0.0025,
            "alt_basket_assets": [
                "A|B|C|D|E"
            ] * len(timestamps),
            "oracle_best_deviation_net25_72h": [
                "BTC"
            ] * len(timestamps),
            "oracle_best_excess_vs_btc_net25_72h": [
                0.0
            ] * len(timestamps),
        })
        data = data[
            data["timestamp_utc"]
            < phase2.HOLDOUT
        ].reset_index(drop=True)

        with patch.object(
            phase2,
            "model_template",
            return_value=DummyRegressor(
                strategy="mean"
            ),
        ):
            predictions, metrics = (
                phase2.walk_forward(
                    data,
                    ["x"],
                )
            )

        self.assertFalse(
            predictions.empty
        )
        self.assertFalse(
            metrics.empty
        )
        self.assertEqual(
            set(metrics["target"]),
            set(phase2.TARGETS),
        )
        self.assertEqual(
            set(metrics["model_id"]),
            {phase2.PRIMARY_MODEL},
        )
        for target in phase2.TARGETS:
            self.assertIn(
                (
                    f"predicted_{target}_"
                    f"{phase2.PRIMARY_MODEL}"
                ),
                predictions.columns,
            )
        self.assertTrue(
            (
                pd.to_datetime(
                    predictions[
                        "timestamp_utc"
                    ],
                    utc=True,
                )
                < phase2.HOLDOUT
            ).all()
        )

    def test_predictive_gates_require_every_target_to_pass(self):
        summary = pd.DataFrame([
            {
                "target": (
                    "alt_excess_vs_btc_net25_72h"
                ),
                "median_pearson_correlation": 0.10,
                "median_mae_improvement_vs_train_mean": 0.001,
                "median_sign_accuracy": 0.55,
            },
            {
                "target": (
                    "cash_excess_vs_btc_net25_72h"
                ),
                "median_pearson_correlation": 0.05,
                "median_mae_improvement_vs_train_mean": -0.001,
                "median_sign_accuracy": 0.60,
            },
        ])
        contract = {
            "predictive_quality_gates": {
                "median_pearson_correlation_each_target_gt": 0.0,
                "median_mae_improvement_vs_train_mean_each_target_gt": 0.0,
                "median_sign_accuracy_each_target_gt": 0.50,
            }
        }

        detail, result = (
            phase2.evaluate_predictive_gates(
                summary,
                contract,
            )
        )

        self.assertEqual(
            result["target_count"],
            2,
        )
        self.assertEqual(
            result[
                "passed_target_count"
            ],
            1,
        )
        self.assertEqual(
            result[
                "passed_predictive_gate_count"
            ],
            5,
        )
        self.assertEqual(
            result[
                "total_predictive_gate_count"
            ],
            6,
        )
        self.assertFalse(
            result[
                "all_predictive_gates_pass"
            ]
        )
        self.assertEqual(
            result["status"],
            "STOP_BEFORE_PORTFOLIO_SIMULATION",
        )
        self.assertEqual(
            len(detail),
            2,
        )

    def test_predictive_gates_allow_simulation_only_when_all_pass(self):
        summary = pd.DataFrame([
            {
                "target": target,
                "median_pearson_correlation": 0.10,
                "median_mae_improvement_vs_train_mean": 0.001,
                "median_sign_accuracy": 0.55,
            }
            for target in phase2.TARGETS
        ])
        contract = {
            "predictive_quality_gates": {
                "median_pearson_correlation_each_target_gt": 0.0,
                "median_mae_improvement_vs_train_mean_each_target_gt": 0.0,
                "median_sign_accuracy_each_target_gt": 0.50,
            }
        }

        _, result = (
            phase2.evaluate_predictive_gates(
                summary,
                contract,
            )
        )
        self.assertTrue(
            result[
                "all_predictive_gates_pass"
            ]
        )
        self.assertEqual(
            result["status"],
            "ALLOW_POLICY_SIMULATION",
        )


if __name__ == "__main__":
    unittest.main()
