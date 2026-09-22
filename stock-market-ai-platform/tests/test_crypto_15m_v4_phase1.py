import unittest

import pandas as pd

from ml.crypto_15m_v4 import phase1


class SharedCryptoV4Phase1Test(unittest.TestCase):
    def _panel(self):
        timestamps = [
            pd.Timestamp("2026-08-31T22:00:00Z"),
            pd.Timestamp("2026-08-31T22:15:00Z"),
            pd.Timestamp("2026-08-31T23:00:00Z"),
            pd.Timestamp("2026-09-01T00:00:00Z"),
        ]
        products = [phase1.BTC] + [f"ALT-{index:02d}" for index in range(10)]
        rows = []
        for t_index, timestamp in enumerate(timestamps):
            for p_index, product in enumerate(products):
                row = {
                    "timestamp_utc": timestamp,
                    "product_id": product,
                    "close": 100.0 + p_index,
                    "volume": 1000.0 + p_index,
                    "forward_return_1h": 0.001 * (p_index + 1),
                    "forward_return_4h": 0.002 * (p_index + 1),
                }
                for f_index, column in enumerate(phase1.ASSET_FEATURES):
                    row[column] = 0.01 + 0.0001 * f_index + 0.00001 * p_index + 0.000001 * t_index
                rows.append(row)
        return pd.DataFrame(rows)

    def test_builds_hourly_horizon_aligned_isolated_datasets(self):
        regime, ranking, contract = phase1.build_datasets(self._panel())
        self.assertEqual(regime["timestamp_utc"].dt.minute.unique().tolist(), [0])
        self.assertTrue((regime["timestamp_utc"] < phase1.FUTURE_HOLDOUT_START).all())
        self.assertTrue((ranking["timestamp_utc"] < phase1.FUTURE_HOLDOUT_START).all())
        self.assertEqual(regime["alt_asset_count"].min(), 10)
        self.assertEqual(ranking["product_id"].nunique(), 10)
        self.assertIn("best_sleeve_1h", regime.columns)
        self.assertIn("forward_return_1h", ranking.columns)
        self.assertNotIn("forward_return_1h", contract["regime_feature_columns"])
        self.assertNotIn("forward_return_1h", contract["ranking_feature_columns"])
        self.assertFalse(contract["safety"]["future_holdout_scored"])
        self.assertFalse(contract["safety"]["shared_crypto_v3_modified"])

    def test_future_rows_cannot_change_pre_holdout_outputs(self):
        panel = self._panel()
        before = phase1.build_datasets(panel)
        future = panel[panel["timestamp_utc"] == pd.Timestamp("2026-09-01T00:00:00Z")].copy()
        future["forward_return_1h"] = 999.0
        after = phase1.build_datasets(pd.concat([panel, future], ignore_index=True))
        pd.testing.assert_frame_equal(before[0], after[0])
        pd.testing.assert_frame_equal(before[1], after[1])


if __name__ == "__main__":
    unittest.main()
