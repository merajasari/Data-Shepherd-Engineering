import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v10_regime_ranker import phase2


class SharedCryptoV10Phase2Test(unittest.TestCase):
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

    def test_only_preregistered_linear_svc_is_used(self):
        pipeline = phase2.model_template()
        model = pipeline.named_steps[
            "model"
        ]

        self.assertEqual(
            phase2.PRIMARY_MODEL,
            "linear_svc",
        )
        self.assertEqual(
            phase2.LINEAR_SVC_C,
            0.25,
        )
        self.assertEqual(
            model.C,
            0.25,
        )
        self.assertEqual(
            model.loss,
            "squared_hinge",
        )
        self.assertEqual(
            model.penalty,
            "l2",
        )
        self.assertIsNone(
            model.class_weight
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

    def test_multiclass_metrics_include_all_three_classes(self):
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
            "BTC", "ALT", "CASH",
            "ALT",
        ])

        metrics = phase2.classification_metrics(
            actual,
            predicted,
            train,
        )

        self.assertGreater(
            metrics["balanced_accuracy"],
            0.0,
        )
        self.assertGreater(
            metrics["macro_f1"],
            0.0,
        )
        self.assertGreater(
            metrics["multiclass_mcc"],
            0.0,
        )
        self.assertEqual(
            metrics[
                "minimum_class_recall"
            ],
            metrics["cash_recall"],
        )

    def test_walk_forward_outputs_direct_sleeve_predictions_and_margins(self):
        timestamps = pd.date_range(
            "2023-01-01T00:00:00Z",
            periods=1000,
            freq="24h",
        )
        x = np.arange(
            len(timestamps),
            dtype=float,
        )
        labels = np.array([
            phase2.CLASSES[
                int(index % 3)
            ]
            for index in x
        ], dtype=object)

        data = pd.DataFrame({
            "timestamp_utc": timestamps,
            "x": np.sin(
                x / 7.0
            ),
            "y": np.cos(
                x / 11.0
            ),
            "btc_forward_return_72h": 0.01,
            "alt_forward_return_72h": 0.02,
            "alt_excess_vs_btc_net25_72h": 0.005,
            "cash_excess_vs_btc_net25_72h": -0.005,
            phase2.TARGET: labels,
            "alt_basket_assets": [
                "A|B|C|D|E"
            ] * len(timestamps),
            "oracle_best_deviation_net25_72h": labels,
        })
        data = data[
            data["timestamp_utc"]
            < phase2.HOLDOUT
        ].reset_index(drop=True)

        predictions, metrics = (
            phase2.walk_forward(
                data,
                ["x", "y"],
            )
        )

        self.assertFalse(
            predictions.empty
        )
        self.assertFalse(
            metrics.empty
        )
        self.assertIn(
            "predicted_sleeve",
            predictions.columns,
        )
        for label in phase2.CLASSES:
            self.assertIn(
                (
                    f"decision_margin_"
                    f"{label.lower()}"
                ),
                predictions.columns,
            )
        self.assertEqual(
            set(metrics["target"]),
            {phase2.TARGET},
        )
        self.assertEqual(
            set(metrics["model_id"]),
            {phase2.PRIMARY_MODEL},
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

    def test_predictive_gates_require_all_five_to_pass(self):
        summary = pd.DataFrame([{
            "target": phase2.TARGET,
            "model_id": phase2.PRIMARY_MODEL,
            "fold_count": 6,
            "median_balanced_accuracy": 0.40,
            "median_macro_f1": 0.39,
            "median_accuracy_improvement_vs_train_majority": 0.02,
            "median_multiclass_mcc": 0.05,
            "median_minimum_class_recall": 0.19,
        }])
        contract = {
            "predictive_quality_gates": {
                "median_balanced_accuracy_gt": 0.36,
                "median_macro_f1_gt": 0.36,
                "median_accuracy_improvement_vs_train_majority_gt": 0.0,
                "median_multiclass_mcc_gt": 0.0,
                "median_minimum_class_recall_gt": 0.20,
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
            5,
        )
        self.assertEqual(
            result[
                "passed_predictive_gate_count"
            ],
            4,
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
            4,
        )

    def test_predictive_gates_allow_simulation_only_when_all_pass(self):
        summary = pd.DataFrame([{
            "target": phase2.TARGET,
            "model_id": phase2.PRIMARY_MODEL,
            "fold_count": 6,
            "median_balanced_accuracy": 0.40,
            "median_macro_f1": 0.39,
            "median_accuracy_improvement_vs_train_majority": 0.02,
            "median_multiclass_mcc": 0.05,
            "median_minimum_class_recall": 0.25,
        }])
        contract = {
            "predictive_quality_gates": {
                "median_balanced_accuracy_gt": 0.36,
                "median_macro_f1_gt": 0.36,
                "median_accuracy_improvement_vs_train_majority_gt": 0.0,
                "median_multiclass_mcc_gt": 0.0,
                "median_minimum_class_recall_gt": 0.20,
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
