import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v11_hierarchical_selector import phase2


class SharedCryptoV11Phase2Test(unittest.TestCase):
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
        self.assertLessEqual(len(folds), phase2.MAX_FOLDS)

        for fold in folds:
            train = timestamps[fold["train"]]
            validation = timestamps[fold["validation"]]

            self.assertEqual(
                fold["train_end"],
                fold["start"] - phase2.PURGE,
            )
            self.assertLess(train.max(), fold["train_end"])
            self.assertGreaterEqual(validation.min(), fold["start"])
            self.assertLess(validation.max(), fold["end"])
            self.assertLess(validation.max(), phase2.HOLDOUT)

    def test_only_fixed_balanced_linear_svc_is_used(self):
        pipeline = phase2.model_template()
        model = pipeline.named_steps["model"]

        self.assertEqual(phase2.PRIMARY_MODEL, "linear_svc")
        self.assertEqual(phase2.LINEAR_SVC_C, 0.25)
        self.assertEqual(phase2.CLASS_WEIGHT, "balanced")
        self.assertEqual(model.C, 0.25)
        self.assertEqual(model.class_weight, "balanced")
        self.assertEqual(model.loss, "squared_hinge")
        self.assertEqual(model.penalty, "l2")

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({
            "timestamp_utc": [phase2.HOLDOUT],
        })

        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase2.validate_pre_holdout(frame, "test")

    def test_binary_metrics_are_stage_specific(self):
        actual = pd.Series([
            "BTC", "BTC", "DEVIATE", "DEVIATE"
        ])
        predicted = np.array([
            "BTC", "DEVIATE", "DEVIATE", "DEVIATE"
        ], dtype=object)

        metrics = phase2.binary_metrics(
            actual,
            predicted,
            phase2.STAGE1_CLASSES,
        )

        self.assertGreater(metrics["balanced_accuracy"], 0.5)
        self.assertGreater(metrics["mcc"], 0.0)

    def test_combined_metrics_keep_three_class_recall(self):
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

        self.assertGreater(metrics["balanced_accuracy"], 0.0)
        self.assertGreater(metrics["macro_f1"], 0.0)
        self.assertGreater(metrics["multiclass_mcc"], 0.0)
        self.assertEqual(
            metrics["minimum_class_recall"],
            metrics["cash_recall"],
        )

    def test_walk_forward_outputs_hierarchical_predictions(self):
        timestamps = pd.date_range(
            "2023-01-01T00:00:00Z",
            periods=1000,
            freq="24h",
        )
        x = np.arange(len(timestamps), dtype=float)

        source = np.array([
            phase2.COMBINED_CLASSES[int(index % 3)]
            for index in x
        ], dtype=object)
        stage1 = np.where(
            source == "BTC",
            "BTC",
            "DEVIATE",
        ).astype(object)
        stage2 = np.array([
            pd.NA if label == "BTC" else label
            for label in source
        ], dtype=object)

        data = pd.DataFrame({
            "timestamp_utc": timestamps,
            "x": np.sin(x / 7.0),
            "y": np.cos(x / 11.0),
            phase2.SOURCE_TARGET: source,
            phase2.STAGE1_TARGET: stage1,
            phase2.STAGE2_TARGET: stage2,
            "alt_basket_assets": ["A|B|C|D|E"] * len(timestamps),
            "btc_forward_return_72h": 0.01,
            "alt_forward_return_72h": 0.02,
            "alt_excess_vs_btc_net25_72h": 0.005,
            "cash_excess_vs_btc_net25_72h": -0.005,
            "oracle_best_deviation_net25_72h": source,
        })
        data = data[
            data["timestamp_utc"] < phase2.HOLDOUT
        ].reset_index(drop=True)

        predictions, metrics = phase2.walk_forward(
            data,
            ["x", "y"],
        )

        self.assertFalse(predictions.empty)
        self.assertFalse(metrics.empty)

        for column in (
            "stage1_predicted",
            "stage1_margin_deviate",
            "stage2_predicted",
            "stage2_margin_cash",
            "predicted_sleeve",
        ):
            self.assertIn(column, predictions.columns)

        self.assertTrue(
            set(predictions["predicted_sleeve"])
            <= set(phase2.COMBINED_CLASSES)
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

    def test_predictive_gates_require_all_nine_to_pass(self):
        summary = pd.DataFrame([{
            "research_version": phase2.RESEARCH_VERSION,
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

        detail, result = phase2.evaluate_predictive_gates(
            summary,
            contract,
        )

        self.assertEqual(
            result["total_predictive_gate_count"],
            9,
        )
        self.assertEqual(
            result["passed_predictive_gate_count"],
            8,
        )
        self.assertFalse(
            result["all_predictive_gates_pass"]
        )
        self.assertEqual(
            result["status"],
            "STOP_BEFORE_PORTFOLIO_SIMULATION",
        )
        self.assertEqual(
            int(detail.iloc[0]["passed_gate_count"]),
            8,
        )

    def test_predictive_gates_allow_simulation_only_when_all_pass(self):
        summary = pd.DataFrame([{
            "research_version": phase2.RESEARCH_VERSION,
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

        _, result = phase2.evaluate_predictive_gates(
            summary,
            contract,
        )

        self.assertTrue(
            result["all_predictive_gates_pass"]
        )
        self.assertEqual(
            result["status"],
            "ALLOW_POLICY_SIMULATION",
        )


if __name__ == "__main__":
    unittest.main()
