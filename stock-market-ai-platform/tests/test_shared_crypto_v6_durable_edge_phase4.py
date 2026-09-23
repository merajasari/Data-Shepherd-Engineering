import unittest

import pandas as pd

from ml.shared_crypto_v6_durable_edge import phase4


def gate_row(**overrides):
    base = {
        "gate_median_fold_net_return_gt_zero": False,
        "gate_positive_fold_fraction_gte_80pct": False,
        "gate_median_excess_vs_always_btc_gt_zero": True,
        "gate_median_excess_vs_shared_v3_gt_zero": True,
        "gate_positive_excess_vs_shared_v3_fraction_gte_80pct": False,
        "gate_worst_maximum_drawdown_gte_minus_20pct": True,
        "gate_single_fold_profit_concentration_lte_40pct": False,
        "gate_survives_50bps_stress": False,
        "passed_gate_count": 3,
        "total_gate_count": 8,
        "status": "DO_NOT_ADVANCE",
    }
    base.update(overrides)
    return base


def policy_summary():
    return pd.DataFrame([
        {
            "cost_bps": 25.0,
            "fold_count": 6,
            "median_fold_net_return": 0.0,
            "mean_fold_net_return": 0.050590,
            "positive_fold_fraction": 1 / 3,
            "median_excess_vs_btc": 0.021045,
            "median_excess_vs_shared_v3": 0.240723,
            "positive_excess_vs_shared_v3_fraction": 2 / 3,
            "worst_maximum_drawdown": -0.138269,
            "single_fold_profit_concentration": 0.795652,
            "mean_total_turnover": 3.761429,
            "mean_cash_weight": 0.920098,
        },
        {
            "cost_bps": 50.0,
            "fold_count": 6,
            "median_fold_net_return": 0.0,
            "mean_fold_net_return": 0.040513,
            "positive_fold_fraction": 1 / 3,
            "median_excess_vs_btc": 0.015685,
            "median_excess_vs_shared_v3": 0.274655,
            "positive_excess_vs_shared_v3_fraction": 5 / 6,
            "worst_maximum_drawdown": -0.142607,
            "single_fold_profit_concentration": 0.805828,
            "mean_total_turnover": 3.761429,
            "mean_cash_weight": 0.920098,
        },
    ])


class SharedCryptoV6Phase4Test(unittest.TestCase):
    def test_rejects_observed_v6_result_and_preserves_all_failed_gates(self):
        disposition, decision = phase4.adjudicate(
            pd.DataFrame([gate_row()]), policy_summary()
        )
        self.assertEqual(decision["status"], "REJECT_CURRENT_V6_POLICY_FAMILY")
        self.assertEqual(decision["qualifying_candidate_count"], 0)
        self.assertEqual(
            len(decision["single_preregistered_policy"]["failed_gates"]), 5
        )
        self.assertIn("failed_gates", disposition.columns)

    def test_qualification_requires_every_gate(self):
        passed = {
            key: True if key.startswith("gate_") else value
            for key, value in gate_row().items()
        }
        passed.update({
            "passed_gate_count": 8,
            "total_gate_count": 8,
            "status": "QUALIFIES_FOR_HUMAN_REVIEW",
        })
        _, decision = phase4.adjudicate(pd.DataFrame([passed]), policy_summary())
        self.assertEqual(decision["status"], "QUALIFIED_FOR_HUMAN_REVIEW")
        self.assertEqual(decision["qualifying_candidate_count"], 1)

    def test_inconsistent_gate_count_fails_closed(self):
        inconsistent = gate_row(passed_gate_count=4)
        with self.assertRaisesRegex(RuntimeError, "passed gate count"):
            phase4.adjudicate(pd.DataFrame([inconsistent]), policy_summary())


if __name__ == "__main__":
    unittest.main()
