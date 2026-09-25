import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v16_risk_gated_rank import phase1


def source_contract():
    ranking_features = [
        *phase1.BTC_BASE_FEATURES,
        "average_dollar_volume_7d",
        "average_dollar_volume_30d",
        "volume_to_average_30d",
        "btc_relative_return_1d",
        "btc_relative_return_3d",
        "btc_relative_return_7d",
        "btc_relative_return_14d",
        "btc_relative_return_30d",
        "correlation_to_btc_14d",
        "correlation_to_btc_30d",
    ]
    ranking_features = list(
        dict.fromkeys(
            ranking_features
        )
    )

    self_count = len(
        ranking_features
    )
    if self_count < 22:
        ranking_features.extend(
            [
                f"extra_feature_{index}"
                for index in range(
                    22 - self_count
                )
            ]
        )

    return {
        "research_version": (
            "shared_crypto_v15_cross_sectional_rank"
        ),
        "future_holdout_start_utc": (
            phase1.HOLDOUT.isoformat()
        ),
        "model_feature_columns": (
            ranking_features[:22]
        ),
        "frozen_policy_for_later_simulation": {
            "evaluation_clock": (
                "non-overlapping exact 7-day blocks"
            ),
            "asset_weight": 0.20,
            "selected_asset_count": 3,
            "cash_weight": 0.40,
            "maximum_gross_crypto_exposure": 0.60,
            "primary_round_trip_cost_bps": 25.0,
            "stress_round_trip_cost_bps": 50.0,
            "maximum_turnover_per_7d_decision": 0.60,
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


def v15_adjudication():
    return {
        "research_version": (
            "shared_crypto_v15_cross_sectional_rank"
        ),
        "status": (
            "REJECT_CURRENT_V15_POLICY_FAMILY"
        ),
        "qualifying_candidate_count": 0,
        "single_preregistered_policy": {
            "passed_gate_count": 3,
            "total_gate_count": 8,
            "failed_gates": [
                "gate_median_excess_vs_always_btc_gt_zero",
                "gate_positive_excess_vs_shared_v3_fraction_gte_80pct",
                "gate_positive_fold_fraction_gte_80pct",
                "gate_single_fold_profit_concentration_lte_40pct",
                "gate_worst_maximum_drawdown_gte_minus_20pct",
            ],
        },
    }


def source_frame():
    contract = source_contract()
    rows = []

    timestamps = pd.date_range(
        "2026-01-01T00:00:00Z",
        periods=3,
        freq="24h",
    )

    for day_index, timestamp in enumerate(
        timestamps
    ):
        for asset_index in range(
            10
        ):
            product = (
                "BTC-USD"
                if asset_index == 0
                else f"ALT{asset_index:02d}-USD"
            )

            raw_target = (
                -0.09
                + 0.02 * asset_index
                + 0.01 * day_index
            )

            row = {
                "timestamp_utc": timestamp,
                "product_id": product,
                phase1.RAW_TARGET: raw_target,
                "target_endpoint_utc_7d": (
                    timestamp
                    + pd.to_timedelta(
                        7,
                        unit="D",
                    )
                ),
            }

            for feature_index, feature in enumerate(
                contract[
                    "model_feature_columns"
                ],
                start=1,
            ):
                row[
                    feature
                ] = (
                    0.01 * feature_index
                    + 0.001 * asset_index
                    + 0.0001 * day_index
                )

            for feature_index, feature in enumerate(
                phase1.BTC_BASE_FEATURES,
                start=1,
            ):
                row[
                    feature
                ] = (
                    0.02 * feature_index
                    + 0.001 * asset_index
                    + 0.0001 * day_index
                )

            row[
                "return_7d"
            ] = (
                -0.05
                + 0.01 * asset_index
                + 0.001 * day_index
            )
            row[
                "return_30d"
            ] = (
                -0.10
                + 0.02 * asset_index
                + 0.001 * day_index
            )
            row[
                "realized_volatility_14d"
            ] = (
                0.20
                + 0.01 * asset_index
            )
            row[
                "drawdown_from_high_30d"
            ] = (
                -0.20
                + 0.01 * asset_index
            )
            row[
                "close_to_sma_30"
            ] = (
                -0.05
                + 0.01 * asset_index
            )

            rows.append(
                row
            )

    return pd.DataFrame(
        rows
    )


class SharedCryptoV16Phase1Test(
    unittest.TestCase
):
    def test_market_target_is_cross_sectional_median_path_utility(self):
        source = source_frame()

        risk, contract = (
            phase1.build_risk_dataset(
                source,
                source_contract(),
                v15_adjudication(),
            )
        )

        first_timestamp = (
            source[
                "timestamp_utc"
            ].min()
        )
        expected = float(
            source[
                source[
                    "timestamp_utc"
                ]
                == first_timestamp
            ][
                phase1.RAW_TARGET
            ].median()
        )

        actual = float(
            risk.iloc[
                0
            ][
                phase1.MARKET_TARGET
            ]
        )

        self.assertAlmostEqual(
            actual,
            expected,
        )
        self.assertEqual(
            contract[
                "market_risk_target"
            ][
                "risk_on_definition"
            ],
            "market_median_path_utility_net25_7d > 0",
        )

    def test_risk_features_are_point_in_time_btc_median_and_breadth(self):
        risk, _ = (
            phase1.build_risk_dataset(
                source_frame(),
                source_contract(),
                v15_adjudication(),
            )
        )

        row = risk.iloc[
            0
        ]

        self.assertEqual(
            len(
                phase1.RISK_FEATURE_COLUMNS
            ),
            18,
        )

        self.assertAlmostEqual(
            float(
                row[
                    "btc_return_1d"
                ]
            ),
            0.02,
        )

        self.assertAlmostEqual(
            float(
                row[
                    "market_median_return_7d"
                ]
            ),
            -0.005,
        )

        self.assertAlmostEqual(
            float(
                row[
                    "breadth_return_7d_positive_fraction"
                ]
            ),
            0.4,
        )

        self.assertAlmostEqual(
            float(
                row[
                    "breadth_above_sma30_fraction"
                ]
            ),
            0.4,
        )

    def test_v15_ranker_is_frozen_and_not_refit(self):
        _, contract = (
            phase1.build_risk_dataset(
                source_frame(),
                source_contract(),
                v15_adjudication(),
            )
        )

        source = contract[
            "source"
        ]
        constraints = contract[
            "research_constraints"
        ]

        self.assertFalse(
            source[
                "ranking_engine_refit_allowed"
            ]
        )
        self.assertTrue(
            constraints[
                "v15_ranker_is_frozen_input"
            ]
        )
        self.assertFalse(
            constraints[
                "v15_ranker_refit_for_v16"
            ]
        )

    def test_risk_model_and_predictive_gates_are_fixed(self):
        _, contract = (
            phase1.build_risk_dataset(
                source_frame(),
                source_contract(),
                v15_adjudication(),
            )
        )

        model = contract[
            "market_risk_model"
        ]

        self.assertEqual(
            model[
                "primary"
            ],
            "hist_gradient_boosting_regressor",
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
            contract[
                "risk_predictive_quality_gates"
            ],
            phase1.EXPECTED_RISK_PREDICTIVE_GATES,
        )

    def test_later_policy_uses_zero_gate_and_unchanged_v15_portfolio_gates(self):
        _, contract = (
            phase1.build_risk_dataset(
                source_frame(),
                source_contract(),
                v15_adjudication(),
            )
        )

        policy = contract[
            "frozen_policy_for_later_simulation"
        ]

        self.assertIn(
            "strictly greater than 0",
            policy[
                "risk_gate_rule"
            ],
        )
        self.assertEqual(
            policy[
                "risk_off_allocation"
            ][
                "cash_weight"
            ],
            1.0,
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
        self.assertEqual(
            contract[
                "selection_gates"
            ],
            source_contract()[
                "selection_gates"
            ],
        )

    def test_v15_rejection_is_required(self):
        adjudication = (
            v15_adjudication()
        )
        adjudication[
            "status"
        ] = (
            "QUALIFIED_FOR_HUMAN_REVIEW"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "immutably rejected",
        ):
            phase1.build_risk_dataset(
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
            phase1.build_risk_dataset(
                source,
                source_contract(),
                v15_adjudication(),
            )

    def test_future_or_target_columns_are_not_risk_features(self):
        _, contract = (
            phase1.build_risk_dataset(
                source_frame(),
                source_contract(),
                v15_adjudication(),
            )
        )

        features = contract[
            "risk_feature_columns"
        ]

        self.assertFalse(
            any(
                "future_"
                in feature
                or "target_"
                in feature
                or "path_utility"
                in feature
                or "endpoint"
                in feature
                for feature
                in features
            )
        )


if __name__ == "__main__":
    unittest.main()
