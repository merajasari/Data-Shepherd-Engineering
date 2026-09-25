import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v8_relative_value_linear import phase1


class SharedCryptoV8Phase1Test(unittest.TestCase):
    def _panel(self):
        timestamps = pd.date_range(
            "2026-01-01T00:00:00Z",
            periods=97,
            freq="1h",
        )
        products = [phase1.BTC] + [
            f"ALT-{index:02d}" for index in range(11)
        ]
        rows = []
        features = sorted(set(
            phase1.BTC_STATE_FEATURES
            + phase1.ALT_STATE_FEATURES
        ))
        for product_index, product in enumerate(products):
            base = 100.0 if product == phase1.BTC else 50.0
            for time_index, timestamp in enumerate(timestamps):
                close = base
                if time_index == 96:
                    close = base * (
                        1.02 if product == phase1.BTC else 1.08
                    )
                row = {
                    "timestamp_utc": timestamp,
                    "product_id": product,
                    "close": close,
                    "volume": 100.0 + product_index,
                }
                row.update({
                    feature: 0.01
                    for feature in features
                })
                rows.append(row)
        return pd.DataFrame(rows)

    def test_exact_72h_forward_return_does_not_bridge_clock_gaps(self):
        frame = pd.DataFrame({
            "timestamp_utc": pd.to_datetime([
                "2026-01-01T00:00:00Z",
                "2026-01-04T01:00:00Z",
            ], utc=True),
            "product_id": [phase1.BTC, phase1.BTC],
            "close": [100.0, 110.0],
        })
        result = phase1._attach_exact_forward_return(frame)
        self.assertTrue(
            np.isnan(result.iloc[0]["forward_return_72h"])
        )

    def test_builds_btc_relative_targets_and_oracle(self):
        regime, assets, contract = phase1.build_datasets(
            self._panel()
        )
        self.assertEqual(len(regime), 1)
        row = regime.iloc[0]

        expected_alt_excess = 0.08 - 0.02 - 0.0025
        expected_cash_excess = -0.02 - 0.0025

        self.assertAlmostEqual(
            row["alt_excess_vs_btc_net25_72h"],
            expected_alt_excess,
        )
        self.assertAlmostEqual(
            row["cash_excess_vs_btc_net25_72h"],
            expected_cash_excess,
        )
        self.assertEqual(
            row["oracle_best_deviation_net25_72h"],
            "ALT",
        )

        selected = assets[
            assets["selected_liquid_top5"]
        ]
        self.assertEqual(len(selected), 5)
        self.assertEqual(
            selected["product_id"].nunique(),
            5,
        )
        self.assertEqual(
            contract["model_candidates"]["primary"],
            "ridge_regression",
        )
        self.assertEqual(
            contract["model_candidates"][
                "primary_regularization_alpha"
            ],
            10.0,
        )
        self.assertEqual(
            contract["model_candidates"]["secondary_models"],
            [],
        )

    def test_relative_targets_are_not_model_features(self):
        regime, _, contract = phase1.build_datasets(
            self._panel()
        )
        features = set(
            contract["regime_feature_columns"]
        )
        for target in (
            "alt_excess_vs_btc_net25_72h",
            "cash_excess_vs_btc_net25_72h",
            "oracle_best_deviation_net25_72h",
            "oracle_best_excess_vs_btc_net25_72h",
        ):
            self.assertNotIn(target, features)
        self.assertIn(
            "alt_excess_vs_btc_net25_72h",
            regime.columns,
        )
        self.assertIn(
            "cash_excess_vs_btc_net25_72h",
            regime.columns,
        )

    def test_future_holdout_rows_are_rejected(self):
        panel = self._panel()
        panel.loc[0, "timestamp_utc"] = phase1.HOLDOUT
        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase1.build_datasets(panel)

    def test_v8_is_separate_from_v7_and_preserves_gates(self):
        _, _, contract = phase1.build_datasets(
            self._panel()
        )
        successor = contract[
            "new_hypothesis_after_rejection"
        ]
        policy = contract[
            "frozen_policy_for_later_simulation"
        ]
        constraints = contract[
            "research_constraints"
        ]

        self.assertEqual(
            successor["rejected_parent"],
            "shared_crypto_v7_expected_return",
        )
        self.assertFalse(
            successor["v7_thresholds_retuned"]
        )
        self.assertFalse(
            successor["v7_primary_model_reused"]
        )
        self.assertFalse(
            successor["v7_policy_reused"]
        )

        self.assertEqual(
            policy["default_state"],
            "BTC",
        )
        self.assertEqual(
            policy["minimum_hold_hours"],
            72,
        )
        self.assertEqual(
            policy["minimum_predicted_excess_return"],
            0.0,
        )
        self.assertEqual(
            policy["maximum_gross_crypto_exposure"],
            1.0,
        )
        self.assertEqual(
            policy["maximum_turnover_per_72h_decision"],
            0.50,
        )
        self.assertFalse(policy["leverage"])
        self.assertFalse(policy["shorting"])
        self.assertFalse(policy["derivatives"])

        self.assertFalse(
            constraints[
                "portfolio_selection_gates_weakened_from_v7"
            ]
        )
        self.assertTrue(
            constraints[
                "nonoverlapping_72h_evaluation_required"
            ]
        )


if __name__ == "__main__":
    unittest.main()
