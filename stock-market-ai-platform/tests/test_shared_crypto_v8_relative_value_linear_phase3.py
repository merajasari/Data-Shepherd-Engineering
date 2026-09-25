import unittest

import pandas as pd

from ml.shared_crypto_v8_relative_value_linear import phase3


def gate_detail():
    return pd.DataFrame([
        {
            "target": "alt_excess_vs_btc_net25_72h",
            "gate_median_pearson_correlation_gt_zero": True,
            "gate_median_mae_improvement_vs_train_mean_gt_zero": False,
            "gate_median_sign_accuracy_gt_50pct": True,
            "passed_gate_count": 2,
            "total_gate_count": 3,
        },
        {
            "target": "cash_excess_vs_btc_net25_72h",
            "gate_median_pearson_correlation_gt_zero": True,
            "gate_median_mae_improvement_vs_train_mean_gt_zero": False,
            "gate_median_sign_accuracy_gt_50pct": True,
            "passed_gate_count": 2,
            "total_gate_count": 3,
        },
    ])


def gate_result():
    return {
        "target_count": 2,
        "passed_target_count": 0,
        "total_predictive_gate_count": 6,
        "passed_predictive_gate_count": 4,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def summary():
    return pd.DataFrame([
        {
            "target": "alt_excess_vs_btc_net25_72h",
            "median_pearson_correlation": 0.066208,
            "median_mae_improvement_vs_train_mean": -0.000364,
            "median_sign_accuracy": 0.552382,
        },
        {
            "target": "cash_excess_vs_btc_net25_72h",
            "median_pearson_correlation": 0.029183,
            "median_mae_improvement_vs_train_mean": -0.000709,
            "median_sign_accuracy": 0.536742,
        },
    ])


class SharedCryptoV8Phase3Test(unittest.TestCase):
    def test_rejects_observed_v8_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            gate_detail(),
            gate_result(),
            summary(),
        )
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V8_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            decision["portfolio_simulation_allowed"]
        )
        self.assertEqual(
            decision["passed_predictive_gate_count"],
            4,
        )
        self.assertEqual(
            decision["total_predictive_gate_count"],
            6,
        )
        self.assertEqual(
            decision["passed_target_count"],
            0,
        )
        self.assertEqual(
            len(disposition),
            2,
        )

    def test_each_target_preserves_failed_mae_gate(self):
        _, decision = phase3.adjudicate(
            gate_detail(),
            gate_result(),
            summary(),
        )
        for target in phase3.EXPECTED_TARGETS:
            result = decision["target_results"][target]
            self.assertEqual(
                result["passed_gate_count"],
                2,
            )
            self.assertEqual(
                result["total_gate_count"],
                3,
            )
            self.assertEqual(
                result["failed_gates"],
                [
                    "gate_median_mae_improvement_vs_train_mean_gt_zero"
                ],
            )

    def test_all_six_gates_are_required_to_allow_simulation(self):
        detail = gate_detail()
        for column in (
            "gate_median_pearson_correlation_gt_zero",
            "gate_median_mae_improvement_vs_train_mean_gt_zero",
            "gate_median_sign_accuracy_gt_50pct",
        ):
            detail[column] = True
        detail["passed_gate_count"] = 3

        result = gate_result()
        result.update({
            "passed_target_count": 2,
            "passed_predictive_gate_count": 6,
            "all_predictive_gates_pass": True,
            "status": "ALLOW_POLICY_SIMULATION",
        })

        _, decision = phase3.adjudicate(
            detail,
            result,
            summary(),
        )
        self.assertEqual(
            decision["status"],
            "QUALIFIED_FOR_POLICY_SIMULATION",
        )
        self.assertTrue(
            decision["portfolio_simulation_allowed"]
        )

    def test_inconsistent_pass_count_fails_closed(self):
        result = gate_result()
        result["passed_predictive_gate_count"] = 5
        with self.assertRaisesRegex(
            RuntimeError,
            "passed predictive gate count",
        ):
            phase3.adjudicate(
                gate_detail(),
                result,
                summary(),
            )

    def test_missing_target_fails_closed(self):
        detail = gate_detail().iloc[[0]].copy()
        with self.assertRaisesRegex(
            RuntimeError,
            "targets do not match",
        ):
            phase3.adjudicate(
                detail,
                gate_result(),
                summary(),
            )


if __name__ == "__main__":
    unittest.main()
