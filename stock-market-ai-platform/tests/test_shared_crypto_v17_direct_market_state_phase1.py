import unittest

import pandas as pd

from ml.shared_crypto_v17_direct_market_state import phase1


def source_contract():
    return {
        "research_version": (
            "shared_crypto_v16_risk_gated_rank"
        ),
        "future_holdout_start_utc": (
            phase1.HOLDOUT.isoformat()
        ),
        "market_risk_target": {
            "primary": (
                phase1.MARKET_TARGET
            ),
            "binary_diagnostic": (
                phase1.MARKET_LABEL
            ),
            "risk_on_definition": (
                "market_median_path_utility_net25_7d > 0"
            ),
        },
        "risk_feature_columns": [
            f"risk_feature_{index}"
            for index in range(
                18
            )
        ],
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "risk_gate_rule": (
                "deploy frozen V15 top-3 ranker only when predicted "
                "market_median_path_utility_net25_7d is strictly greater than 0"
            ),
            "risk_off_allocation": {
                "cash_weight": 1.0,
                "crypto_weight": 0.0,
            },
            "risk_on_selection_engine": (
                "frozen V15 Phase 2 out-of-sample predicted_rank_score"
            ),
            "risk_on_selected_asset_count": 3,
            "risk_on_asset_weight": 0.20,
            "risk_on_cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "maximum_turnover_per_7d_decision": 0.60,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "leverage": False,
            "shorting": False,
            "derivatives": False,
        },
        "selection_gates": {
            "median_fold_net_return_gt": 0.0,
            "positive_fold_fraction_gte": 0.80,
            "median_excess_vs_always_btc_gt": 0.0,
            "median_excess_vs_shared_crypto_v3_gt": 0.0,
            "positive_excess_vs_shared_crypto_v3_fraction_gte": 0.80,
            "worst_maximum_drawdown_gte": -0.20,
            "single_fold_profit_concentration_lte": 0.40,
            "survives_stress_cost_bps": 50.0,
        },
    }


def v16_adjudication():
    return {
        "research_version": (
            "shared_crypto_v16_risk_gated_rank"
        ),
        "status": (
            "REJECT_CURRENT_V16_RISK_GATE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": False,
        "passed_predictive_gate_count": 1,
        "total_predictive_gate_count": 4,
    }


def source_frame():
    rows = []

    utilities = [
        -0.20,
        -0.10,
        0.05,
        0.15,
    ]

    for index, utility in enumerate(
        utilities
    ):
        timestamp = pd.Timestamp(
            "2026-01-01T00:00:00Z"
        ) + pd.to_timedelta(
            index,
            unit="D",
        )

        row = {
            "timestamp_utc": timestamp,
            "target_endpoint_utc_7d": (
                timestamp
                + pd.to_timedelta(
                    7,
                    unit="D",
                )
            ),
            "eligible_asset_count": 20,
            phase1.MARKET_TARGET: utility,
            phase1.MARKET_LABEL: int(
                utility > 0.0
            ),
        }

        for feature_index in range(
            18
        ):
            row[
                f"risk_feature_{feature_index}"
            ] = (
                feature_index
                + 0.01 * index
            )

        rows.append(
            row
        )

    return pd.DataFrame(
        rows
    )


class SharedCryptoV17Phase1Test(
    unittest.TestCase
):
    def test_dataset_preserves_exact_v16_labels(self):
        dataset, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v16_adjudication(),
            )
        )

        expected = (
            dataset[
                phase1.MARKET_TARGET
            ]
            > 0.0
        ).astype(
            int
        )

        self.assertTrue(
            dataset[
                phase1.MARKET_LABEL
            ].astype(
                int
            ).equals(
                expected
            )
        )

        self.assertEqual(
            contract[
                "market_state_target"
            ][
                "primary"
            ],
            phase1.MARKET_LABEL,
        )

    def test_direct_classifier_and_balanced_weighting_are_frozen(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v16_adjudication(),
            )
        )

        model = contract[
            "market_state_model"
        ]

        self.assertEqual(
            model[
                "primary"
            ],
            "hist_gradient_boosting_classifier",
        )
        self.assertEqual(
            model[
                "learning_rate"
            ],
            0.05,
        )
        self.assertEqual(
            model[
                "max_iter"
            ],
            200,
        )
        self.assertEqual(
            model[
                "max_leaf_nodes"
            ],
            15,
        )
        self.assertEqual(
            model[
                "min_samples_leaf"
            ],
            30,
        )
        self.assertEqual(
            model[
                "l2_regularization"
            ],
            1.0,
        )
        self.assertEqual(
            model[
                "class_weight_method"
            ],
            "balanced_sample_weight",
        )

    def test_four_predictive_gates_are_fixed(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v16_adjudication(),
            )
        )

        self.assertEqual(
            contract[
                "predictive_quality_gates"
            ],
            phase1.EXPECTED_PREDICTIVE_GATES,
        )

    def test_v16_features_and_zero_labels_are_unchanged(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v16_adjudication(),
            )
        )

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "same_18_features_as_v16"
            ]
        )
        self.assertTrue(
            constraints[
                "same_zero_defined_labels_as_v16"
            ]
        )
        self.assertTrue(
            constraints[
                "no_probability_threshold"
            ]
        )
        self.assertTrue(
            constraints[
                "no_probability_threshold_search"
            ]
        )

    def test_later_policy_uses_class_prediction_and_frozen_v15_ranker(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v16_adjudication(),
            )
        )

        policy = contract[
            "frozen_policy_for_later_simulation"
        ]

        self.assertIn(
            "predicts RISK_ON class 1",
            policy[
                "risk_gate_rule"
            ],
        )
        self.assertIsNone(
            policy[
                "risk_gate_probability_threshold"
            ]
        )
        self.assertEqual(
            policy[
                "risk_on_selected_asset_count"
            ],
            3,
        )
        self.assertEqual(
            policy[
                "risk_on_asset_weight"
            ],
            0.20,
        )
        self.assertEqual(
            policy[
                "risk_on_cash_weight"
            ],
            0.40,
        )

    def test_v16_rejection_is_required(self):
        adjudication = (
            v16_adjudication()
        )
        adjudication[
            "status"
        ] = (
            "QUALIFIED_FOR_POLICY_SIMULATION"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "immutably rejected",
        ):
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                adjudication,
            )

    def test_future_holdout_is_rejected(self):
        source = (
            source_frame()
        )
        source.loc[
            0,
            "timestamp_utc",
        ] = (
            phase1.HOLDOUT
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase1.build_dataset(
                source,
                source_contract(),
                v16_adjudication(),
            )

    def test_tampered_binary_label_fails_closed(self):
        source = (
            source_frame()
        )
        source.loc[
            0,
            phase1.MARKET_LABEL,
        ] = 1

        with self.assertRaisesRegex(
            RuntimeError,
            "zero-defined target",
        ):
            phase1.build_dataset(
                source,
                source_contract(),
                v16_adjudication(),
            )


if __name__ == "__main__":
    unittest.main()
