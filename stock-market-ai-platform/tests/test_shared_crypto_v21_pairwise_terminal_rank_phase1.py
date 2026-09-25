import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v21_pairwise_terminal_rank import phase1


def source_contract():
    features = [
        f"feature_{index}"
        for index in range(
            22
        )
    ]

    return {
        "research_version": (
            phase1.SOURCE_VERSION
        ),
        "future_holdout_start_utc": (
            phase1.HOLDOUT.isoformat()
        ),
        "model_feature_columns": (
            features
        ),
        "learning_target": {
            "raw_economic_target": (
                phase1.RAW_RELATIVE_TARGET
            ),
        },
        "research_constraints": {
            "offline_research_only": True,
            "future_holdout_must_remain_untouched_until_candidate_freeze": True,
        },
    }


def source_adjudication():
    return {
        "research_version": (
            phase1.SOURCE_VERSION
        ),
        "status": (
            "REJECT_CURRENT_V20_BTC_RELATIVE_TERMINAL_RANK_HYPOTHESIS"
        ),
        "offline_portfolio_simulation_allowed": False,
    }


def source_frame():
    products = [
        "ADA-USD",
        "AVAX-USD",
        "BCH-USD",
        "BTC-USD",
        "DOGE-USD",
        "ETH-USD",
        "LINK-USD",
        "LTC-USD",
        "SOL-USD",
        "XRP-USD",
    ]

    rows = []

    for day_index, timestamp in enumerate(
        pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        ])
    ):
        for asset_index, product in enumerate(
            products
        ):
            relative = (
                (
                    asset_index
                    - 4
                )
                * 0.01
                * (
                    1
                    if day_index == 0
                    else -1
                )
            )

            row = {
                "timestamp_utc": (
                    timestamp
                ),
                "product_id": (
                    product
                ),
                phase1.RAW_RELATIVE_TARGET: (
                    relative
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
                    asset_index
                    + 0.1
                    * feature_index
                    + 0.01
                    * day_index
                )

            rows.append(
                row
            )

    return pd.DataFrame(
        rows
    )


class SharedCryptoV21Phase1Test(
    unittest.TestCase
):
    def build(self):
        return (
            phase1.build_pairwise_dataset(
                source_frame(),
                source_contract(),
                source_adjudication(),
            )
        )

    def test_all_canonical_unordered_pairs_are_built(self):
        pairwise, _ = self.build()

        expected_per_day = (
            10
            * 9
            // 2
        )

        self.assertEqual(
            len(
                pairwise
            ),
            expected_per_day
            * 2,
        )

        self.assertTrue(
            (
                pairwise[
                    "left_product_id"
                ]
                < pairwise[
                    "right_product_id"
                ]
            ).all()
        )

    def test_pair_label_matches_target_margin(self):
        pairwise, _ = self.build()

        self.assertTrue(
            (
                pairwise[
                    phase1.PAIR_LABEL
                ]
                == (
                    pairwise[
                        phase1.PAIR_MARGIN
                    ]
                    > 0.0
                ).astype(
                    int
                )
            ).all()
        )

        self.assertEqual(
            set(
                pairwise[
                    phase1.PAIR_LABEL
                ].unique()
            ),
            {
                0,
                1,
            },
        )

    def test_difference_and_mean_features_are_exact(self):
        pairwise, _ = self.build()

        row = pairwise.iloc[
            0
        ]

        left = row[
            "left_product_id"
        ]

        right = row[
            "right_product_id"
        ]

        source = source_frame()

        day = source[
            source[
                "timestamp_utc"
            ]
            == row[
                "timestamp_utc"
            ]
        ]

        left_row = day[
            day[
                "product_id"
            ]
            == left
        ].iloc[
            0
        ]

        right_row = day[
            day[
                "product_id"
            ]
            == right
        ].iloc[
            0
        ]

        self.assertAlmostEqual(
            float(
                row[
                    "diff__feature_0"
                ]
            ),
            float(
                left_row[
                    "feature_0"
                ]
                - right_row[
                    "feature_0"
                ]
            ),
        )

        self.assertAlmostEqual(
            float(
                row[
                    "mean__feature_0"
                ]
            ),
            float(
                (
                    left_row[
                        "feature_0"
                    ]
                    + right_row[
                        "feature_0"
                    ]
                )
                / 2.0
            ),
        )

    def test_model_feature_count_is_44(self):
        _, contract = self.build()

        self.assertEqual(
            len(
                contract[
                    "base_feature_columns"
                ]
            ),
            22,
        )

        self.assertEqual(
            len(
                contract[
                    "difference_feature_columns"
                ]
            ),
            22,
        )

        self.assertEqual(
            len(
                contract[
                    "pair_mean_feature_columns"
                ]
            ),
            22,
        )

        self.assertEqual(
            len(
                contract[
                    "model_feature_columns"
                ]
            ),
            44,
        )

    def test_exact_target_ties_are_dropped_and_counted(self):
        source = source_frame()

        timestamp = pd.Timestamp(
            "2026-01-01T00:00:00Z"
        )

        day_mask = (
            source[
                "timestamp_utc"
            ]
            == timestamp
        )

        products = list(
            source.loc[
                day_mask,
                "product_id",
            ]
        )

        first = products[
            0
        ]

        second = products[
            1
        ]

        first_value = float(
            source.loc[
                day_mask
                & (
                    source[
                        "product_id"
                    ]
                    == first
                ),
                phase1.RAW_RELATIVE_TARGET,
            ].iloc[
                0
            ]
        )

        source.loc[
            day_mask
            & (
                source[
                    "product_id"
                ]
                == second
            ),
            phase1.RAW_RELATIVE_TARGET,
        ] = (
            first_value
        )

        pairwise, contract = (
            phase1.build_pairwise_dataset(
                source,
                source_contract(),
                source_adjudication(),
            )
        )

        self.assertEqual(
            int(
                contract[
                    "dataset"
                ][
                    "dropped_tie_pair_count"
                ]
            ),
            1,
        )

        self.assertFalse(
            np.isclose(
                pairwise[
                    phase1.PAIR_MARGIN
                ].to_numpy(
                    dtype=float
                ),
                0.0,
                rtol=0.0,
                atol=phase1.PAIR_TIE_ATOL,
            ).any()
        )

    def test_v20_rejection_is_required(self):
        adjudication = (
            source_adjudication()
        )

        adjudication[
            "status"
        ] = (
            "QUALIFIED_FOR_OFFLINE_PORTFOLIO_SIMULATION"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "V20",
        ):
            phase1.build_pairwise_dataset(
                source_frame(),
                source_contract(),
                adjudication,
            )

    def test_future_holdout_is_rejected(self):
        source = source_frame()

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
            phase1.build_pairwise_dataset(
                source,
                source_contract(),
                source_adjudication(),
            )

    def test_model_and_six_predictive_gates_are_frozen(self):
        _, contract = self.build()

        model = contract[
            "model"
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
            len(
                contract[
                    "predictive_quality_gates"
                ]
            )
            - 1,
            6,
        )

    def test_offline_no_threshold_no_topk_search(self):
        _, contract = self.build()

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "offline_research_only"
            ]
        )

        self.assertTrue(
            constraints[
                "no_probability_threshold_for_ranking"
            ]
        )

        self.assertTrue(
            constraints[
                "no_probability_threshold_search"
            ]
        )

        self.assertTrue(
            constraints[
                "no_top_k_search"
            ]
        )

        self.assertFalse(
            constraints[
                "brokerage_orders"
            ]
        )


if __name__ == "__main__":
    unittest.main()
