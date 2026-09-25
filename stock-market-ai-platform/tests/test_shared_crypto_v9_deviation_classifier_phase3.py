import unittest

import pandas as pd

from ml.shared_crypto_v9_deviation_classifier import phase3


def observed_gate_detail():
    return pd.DataFrame([
        {
            "target": "alt_beats_btc_net25_72h",
            "gate_median_roc_auc_gt_52pct": False,
            "gate_median_balanced_accuracy_gt_52pct": True,
            "gate_median_brier_improvement_gt_zero": False,
            "gate_median_log_loss_improvement_gt_zero": False,
            "passed_gate_count": 1,
            "total_gate_count": 4,
        },
        {
            "target": "cash_beats_btc_net25_72h",
            "gate_median_roc_auc_gt_52pct": True,
            "gate_median_balanced_accuracy_gt_52pct": False,
            "gate_median_brier_improvement_gt_zero": False,
            "gate_median_log_loss_improvement_gt_zero": False,
            "passed_gate_count": 1,
            "total_gate_count": 4,
        },
    ])


def observed_gate_result():
    return {
        "target_count": 2,
        "passed_target_count": 0,
        "total_predictive_gate_count": 8,
        "passed_predictive_gate_count": 2,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([
        {
            "target": "alt_beats_btc_net25_72h",
            "median_roc_auc": 0.517529,
            "median_balanced_accuracy": 0.528956,
            "median_brier_improvement_vs_train_prevalence": -0.002936,
            "median_log_loss_improvement_vs_train_prevalence": -0.006107,
        },
        {
            "target": "cash_beats_btc_net25_72h",
            "median_roc_auc": 0.538957,
            "median_balanced_accuracy": 0.494588,
            "median_brier_improvement_vs_train_prevalence": -0.000851,
            "median_log_loss_improvement_vs_train_prevalence": -0.002333,
        },
    ])


class SharedCryptoV9Phase3Test(unittest.TestCase):
    def test_rejects_observed_v9_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V9_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            decision["portfolio_simulation_allowed"]
        )
        self.assertEqual(
            decision["passed_predictive_gate_count"],
            2,
        )
        self.assertEqual(
            decision["total_predictive_gate_count"],
            8,
        )
        self.assertEqual(
            decision["passed_target_count"],
            0,
        )
        self.assertEqual(
            len(disposition),
            2,
        )

    def test_observed_failed_gates_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )

        alt = decision["target_results"][
            "alt_beats_btc_net25_72h"
        ]
        cash = decision["target_results"][
            "cash_beats_btc_net25_72h"
        ]

        self.assertEqual(
            alt["passed_gate_count"],
            1,
        )
        self.assertEqual(
            cash["passed_gate_count"],
            1,
        )
        self.assertIn(
            "gate_median_roc_auc_gt_52pct",
            alt["failed_gates"],
        )
        self.assertIn(
            "gate_median_balanced_accuracy_gt_52pct",
            cash["failed_gates"],
        )
        self.assertIn(
            "gate_median_brier_improvement_gt_zero",
            alt["failed_gates"],
        )
        self.assertIn(
            "gate_median_log_loss_improvement_gt_zero",
            cash["failed_gates"],
        )

    def test_all_eight_gates_are_required_to_allow_simulation(self):
        detail = observed_gate_detail()
        for column in phase3.EXPECTED_GATE_COLUMNS:
            detail[column] = True
        detail["passed_gate_count"] = 4

        result = observed_gate_result()
        result.update({
            "passed_target_count": 2,
            "passed_predictive_gate_count": 8,
            "all_predictive_gates_pass": True,
            "status": "ALLOW_POLICY_SIMULATION",
        })

        _, decision = phase3.adjudicate(
            detail,
            result,
            observed_summary(),
        )

        self.assertEqual(
            decision["status"],
            "QUALIFIED_FOR_POLICY_SIMULATION",
        )
        self.assertTrue(
            decision["portfolio_simulation_allowed"]
        )

    def test_inconsistent_gate_count_fails_closed(self):
        result = observed_gate_result()
        result["passed_predictive_gate_count"] = 3

        with self.assertRaisesRegex(
            RuntimeError,
            "passed predictive gate count",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                result,
                observed_summary(),
            )

    def test_missing_target_fails_closed(self):
        detail = observed_gate_detail().iloc[[0]].copy()

        with self.assertRaisesRegex(
            RuntimeError,
            "targets do not match",
        ):
            phase3.adjudicate(
                detail,
                observed_gate_result(),
                observed_summary(),
            )


if __name__ == "__main__":
    unittest.main()
