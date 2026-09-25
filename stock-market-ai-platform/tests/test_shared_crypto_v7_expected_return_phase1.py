import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v7_expected_return import phase1


class SharedCryptoV7Phase1Test(unittest.TestCase):
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
                        1.01 if product == phase1.BTC else 1.06
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

    def test_builds_preregistered_72h_regression_dataset(self):
        regime, assets, contract = phase1.build_datasets(
            self._panel()
        )
        self.assertEqual(len(regime), 1)
        self.assertEqual(
            regime.iloc[0]["timestamp_utc"].hour,
            phase1.DECISION_HOUR_UTC,
        )
        self.assertEqual(
            regime.iloc[0]["oracle_best_sleeve_net25_72h"],
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
            contract["economic_horizon"],
            "exact 72 hours",
        )
        self.assertEqual(
            contract["model_candidates"]["primary"],
            "hist_gradient_boosting_regressor",
        )
        self.assertEqual(
            contract["model_candidates"]["targets"],
            [
                "btc_net_entry_return_72h",
                "alt_net_entry_return_72h",
            ],
        )
        self.assertFalse(
            contract["alt_sleeve"]["learned_ranker"]
        )

    def test_regression_targets_are_not_features(self):
        regime, _, contract = phase1.build_datasets(
            self._panel()
        )
        features = set(
            contract["regime_feature_columns"]
        )
        self.assertNotIn(
            "btc_net_entry_return_72h",
            features,
        )
        self.assertNotIn(
            "alt_net_entry_return_72h",
            features,
        )
        self.assertNotIn(
            "oracle_best_sleeve_net25_72h",
            features,
        )
        self.assertIn(
            "btc_net_entry_return_72h",
            regime.columns,
        )
        self.assertIn(
            "alt_net_entry_return_72h",
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

    def test_v7_policy_is_frozen_without_v6_retuning(self):
        _, _, contract = phase1.build_datasets(
            self._panel()
        )
        hypothesis = contract[
            "new_hypothesis_after_rejection"
        ]
        policy = contract[
            "frozen_policy_for_later_simulation"
        ]
        constraints = contract["research_constraints"]

        self.assertEqual(
            hypothesis["rejected_parent"],
            "shared_crypto_v6_durable_edge",
        )
        self.assertFalse(
            hypothesis["v6_thresholds_retuned"]
        )
        self.assertFalse(
            hypothesis["v6_policy_reused"]
        )
        self.assertEqual(
            policy["minimum_hold_hours"],
            72,
        )
        self.assertEqual(
            policy["minimum_predicted_net_return"],
            0.0,
        )
        self.assertFalse(
            policy["probability_confidence_filter"]
        )
        self.assertFalse(
            policy["probability_margin_filter"]
        )
        self.assertEqual(
            policy["primary_round_trip_cost_bps"],
            25.0,
        )
        self.assertEqual(
            policy["stress_round_trip_cost_bps"],
            50.0,
        )
        self.assertFalse(policy["leverage"])
        self.assertFalse(policy["shorting"])
        self.assertFalse(policy["derivatives"])
        self.assertFalse(
            constraints["selection_gates_weakened_from_v6"]
        )


if __name__ == "__main__":
    unittest.main()
