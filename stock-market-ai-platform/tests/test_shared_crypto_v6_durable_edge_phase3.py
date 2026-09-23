import unittest

import pandas as pd

from ml.shared_crypto_v6_durable_edge import phase3


def policy():
    return {
        "minimum_hold_hours": 24,
        "confirmation_count": 2,
        "minimum_predicted_probability": 0.55,
        "minimum_probability_margin": 0.10,
        "minimum_cash_weight": 0.40,
        "maximum_gross_crypto_exposure": 0.60,
        "maximum_btc_weight": 0.60,
        "maximum_alt_weight": 0.12,
        "maximum_turnover_per_daily_decision": 0.30,
    }


class SharedCryptoV6Phase3Test(unittest.TestCase):
    def test_targets_obey_all_exposure_caps(self):
        assets = ["A", "B", "C", "D", "E"]
        alt = phase3.build_target_weights("ALT", assets, policy())
        btc = phase3.build_target_weights("BTC", assets, policy())
        cash = phase3.build_target_weights(phase3.CASH, assets, policy())
        self.assertAlmostEqual(sum(alt.values()), 1.0)
        self.assertAlmostEqual(alt[phase3.CASH], 0.40)
        self.assertTrue(all(alt[asset] == 0.12 for asset in assets))
        self.assertEqual(btc, {phase3.BTC: 0.60, phase3.CASH: 0.40})
        self.assertEqual(cash, {phase3.CASH: 1.0})

    def test_turnover_cap_is_enforced(self):
        old = {phase3.CASH: 1.0}
        target = {phase3.BTC: 0.60, phase3.CASH: 0.40}
        adjusted, actual = phase3.cap_turnover(old, target, 0.30)
        self.assertAlmostEqual(actual, 0.30)
        self.assertEqual(adjusted, {phase3.BTC: 0.30, phase3.CASH: 0.70})

    def test_policy_requires_two_qualified_confirmations(self):
        timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=4, freq="24h")
        predictions = pd.DataFrame({
            "timestamp_utc": timestamps,
            "fold_id": ["fold_01"] * 4,
            "btc_forward_return_24h": [0.01] * 4,
            "alt_forward_return_24h": [0.02] * 4,
            "alt_basket_assets": ["A|B|C|D|E"] * 4,
            phase3.PREDICTED_LABEL: ["BTC", "BTC", "ALT", "ALT"],
            phase3.CONFIDENCE: [0.70, 0.70, 0.70, 0.70],
            phase3.MARGIN: [0.20, 0.20, 0.20, 0.20],
        })
        assets = pd.DataFrame([
            {
                "timestamp_utc": timestamp,
                "product_id": asset,
                "forward_return_24h": 0.02,
                "selected_liquid_top5": True,
            }
            for timestamp in timestamps for asset in ["A", "B", "C", "D", "E"]
        ])
        periods, _ = phase3.simulate_candidate(predictions, assets, policy(), 25.0)
        self.assertEqual(periods["policy_state"].tolist(), ["CASH", "BTC", "BTC", "ALT"])
        self.assertTrue((periods["turnover"] <= 0.30 + 1e-12).all())

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
