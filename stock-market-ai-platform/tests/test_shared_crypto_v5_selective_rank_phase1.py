import unittest

import pandas as pd

from ml.shared_crypto_v5_selective_rank import phase1


class SharedCryptoV5Phase1Test(unittest.TestCase):
    def _contract(self):
        return {
            "regime_feature_columns": ["btc_return", "breadth"],
            "ranking_feature_columns": ["asset_return", "rank_return"],
        }

    def _frames(self):
        timestamps = pd.to_datetime([
            "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"
        ], utc=True)
        regime = pd.DataFrame({
            "timestamp_utc": timestamps,
            "btc_return": [0.1, 0.2],
            "breadth": [0.4, 0.6],
            "btc_forward_return_1h": [0.01, -0.02],
            "alt_forward_return_1h": [0.02, -0.01],
        })
        ranking = pd.DataFrame({
            "timestamp_utc": [timestamps[0], timestamps[0], timestamps[1], timestamps[1]],
            "product_id": ["A", "B", "A", "B"],
            "asset_return": [0.1, 0.2, 0.3, 0.4],
            "rank_return": [0.5, 1.0, 0.5, 1.0],
            "forward_return_1h": [0.03, 0.00, -0.01, -0.03],
        })
        return regime, ranking

    def test_builds_isolated_risk_and_excess_return_targets(self):
        regime, ranking = self._frames()
        risk, selection, contract = phase1.build_datasets(
            regime, ranking, self._contract()
        )
        self.assertEqual(risk["btc_positive_1h"].tolist(), [1, 0])
        self.assertAlmostEqual(selection.iloc[0]["alt_excess_vs_btc_1h"], 0.02)
        self.assertEqual(len(selection), 4)
        self.assertEqual(contract["frozen_policy_for_later_simulation"]["top_n"], 5)

    def test_future_holdout_rows_are_rejected(self):
        regime, ranking = self._frames()
        regime.loc[0, "timestamp_utc"] = phase1.HOLDOUT
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase1.build_datasets(regime, ranking, self._contract())

    def test_future_rows_cannot_change_pre_holdout_outputs(self):
        regime, ranking = self._frames()
        base_risk, base_selection, _ = phase1.build_datasets(
            regime, ranking, self._contract()
        )
        future_regime = regime.copy()
        future_ranking = ranking.copy()
        future_regime["timestamp_utc"] = future_regime["timestamp_utc"] + pd.DateOffset(years=2)
        future_ranking["timestamp_utc"] = future_ranking["timestamp_utc"] + pd.DateOffset(years=2)
        filtered_regime = pd.concat([regime, future_regime], ignore_index=True)
        filtered_ranking = pd.concat([ranking, future_ranking], ignore_index=True)
        filtered_regime = filtered_regime[filtered_regime["timestamp_utc"] < phase1.HOLDOUT]
        filtered_ranking = filtered_ranking[filtered_ranking["timestamp_utc"] < phase1.HOLDOUT]
        new_risk, new_selection, _ = phase1.build_datasets(
            filtered_regime, filtered_ranking, self._contract()
        )
        pd.testing.assert_frame_equal(base_risk, new_risk)
        pd.testing.assert_frame_equal(base_selection, new_selection)


if __name__ == "__main__":
    unittest.main()
