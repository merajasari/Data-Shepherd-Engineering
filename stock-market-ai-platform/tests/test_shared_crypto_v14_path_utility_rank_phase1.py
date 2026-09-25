import unittest

import numpy as np
import pandas as pd

from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES
from ml.shared_crypto_v14_path_utility_rank import phase1


class SharedCryptoV14Phase1Test(unittest.TestCase):
    def _featured(
        self,
        start="2026-01-01T00:00:00Z",
        days=10,
        assets=12,
    ):
        timestamps = pd.date_range(
            start,
            periods=days,
            freq="24h",
        )
        rows = []

        for asset_index in range(
            assets
        ):
            product = (
                "BTC-USD"
                if asset_index == 0
                else f"ALT{asset_index:02d}-USD"
            )

            for day_index, timestamp in enumerate(
                timestamps
            ):
                base = (
                    100.0
                    + asset_index
                )
                close = (
                    base
                    * (
                        1.0
                        + 0.01
                        * day_index
                    )
                )

                row = {
                    "product_id": product,
                    "timestamp_utc": timestamp,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                    "source_provider": "test_provider",
                    "source_granularity": "daily",
                    "is_eligible": True,
                }

                for feature_index, feature in enumerate(
                    REQUIRED_FEATURES,
                    start=1,
                ):
                    row[feature] = (
                        0.001
                        * feature_index
                        + 0.0001
                        * day_index
                    )

                rows.append(
                    row
                )

        return pd.DataFrame(
            rows
        )

    def test_exact_seven_day_path_utility_formula(self):
        source = self._featured(
            days=8,
        )

        btc_mask = (
            source["product_id"]
            == "BTC-USD"
        )

        btc_rows = (
            source.loc[
                btc_mask
            ]
            .sort_values(
                "timestamp_utc"
            )
            .index
        )

        closes = [
            100.0,
            99.0,
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            107.0,
        ]

        for index, close in zip(
            btc_rows,
            closes,
        ):
            source.loc[
                index,
                [
                    "open",
                    "high",
                    "low",
                    "close",
                ],
            ] = close

        dataset, _ = (
            phase1.build_path_utility_dataset(
                source
            )
        )

        row = dataset[
            (
                dataset["product_id"]
                == "BTC-USD"
            )
            & (
                dataset["timestamp_utc"]
                == pd.Timestamp(
                    "2026-01-01T00:00:00Z"
                )
            )
        ].iloc[0]

        self.assertAlmostEqual(
            float(
                row[
                    phase1.TERMINAL_TARGET
                ]
            ),
            0.0675,
            places=10,
        )

        self.assertAlmostEqual(
            float(
                row[
                    phase1.ADVERSE_TARGET
                ]
            ),
            -0.01,
            places=10,
        )

        self.assertAlmostEqual(
            float(
                row[
                    phase1.FAVORABLE_TARGET
                ]
            ),
            0.07,
            places=10,
        )

        self.assertAlmostEqual(
            float(
                row[
                    phase1.TARGET
                ]
            ),
            0.0575,
            places=10,
        )

    def test_missing_exact_future_day_drops_only_invalid_asset_path(self):
        source = self._featured(
            days=9,
            assets=12,
        )

        source = source[
            ~(
                (
                    source[
                        "product_id"
                    ]
                    == "ALT01-USD"
                )
                & (
                    source[
                        "timestamp_utc"
                    ]
                    == pd.Timestamp(
                        "2026-01-04T00:00:00Z"
                    )
                )
            )
        ].copy()

        dataset, _ = (
            phase1.build_path_utility_dataset(
                source
            )
        )

        invalid = dataset[
            (
                dataset[
                    "product_id"
                ]
                == "ALT01-USD"
            )
            & (
                dataset[
                    "timestamp_utc"
                ]
                == pd.Timestamp(
                    "2026-01-01T00:00:00Z"
                )
            )
        ]

        valid_peer = dataset[
            (
                dataset[
                    "product_id"
                ]
                == "ALT02-USD"
            )
            & (
                dataset[
                    "timestamp_utc"
                ]
                == pd.Timestamp(
                    "2026-01-01T00:00:00Z"
                )
            )
        ]

        self.assertTrue(
            invalid.empty
        )
        self.assertEqual(
            len(
                valid_peer
            ),
            1,
        )

    def test_target_path_must_finish_before_holdout(self):
        source = self._featured(
            start="2026-08-20T00:00:00Z",
            days=12,
            assets=12,
        )

        dataset, _ = (
            phase1.build_path_utility_dataset(
                source
            )
        )

        endpoint = (
            dataset[
                "target_endpoint_utc_7d"
            ]
        )

        self.assertTrue(
            (
                endpoint
                < phase1.HOLDOUT
            ).all()
        )

        self.assertLessEqual(
            dataset[
                "timestamp_utc"
            ].max(),
            pd.Timestamp(
                "2026-08-24T00:00:00Z"
            ),
        )

    def test_btc_is_an_investable_asset_and_cash_is_not_synthetic_row(self):
        dataset, contract = (
            phase1.build_path_utility_dataset(
                self._featured(
                    days=9,
                    assets=12,
                )
            )
        )

        self.assertIn(
            "BTC-USD",
            set(
                dataset[
                    "product_id"
                ]
            ),
        )

        self.assertNotIn(
            "CASH",
            set(
                dataset[
                    "product_id"
                ]
            ),
        )

        self.assertEqual(
            contract[
                "research_family_reset"
            ][
                "cash_representation"
            ],
            "abstention_if_no_positive_predicted_utility",
        )

    def test_model_and_predictive_gates_are_fixed_before_fit(self):
        _, contract = (
            phase1.build_path_utility_dataset(
                self._featured(
                    days=9,
                    assets=12,
                )
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
        self.assertEqual(
            model[
                "secondary_models"
            ],
            [],
        )

        gates = contract[
            "predictive_quality_gates"
        ]

        self.assertEqual(
            gates[
                "median_fold_daily_spearman_ic_gt"
            ],
            0.05,
        )
        self.assertEqual(
            gates[
                "median_fold_positive_ic_day_fraction_gt"
            ],
            0.52,
        )
        self.assertEqual(
            gates[
                "positive_fold_top3_target_utility_excess_fraction_gte"
            ],
            0.75,
        )
        self.assertTrue(
            gates[
                "all_gates_required_before_portfolio_simulation"
            ]
        )

    def test_provenance_and_targets_are_not_model_features(self):
        _, contract = (
            phase1.build_path_utility_dataset(
                self._featured(
                    days=9,
                    assets=12,
                )
            )
        )

        features = set(
            contract[
                "model_feature_columns"
            ]
        )

        self.assertNotIn(
            "source_provider",
            features,
        )
        self.assertNotIn(
            "source_granularity",
            features,
        )
        self.assertNotIn(
            phase1.TARGET,
            features,
        )
        self.assertFalse(
            any(
                "future_"
                in feature
                for feature
                in features
            )
        )

    def test_family_reset_preserves_v8_through_v13_as_closed(self):
        _, contract = (
            phase1.build_path_utility_dataset(
                self._featured(
                    days=9,
                    assets=12,
                )
            )
        )

        reset = contract[
            "research_family_reset"
        ]

        self.assertEqual(
            reset[
                "new_task"
            ],
            "asset_level_regression_and_cross_sectional_ranking",
        )

        self.assertIn(
            "shared_crypto_v13_regime_transition",
            reset[
                "closed_versions"
            ],
        )

        self.assertFalse(
            reset[
                "prior_models_retuned"
            ]
        )
        self.assertFalse(
            reset[
                "prior_gates_weakened"
            ]
        )
        self.assertFalse(
            reset[
                "prior_portfolios_simulated_after_predictive_failure"
            ]
        )


if __name__ == "__main__":
    unittest.main()
