import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v7_weekly_return_regression import phase1


class SharedCryptoV7Phase1Test(unittest.TestCase):
    def _panel(self):
        timestamps = pd.date_range(
            "2026-01-01T00:00:00Z", periods=337, freq="1h"
        )
        products = [phase1.BTC] + [f"ALT-{index:02d}" for index in range(11)]
        rows = []
        features = sorted(set(
            phase1.BTC_STATE_FEATURES + phase1.ALT_STATE_FEATURES
        ))
        for product_index, product in enumerate(products):
            base = 100.0 if product == phase1.BTC else 50.0
            hourly_growth = 0.00005 if product == phase1.BTC else 0.00010
            for time_index, timestamp in enumerate(timestamps):
                row = {
                    "timestamp_utc": timestamp,
                    "product_id": product,
                    "close": base * (1.0 + hourly_growth * time_index),
                    "volume": 100.0 + product_index,
                }
                row.update({feature: 0.01 for feature in features})
                rows.append(row)
        return pd.DataFrame(rows)

    def test_exact_weekly_return_does_not_bridge_clock_gaps(self):
        frame = pd.DataFrame({
            "timestamp_utc": pd.to_datetime([
                "2026-01-01T00:00:00Z", "2026-01-08T01:00:00Z"
            ], utc=True),
            "product_id": [phase1.BTC, phase1.BTC],
            "close": [100.0, 110.0],
        })
        result = phase1._attach_exact_horizon_returns(frame)
        self.assertTrue(np.isnan(result.iloc[0]["forward_return_168h"]))
        self.assertTrue(np.isnan(result.iloc[1]["trailing_return_168h"]))

    def test_builds_two_cost_aware_weekly_regression_targets(self):
        regime, assets, contract = phase1.build_datasets(self._panel())
        self.assertGreaterEqual(len(regime), 1)
        self.assertTrue((regime["timestamp_utc"].dt.hour == 0).all())
        self.assertIn("btc_net_entry_return_168h", regime.columns)
        self.assertIn("alt_net_entry_return_168h", regime.columns)
        self.assertTrue(
            (regime["alt_net_entry_return_168h"]
             > regime["btc_net_entry_return_168h"]).all()
        )
        selected = assets[assets["selected_liquid_top5"]]
        self.assertTrue((selected.groupby("timestamp_utc")["product_id"].nunique() == 5).all())
        self.assertEqual(contract["economic_horizon"], "exact 168 hours")
        self.assertEqual(
            contract["model_candidates"]["primary"],
            "two_hist_gradient_boosting_absolute_error_regressors",
        )
        self.assertFalse(contract["alt_sleeve"]["learned_ranker"])

    def test_future_holdout_rows_are_rejected(self):
        panel = self._panel()
        panel.loc[0, "timestamp_utc"] = phase1.HOLDOUT
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase1.build_datasets(panel)

    def test_preregistered_policy_uses_weekly_hold_and_no_threshold_search(self):
        _, _, contract = phase1.build_datasets(self._panel())
        policy = contract["frozen_policy_for_later_simulation"]
        self.assertEqual(policy["minimum_hold_hours"], 168)
        self.assertEqual(policy["confirmation_count"], 2)
        self.assertEqual(policy["minimum_predicted_net_return"], 0.0)
        self.assertEqual(policy["primary_round_trip_cost_bps"], 25.0)
        self.assertTrue(
            contract["research_constraints"]["no_post_result_threshold_search"]
        )
        self.assertFalse(policy["leverage"])
        self.assertFalse(policy["shorting"])
        self.assertFalse(policy["derivatives"])


if __name__ == "__main__":
    unittest.main()
