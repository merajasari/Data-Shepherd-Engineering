import unittest

import pandas as pd

from ml.shared_crypto_v5_selective_rank import phase4


def gate_row(**overrides):
    base = {
        "gate_median_fold_net_return_gt_zero": False,
        "gate_positive_fold_fraction_gte_80pct": False,
        "gate_median_excess_vs_always_btc_gt_zero": False,
        "gate_median_excess_vs_shared_v3_gt_zero": True,
        "gate_positive_excess_vs_shared_v3_fraction_gte_80pct": False,
        "gate_worst_maximum_drawdown_gte_minus_20pct": False,
        "gate_single_fold_profit_concentration_lte_40pct": False,
        "gate_survives_50bps_stress": False,
        "passed_gate_count": 1,
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
            "median_fold_net_return": -0.303033,
            "mean_fold_net_return": -0.287534,
            "positive_fold_fraction": 0.0,
            "median_excess_vs_btc": -0.19225,
            "median_excess_vs_shared_v3": 0.09848,
            "positive_excess_vs_shared_v3_fraction": 2 / 3,
            "worst_maximum_drawdown": -0.33783,
            "single_fold_profit_concentration": 1.0,
            "mean_total_turnover": 135.422755,
            "mean_cash_weight": 0.938503,
        },
        {
            "cost_bps": 50.0,
            "fold_count": 6,
            "median_fold_net_return": -0.515331,
            "mean_fold_net_return": -0.49077,
            "positive_fold_fraction": 0.0,
            "median_excess_vs_btc": -0.37530,
            "median_excess_vs_shared_v3": 0.129457,
            "positive_excess_vs_shared_v3_fraction": 1.0,
            "worst_maximum_drawdown": -0.548924,
            "single_fold_profit_concentration": 1.0,
            "mean_total_turnover": 135.398611,
            "mean_cash_weight": 0.938479,
        },
    ])


class SharedCryptoV5Phase4Test(unittest.TestCase):
    def test_rejects_observed_v5_result_and_preserves_all_failed_gates(self):
        disposition, decision = phase4.adjudicate(
            pd.DataFrame([gate_row()]), policy_summary()
        )
        self.assertEqual(decision["status"], "REJECT_CURRENT_V5_POLICY_FAMILY")
        self.assertEqual(decision["qualifying_candidate_count"], 0)
        self.assertEqual(
            len(decision["single_preregistered_policy"]["failed_gates"]), 7
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
        inconsistent = gate_row(passed_gate_count=2)
        with self.assertRaisesRegex(RuntimeError, "passed gate count"):
            phase4.adjudicate(pd.DataFrame([inconsistent]), policy_summary())


if __name__ == "__main__":
    unittest.main()
