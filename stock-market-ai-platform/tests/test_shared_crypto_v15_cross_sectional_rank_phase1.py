import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v15_cross_sectional_rank import phase1


def source_contract():
    return {
        "research_version": (
            "shared_crypto_v14_path_utility_rank"
        ),
        "future_holdout_start_utc": (
            phase1.HOLDOUT.isoformat()
        ),
        "target": {
            "primary": (
                phase1.RAW_TARGET
            ),
            "primary_round_trip_cost_bps": 25.0,
        },
        "model_feature_columns": [
            f"feature_{index}"
            for index in range(22)
        ],
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
        "predictive_quality_gates": dict(
            phase1.EXPECTED_PREDICTIVE_GATES
        ),
        "selection_gates": {
            "median_fold_net_return_gt": 0.0,
            "positive_fold_fraction_gte": 0.80,
        },
    }


def v14_adjudication():
    return {
        "research_version": (
            "shared_crypto_v14_path_utility_rank"
        ),
        "status": (
            "REJECT_CURRENT_V14_PREDICTIVE_HYPOTHESIS"
        ),
        "portfolio_simulation_allowed": False,
        "passed_predictive_gate_count": 3,
        "failed_gates": [
            "gate_median_fold_daily_spearman_ic_gt_005"
        ],
    }


def source_frame():
    rows = []

    for day_index, timestamp in enumerate(
        pd.date_range(
            "2026-01-01T00:00:00Z",
            periods=3,
            freq="24h",
        )
    ):
        for asset_index in range(
            10
        ):
            raw = (
                -0.10
                + 0.02 * asset_index
                + 0.001 * day_index
            )

            row = {
                "timestamp_utc": timestamp,
                "product_id": (
                    f"ASSET{asset_index:02d}-USD"
                ),
                phase1.RAW_TARGET: raw,
                "net_terminal_return_7d_25bps": (
                    raw + 0.01
                ),
                "maximum_adverse_close_return_7d": (
                    -0.01
                ),
                "maximum_favorable_close_return_7d": (
                    0.05
                ),
                "target_top3_path_utility_7d": (
                    asset_index >= 7
                ),
                "eligible_asset_count": 10,
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
                    float(
                        feature_index
                    )
                    + 0.01
                    * asset_index
                )

            rows.append(
                row
            )

    frame = pd.DataFrame(
        rows
    )

    frame[
        phase1.RANK_TARGET
    ] = (
        frame.groupby(
            "timestamp_utc"
        )[
            phase1.RAW_TARGET
        ]
        .rank(
            pct=True
        )
    )

    return frame


class SharedCryptoV15Phase1Test(
    unittest.TestCase
):
    def test_rank_target_equals_within_day_percentile(self):
        dataset, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v14_adjudication(),
            )
        )

        expected = (
            dataset.groupby(
                "timestamp_utc"
            )[
                phase1.RAW_TARGET
            ]
            .rank(
                pct=True
            )
        )

        self.assertTrue(
            np.allclose(
                expected.to_numpy(),
                dataset[
                    phase1.RANK_TARGET
                ].to_numpy(),
            )
        )

        self.assertEqual(
            contract[
                "learning_target"
            ][
                "primary"
            ],
            phase1.RANK_TARGET,
        )

    def test_only_learning_target_changes_from_v14(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v14_adjudication(),
            )
        )

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "only_learning_target_changed_from_v14"
            ]
        )
        self.assertTrue(
            constraints[
                "same_22_features_as_v14"
            ]
        )
        self.assertTrue(
            constraints[
                "same_model_specification_as_v14"
            ]
        )
        self.assertTrue(
            constraints[
                "same_walk_forward_protocol_as_v14"
            ]
        )
        self.assertTrue(
            constraints[
                "same_predictive_gates_as_v14"
            ]
        )

    def test_predictive_gates_are_not_lowered(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v14_adjudication(),
            )
        )

        self.assertEqual(
            contract[
                "predictive_quality_gates"
            ],
            phase1.EXPECTED_PREDICTIVE_GATES,
        )

        self.assertEqual(
            contract[
                "predictive_quality_gates"
            ][
                "median_fold_daily_spearman_ic_gt"
            ],
            0.05,
        )

    def test_model_is_unchanged_from_v14(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v14_adjudication(),
            )
        )

        model = contract[
            "model"
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

    def test_later_policy_uses_fixed_top3_without_new_threshold(self):
        _, contract = (
            phase1.build_dataset(
                source_frame(),
                source_contract(),
                v14_adjudication(),
            )
        )

        policy = contract[
            "frozen_policy_for_later_simulation"
        ]

        self.assertEqual(
            policy[
                "selected_asset_count"
            ],
            3,
        )
        self.assertEqual(
            policy[
                "asset_weight"
            ],
            0.20,
        )
        self.assertEqual(
            policy[
                "cash_weight"
            ],
            0.40,
        )
        self.assertIn(
            "no prediction threshold",
            policy[
                "selection_rule"
            ],
        )

    def test_v14_rejection_is_required(self):
        adjudication = (
            v14_adjudication()
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
                v14_adjudication(),
            )

    def test_source_rank_tampering_fails_closed(self):
        source = (
            source_frame()
        )
        source.loc[
            0,
            phase1.RANK_TARGET,
        ] = 0.123456

        with self.assertRaisesRegex(
            RuntimeError,
            "rank target",
        ):
            phase1.build_dataset(
                source,
                source_contract(),
                v14_adjudication(),
            )


if __name__ == "__main__":
    unittest.main()
