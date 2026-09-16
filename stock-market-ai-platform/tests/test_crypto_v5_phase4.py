import unittest

import pandas as pd

from ml.crypto_v5.phase4 import common_clock_comparison, validate_selection


class CryptoV5Phase4Test(unittest.TestCase):
    def _metrics(self):
        common = {
            "model_id": "ridge", "horizon_days": 3, "top_n": 3,
            "ending_equity": 1.8, "cumulative_return": .8,
            "annualized_return": .17, "sharpe": .75, "sortino": .77,
            "maximum_drawdown": -.20, "total_turnover": 82.0,
            "cash_fraction": .64,
        }
        return pd.DataFrame([
            {**common, "cost_bps_round_trip": 25.0},
            {**common, "cost_bps_round_trip": 50.0, "ending_equity": 1.5,
             "annualized_return": .11, "sharpe": .5, "maximum_drawdown": -.21},
        ])

    def test_selection_requires_cost_and_v4_safety_gates(self):
        comparison = {"v4": {"ending_equity": .9, "maximum_drawdown": -.7},
                      "v5": {"ending_equity": 1.7, "maximum_drawdown": -.2}}
        evidence = validate_selection(self._metrics(), comparison)
        self.assertTrue(all(evidence["checks"].values()))

    def test_common_clock_uses_frozen_v4_and_selected_v5(self):
        dates = pd.date_range("2023-01-01", periods=4, freq="7D", tz="UTC")
        v4 = pd.DataFrame({"timestamp_utc": dates, "variant": "v4_hgb_allocator",
                           "cost_bps_round_trip": 25.0, "net_period_return_7d": [-.1] * 4,
                           "turnover": [.5] * 4})
        v5 = pd.DataFrame({"timestamp_utc": dates, "model_id": "ridge",
                           "horizon_days": 3, "top_n": 3, "cost_bps_round_trip": 25.0,
                           "net_return": [.05] * 4, "turnover": [.2] * 4})
        result = common_clock_comparison(v4, v5)
        self.assertGreater(result["v5"]["ending_equity"], result["v4"]["ending_equity"])
        self.assertEqual(result["boundary_start_utc"], dates[0].isoformat())


if __name__ == "__main__":
    unittest.main()
