import unittest

import pandas as pd

from ml.shared_crypto_v7_expected_return import phase3


def policy():
    return {
        "minimum_hold_hours": 72,
        "minimum_predicted_net_return": 0.0,
        "probability_confidence_filter": False,
        "probability_margin_filter": False,
        "minimum_cash_weight": 0.50,
        "maximum_gross_crypto_exposure": 0.50,
        "maximum_btc_weight": 0.50,
        "maximum_alt_weight_per_asset": 0.10,
        "maximum_turnover_per_daily_decision": 0.20,
    }


class SharedCryptoV7Phase3Test(unittest.TestCase):
    def test_targets_obey_all_exposure_caps(self):
        assets = ["A", "B", "C", "D", "E"]
        alt = phase3.build_target_weights("ALT", assets, policy())
        btc = phase3.build_target_weights("BTC", assets, policy())
        cash = phase3.build_target_weights(phase3.CASH, assets, policy())

        self.assertAlmostEqual(sum(alt.values()), 1.0)
        self.assertAlmostEqual(alt[phase3.CASH], 0.50)
        self.assertTrue(
            all(alt[asset] == 0.10 for asset in assets)
        )
        self.assertEqual(
            btc,
            {phase3.BTC: 0.50, phase3.CASH: 0.50},
        )
        self.assertEqual(cash, {phase3.CASH: 1.0})

    def test_turnover_cap_is_enforced(self):
        old = {phase3.CASH: 1.0}
        target = {
            phase3.BTC: 0.50,
            phase3.CASH: 0.50,
        }
        adjusted, actual = phase3.cap_turnover(
            old,
            target,
            0.20,
        )
        self.assertAlmostEqual(actual, 0.20)
        self.assertEqual(
            adjusted,
            {
                phase3.BTC: 0.20,
                phase3.CASH: 0.80,
            },
        )

    def test_positive_expected_return_rule_has_no_posthoc_filter(self):
        p = policy()
        self.assertEqual(
            phase3.select_sleeve(0.03, 0.02, p),
            "BTC",
        )
        self.assertEqual(
            phase3.select_sleeve(0.01, 0.04, p),
            "ALT",
        )
        self.assertEqual(
            phase3.select_sleeve(-0.01, -0.02, p),
            phase3.CASH,
        )
        self.assertEqual(
            phase3.select_sleeve(0.0, -0.02, p),
            phase3.CASH,
        )

    def test_evaluation_blocks_do_not_overlap(self):
        timestamps = pd.date_range(
            "2025-01-01T00:00:00Z",
            periods=10,
            freq="24h",
        )
        predictions = pd.DataFrame({
            "timestamp_utc": timestamps,
            "fold_id": ["fold_01"] * 10,
            "x": list(range(10)),
        })
        blocks = phase3.select_non_overlapping_blocks(
            predictions
        )
        self.assertEqual(
            blocks["timestamp_utc"].tolist(),
            [
                timestamps[0],
                timestamps[3],
                timestamps[6],
                timestamps[9],
            ],
        )
        gaps = blocks["timestamp_utc"].diff().dropna()
        self.assertTrue(
            (gaps >= phase3.HORIZON).all()
        )

    def test_simulation_uses_frozen_primary_predictions(self):
        timestamps = pd.date_range(
            "2025-01-01T00:00:00Z",
            periods=3,
            freq="72h",
        )
        predictions = pd.DataFrame({
            "timestamp_utc": timestamps,
            "fold_id": ["fold_01"] * 3,
            "btc_forward_return_72h": [0.10, -0.10, 0.05],
            "alt_forward_return_72h": [0.02, 0.12, -0.03],
            "alt_basket_assets": ["A|B|C|D|E"] * 3,
            phase3.PREDICTED_BTC: [0.03, -0.02, -0.01],
            phase3.PREDICTED_ALT: [0.01, 0.04, -0.02],
        })
        assets = pd.DataFrame([
            {
                "timestamp_utc": timestamp,
                "product_id": asset,
                "forward_return_72h": alt_return,
                "selected_liquid_top5": True,
            }
            for timestamp, alt_return in zip(
                timestamps,
                [0.02, 0.12, -0.03],
            )
            for asset in ["A", "B", "C", "D", "E"]
        ])

        periods, folds = phase3.simulate_candidate(
            predictions,
            assets,
            policy(),
            25.0,
        )
        self.assertEqual(
            periods["policy_state"].tolist(),
            ["BTC", "ALT", phase3.CASH],
        )
        self.assertTrue(
            (periods["turnover"] <= 0.20 + 1e-12).all()
        )
        self.assertEqual(len(folds), 1)

    def test_future_holdout_is_rejected(self):
        frame = pd.DataFrame({
            "timestamp_utc": [phase3.HOLDOUT],
        })
        with self.assertRaisesRegex(
            RuntimeError,
            "future-holdout",
        ):
            phase3.validate_pre_holdout(frame, "test")

    def test_all_preregistered_gates_are_required(self):
        fold_rows = []
        control_rows = []
        for cost in (25.0, 50.0):
            for index in range(5):
                fold_rows.append({
                    "cost_bps": cost,
                    "fold_id": f"fold_{index}",
                    "net_return": (
                        0.30 if index == 0 else 0.05
                    ),
                    "maximum_drawdown": -0.10,
                    "total_turnover": 1.0,
                    "mean_cash_weight": 0.50,
                    "mean_btc_weight": 0.25,
                    "mean_alt_weight": 0.25,
                    "cash_state_fraction": 0.20,
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
            pd.DataFrame(fold_rows),
            pd.DataFrame(control_rows),
            25.0,
            50.0,
        )
        self.assertEqual(
            result["total_gate_count"],
            8,
        )
        self.assertEqual(
            result["status"],
            "DO_NOT_ADVANCE",
        )
        self.assertFalse(
            result[
                "gate_single_fold_profit_concentration_lte_40pct"
            ]
        )


if __name__ == "__main__":
    unittest.main()
