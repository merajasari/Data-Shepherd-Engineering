import unittest

import pandas as pd

from ml.shared_crypto_v13_regime_transition import phase1


class SharedCryptoV13Phase1Test(unittest.TestCase):
    def _source_contract(self):
        return {
            "research_version": (
                "shared_crypto_v12_btc_specialist"
            ),
            "future_holdout_start_utc": (
                phase1.HOLDOUT.isoformat()
            ),
            "regime_feature_columns": list(
                phase1.TRANSITION_BASE_FEATURES
            ) + ["other_feature"],
            "models": {
                "stage1": dict(
                    phase1.EXPECTED_STAGE1_MODEL
                ),
                "stage2": dict(
                    phase1.EXPECTED_STAGE2_MODEL
                ),
            },
            "walk_forward": {
                "purge_hours": 72,
                "minimum_train_days": 730,
                "validation_days": 180,
                "max_folds": 6,
            },
            "predictive_quality_gates": dict(
                phase1.EXPECTED_PREDICTIVE_GATES
            ),
            "frozen_policy_for_later_simulation": {
                "evaluation_clock": (
                    "non-overlapping exact 72-hour blocks inside each validation fold"
                ),
            },
            "selection_gates": {
                "median_fold_net_return_gt": 0.0,
            },
        }

    def _source(self):
        timestamps = pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            "2026-01-03T00:00:00Z",
            "2026-01-04T00:00:00Z",
            "2026-01-05T00:00:00Z",
            "2026-01-06T00:00:00Z",
        ], utc=True)

        labels = [
            "BTC", "ALT", "CASH",
            "BTC", "ALT", "CASH",
        ]

        data = {
            "timestamp_utc": timestamps,
            "best_sleeve_net25_72h": labels,
            "btc_vs_deviate_72h": [
                "BTC", "DEVIATE", "DEVIATE",
                "BTC", "DEVIATE", "DEVIATE",
            ],
            "alt_vs_cash_when_deviate_72h": [
                pd.NA, "ALT", "CASH",
                pd.NA, "ALT", "CASH",
            ],
            "alt_basket_assets": [
                "A|B|C|D|E"
            ] * 6,
            "other_feature": [
                10.0, 11.0, 12.0,
                13.0, 14.0, 15.0,
            ],
        }

        for index, feature in enumerate(
            phase1.TRANSITION_BASE_FEATURES,
            start=1,
        ):
            data[feature] = [
                float(
                    index * 10
                    + day
                )
                for day in range(
                    6
                )
            ]

        return pd.DataFrame(
            data
        )

    def test_exact_lags_and_deltas_are_created(self):
        dataset, contract = (
            phase1.build_dataset(
                self._source(),
                self._source_contract(),
            )
        )

        self.assertEqual(
            len(dataset),
            3,
        )

        first = dataset.iloc[0]
        feature = (
            phase1.TRANSITION_BASE_FEATURES[0]
        )

        self.assertEqual(
            first[
                "timestamp_utc"
            ],
            pd.Timestamp(
                "2026-01-04T00:00:00Z"
            ),
        )
        self.assertAlmostEqual(
            first[
                f"{feature}_lag_24h"
            ],
            12.0,
        )
        self.assertAlmostEqual(
            first[
                f"{feature}_delta_24h"
            ],
            1.0,
        )
        self.assertAlmostEqual(
            first[
                f"{feature}_lag_72h"
            ],
            10.0,
        )
        self.assertAlmostEqual(
            first[
                f"{feature}_delta_72h"
            ],
            3.0,
        )

        expected_new = (
            len(
                phase1.TRANSITION_BASE_FEATURES
            )
            * len(
                phase1.TRANSITION_LAG_HOURS
            )
            * 2
        )
        self.assertEqual(
            contract[
                "feature_engineering"
            ][
                "transition_feature_count"
            ],
            expected_new,
        )

    def test_v13_keeps_v12_models_unchanged(self):
        _, contract = (
            phase1.build_dataset(
                self._source(),
                self._source_contract(),
            )
        )

        self.assertEqual(
            contract[
                "models"
            ]["stage1"],
            phase1.EXPECTED_STAGE1_MODEL,
        )
        self.assertEqual(
            contract[
                "models"
            ]["stage2"],
            phase1.EXPECTED_STAGE2_MODEL,
        )

    def test_v13_keeps_v12_predictive_gates_unchanged(self):
        _, contract = (
            phase1.build_dataset(
                self._source(),
                self._source_contract(),
            )
        )

        self.assertEqual(
            contract[
                "predictive_quality_gates"
            ],
            phase1.EXPECTED_PREDICTIVE_GATES,
        )

    def test_only_information_set_changes(self):
        _, contract = (
            phase1.build_dataset(
                self._source(),
                self._source_contract(),
            )
        )

        constraints = contract[
            "research_constraints"
        ]

        self.assertTrue(
            constraints[
                "models_carried_forward_unchanged_from_v12"
            ]
        )
        self.assertTrue(
            constraints[
                "predictive_gates_carried_forward_unchanged_from_v12"
            ]
        )
        self.assertTrue(
            constraints[
                "only_information_set_changed"
            ]
        )
        self.assertTrue(
            constraints[
                "exact_timestamp_lags_only"
            ]
        )

    def test_future_information_is_not_a_feature(self):
        dataset, contract = (
            phase1.build_dataset(
                self._source(),
                self._source_contract(),
            )
        )

        features = set(
            contract[
                "regime_feature_columns"
            ]
        )
        forbidden = {
            phase1.SOURCE_TARGET,
            phase1.STAGE1_TARGET,
            phase1.STAGE2_TARGET,
            "btc_forward_return_72h",
            "alt_forward_return_72h",
            "alt_excess_vs_btc_net25_72h",
            "cash_excess_vs_btc_net25_72h",
            "oracle_best_deviation_net25_72h",
        }

        self.assertFalse(
            forbidden
            & features
        )
        self.assertFalse(
            dataset.empty
        )

    def test_missing_transition_base_fails_closed(self):
        source = (
            self._source()
            .drop(
                columns=[
                    phase1.TRANSITION_BASE_FEATURES[0]
                ]
            )
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "missing columns|missing transition bases",
        ):
            phase1.build_dataset(
                source,
                self._source_contract(),
            )

    def test_future_holdout_is_rejected(self):
        source = (
            self._source()
        )
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
                self._source_contract(),
            )


if __name__ == "__main__":
    unittest.main()
