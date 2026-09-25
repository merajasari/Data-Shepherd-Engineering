import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v12_btc_specialist import phase2


class SharedCryptoV12Phase2Test(unittest.TestCase):
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
                fold["start"]
                - phase2.PURGE,
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

    def test_stage1_uses_only_frozen_hist_gradient_boosting(self):
        model = phase2.stage1_model_template()

        self.assertEqual(
            phase2.STAGE1_MODEL,
            "hist_gradient_boosting_classifier",
        )
        self.assertEqual(
            model.learning_rate,
            0.05,
        )
        self.assertEqual(
            model.max_iter,
            200,
        )
        self.assertEqual(
            model.max_leaf_nodes,
            15,
        )
        self.assertEqual(
            model.min_samples_leaf,
            30,
        )
        self.assertEqual(
            model.l2_regularization,
            1.0,
        )

    def test_stage2_is_unchanged_balanced_linear_svc(self):
        pipeline = (
            phase2.stage2_model_template()
        )
        model = pipeline.named_steps[
            "model"
        ]

        self.assertEqual(
            phase2.STAGE2_MODEL,
            "linear_svc",
        )
        self.assertEqual(
            model.C,
            0.25,
        )
        self.assertEqual(
            model.class_weight,
            "balanced",
        )
        self.assertEqual(
            model.loss,
            "squared_hinge",
        )
        self.assertEqual(
            model.penalty,
            "l2",
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

    def test_combined_metrics_preserve_three_class_recall(self):
        actual = pd.Series([
            "BTC", "ALT", "CASH",
            "BTC", "ALT", "CASH",
        ])
        predicted = np.array([
            "BTC", "ALT", "CASH",
            "BTC", "ALT", "BTC",
        ], dtype=object)
        train = pd.Series([
            "BTC", "ALT", "CASH",
            "ALT", "CASH", "CASH",
        ])

        metrics = phase2.combined_metrics(
            actual,
            predicted,
            train,
        )

        self.assertGreater(
            metrics[
                "balanced_accuracy"
            ],
            0.0,
        )
        self.assertGreater(
            metrics[
                "macro_f1"
            ],
            0.0,
        )
        self.assertGreater(
            metrics[
                "multiclass_mcc"
            ],
            0.0,
        )
        self.assertEqual(
            metrics[
                "minimum_class_recall"
            ],
            metrics[
                "cash_recall"
            ],
        )

    def test_predictive_gates_require_all_nine_to_pass(self):
        summary = pd.DataFrame([{
            "research_version": (
                phase2.RESEARCH_VERSION
            ),
            "fold_count": 6,
            "median_stage1_balanced_accuracy": 0.55,
            "median_stage1_mcc": 0.08,
            "median_stage2_balanced_accuracy": 0.54,
            "median_stage2_mcc": 0.06,
            "median_combined_balanced_accuracy": 0.39,
            "median_combined_macro_f1": 0.38,
            "median_combined_accuracy_improvement_vs_train_majority": 0.02,
            "median_combined_multiclass_mcc": 0.05,
            "median_combined_minimum_class_recall": 0.19,
        }])
        contract = {
            "predictive_quality_gates": {
                "stage1_median_balanced_accuracy_gt": 0.52,
                "stage1_median_mcc_gt": 0.0,
                "stage2_median_balanced_accuracy_gt": 0.52,
                "stage2_median_mcc_gt": 0.0,
                "combined_median_balanced_accuracy_gt": 0.36,
                "combined_median_macro_f1_gt": 0.36,
                "combined_median_accuracy_improvement_vs_train_majority_gt": 0.0,
                "combined_median_multiclass_mcc_gt": 0.0,
                "combined_median_minimum_class_recall_gt": 0.20,
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
            9,
        )
        self.assertEqual(
            result[
                "passed_predictive_gate_count"
            ],
            8,
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
            int(
                detail.iloc[0][
                    "passed_gate_count"
                ]
            ),
            8,
        )

    def test_predictive_gates_allow_simulation_only_when_all_pass(self):
        summary = pd.DataFrame([{
            "research_version": (
                phase2.RESEARCH_VERSION
            ),
            "fold_count": 6,
            "median_stage1_balanced_accuracy": 0.55,
            "median_stage1_mcc": 0.08,
            "median_stage2_balanced_accuracy": 0.54,
            "median_stage2_mcc": 0.06,
            "median_combined_balanced_accuracy": 0.39,
            "median_combined_macro_f1": 0.38,
            "median_combined_accuracy_improvement_vs_train_majority": 0.02,
            "median_combined_multiclass_mcc": 0.05,
            "median_combined_minimum_class_recall": 0.25,
        }])
        contract = {
            "predictive_quality_gates": {
                "stage1_median_balanced_accuracy_gt": 0.52,
                "stage1_median_mcc_gt": 0.0,
                "stage2_median_balanced_accuracy_gt": 0.52,
                "stage2_median_mcc_gt": 0.0,
                "combined_median_balanced_accuracy_gt": 0.36,
                "combined_median_macro_f1_gt": 0.36,
                "combined_median_accuracy_improvement_vs_train_majority_gt": 0.0,
                "combined_median_multiclass_mcc_gt": 0.0,
                "combined_median_minimum_class_recall_gt": 0.20,
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

    def test_balanced_sample_weights_equalize_class_mass(self):
        target = pd.Series(
            ["BTC", "BTC", "DEVIATE", "DEVIATE", "DEVIATE", "DEVIATE"]
        )
        weights = phase2.compute_sample_weight(
            class_weight="balanced",
            y=target,
        )

        frame = pd.DataFrame({
            "target": target,
            "weight": weights,
        })
        mass = frame.groupby(
            "target"
        )["weight"].sum()

        self.assertAlmostEqual(
            float(mass.loc["BTC"]),
            float(mass.loc["DEVIATE"]),
        )


if __name__ == "__main__":
    unittest.main()
