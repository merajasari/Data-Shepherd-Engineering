import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier

from ml.shared_crypto_v9_deviation_classifier import phase2


class SharedCryptoV9Phase2Test(unittest.TestCase):
    def test_folds_use_full_72h_purge(self):
        timestamps = pd.Series(pd.date_range(
            "2021-01-01T00:00:00Z",
            periods=1900,
            freq="24h",
        ))
        timestamps = timestamps[
            timestamps < phase2.HOLDOUT
        ].reset_index(drop=True)

        folds = phase2.make_folds(
            timestamps
        )
        self.assertGreaterEqual(
            len(folds),
            1,
        )
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

    def test_only_preregistered_logistic_family_is_used(self):
        pipeline = phase2.model_template()

        self.assertEqual(
            phase2.PRIMARY_MODEL,
            "logistic_regression",
        )
        self.assertEqual(
            phase2.LOGISTIC_C,
            0.5,
        )
        self.assertEqual(
            phase2.PROBABILITY_THRESHOLD,
            0.50,
        )

        model = pipeline.named_steps[
            "model"
        ]
        self.assertEqual(
            model.C,
            0.5,
        )
        self.assertEqual(
            model.penalty,
            "l2",
        )
        self.assertEqual(
            model.solver,
            "lbfgs",
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

    def test_classification_metrics_use_fixed_threshold_and_prevalence_baseline(self):
        actual = pd.Series(
            [0, 0, 1, 1]
        )
        probability = np.array([
            0.20,
            0.40,
            0.60,
            0.80,
        ])

        metrics = phase2.classification_metrics(
            actual,
            probability,
            train_prevalence=0.50,
        )

        self.assertAlmostEqual(
            metrics[
                "balanced_accuracy"
            ],
            1.0,
        )
        self.assertGreater(
            metrics[
                "brier_improvement_vs_train_prevalence"
            ],
            0.0,
        )
        self.assertGreater(
            metrics[
                "log_loss_improvement_vs_train_prevalence"
            ],
            0.0,
        )

    def test_walk_forward_fits_targets_independently(self):
        timestamps = pd.date_range(
            "2023-01-01T00:00:00Z",
            periods=1000,
            freq="24h",
        )
        x = np.arange(
            len(timestamps)
        )
        alternating = (
            x % 2
        ).astype(int)

        data = pd.DataFrame({
            "timestamp_utc": timestamps,
            "x": x.astype(float),
            "btc_forward_return_72h": (
                np.where(
                    alternating == 1,
                    -0.02,
                    0.02,
                )
            ),
            "alt_forward_return_72h": (
                np.where(
                    alternating == 1,
                    0.03,
                    0.00,
                )
            ),
            "alt_excess_vs_btc_net25_72h": (
                np.where(
                    alternating == 1,
                    0.0475,
                    -0.0225,
                )
            ),
            "cash_excess_vs_btc_net25_72h": (
                np.where(
                    alternating == 1,
                    0.0175,
                    -0.0225,
                )
            ),
            "alt_beats_btc_net25_72h": alternating,
            "cash_beats_btc_net25_72h": alternating,
            "alt_basket_assets": [
                "A|B|C|D|E"
            ] * len(timestamps),
            "oracle_best_deviation_net25_72h": [
                "ALT"
            ] * len(timestamps),
        })
        data = data[
            data["timestamp_utc"]
            < phase2.HOLDOUT
        ].reset_index(drop=True)

        with patch.object(
            phase2,
            "model_template",
            return_value=DummyClassifier(
                strategy="prior"
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
                    f"probability_{target}_"
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

    def test_predictive_gates_require_all_eight_to_pass(self):
        summary = pd.DataFrame([
            {
                "target": (
                    "alt_beats_btc_net25_72h"
                ),
                "median_roc_auc": 0.56,
                "median_balanced_accuracy": 0.55,
                "median_brier_improvement_vs_train_prevalence": 0.001,
                "median_log_loss_improvement_vs_train_prevalence": 0.002,
            },
            {
                "target": (
                    "cash_beats_btc_net25_72h"
                ),
                "median_roc_auc": 0.55,
                "median_balanced_accuracy": 0.51,
                "median_brier_improvement_vs_train_prevalence": 0.001,
                "median_log_loss_improvement_vs_train_prevalence": 0.002,
            },
        ])
        contract = {
            "predictive_quality_gates": {
                "median_roc_auc_each_target_gt": 0.52,
                "median_balanced_accuracy_each_target_gt": 0.52,
                "median_brier_improvement_vs_train_prevalence_each_target_gt": 0.0,
                "median_log_loss_improvement_vs_train_prevalence_each_target_gt": 0.0,
            }
        }

        detail, result = (
            phase2.evaluate_predictive_gates(
                summary,
                contract,
            )
        )

        self.assertEqual(
            result[
                "total_predictive_gate_count"
            ],
            8,
        )
        self.assertEqual(
            result[
                "passed_predictive_gate_count"
            ],
            7,
        )
        self.assertEqual(
            result[
                "passed_target_count"
            ],
            1,
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
                "median_roc_auc": 0.56,
                "median_balanced_accuracy": 0.55,
                "median_brier_improvement_vs_train_prevalence": 0.001,
                "median_log_loss_improvement_vs_train_prevalence": 0.002,
            }
            for target in phase2.TARGETS
        ])
        contract = {
            "predictive_quality_gates": {
                "median_roc_auc_each_target_gt": 0.52,
                "median_balanced_accuracy_each_target_gt": 0.52,
                "median_brier_improvement_vs_train_prevalence_each_target_gt": 0.0,
                "median_log_loss_improvement_vs_train_prevalence_each_target_gt": 0.0,
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
