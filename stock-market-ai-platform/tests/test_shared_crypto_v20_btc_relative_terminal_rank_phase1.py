import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v20_btc_relative_terminal_rank import phase1


def v15_contract():
    features = [
        f"feature_{index}"
        for index in range(22)
    ]

    return {
        "research_version": (
            "shared_crypto_v15_cross_sectional_rank"
        ),
        "future_holdout_start_utc": (
            phase1.HOLDOUT.isoformat()
        ),
        "model_feature_columns": features,
        "model": {
            "primary": (
                phase1.PRIMARY_MODEL
            ),
            "learning_rate": (
                phase1.MODEL_LEARNING_RATE
            ),
            "max_iter": (
                phase1.MODEL_MAX_ITER
            ),
            "max_leaf_nodes": (
                phase1.MODEL_MAX_LEAF_NODES
            ),
            "max_depth": None,
            "min_samples_leaf": (
                phase1.MODEL_MIN_SAMPLES_LEAF
            ),
            "l2_regularization": (
                phase1.MODEL_L2_REGULARIZATION
            ),
            "random_state": (
                phase1.RANDOM_STATE
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


def v15_phase2_manifest():
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


def v19_adjudication():
    return {
        "research_version": (
            "shared_crypto_v19_relative_sleeve_router"
        ),
        "status": (
            "REJECT_CURRENT_V19_RELATIVE_SLEEVE_ROUTER_HYPOTHESIS"
        ),
        "offline_portfolio_simulation_allowed": False,
    }


def source_frame():
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

    days = [
        pd.Timestamp(
            "2026-01-01T00:00:00Z"
        ),
        pd.Timestamp(
            "2026-01-02T00:00:00Z"
        ),
    ]

    rows = []

    for day_index, timestamp in enumerate(
        days
    ):
        btc_return = (
            0.02
            + 0.01 * day_index
        )

        for asset_index, product in enumerate(
            products
        ):
            if product == "BTC-USD":
                terminal = btc_return
            else:
                terminal = (
                    btc_return
                    - 0.05
                    + 0.012
                    * asset_index
                )

            row = {
                "timestamp_utc": timestamp,
                "product_id": product,
                "net_terminal_return_7d_25bps": (
                    terminal
                ),
                "eligible_asset_count": (
                    len(products)
                ),
                "target_endpoint_utc_7d": (
                    timestamp
                    + pd.to_timedelta(
                        7,
                        unit="D",
                    )
                ),
            }

            for feature_index in range(
                22
            ):
                row[
                    f"feature_{feature_index}"
                ] = (
                    0.001
                    * feature_index
                    + 0.01
                    * asset_index
                    + 0.0001
                    * day_index
                )

            rows.append(
                row
            )

    return pd.DataFrame(
        rows
    )


class SharedCryptoV20Phase1Test(
    unittest.TestCase
):
    def build(self):
        return phase1.build_dataset(
            source_frame(),
            v15_contract(),
            v15_phase2_manifest(),
            v15_adjudication(),
            v19_adjudication(),
        )

    def test_raw_target_is_asset_terminal_minus_same_day_btc(self):
        dataset, _ = self.build()

        first_day = dataset[
            dataset[
                "timestamp_utc"
            ]
            == pd.Timestamp(
                "2026-01-01T00:00:00Z"
            )
        ]

        eth = first_day[
            first_day[
                "product_id"
            ]
            == "ETH-USD"
        ].iloc[0]

        self.assertAlmostEqual(
            float(
                eth[
                    phase1.RAW_RELATIVE_TARGET
                ]
            ),
            float(
                eth[
                    phase1.NET_TERMINAL
                ]
                - eth[
                    phase1.BTC_NET_TERMINAL
                ]
            ),
        )

    def test_btc_raw_relative_target_is_exactly_zero(self):
        dataset, _ = self.build()

        btc = dataset[
            dataset[
                "product_id"
            ]
            == "BTC-USD"
        ][
            phase1.RAW_RELATIVE_TARGET
        ].to_numpy(
            dtype=float
        )

        self.assertTrue(
            np.allclose(
                btc,
                0.0,
                rtol=0.0,
                atol=1e-12,
            )
        )

    def test_rank_target_is_within_day_percentile_rank(self):
        dataset, _ = self.build()

        expected = (
            dataset.groupby(
                "timestamp_utc"
            )[
                phase1.RAW_RELATIVE_TARGET
            ]
            .rank(
                pct=True
            )
        )

        self.assertTrue(
            np.allclose(
                dataset[
                    phase1.RANK_TARGET
                ].to_numpy(
                    dtype=float
                ),
                expected.to_numpy(
                    dtype=float
                ),
                rtol=0.0,
                atol=1e-12,
            )
        )

    def test_same_22_features_and_v15_model_are_frozen(self):
        _, contract = self.build()

        self.assertEqual(
            len(
                contract[
                    "model_feature_columns"
                ]
            ),
            22,
        )

        self.assertEqual(
            contract[
                "model"
            ][
                "primary"
            ],
            "hist_gradient_boosting_regressor",
        )

        self.assertTrue(
            contract[
                "research_constraints"
            ][
                "same_22_features_as_v15"
            ]
        )

        self.assertTrue(
            contract[
                "research_constraints"
            ][
                "same_model_specification_as_v15"
            ]
        )

    def test_walk_forward_and_five_predictive_gates_are_frozen(self):
        _, contract = self.build()

        self.assertEqual(
            contract[
                "walk_forward"
            ],
            {
                "purge_days": 7,
                "minimum_train_days": 730,
                "validation_days": 180,
                "max_folds": 8,
                "minimum_cross_section_assets": 10,
            },
        )

        gates = contract[
            "predictive_quality_gates"
        ]

        self.assertEqual(
            gates,
            phase1.EXPECTED_PREDICTIVE_GATES,
        )

        self.assertEqual(
            len(
                gates
            )
            - 1,
            5,
        )

    def test_no_day_level_binary_gate_or_threshold_search(self):
        _, contract = self.build()

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "asset_level_cross_sectional_learning"
            ]
        )

        self.assertFalse(
            constraints[
                "day_level_binary_gate"
            ]
        )

        self.assertTrue(
            constraints[
                "no_probability_threshold"
            ]
        )

        self.assertTrue(
            constraints[
                "no_post_result_threshold_search"
            ]
        )

    def test_v19_rejection_is_required(self):
        adjudication = (
            v19_adjudication()
        )

        adjudication[
            "status"
        ] = (
            "QUALIFIED_FOR_OFFLINE_PORTFOLIO_SIMULATION"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "V19",
        ):
            phase1.build_dataset(
                source_frame(),
                v15_contract(),
                v15_phase2_manifest(),
                v15_adjudication(),
                adjudication,
            )

    def test_future_holdout_is_rejected(self):
        source = source_frame()

        source.loc[
            0,
            "timestamp_utc",
        ] = phase1.HOLDOUT

        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase1.build_dataset(
                source,
                v15_contract(),
                v15_phase2_manifest(),
                v15_adjudication(),
                v19_adjudication(),
            )

    def test_phase1_contract_is_offline_and_no_model_fit(self):
        _, contract = self.build()

        self.assertTrue(
            contract[
                "research_constraints"
            ][
                "offline_research_only"
            ]
        )

        self.assertFalse(
            contract[
                "research_constraints"
            ][
                "paper_state_modified"
            ]
        )

        self.assertFalse(
            contract[
                "research_constraints"
            ][
                "brokerage_orders"
            ]
        )


if __name__ == "__main__":
    unittest.main()
