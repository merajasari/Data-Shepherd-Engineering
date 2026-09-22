import unittest

import pandas as pd

from ml.shared_crypto_v5_selective_rank import phase3


class SharedCryptoV5Phase3Test(unittest.TestCase):
    def test_inverse_volatility_target_respects_all_exposure_caps(self):
        assets = ["A", "B", "C", "D", "E"]
        volatility = {"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.04, "E": 0.05}
        weights = phase3.build_target_weights(
            "ALT", assets, volatility, 0.60, 0.60, 0.15
        )
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertGreaterEqual(weights[phase3.CASH], 0.40)
        self.assertLessEqual(max(weights[asset] for asset in assets), 0.15)
        self.assertAlmostEqual(sum(weights[asset] for asset in assets), 0.60)

    def test_btc_and_cash_targets_obey_frozen_policy(self):
        btc = phase3.build_target_weights("BTC", [], {}, 0.60, 0.60, 0.15)
        cash = phase3.build_target_weights(phase3.CASH, [], {}, 0.60, 0.60, 0.15)
        self.assertEqual(btc, {phase3.BTC: 0.60, phase3.CASH: 0.40})
        self.assertEqual(cash, {phase3.CASH: 1.0})

    def test_turnover_cap_is_enforced(self):
        old = {phase3.CASH: 1.0}
        target = {"A": 0.15, "B": 0.15, "C": 0.15, "D": 0.15,
                  phase3.CASH: 0.40}
        adjusted, actual = phase3.cap_turnover(old, target, 0.25)
        self.assertAlmostEqual(actual, 0.25)
        self.assertAlmostEqual(sum(adjusted.values()), 1.0)

    def test_alt_selection_requires_full_top_five_and_retains_incumbent(self):
        frame = pd.DataFrame({
            "product_id": ["A", "B", "C", "D", "E", "F"],
            phase3.PRIMARY_LOWER_BOUND_COLUMN: [0.010, 0.009, 0.008, 0.007, 0.006, 0.0055],
            phase3.PRIMARY_DOWNSIDE_COLUMN: [0.10] * 6,
        })
        chosen = phase3.select_alt_assets(
            frame, {"F"}, 5, 0.003, 0.35, 0.001
        )
        self.assertEqual(len(chosen), 5)
        self.assertIn("F", chosen)
        too_few = phase3.select_alt_assets(
            frame.head(4), set(), 5, 0.003, 0.35, 0.001
        )
        self.assertEqual(too_few, [])

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({"timestamp_utc": [phase3.HOLDOUT]})
        with self.assertRaisesRegex(RuntimeError, "future-holdout"):
            phase3.validate_pre_holdout(frame, "test")

    def test_all_preregistered_gates_are_required(self):
        fold_rows = []
        control_rows = []
        for cost in (25.0, 50.0):
            for index in range(5):
                fold_rows.append({
                    "cost_bps": cost,
                    "fold_id": f"fold_{index}",
                    "net_return": 0.30 if index == 0 else 0.05,
                    "maximum_drawdown": -0.10,
                    "total_turnover": 1.0,
                    "mean_cash_weight": 0.50,
                })
                control_rows.append({
                    "cost_bps": cost,
                    "fold_id": f"fold_{index}",
                    "shared_v3_net_return": 0.01,
                    "shared_v3_maximum_drawdown": -0.15,
                    "btc_return": 0.02,
                    "btc_maximum_drawdown": -0.20,
                })
        _, result = phase3.summarize_and_gate(
            pd.DataFrame(fold_rows), pd.DataFrame(control_rows), 25.0, 50.0
        )
        self.assertEqual(result["total_gate_count"], 8)
        self.assertEqual(result["status"], "DO_NOT_ADVANCE")
        self.assertFalse(result["gate_single_fold_profit_concentration_lte_40pct"])


if __name__ == "__main__":
    unittest.main()
