import unittest

import pandas as pd

from ml.btc_v1.phase3 import (
    PRIMARY_MODEL_ID,
    REBALANCE_DAYS,
    SIGNAL_THRESHOLD,
    rebalance_dates,
    simulate,
)


class BTCV1Phase3Tests(unittest.TestCase):
    def sample_inputs(self):
        dates = pd.date_range("2026-01-01", periods=22, freq="D", tz="UTC")
        data = pd.DataFrame({"timestamp_utc": dates, "return_1d": 0.01})
        pred = pd.DataFrame({
            "timestamp_utc": dates,
            "actual_forward_return_7d": 0.02,
            "predicted_return_7d": [0.02] * 7 + [-0.01] * 7 + [0.03] * 8,
            "model_id": PRIMARY_MODEL_ID,
            "fold_id": "dev_01",
            "split": "development",
        })
        return pred, data

    def test_rebalance_schedule_is_seven_days(self):
        pred, _ = self.sample_inputs()
        dates = rebalance_dates(pred["timestamp_utc"])
        self.assertEqual(REBALANCE_DAYS, 7)
        self.assertEqual(list(dates[:4]), [
            pd.Timestamp("2026-01-01", tz="UTC"),
            pd.Timestamp("2026-01-08", tz="UTC"),
            pd.Timestamp("2026-01-15", tz="UTC"),
            pd.Timestamp("2026-01-22", tz="UTC"),
        ])

    def test_primary_rule_moves_between_btc_and_cash(self):
        pred, data = self.sample_inputs()
        path = simulate(pred, data, "hgb_positive_else_cash", 0.0)
        rebalances = path[path["is_rebalance"]]
        self.assertEqual(SIGNAL_THRESHOLD, 0.0)
        self.assertEqual(rebalances.iloc[0]["btc_exposure"], 1.0)
        self.assertEqual(rebalances.iloc[1]["btc_exposure"], 0.0)
        self.assertEqual(rebalances.iloc[2]["btc_exposure"], 1.0)

    def test_cash_has_constant_equity_without_cost(self):
        pred, data = self.sample_inputs()
        path = simulate(pred, data, "cash", 0.0)
        self.assertTrue((path["equity"] == 1.0).all())
        self.assertTrue((path["btc_exposure"] == 0.0).all())

    def test_buy_and_hold_is_fully_exposed_after_first_rebalance(self):
        pred, data = self.sample_inputs()
        path = simulate(pred, data, "btc_buy_and_hold", 0.0)
        self.assertEqual(path.iloc[0]["btc_exposure"], 1.0)
        self.assertTrue((path.iloc[1:]["btc_exposure"] > 0.999999).all())
        self.assertGreater(path.iloc[-1]["equity"], 1.0)


if __name__ == "__main__":
    unittest.main()
