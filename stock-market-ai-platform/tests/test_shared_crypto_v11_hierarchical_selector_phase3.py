import unittest

import pandas as pd

from ml.shared_crypto_v11_hierarchical_selector import phase3


def observed_gate_detail():
    return pd.DataFrame([{
        "research_version": "shared_crypto_v11_hierarchical_selector",
        "gate_stage1_median_balanced_accuracy_gt_52pct": False,
        "gate_stage1_median_mcc_gt_zero": True,
        "gate_stage2_median_balanced_accuracy_gt_52pct": True,
        "gate_stage2_median_mcc_gt_zero": True,
        "gate_combined_median_balanced_accuracy_gt_36pct": False,
        "gate_combined_median_macro_f1_gt_36pct": False,
        "gate_combined_median_accuracy_improvement_vs_train_majority_gt_zero": False,
        "gate_combined_median_multiclass_mcc_gt_zero": True,
        "gate_combined_median_minimum_class_recall_gt_20pct": True,
        "passed_gate_count": 5,
        "total_gate_count": 9,
    }])


def observed_gate_result():
    return {
        "target_count": 3,
        "stage_count": 2,
        "total_predictive_gate_count": 9,
        "passed_predictive_gate_count": 5,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([{
        "research_version": "shared_crypto_v11_hierarchical_selector",
        "median_stage1_balanced_accuracy": 0.508498,
        "median_stage1_mcc": 0.015160,
        "median_stage2_balanced_accuracy": 0.555379,
        "median_stage2_mcc": 0.127440,
        "median_combined_balanced_accuracy": 0.353786,
        "median_combined_macro_f1": 0.342449,
        "median_combined_accuracy_improvement_vs_train_majority": -0.021054,
        "median_combined_multiclass_mcc": 0.043303,
        "median_combined_minimum_class_recall": 0.282258,
        "median_combined_btc_recall": 0.423481,
        "median_combined_alt_recall": 0.300078,
        "median_combined_cash_recall": 0.349488,
    }])


def observed_predictions():
    return pd.DataFrame({
        "predicted_sleeve": (
            ["BTC"] * 422
            + ["ALT"] * 209
            + ["CASH"] * 322
        )
    })


class SharedCryptoV11Phase3Test(unittest.TestCase):
    def test_rejects_observed_v11_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V11_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            decision["portfolio_simulation_allowed"]
        )
        self.assertEqual(
            decision["passed_predictive_gate_count"],
            5,
        )
        self.assertEqual(
            decision["total_predictive_gate_count"],
            9,
        )
        self.assertEqual(
            len(disposition),
            1,
        )

    def test_observed_failed_gates_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )
        self.assertEqual(
            decision["failed_gates"],
            [
                "gate_stage1_median_balanced_accuracy_gt_52pct",
                "gate_combined_median_balanced_accuracy_gt_36pct",
                "gate_combined_median_macro_f1_gt_36pct",
                "gate_combined_median_accuracy_improvement_vs_train_majority_gt_zero",
            ],
        )

    def test_stage2_success_and_btc_recall_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )
        metrics = decision["observed_predictive_metrics"]
        self.assertGreater(
            metrics["median_stage2_balanced_accuracy"],
            0.52,
        )
        self.assertGreater(
            metrics["median_stage2_mcc"],
            0.0,
        )
        self.assertAlmostEqual(
            metrics["median_combined_btc_recall"],
            0.423481,
        )

    def test_observed_prediction_counts_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )
        self.assertEqual(
            decision["observed_prediction_counts"],
            {
                "BTC": 422,
                "ALT": 209,
                "CASH": 322,
            },
        )
        self.assertEqual(
            decision["observed_prediction_rows"],
            953,
        )

    def test_all_nine_gates_are_required_to_allow_simulation(self):
        detail = observed_gate_detail()
        for column in phase3.EXPECTED_GATE_COLUMNS:
            detail[column] = True
        detail["passed_gate_count"] = 9

        result = observed_gate_result()
        result.update({
            "passed_predictive_gate_count": 9,
            "all_predictive_gates_pass": True,
            "status": "ALLOW_POLICY_SIMULATION",
        })

        _, decision = phase3.adjudicate(
            detail,
            result,
            observed_summary(),
            observed_predictions(),
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
        result["passed_predictive_gate_count"] = 6

        with self.assertRaisesRegex(
            RuntimeError,
            "passed predictive gate count",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                result,
                observed_summary(),
                observed_predictions(),
            )

    def test_unexpected_prediction_class_fails_closed(self):
        predictions = observed_predictions().copy()
        predictions.loc[0, "predicted_sleeve"] = "UNKNOWN"

        with self.assertRaisesRegex(
            RuntimeError,
            "unexpected sleeve class",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
                predictions,
            )


if __name__ == "__main__":
    unittest.main()
