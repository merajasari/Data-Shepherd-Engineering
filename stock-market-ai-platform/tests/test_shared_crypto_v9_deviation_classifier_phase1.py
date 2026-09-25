import unittest

import pandas as pd

from ml.shared_crypto_v9_deviation_classifier import phase1


class SharedCryptoV9Phase1Test(unittest.TestCase):
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
            ], utc=True),
            "feature_a": [1.0, 2.0, 3.0, 4.0],
            "feature_b": [4.0, 3.0, 2.0, 1.0],
            "btc_forward_return_72h": [0.01, -0.02, 0.03, -0.04],
            "alt_forward_return_72h": [0.04, -0.01, 0.01, -0.05],
            "alt_excess_vs_btc_net25_72h": [
                0.0275,
                0.0075,
                -0.0225,
                -0.0125,
            ],
            "cash_excess_vs_btc_net25_72h": [
                -0.0125,
                0.0175,
                -0.0325,
                0.0375,
            ],
            "alt_basket_assets": [
                "A|B|C|D|E",
                "A|B|C|D|E",
                "A|B|C|D|E",
                "A|B|C|D|E",
            ],
            "oracle_best_deviation_net25_72h": [
                "ALT",
                "CASH",
                "BTC",
                "CASH",
            ],
        })

    def test_binary_targets_match_positive_excess_events(self):
        dataset, _ = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        self.assertEqual(
            dataset[phase1.ALT_LABEL].tolist(),
            [1, 1, 0, 0],
        )
        self.assertEqual(
            dataset[phase1.CASH_LABEL].tolist(),
            [0, 1, 0, 1],
        )

    def test_future_targets_and_labels_are_not_features(self):
        dataset, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        features = set(
            contract["regime_feature_columns"]
        )
        forbidden = {
            phase1.ALT_EXCESS,
            phase1.CASH_EXCESS,
            phase1.ALT_LABEL,
            phase1.CASH_LABEL,
            "btc_forward_return_72h",
            "alt_forward_return_72h",
            "oracle_best_deviation_net25_72h",
        }
        self.assertFalse(
            forbidden & features
        )
        self.assertIn(
            phase1.ALT_LABEL,
            dataset.columns,
        )
        self.assertIn(
            phase1.CASH_LABEL,
            dataset.columns,
        )

    def test_v9_preregisters_single_fixed_logistic_model(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        model = contract["model"]
        policy = contract[
            "predictive_policy"
        ]
        self.assertEqual(
            model["primary"],
            "logistic_regression",
        )
        self.assertEqual(
            model["penalty"],
            "l2",
        )
        self.assertEqual(
            model["C"],
            0.5,
        )
        self.assertEqual(
            model["secondary_models"],
            [],
        )
        self.assertEqual(
            policy["fixed_probability_threshold"],
            0.50,
        )
        self.assertFalse(
            policy["threshold_search"]
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
                "median_roc_auc_each_target_gt"
            ],
            0.52,
        )
        self.assertEqual(
            gates[
                "median_balanced_accuracy_each_target_gt"
            ],
            0.52,
        )
        self.assertEqual(
            gates[
                "median_brier_improvement_vs_train_prevalence_each_target_gt"
            ],
            0.0,
        )
        self.assertEqual(
            gates[
                "median_log_loss_improvement_vs_train_prevalence_each_target_gt"
            ],
            0.0,
        )
        self.assertTrue(
            gates[
                "all_gates_required_before_portfolio_simulation"
            ]
        )

    def test_v9_is_separate_from_rejected_v8(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        successor = contract[
            "new_hypothesis_after_rejection"
        ]
        self.assertEqual(
            successor["rejected_parent"],
            "shared_crypto_v8_relative_value_linear",
        )
        self.assertEqual(
            successor["parent_disposition"],
            "REJECT_CURRENT_V8_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            successor["v8_thresholds_retuned"]
        )
        self.assertFalse(
            successor["v8_ridge_reused"]
        )
        self.assertFalse(
            successor["v8_portfolio_simulated"]
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
