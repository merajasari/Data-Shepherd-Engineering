import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v20_btc_relative_terminal_rank import phase2


class SharedCryptoV20Phase2Test(
    unittest.TestCase
):
    def test_folds_use_full_seven_day_purge(self):
        timestamps = pd.Series(
            pd.date_range(
                "2021-01-12T00:00:00Z",
                periods=2051,
                freq="24h",
            )
        )

        timestamps = timestamps[
            timestamps
            < phase2.HOLDOUT
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
                fold[
                    "train"
                ]
            ]

            validation = timestamps[
                fold[
                    "validation"
                ]
            ]

            self.assertEqual(
                fold[
                    "train_end"
                ],
                fold[
                    "start"
                ]
                - pd.to_timedelta(
                    7,
                    unit="D",
                ),
            )

            self.assertLess(
                train.max(),
                fold[
                    "train_end"
                ],
            )

            self.assertGreaterEqual(
                validation.min(),
                fold[
                    "start"
                ],
            )

            self.assertLess(
                validation.max(),
                fold[
                    "end"
                ],
            )

            self.assertLess(
                validation.max(),
                phase2.HOLDOUT,
            )

    def test_model_is_exact_preregistered_hgb(self):
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

    def test_daily_metrics_use_raw_btc_relative_economics(self):
        timestamp = pd.Timestamp(
            "2026-01-01T00:00:00Z"
        )

        products = [
            "BTC-USD",
            "ETH-USD",
            "SOL-USD",
            "XRP-USD",
            "ADA-USD",
            "DOGE-USD",
            "LTC-USD",
            "LINK-USD",
            "AVAX-USD",
            "BCH-USD",
        ]

        relative = np.array([
            0.00,
            0.08,
            0.06,
            0.04,
            0.02,
            -0.01,
            -0.02,
            -0.03,
            -0.04,
            -0.05,
        ])

        btc_return = 0.03

        validation = pd.DataFrame({
            "timestamp_utc": [
                timestamp
                for _ in products
            ],
            "product_id": products,
            phase2.RAW_RELATIVE_TARGET: (
                relative
            ),
            phase2.RANK_TARGET: (
                pd.Series(
                    relative
                ).rank(
                    pct=True
                )
            ),
            phase2.NET_TERMINAL: (
                relative
                + btc_return
            ),
            phase2.BTC_NET_TERMINAL: [
                btc_return
                for _ in products
            ],
        })

        predicted = relative.copy()

        daily = phase2.daily_ranking_metrics(
            validation,
            predicted,
        )

        self.assertEqual(
            len(
                daily
            ),
            1,
        )

        row = daily.iloc[
            0
        ]

        expected_top3 = (
            0.08
            + 0.06
            + 0.04
        ) / 3.0

        self.assertAlmostEqual(
            float(
                row[
                    "top3_mean_btc_relative_terminal_return"
                ]
            ),
            expected_top3,
        )

        self.assertAlmostEqual(
            float(
                row[
                    "top3_mean_net_terminal_return"
                ]
            ),
            expected_top3
            + btc_return,
        )

        self.assertAlmostEqual(
            float(
                row[
                    "btc_net_terminal_return"
                ]
            ),
            btc_return,
        )

        self.assertTrue(
            bool(
                row[
                    "top3_beats_btc"
                ]
            )
        )

        self.assertAlmostEqual(
            float(
                row[
                    "spearman_ic"
                ]
            ),
            1.0,
        )

    def test_fold_metrics_measure_btc_win_fraction(self):
        daily = pd.DataFrame({
            "spearman_ic": [
                0.3,
                0.2,
                -0.1,
                0.4,
            ],
            "top3_mean_btc_relative_terminal_return": [
                0.05,
                0.02,
                -0.01,
                0.03,
            ],
        })

        metrics = phase2.fold_ranking_metrics(
            daily
        )

        self.assertAlmostEqual(
            metrics[
                "positive_ic_day_fraction"
            ],
            0.75,
        )

        self.assertAlmostEqual(
            metrics[
                "top3_daily_btc_win_fraction"
            ],
            0.75,
        )

        self.assertGreater(
            metrics[
                "mean_top3_btc_relative_terminal_excess"
            ],
            0.0,
        )

    def test_all_five_predictive_gates_are_required(self):
        summary = pd.DataFrame([
            {
                "research_version": (
                    phase2.RESEARCH_VERSION
                ),
                "fold_count": 8,
                "median_fold_daily_spearman_ic": 0.08,
                "mean_fold_daily_spearman_ic": 0.07,
                "median_fold_positive_ic_day_fraction": 0.56,
                "median_fold_top3_btc_relative_terminal_excess": 0.01,
                "mean_fold_top3_btc_relative_terminal_excess": 0.008,
                "positive_fold_top3_btc_relative_terminal_excess_fraction": 0.75,
                "median_fold_top3_daily_btc_win_fraction": 0.49,
            }
        ])

        contract = {
            "predictive_quality_gates": {
                "median_fold_daily_spearman_ic_gt": 0.05,
                "median_fold_positive_ic_day_fraction_gt": 0.52,
                "median_fold_top3_btc_relative_terminal_excess_gt": 0.0,
                "positive_fold_top3_btc_relative_terminal_excess_fraction_gte": 0.75,
                "median_fold_top3_daily_btc_win_fraction_gt": 0.50,
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
            4,
        )
        self.assertEqual(
            result[
                "total_predictive_gate_count"
            ],
            5,
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
                detail.iloc[
                    0
                ][
                    "passed_gate_count"
                ]
            ),
            4,
        )

    def test_all_five_gates_allow_offline_simulation(self):
        summary = pd.DataFrame([
            {
                "research_version": (
                    phase2.RESEARCH_VERSION
                ),
                "fold_count": 8,
                "median_fold_daily_spearman_ic": 0.08,
                "mean_fold_daily_spearman_ic": 0.07,
                "median_fold_positive_ic_day_fraction": 0.56,
                "median_fold_top3_btc_relative_terminal_excess": 0.01,
                "mean_fold_top3_btc_relative_terminal_excess": 0.008,
                "positive_fold_top3_btc_relative_terminal_excess_fraction": 0.75,
                "median_fold_top3_daily_btc_win_fraction": 0.55,
            }
        ])

        contract = {
            "predictive_quality_gates": {
                "median_fold_daily_spearman_ic_gt": 0.05,
                "median_fold_positive_ic_day_fraction_gt": 0.52,
                "median_fold_top3_btc_relative_terminal_excess_gt": 0.0,
                "positive_fold_top3_btc_relative_terminal_excess_fraction_gte": 0.75,
                "median_fold_top3_daily_btc_win_fraction_gt": 0.50,
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

    def test_contract_requires_exact_target_model_walk_and_gates(self):
        features = [
            f"feature_{index}"
            for index in range(
                22
            )
        ]

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
                "raw_economic_target": (
                    phase2.RAW_RELATIVE_TARGET
                ),
                "btc_reference_return": (
                    phase2.BTC_NET_TERMINAL
                ),
            },
            "model_feature_columns": (
                features
            ),
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
            "predictive_quality_gates": {
                "median_fold_daily_spearman_ic_gt": 0.05,
                "median_fold_positive_ic_day_fraction_gt": 0.52,
                "median_fold_top3_btc_relative_terminal_excess_gt": 0.0,
                "positive_fold_top3_btc_relative_terminal_excess_fraction_gte": 0.75,
                "median_fold_top3_daily_btc_win_fraction_gt": 0.50,
                "all_gates_required_before_portfolio_simulation": True,
            },
            "research_constraints": {
                "offline_research_only": True,
                "asset_level_cross_sectional_learning": True,
                "day_level_binary_gate": False,
                "same_22_features_as_v15": True,
                "same_model_specification_as_v15": True,
                "same_walk_forward_protocol_as_v15": True,
                "btc_relative_terminal_target_fixed_before_fit": True,
                "predictive_gates_fixed_before_fit": True,
                "no_model_family_search": True,
                "no_secondary_model_search": True,
                "no_hyperparameter_search": True,
                "no_probability_threshold": True,
                "no_post_result_threshold_search": True,
                "predictive_gates_required_before_portfolio_simulation": True,
                "future_holdout_must_remain_untouched_until_candidate_freeze": True,
                "paper_state_modified": False,
                "brokerage_orders": False,
                "automatic_promotion": False,
            },
        }

        actual = phase2._validate_contract(
            contract
        )

        self.assertEqual(
            actual,
            features,
        )

    def test_inconsistent_btc_reference_fails_closed(self):
        timestamp = pd.Timestamp(
            "2026-01-01T00:00:00Z"
        )

        products = [
            f"ASSET-{index}"
            for index in range(
                10
            )
        ]

        validation = pd.DataFrame({
            "timestamp_utc": [
                timestamp
                for _ in products
            ],
            "product_id": products,
            phase2.RAW_RELATIVE_TARGET: np.linspace(
                -0.1,
                0.1,
                10,
            ),
            phase2.RANK_TARGET: np.linspace(
                0.1,
                1.0,
                10,
            ),
            phase2.NET_TERMINAL: np.linspace(
                -0.05,
                0.15,
                10,
            ),
            phase2.BTC_NET_TERMINAL: [
                0.05
                for _ in range(
                    9
                )
            ]
            + [
                0.06
            ],
        })

        with self.assertRaisesRegex(
            RuntimeError,
            "inconsistent BTC reference",
        ):
            phase2.daily_ranking_metrics(
                validation,
                np.linspace(
                    0.0,
                    1.0,
                    10,
                ),
            )


if __name__ == "__main__":
    unittest.main()
