import unittest

import pandas as pd

from ml.shared_crypto_v4_net_edge import phase4


def row(**overrides):
    base = {
        "regime_model_id": "hgb",
        "ranking_model_id": "hgb",
        "top_n": 5,
        "cost_bps": 25.0,
        "median_fold_net_return": -0.01,
        "positive_fold_fraction": 1 / 3,
        "median_excess_vs_shared_v3": 0.30,
        "mean_excess_vs_btc": 0.01,
        "worst_maximum_drawdown": -0.30,
        "single_fold_profit_concentration": 0.60,
        "gate_drawdown_vs_shared_v3": True,
        "gate_median_excess_vs_shared_v3": True,
        "gate_net_excess_vs_btc": True,
        "gate_positive_fold_fraction": False,
        "gate_profit_concentration": False,
        "gate_survives_25bps": False,
        "passed_gate_count": 3,
        "total_gate_count": 6,
        "status": "DO_NOT_ADVANCE",
    }
    base.update(overrides)
    return base


class SharedCryptoV4Phase4Test(unittest.TestCase):
    def test_rejects_when_no_candidate_passes_every_gate(self):
        disposition, decision = phase4.adjudicate(pd.DataFrame([row()]))
        self.assertEqual(decision["status"], "REJECT_CURRENT_V4_POLICY_FAMILY")
        self.assertEqual(decision["qualifying_candidate_count"], 0)
        self.assertEqual(len(decision["best_observed_candidate"]["failed_gates"]), 3)
        self.assertIn("failed_gates", disposition.columns)

    def test_qualification_requires_all_preregistered_gates(self):
        passed = row(
            median_fold_net_return=0.01,
            positive_fold_fraction=5 / 6,
            single_fold_profit_concentration=0.40,
            gate_positive_fold_fraction=True,
            gate_profit_concentration=True,
            gate_survives_25bps=True,
            passed_gate_count=6,
            status="QUALIFIES_FOR_HUMAN_REVIEW",
        )
        _, decision = phase4.adjudicate(pd.DataFrame([passed]))
        self.assertEqual(decision["status"], "QUALIFIED_FOR_HUMAN_REVIEW")
        self.assertEqual(decision["qualifying_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
