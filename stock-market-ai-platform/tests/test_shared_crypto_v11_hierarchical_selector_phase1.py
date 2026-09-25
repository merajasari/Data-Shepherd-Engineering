import unittest

import pandas as pd

from ml.shared_crypto_v11_hierarchical_selector import phase1


class SharedCryptoV11Phase1Test(unittest.TestCase):
    def _source_contract(self):
        return {
            "research_version": "shared_crypto_v10_regime_ranker",
            "future_holdout_start_utc": phase1.HOLDOUT.isoformat(),
            "regime_feature_columns": ["feature_a", "feature_b"],
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
                "BTC", "ALT", "CASH", "BTC", "ALT", "CASH"
            ],
            "alt_basket_assets": ["A|B|C|D|E"] * 6,
            "btc_forward_return_72h": [0.01] * 6,
            "alt_forward_return_72h": [0.02] * 6,
            "alt_excess_vs_btc_net25_72h": [0.005] * 6,
            "cash_excess_vs_btc_net25_72h": [-0.005] * 6,
            "oracle_best_deviation_net25_72h": [
                "BTC", "ALT", "CASH", "BTC", "ALT", "CASH"
            ],
        })

    def test_builds_two_stage_targets(self):
        dataset, _ = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )

        self.assertEqual(
            dataset[phase1.STAGE1_TARGET].tolist(),
            ["BTC", "DEVIATE", "DEVIATE", "BTC", "DEVIATE", "DEVIATE"],
        )

        stage2 = dataset[dataset[phase1.STAGE2_TARGET].notna()]
        self.assertEqual(
            stage2[phase1.STAGE2_TARGET].tolist(),
            ["ALT", "CASH", "ALT", "CASH"],
        )

    def test_stage2_is_defined_only_on_deviation_rows(self):
        dataset, _ = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )

        btc_rows = dataset[
            dataset[phase1.SOURCE_TARGET] == "BTC"
        ]
        self.assertTrue(
            btc_rows[phase1.STAGE2_TARGET].isna().all()
        )

    def test_v11_preregisters_fixed_balanced_linear_svc(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        model = contract["model"]

        self.assertEqual(model["primary"], "linear_svc")
        self.assertEqual(model["C"], 0.25)
        self.assertEqual(model["class_weight"], "balanced")
        self.assertEqual(model["secondary_models"], [])
        self.assertIsNone(model["probability_calibration"])

    def test_combined_gates_are_not_weakened_from_v10(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        gates = contract["predictive_quality_gates"]

        self.assertEqual(
            gates["combined_median_balanced_accuracy_gt"],
            0.36,
        )
        self.assertEqual(
            gates["combined_median_macro_f1_gt"],
            0.36,
        )
        self.assertEqual(
            gates["combined_median_minimum_class_recall_gt"],
            0.20,
        )
        self.assertEqual(
            gates["stage1_median_balanced_accuracy_gt"],
            0.52,
        )
        self.assertEqual(
            gates["stage2_median_balanced_accuracy_gt"],
            0.52,
        )

    def test_future_information_is_not_a_feature(self):
        dataset, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        features = set(contract["regime_feature_columns"])

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

        self.assertFalse(forbidden & features)
        self.assertIn(phase1.STAGE1_TARGET, dataset.columns)
        self.assertIn(phase1.STAGE2_TARGET, dataset.columns)

    def test_v11_is_separate_from_rejected_v10(self):
        _, contract = phase1.build_dataset(
            self._source(),
            self._source_contract(),
        )
        successor = contract["new_hypothesis_after_rejection"]

        self.assertEqual(
            successor["rejected_parent"],
            "shared_crypto_v10_regime_ranker",
        )
        self.assertEqual(
            successor["parent_disposition"],
            "REJECT_CURRENT_V10_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(successor["v10_class_weight_changed"])
        self.assertFalse(successor["v10_linear_svc_c_changed"])
        self.assertFalse(successor["v10_portfolio_simulated"])

    def test_future_holdout_is_rejected(self):
        source = self._source()
        source.loc[0, "timestamp_utc"] = phase1.HOLDOUT

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
