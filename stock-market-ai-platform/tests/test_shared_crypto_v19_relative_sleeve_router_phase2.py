import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v19_relative_sleeve_router import phase2


class SharedCryptoV19Phase2Test(unittest.TestCase):
    def test_folds_use_full_seven_day_purge(self):
        timestamps = pd.Series(
            pd.date_range(
                "2023-01-12T00:00:00Z",
                periods=1321,
                freq="24h",
            )
        )

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
                fold["start"]
                - pd.to_timedelta(
                    7,
                    unit="D",
                ),
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

    def test_model_is_exact_preregistered_classifier(self):
        model = phase2.model_template()

        self.assertEqual(
            phase2.PRIMARY_MODEL,
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
        self.assertEqual(
            model.random_state,
            1729,
        )

    def test_balanced_sample_weights_equalize_class_mass(self):
        labels = pd.Series(
            [
                0,
                0,
                0,
                1,
            ]
        )

        weights = phase2.balanced_sample_weights(
            labels
        )

        self.assertAlmostEqual(
            float(
                weights[
                    labels.to_numpy()
                    == 0
                ].sum()
            ),
            float(
                weights[
                    labels.to_numpy()
                    == 1
                ].sum()
            ),
        )

    def test_balanced_weights_require_both_classes(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "requires both BTC and TOP3",
        ):
            phase2.balanced_sample_weights(
                pd.Series(
                    [
                        0,
                        0,
                        0,
                    ]
                )
            )

    def test_classification_metrics_capture_both_recalls(self):
        actual = pd.Series(
            [
                0,
                0,
                1,
                1,
            ]
        )

        predicted = np.array(
            [
                0,
                1,
                1,
                1,
            ]
        )

        metrics = phase2.classification_metrics(
            actual,
            predicted,
        )

        self.assertAlmostEqual(
            metrics["btc_recall"],
            0.5,
        )
        self.assertAlmostEqual(
            metrics["top3_recall"],
            1.0,
        )
        self.assertAlmostEqual(
            metrics["minimum_class_recall"],
            0.5,
        )
        self.assertGreater(
            metrics["balanced_accuracy"],
            0.5,
        )
        self.assertGreater(
            metrics["macro_f1"],
            0.5,
        )

    def test_all_four_predictive_gates_are_required(self):
        summary = pd.DataFrame([
            {
                "research_version": (
                    phase2.RESEARCH_VERSION
                ),
                "fold_count": 6,
                "median_fold_balanced_accuracy": 0.60,
                "mean_fold_balanced_accuracy": 0.59,
                "median_fold_macro_f1": 0.60,
                "mean_fold_macro_f1": 0.59,
                "median_fold_mcc": 0.10,
                "mean_fold_mcc": 0.09,
                "median_fold_minimum_class_recall": 0.49,
                "median_fold_btc_recall": 0.70,
                "median_fold_top3_recall": 0.49,
                "median_fold_predicted_top3_fraction": 0.40,
                "median_fold_actual_top3_fraction": 0.39,
            }
        ])

        contract = {
            "predictive_quality_gates": {
                "median_fold_balanced_accuracy_gt": 0.55,
                "median_fold_macro_f1_gt": 0.55,
                "median_fold_mcc_gt": 0.0,
                "median_fold_minimum_class_recall_gt": 0.50,
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
                "passed_predictive_gate_count"
            ],
            3,
        )
        self.assertEqual(
            result[
                "total_predictive_gate_count"
            ],
            4,
        )
        self.assertFalse(
            result[
                "all_predictive_gates_pass"
            ]
        )
        self.assertEqual(
            result[
                "status"
            ],
            "STOP_BEFORE_PORTFOLIO_SIMULATION",
        )
        self.assertEqual(
            int(
                detail.iloc[0][
                    "passed_gate_count"
                ]
            ),
            3,
        )

    def test_all_four_gates_allow_offline_simulation(self):
        summary = pd.DataFrame([
            {
                "research_version": (
                    phase2.RESEARCH_VERSION
                ),
                "fold_count": 6,
                "median_fold_balanced_accuracy": 0.60,
                "mean_fold_balanced_accuracy": 0.59,
                "median_fold_macro_f1": 0.60,
                "mean_fold_macro_f1": 0.59,
                "median_fold_mcc": 0.10,
                "mean_fold_mcc": 0.09,
                "median_fold_minimum_class_recall": 0.55,
                "median_fold_btc_recall": 0.70,
                "median_fold_top3_recall": 0.55,
                "median_fold_predicted_top3_fraction": 0.40,
                "median_fold_actual_top3_fraction": 0.39,
            }
        ])

        contract = {
            "predictive_quality_gates": {
                "median_fold_balanced_accuracy_gt": 0.55,
                "median_fold_macro_f1_gt": 0.55,
                "median_fold_mcc_gt": 0.0,
                "median_fold_minimum_class_recall_gt": 0.50,
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
            result[
                "status"
            ],
            "ALLOW_OFFLINE_PORTFOLIO_SIMULATION",
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

    def test_contract_requires_34_features_and_offline_safeguards(self):
        rank_features = [
            f"rank_feature_{index}"
            for index in range(11)
        ]
        btc_features = [
            f"btc_relative_feature_{index}"
            for index in range(5)
        ]
        market_features = [
            f"market_feature_{index}"
            for index in range(18)
        ]

        contract = {
            "research_version": (
                phase2.RESEARCH_VERSION
            ),
            "future_holdout_start_utc": (
                phase2.HOLDOUT.isoformat()
            ),
            "relative_target": {
                "continuous": (
                    phase2.RELATIVE_CONTINUOUS_TARGET
                ),
                "binary": (
                    phase2.RELATIVE_BINARY_TARGET
                ),
                "binary_definition": (
                    "1 when selected_top3_excess_vs_btc_net_terminal_7d_25bps > 0, else 0"
                ),
            },
            "router_model": {
                "primary": (
                    phase2.PRIMARY_MODEL
                ),
                "learning_rate": (
                    phase2.MODEL_LEARNING_RATE
                ),
                "max_iter": (
                    phase2.MODEL_MAX_ITER
                ),
                "max_leaf_nodes": (
                    phase2.MODEL_MAX_LEAF_NODES
                ),
                "max_depth": None,
                "min_samples_leaf": (
                    phase2.MODEL_MIN_SAMPLES_LEAF
                ),
                "l2_regularization": (
                    phase2.MODEL_L2_REGULARIZATION
                ),
                "random_state": (
                    phase2.RANDOM_STATE
                ),
                "class_weight_method": (
                    phase2.CLASS_WEIGHT_METHOD
                ),
                "secondary_models": [],
            },
            "walk_forward": {
                "purge_days": 7,
                "minimum_train_days": 360,
                "validation_days": 180,
                "max_folds": 6,
            },
            "predictive_quality_gates": {
                "median_fold_balanced_accuracy_gt": 0.55,
                "median_fold_macro_f1_gt": 0.55,
                "median_fold_mcc_gt": 0.0,
                "median_fold_minimum_class_recall_gt": 0.50,
                "all_gates_required_before_portfolio_simulation": True,
            },
            "research_constraints": {
                "offline_research_only": True,
                "v15_oos_predictions_are_frozen_input": True,
                "v15_ranker_refit": False,
                "market_timing_or_cash_gate": False,
                "gross_crypto_weight_fixed_at_60pct": True,
                "cash_weight_fixed_at_40pct": True,
                "relative_target_fixed_before_fit": True,
                "zero_relative_excess_boundary_fixed_before_fit": True,
                "score_diagnostics_fixed_before_fit": True,
                "same_18_point_in_time_market_features_as_v16": True,
                "router_model_fixed_before_fit": True,
                "balanced_sample_weight_fixed_before_fit": True,
                "no_probability_threshold": True,
                "no_probability_threshold_search": True,
                "no_feature_search": True,
                "no_secondary_model_search": True,
                "no_hyperparameter_search": True,
                "predictive_gates_required_before_portfolio_simulation": True,
                "portfolio_gates_fixed_before_simulation": True,
                "future_holdout_must_remain_untouched_until_candidate_freeze": True,
                "automatic_promotion": False,
                "brokerage_orders": False,
            },
            "v18_rank_diagnostic_feature_columns": (
                rank_features
            ),
            "btc_relative_feature_columns": (
                btc_features
            ),
            "market_context_feature_columns": (
                market_features
            ),
            "model_feature_columns": (
                rank_features
                + btc_features
                + market_features
            ),
        }

        features = phase2._validate_contract(
            contract
        )

        self.assertEqual(
            len(features),
            34,
        )


if __name__ == "__main__":
    unittest.main()
