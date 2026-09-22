import unittest

import numpy as np
import pandas as pd

from ml.shared_crypto_v6_durable_edge import phase1


class SharedCryptoV6Phase1Test(unittest.TestCase):
    def _panel(self):
        timestamps = pd.date_range(
            "2026-01-01T00:00:00Z", periods=49, freq="1h"
        )
        products = [phase1.BTC] + [f"ALT-{index:02d}" for index in range(11)]
        rows = []
        features = sorted(set(
            phase1.BTC_STATE_FEATURES + phase1.ALT_STATE_FEATURES
        ))
        for product_index, product in enumerate(products):
            base = 100.0 if product == phase1.BTC else 50.0
            for time_index, timestamp in enumerate(timestamps):
                close = base
                if time_index == 48:
                    close = base * (1.02 if product == phase1.BTC else 1.04)
                row = {
                    "timestamp_utc": timestamp,
                    "product_id": product,
                    "close": close,
                    "volume": 100.0 + product_index,
                }
                row.update({feature: 0.01 for feature in features})
                rows.append(row)
        return pd.DataFrame(rows)

    def test_exact_forward_return_does_not_bridge_clock_gaps(self):
        frame = pd.DataFrame({
            "timestamp_utc": pd.to_datetime([
                "2026-01-01T00:00:00Z", "2026-01-02T01:00:00Z"
            ], utc=True),
            "product_id": [phase1.BTC, phase1.BTC],
            "close": [100.0, 110.0],
        })
        result = phase1._attach_exact_forward_return(frame)
        self.assertTrue(np.isnan(result.iloc[0]["forward_return_24h"]))

    def test_builds_daily_cost_aware_direct_action_dataset(self):
        regime, assets, contract = phase1.build_datasets(self._panel())
        self.assertEqual(len(regime), 1)
        self.assertEqual(regime.iloc[0]["timestamp_utc"].hour, 0)
        self.assertEqual(regime.iloc[0]["best_sleeve_net25_24h"], "ALT")
        selected = assets[assets["selected_liquid_top5"]]
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected["product_id"].nunique(), 5)
        self.assertEqual(contract["decision_cadence"], "daily at 00:00 UTC")
        self.assertEqual(
            contract["model_candidates"]["primary"],
            "hist_gradient_boosting_classifier",
        )
        self.assertFalse(contract["alt_sleeve"]["learned_ranker"])

    def test_future_holdout_rows_are_rejected(self):
        panel = self._panel()
        panel.loc[0, "timestamp_utc"] = phase1.HOLDOUT
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase1.build_datasets(panel)

    def test_preregistered_policy_is_persistent_and_broker_safe(self):
        _, _, contract = phase1.build_datasets(self._panel())
        policy = contract["frozen_policy_for_later_simulation"]
        self.assertEqual(policy["minimum_hold_hours"], 24)
        self.assertEqual(policy["confirmation_count"], 2)
        self.assertEqual(policy["primary_round_trip_cost_bps"], 25.0)
        self.assertFalse(policy["leverage"])
        self.assertFalse(policy["shorting"])
        self.assertFalse(policy["derivatives"])


if __name__ == "__main__":
    unittest.main()
