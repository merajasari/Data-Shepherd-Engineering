import unittest

import pandas as pd

from ml.shared_crypto_v7_expected_return import phase4


def gate_row(**overrides):
    base = {
        "gate_median_fold_net_return_gt_zero": False,
        "gate_positive_fold_fraction_gte_80pct": False,
        "gate_median_excess_vs_always_btc_gt_zero": False,
        "gate_median_excess_vs_shared_v3_gt_zero": True,
        "gate_positive_excess_vs_shared_v3_fraction_gte_80pct": True,
        "gate_worst_maximum_drawdown_gte_minus_20pct": False,
        "gate_single_fold_profit_concentration_lte_40pct": False,
        "gate_survives_50bps_stress": False,
        "passed_gate_count": 2,
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
            "median_fold_net_return": -0.011580,
            "mean_fold_net_return": 0.022809,
            "positive_fold_fraction": 0.50,
            "median_excess_vs_btc": -0.037011,
            "median_excess_vs_shared_v3": 0.193011,
            "positive_excess_vs_shared_v3_fraction": 5.0 / 6.0,
            "worst_maximum_drawdown": -0.218263,
            "single_fold_profit_concentration": 0.735969,
            "mean_total_turnover": 9.41684,
            "mean_cash_weight": 0.656353,
            "mean_btc_weight": 0.208277,
            "mean_alt_weight": 0.135369,
            "mean_cash_state_fraction": 0.283333,
        },
        {
            "cost_bps": 50.0,
            "fold_count": 6,
            "median_fold_net_return": -0.030144,
            "mean_fold_net_return": -0.001081,
            "positive_fold_fraction": 0.50,
            "median_excess_vs_btc": -0.063787,
            "median_excess_vs_shared_v3": 0.182431,
            "positive_excess_vs_shared_v3_fraction": 5.0 / 6.0,
            "worst_maximum_drawdown": -0.228045,
            "single_fold_profit_concentration": 0.790937,
            "mean_total_turnover": 9.41684,
            "mean_cash_weight": 0.656353,
            "mean_btc_weight": 0.208277,
            "mean_alt_weight": 0.135369,
            "mean_cash_state_fraction": 0.283333,
        },
    ])


class SharedCryptoV7Phase4Test(unittest.TestCase):
    def test_rejects_observed_v7_result_and_preserves_failed_gates(self):
        disposition, decision = phase4.adjudicate(
            pd.DataFrame([gate_row()]),
            policy_summary(),
        )
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V7_POLICY_FAMILY",
        )
        self.assertEqual(
            decision["qualifying_candidate_count"],
            0,
        )
        self.assertEqual(
            len(
                decision[
                    "single_preregistered_policy"
                ]["failed_gates"]
            ),
            6,
        )
        self.assertIn(
            "failed_gates",
            disposition.columns,
        )

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
        _, decision = phase4.adjudicate(
            pd.DataFrame([passed]),
            policy_summary(),
        )
        self.assertEqual(
            decision["status"],
            "QUALIFIED_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(
            decision["qualifying_candidate_count"],
            1,
        )

    def test_inconsistent_gate_count_fails_closed(self):
        inconsistent = gate_row(
            passed_gate_count=3
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "passed gate count",
        ):
            phase4.adjudicate(
                pd.DataFrame([inconsistent]),
                policy_summary(),
            )

    def test_primary_summary_preserves_observed_v7_failure(self):
        _, decision = phase4.adjudicate(
            pd.DataFrame([gate_row()]),
            policy_summary(),
        )
        result = decision[
            "single_preregistered_policy"
        ]
        self.assertAlmostEqual(
            result["median_fold_net_return"],
            -0.011580,
        )
        self.assertAlmostEqual(
            result["positive_fold_fraction"],
            0.50,
        )
        self.assertAlmostEqual(
            result["median_excess_vs_always_btc"],
            -0.037011,
        )
        self.assertAlmostEqual(
            result["worst_maximum_drawdown"],
            -0.218263,
        )
        self.assertAlmostEqual(
            result["single_fold_profit_concentration"],
            0.735969,
        )
        self.assertAlmostEqual(
            result["stress_median_fold_net_return"],
            -0.030144,
        )


if __name__ == "__main__":
    unittest.main()
