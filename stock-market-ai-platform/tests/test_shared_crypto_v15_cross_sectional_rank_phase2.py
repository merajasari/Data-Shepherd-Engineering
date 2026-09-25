import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v15_cross_sectional_rank import phase2


class SharedCryptoV15Phase2Test(unittest.TestCase):
    def test_folds_use_full_seven_day_purge(self):
        timestamps = pd.Series(
            pd.date_range(
                "2021-01-12T00:00:00Z",
                periods=2051,
                freq="24h",
            )
        )
        timestamps = timestamps[
            timestamps < phase2.HOLDOUT
        ].reset_index(
            drop=True
        )

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

    def test_model_is_exact_frozen_v14_hgb(self):
        model = phase2.model_template()

        self.assertEqual(
            phase2.PRIMARY_MODEL,
            "hist_gradient_boosting_regressor",
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

    def test_daily_metrics_evaluate_raw_utility_not_rank_target(self):
        products = [
            f"ASSET{index:02d}-USD"
            for index in range(
                10
            )
        ]

        raw = np.linspace(
            -0.10,
            0.10,
            10,
        )

        rank_target = pd.Series(
            raw
        ).rank(
            pct=True
        ).to_numpy()

        validation = pd.DataFrame({
            "timestamp_utc": [
                pd.Timestamp(
                    "2026-01-01T00:00:00Z"
                )
            ] * 10,
            "product_id": products,
            phase2.RAW_TARGET: raw,
            phase2.RANK_TARGET: rank_target,
        })

        daily = phase2.daily_ranking_metrics(
            validation,
            rank_target.copy(),
        )

        self.assertAlmostEqual(
            float(
                daily.iloc[0][
                    "spearman_ic"
                ]
            ),
            1.0,
            places=12,
        )

        self.assertGreater(
            float(
                daily.iloc[0][
                    "top3_target_utility_excess_vs_universe"
                ]
            ),
            0.0,
        )

    def test_fold_metrics_preserve_ranking_evidence(self):
        daily = pd.DataFrame({
            "spearman_ic": [
                0.10,
                0.20,
                -0.05,
                0.30,
            ],
            "top3_target_utility_excess_vs_universe": [
                0.01,
                0.02,
                -0.01,
                0.03,
            ],
            "mean_predicted_rank_score": [
                0.50,
                0.51,
                0.52,
                0.53,
            ],
            "maximum_predicted_rank_score": [
                0.80,
                0.81,
                0.82,
                0.83,
            ],
        })

        metrics = phase2.fold_ranking_metrics(
            daily
        )

        self.assertAlmostEqual(
            metrics[
                "median_daily_spearman_ic"
            ],
            0.15,
        )
        self.assertAlmostEqual(
            metrics[
                "positive_ic_day_fraction"
            ],
            0.75,
        )
        self.assertGreater(
            metrics[
                "mean_top3_target_utility_excess_vs_universe"
            ],
            0.0,
        )

    def test_all_four_predictive_gates_are_required(self):
        summary = pd.DataFrame([{
            "research_version": (
                phase2.RESEARCH_VERSION
            ),
            "fold_count": 8,
            "median_fold_daily_spearman_ic": 0.06,
            "mean_fold_daily_spearman_ic": 0.07,
            "median_fold_positive_ic_day_fraction": 0.53,
            "median_fold_top3_target_utility_excess_vs_universe": 0.01,
            "mean_fold_top3_target_utility_excess_vs_universe": 0.01,
            "positive_fold_top3_target_utility_excess_fraction": 0.625,
        }])

        contract = {
            "predictive_quality_gates": {
                "median_fold_daily_spearman_ic_gt": 0.05,
                "median_fold_positive_ic_day_fraction_gt": 0.52,
                "median_fold_top3_target_utility_excess_vs_universe_gt": 0.0,
                "positive_fold_top3_target_utility_excess_fraction_gte": 0.75,
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
            4,
        )
        self.assertEqual(
            result[
                "passed_predictive_gate_count"
            ],
            3,
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

    def test_all_four_gates_allow_policy_simulation(self):
        summary = pd.DataFrame([{
            "research_version": (
                phase2.RESEARCH_VERSION
            ),
            "fold_count": 8,
            "median_fold_daily_spearman_ic": 0.06,
            "mean_fold_daily_spearman_ic": 0.07,
            "median_fold_positive_ic_day_fraction": 0.53,
            "median_fold_top3_target_utility_excess_vs_universe": 0.01,
            "mean_fold_top3_target_utility_excess_vs_universe": 0.01,
            "positive_fold_top3_target_utility_excess_fraction": 0.75,
        }])

        contract = {
            "predictive_quality_gates": {
                "median_fold_daily_spearman_ic_gt": 0.05,
                "median_fold_positive_ic_day_fraction_gt": 0.52,
                "median_fold_top3_target_utility_excess_vs_universe_gt": 0.0,
                "positive_fold_top3_target_utility_excess_fraction_gte": 0.75,
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
            "ALLOW_POLICY_SIMULATION",
        )

    def test_contract_requires_only_target_change(self):
        contract = {
            "research_version": (
                phase2.RESEARCH_VERSION
            ),
            "future_holdout_start_utc": (
                phase2.HOLDOUT.isoformat()
            ),
            "learning_target": {
                "primary": (
                    phase2.RANK_TARGET
                ),
                "raw_economic_target_retained_for_evaluation": (
                    phase2.RAW_TARGET
                ),
            },
            "model": {
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
                "secondary_models": [],
            },
            "walk_forward": {
                "purge_days": 7,
                "minimum_train_days": 730,
                "validation_days": 180,
                "max_folds": 8,
                "minimum_cross_section_assets": 10,
            },
            "research_constraints": {
                "only_learning_target_changed_from_v14": True,
                "same_22_features_as_v14": True,
                "same_model_specification_as_v14": True,
                "same_walk_forward_protocol_as_v14": True,
                "same_predictive_gates_as_v14": True,
                "rank_target_fixed_before_fit": True,
                "no_model_family_search": True,
                "no_secondary_model_search": True,
                "no_hyperparameter_search": True,
                "no_post_result_threshold_search": True,
                "predictive_gates_required_before_portfolio_simulation": True,
                "future_holdout_must_remain_untouched_until_candidate_freeze": True,
            },
            "model_feature_columns": [
                f"feature_{index}"
                for index in range(
                    22
                )
            ],
        }

        features = (
            phase2._validate_contract(
                contract
            )
        )

        self.assertEqual(
            len(features),
            22,
        )


if __name__ == "__main__":
    unittest.main()
