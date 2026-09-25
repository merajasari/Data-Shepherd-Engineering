import unittest

import pandas as pd

from ml.shared_crypto_v10_regime_ranker import phase1


class SharedCryptoV10Phase1Test(unittest.TestCase):
    def _source_contract(self):
        return {
            "research_version": (
                "shared_crypto_v8_relative_value_linear"
            ),
            "future_holdout_start_utc": (
                phase1.HOLDOUT.isoformat()
            ),
            "regime_feature_columns": [
                "feature_a",
                "feature_b",
            ],
        }

    def _source(self):
        return pd.DataFrame({
            "timestamp_utc": pd.to_datetime([
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
                "2026-01-03T00:00:00Z",
                "2026-01-04T00:00:00Z",
                "2026-01-05T00:00:00Z",
                "2026-01-06T00:00:00Z",
            ], utc=True),
            "feature_a": [1, 2, 3, 4, 5, 6],
            "feature_b": [6, 5, 4, 3, 2, 1],
            "btc_forward_return_72h": [
                0.01, -0.02, 0.03, 0.01, -0.03, 0.02
            ],
            "alt_forward_return_72h": [
                0.05, -0.01, 0.01, 0.02, -0.02, 0.01
            ],
            "alt_excess_vs_btc_net25_72h": [
                0.0375, 0.0075, -0.0225, 0.0075, 0.0075, -0.0125
            ],
            "cash_excess_vs_btc_net25_72h": [
                -0.0125, 0.0175, -0.0325, -0.0125, 0.0275, -0.0225
            ],
            "alt_basket_assets": [
                "A|B|C|D|E"
            ] * 6,
            "oracle_best_deviation_net25_72h": [
                "ALT", "CASH", "BTC", "ALT", "CASH", "BTC"
            ],
        })

    def test_derives_direct_three_class_sleeve_target(self):
        dataset, _ = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        self.assertEqual(
            dataset[phase1.TARGET].tolist(),
            ["ALT", "CASH", "BTC", "ALT", "CASH", "BTC"],
        )
        self.assertEqual(
            set(dataset[phase1.TARGET]),
            {"BTC", "ALT", "CASH"},
        )

    def test_target_matches_existing_oracle_diagnostic(self):
        source = self._source()
        source.loc[
            0,
            "oracle_best_deviation_net25_72h",
        ] = "BTC"
        with self.assertRaisesRegex(
            RuntimeError,
            "disagrees with V8 oracle",
        ):
            phase1.build_dataset(
                source,
                self._source_contract(),
            )

    def test_future_information_is_not_a_model_feature(self):
        dataset, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        features = set(
            contract["regime_feature_columns"]
        )
        forbidden = {
            phase1.TARGET,
            phase1.ALT_EXCESS,
            phase1.CASH_EXCESS,
            "btc_forward_return_72h",
            "alt_forward_return_72h",
            "oracle_best_deviation_net25_72h",
        }
        self.assertFalse(
            forbidden & features
        )
        self.assertIn(
            phase1.TARGET,
            dataset.columns,
        )

    def test_v10_preregisters_one_margin_based_model(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        model = contract["model"]

        self.assertEqual(
            model["primary"],
            "linear_svc",
        )
        self.assertEqual(
            model["C"],
            0.25,
        )
        self.assertEqual(
            model["loss"],
            "squared_hinge",
        )
        self.assertEqual(
            model["secondary_models"],
            [],
        )
        self.assertIsNone(
            model["probability_calibration"]
        )

    def test_predictive_gates_are_fixed_before_model_fit(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        gates = contract[
            "predictive_quality_gates"
        ]

        self.assertEqual(
            gates[
                "median_balanced_accuracy_gt"
            ],
            0.36,
        )
        self.assertEqual(
            gates[
                "median_macro_f1_gt"
            ],
            0.36,
        )
        self.assertEqual(
            gates[
                "median_accuracy_improvement_vs_train_majority_gt"
            ],
            0.0,
        )
        self.assertEqual(
            gates[
                "median_multiclass_mcc_gt"
            ],
            0.0,
        )
        self.assertEqual(
            gates[
                "median_minimum_class_recall_gt"
            ],
            0.20,
        )
        self.assertTrue(
            gates[
                "all_gates_required_before_portfolio_simulation"
            ]
        )

    def test_v10_is_separate_from_v9(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        successor = contract[
            "new_hypothesis_after_rejection"
        ]

        self.assertEqual(
            successor["rejected_parent"],
            "shared_crypto_v9_deviation_classifier",
        )
        self.assertEqual(
            successor["parent_disposition"],
            "REJECT_CURRENT_V9_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            successor["v9_threshold_retuned"]
        )
        self.assertFalse(
            successor["v9_logistic_model_reused"]
        )
        self.assertFalse(
            successor["v9_portfolio_simulated"]
        )

    def test_future_holdout_is_rejected(self):
        source = self._source()
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
