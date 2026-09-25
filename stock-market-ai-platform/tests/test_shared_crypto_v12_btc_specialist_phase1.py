import unittest

import pandas as pd

from ml.shared_crypto_v12_btc_specialist import phase1


class SharedCryptoV12Phase1Test(unittest.TestCase):
    def _source_contract(self):
        return {
            "research_version": (
                "shared_crypto_v11_hierarchical_selector"
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
            "best_sleeve_net25_72h": [
                "BTC", "ALT", "CASH",
                "BTC", "ALT", "CASH",
            ],
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
            "btc_forward_return_72h": [0.01] * 6,
            "alt_forward_return_72h": [0.02] * 6,
            "alt_excess_vs_btc_net25_72h": [0.005] * 6,
            "cash_excess_vs_btc_net25_72h": [-0.005] * 6,
            "oracle_best_deviation_net25_72h": [
                "BTC", "ALT", "CASH",
                "BTC", "ALT", "CASH",
            ],
        })

    def test_reuses_v11_hierarchical_targets_without_relabeling(self):
        dataset, _ = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )

        self.assertEqual(
            dataset[
                phase1.STAGE1_TARGET
            ].tolist(),
            [
                "BTC", "DEVIATE", "DEVIATE",
                "BTC", "DEVIATE", "DEVIATE",
            ],
        )

        stage2 = dataset[
            dataset[
                phase1.STAGE2_TARGET
            ].notna()
        ]
        self.assertEqual(
            stage2[
                phase1.STAGE2_TARGET
            ].tolist(),
            [
                "ALT", "CASH", "ALT", "CASH",
            ],
        )

    def test_v12_changes_only_stage1_model_family(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )

        stage1 = contract["models"]["stage1"]
        stage2 = contract["models"]["stage2"]

        self.assertEqual(
            stage1["primary"],
            "hist_gradient_boosting_classifier",
        )
        self.assertEqual(
            stage1["learning_rate"],
            0.05,
        )
        self.assertEqual(
            stage1["max_iter"],
            200,
        )
        self.assertEqual(
            stage1["max_leaf_nodes"],
            15,
        )
        self.assertEqual(
            stage1["min_samples_leaf"],
            30,
        )
        self.assertEqual(
            stage1["l2_regularization"],
            1.0,
        )
        self.assertEqual(
            stage1["class_weight"],
            "balanced",
        )

        self.assertEqual(
            stage2["primary"],
            "linear_svc",
        )
        self.assertEqual(
            stage2["C"],
            0.25,
        )
        self.assertEqual(
            stage2["class_weight"],
            "balanced",
        )

    def test_predictive_gates_are_not_weakened(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )

        gates = contract[
            "predictive_quality_gates"
        ]

        self.assertEqual(
            gates[
                "stage1_median_balanced_accuracy_gt"
            ],
            0.52,
        )
        self.assertEqual(
            gates[
                "stage2_median_balanced_accuracy_gt"
            ],
            0.52,
        )
        self.assertEqual(
            gates[
                "combined_median_balanced_accuracy_gt"
            ],
            0.36,
        )
        self.assertEqual(
            gates[
                "combined_median_macro_f1_gt"
            ],
            0.36,
        )
        self.assertEqual(
            gates[
                "combined_median_minimum_class_recall_gt"
            ],
            0.20,
        )

    def test_v12_is_separate_from_rejected_v11(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )

        successor = contract[
            "new_hypothesis_after_rejection"
        ]

        self.assertEqual(
            successor["rejected_parent"],
            "shared_crypto_v11_hierarchical_selector",
        )
        self.assertEqual(
            successor["parent_disposition"],
            "REJECT_CURRENT_V11_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            successor["v11_stage1_retuned"]
        )
        self.assertFalse(
            successor["v11_stage2_retuned"]
        )
        self.assertFalse(
            successor["v11_portfolio_simulated"]
        )

    def test_future_information_is_not_a_feature(self):
        dataset, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
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
            forbidden & features
        )
        self.assertIn(
            phase1.STAGE1_TARGET,
            dataset.columns,
        )
        self.assertIn(
            phase1.STAGE2_TARGET,
            dataset.columns,
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
