import unittest

import pandas as pd

from ml.btc_v1.phase3 import PRIMARY_MODEL_ID, simulate
from ml.btc_v1.phase4 import build_transition_audit


class BTCV1Phase4Tests(unittest.TestCase):
    def sample_inputs(self):
        dates = pd.date_range("2026-01-01", periods=29, freq="D", tz="UTC")
        data = pd.DataFrame({"timestamp_utc": dates, "return_1d": 0.01})
        scores = [0.02] * 14 + [-0.01] * 7 + [0.03] * 8
        pred = pd.DataFrame({
            "timestamp_utc": dates,
            "actual_forward_return_7d": 0.02,
            "predicted_return_7d": scores,
            "model_id": PRIMARY_MODEL_ID,
            "fold_id": "dev_01",
            "split": "development",
        })
        return pred, data

    def test_same_state_scheduled_rebalance_is_not_transition(self):
        pred, _ = self.sample_inputs()
        audit = build_transition_audit(pred)
        self.assertEqual(list(audit["target_state"][:4]), ["btc", "btc", "cash", "btc"])
        self.assertEqual(list(audit["state_changed"][:4]), [True, False, True, True])

    def test_phase3_has_zero_turnover_when_target_state_unchanged(self):
        pred, data = self.sample_inputs()
        audit = build_transition_audit(pred)
        path = simulate(pred, data, "hgb_positive_else_cash", 0.0)
        rb = path[path["is_rebalance"]].reset_index(drop=True)
        audit = audit.reset_index(drop=True)
        self.assertEqual(len(rb), len(audit))
        for i in range(1, len(audit)):
            if not bool(audit.loc[i, "state_changed"]):
                self.assertAlmostEqual(float(rb.loc[i, "turnover"]), 0.0, places=12)
            else:
                self.assertGreater(float(rb.loc[i, "turnover"]), 0.999999)

    def test_transition_count_matches_positive_turnover_after_initial(self):
        pred, data = self.sample_inputs()
        audit = build_transition_audit(pred)
        path = simulate(pred, data, "hgb_positive_else_cash", 0.0)
        rb = path[path["is_rebalance"]].reset_index(drop=True)
        transitions = int(audit.iloc[1:]["state_changed"].sum())
        turnover_events = int((rb.iloc[1:]["turnover"] > 1e-12).sum())
        self.assertEqual(transitions, turnover_events)


if __name__ == "__main__":
    unittest.main()
