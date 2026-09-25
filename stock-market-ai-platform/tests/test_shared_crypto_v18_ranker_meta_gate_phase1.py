import unittest

import pandas as pd

from ml.shared_crypto_v18_ranker_meta_gate import phase1


def v15_manifest():
    return {
        "research_version": (
            "shared_crypto_v15_cross_sectional_rank"
        ),
        "predictive_gate_status": (
            "ALLOW_POLICY_SIMULATION"
        ),
        "passed_predictive_gate_count": 4,
    }


def v15_adjudication():
    return {
        "research_version": (
            "shared_crypto_v15_cross_sectional_rank"
        ),
        "status": (
            "REJECT_CURRENT_V15_POLICY_FAMILY"
        ),
    }


def v16_contract():
    features = [
        f"risk_feature_{index}"
        for index in range(
            18
        )
    ]

    return {
        "research_version": (
            "shared_crypto_v16_risk_gated_rank"
        ),
        "risk_feature_columns": features,
        "frozen_policy_for_later_simulation": {
            "risk_on_selected_asset_count": 3,
            "risk_on_asset_weight": 0.20,
            "risk_on_cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "maximum_turnover_per_7d_decision": 0.60,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
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


def v17_adjudication():
    return {
        "research_version": (
            "shared_crypto_v17_direct_market_state"
        ),
        "status": (
            "REJECT_CURRENT_V17_DIRECT_MARKET_STATE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": False,
    }


def predictions():
    rows = []

    days = [
        (
            pd.Timestamp(
                "2026-01-01T00:00:00Z"
            ),
            [
                -0.10,
                -0.05,
                0.02,
                0.50,
            ],
        ),
        (
            pd.Timestamp(
                "2026-01-02T00:00:00Z"
            ),
            [
                0.10,
                0.05,
                0.02,
                -0.50,
            ],
        ),
    ]

    products = [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD",
        "XRP-USD",
    ]

    scores = [
        0.90,
        0.80,
        0.70,
        0.60,
    ]

    for timestamp, terminals in days:
        for (
            product,
            score,
            terminal,
        ) in zip(
            products,
            scores,
            terminals,
        ):
            rows.append({
                "timestamp_utc": (
                    timestamp
                ),
                "product_id": (
                    product
                ),
                "fold_id": (
                    "fold_01"
                ),
                phase1.PREDICTED_SCORE: (
                    score
                ),
                phase1.NET_TERMINAL: (
                    terminal
                ),
                phase1.RAW_PATH_UTILITY: (
                    terminal
                    - 0.01
                ),
                "target_endpoint_utc_7d": (
                    timestamp
                    + pd.to_timedelta(
                        7,
                        unit="D",
                    )
                ),
                "eligible_asset_count": 4,
            })

    return pd.DataFrame(
        rows
    )


def market_context():
    rows = []

    for day_index, timestamp in enumerate(
        pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        ])
    ):
        row = {
            "timestamp_utc": (
                timestamp
            )
        }

        for feature_index in range(
            18
        ):
            row[
                f"risk_feature_{feature_index}"
            ] = (
                0.01
                * feature_index
                + 0.001
                * day_index
            )

        rows.append(
            row
        )

    return pd.DataFrame(
        rows
    )


class SharedCryptoV18Phase1Test(
    unittest.TestCase
):
    def build(self):
        return phase1.build_meta_dataset(
            predictions(),
            market_context(),
            v15_manifest(),
            v15_adjudication(),
            v16_contract(),
            v17_adjudication(),
        )

    def test_target_uses_only_frozen_v15_top3(self):
        dataset, _ = self.build()

        first = dataset.iloc[
            0
        ]

        expected = (
            -0.10
            - 0.05
            + 0.02
        ) / 3.0

        self.assertAlmostEqual(
            float(
                first[
                    phase1.META_CONTINUOUS_TARGET
                ]
            ),
            expected,
        )

        self.assertEqual(
            int(
                first[
                    phase1.META_BINARY_TARGET
                ]
            ),
            0,
        )

        second = dataset.iloc[
            1
        ]

        self.assertEqual(
            int(
                second[
                    phase1.META_BINARY_TARGET
                ]
            ),
            1,
        )

    def test_rank_diagnostics_are_exact(self):
        dataset, _ = self.build()

        row = dataset.iloc[
            0
        ]

        self.assertAlmostEqual(
            float(
                row[
                    "meta_top1_predicted_rank_score"
                ]
            ),
            0.90,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "meta_top3_predicted_rank_score"
                ]
            ),
            0.70,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "meta_top1_minus_top3_predicted_score"
                ]
            ),
            0.20,
        )
        self.assertAlmostEqual(
            float(
                row[
                    "meta_top3_minus_fourth_predicted_score"
                ]
            ),
            0.10,
        )

    def test_model_feature_count_is_29(self):
        _, contract = self.build()

        self.assertEqual(
            len(
                contract[
                    "rank_diagnostic_feature_columns"
                ]
            ),
            11,
        )

        self.assertEqual(
            len(
                contract[
                    "market_context_feature_columns"
                ]
            ),
            18,
        )

        self.assertEqual(
            len(
                contract[
                    "model_feature_columns"
                ]
            ),
            29,
        )

    def test_broad_market_state_label_is_not_reused(self):
        _, contract = self.build()

        constraints = contract[
            "research_constraints"
        ]

        self.assertFalse(
            constraints[
                "broad_market_state_label_reused"
            ]
        )

        self.assertNotEqual(
            contract[
                "deployment_target"
            ][
                "binary"
            ],
            "market_risk_on_7d",
        )

    def test_v15_ranker_is_frozen_and_no_threshold_search(self):
        _, contract = self.build()

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "v15_oos_predictions_are_frozen_input"
            ]
        )
        self.assertFalse(
            constraints[
                "v15_ranker_refit"
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

    def test_meta_model_and_gates_are_frozen(self):
        _, contract = self.build()

        model = contract[
            "meta_model"
        ]

        self.assertEqual(
            model[
                "primary"
            ],
            "hist_gradient_boosting_classifier",
        )
        self.assertEqual(
            model[
                "class_weight_method"
            ],
            "balanced_sample_weight",
        )
        self.assertEqual(
            contract[
                "predictive_quality_gates"
            ],
            phase1.EXPECTED_PREDICTIVE_GATES,
        )
        self.assertEqual(
            contract[
                "walk_forward"
            ][
                "minimum_train_days"
            ],
            360,
        )
        self.assertEqual(
            contract[
                "walk_forward"
            ][
                "max_folds"
            ],
            6,
        )

    def test_v17_rejection_is_required(self):
        adjudication = (
            v17_adjudication()
        )
        adjudication[
            "status"
        ] = (
            "QUALIFIED_FOR_POLICY_SIMULATION"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "V17",
        ):
            phase1.build_meta_dataset(
                predictions(),
                market_context(),
                v15_manifest(),
                v15_adjudication(),
                v16_contract(),
                adjudication,
            )

    def test_future_holdout_is_rejected(self):
        source = (
            predictions()
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
            phase1.build_meta_dataset(
                source,
                market_context(),
                v15_manifest(),
                v15_adjudication(),
                v16_contract(),
                v17_adjudication(),
            )

    def test_missing_market_context_feature_fails_closed(self):
        context = (
            market_context()
            .drop(
                columns=[
                    "risk_feature_17"
                ]
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "market context missing",
        ):
            phase1.build_meta_dataset(
                predictions(),
                context,
                v15_manifest(),
                v15_adjudication(),
                v16_contract(),
                v17_adjudication(),
            )


if __name__ == "__main__":
    unittest.main()
