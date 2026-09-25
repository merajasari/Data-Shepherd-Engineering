import unittest

import pandas as pd

from ml.shared_crypto_v10_regime_ranker import phase3


def observed_gate_detail():
    return pd.DataFrame([{
        "target": "best_sleeve_net25_72h",
        "gate_median_balanced_accuracy_gt_36pct": True,
        "gate_median_macro_f1_gt_36pct": False,
        "gate_median_accuracy_improvement_vs_train_majority_gt_zero": True,
        "gate_median_multiclass_mcc_gt_zero": True,
        "gate_median_minimum_class_recall_gt_20pct": False,
        "passed_gate_count": 3,
        "total_gate_count": 5,
    }])


def observed_gate_result():
    return {
        "target_count": 1,
        "passed_target_count": 0,
        "total_predictive_gate_count": 5,
        "passed_predictive_gate_count": 3,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([{
        "target": "best_sleeve_net25_72h",
        "median_balanced_accuracy": 0.370143,
        "median_macro_f1": 0.339929,
        "median_accuracy_improvement_vs_train_majority": 0.025832,
        "median_multiclass_mcc": 0.079325,
        "median_minimum_class_recall": 0.087603,
        "median_btc_recall": 0.087603,
        "median_alt_recall": 0.363429,
        "median_cash_recall": 0.651380,
        "median_predicted_btc_fraction": 0.107604,
        "median_predicted_alt_fraction": 0.301136,
        "median_predicted_cash_fraction": 0.568119,
    }])


def observed_predictions():
    return pd.DataFrame({
        "predicted_sleeve": (
            ["BTC"] * 97
            + ["ALT"] * 311
            + ["CASH"] * 545
        )
    })


class SharedCryptoV10Phase3Test(unittest.TestCase):
    def test_rejects_observed_v10_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )

        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V10_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            decision["portfolio_simulation_allowed"]
        )
        self.assertEqual(
            decision["passed_predictive_gate_count"],
            3,
        )
        self.assertEqual(
            decision["total_predictive_gate_count"],
            5,
        )
        self.assertEqual(
            decision["passed_target_count"],
            0,
        )
        self.assertEqual(
            len(disposition),
            1,
        )

    def test_failed_macro_f1_and_minimum_recall_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )

        self.assertEqual(
            decision["failed_gates"],
            [
                "gate_median_macro_f1_gt_36pct",
                "gate_median_minimum_class_recall_gt_20pct",
            ],
        )
        self.assertAlmostEqual(
            decision[
                "observed_predictive_metrics"
            ]["median_minimum_class_recall"],
            0.087603,
        )
        self.assertAlmostEqual(
            decision[
                "observed_predictive_metrics"
            ]["median_btc_recall"],
            0.087603,
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
                "BTC": 97,
                "ALT": 311,
                "CASH": 545,
            },
        )
        self.assertEqual(
            decision["observed_prediction_rows"],
            953,
        )

    def test_all_five_gates_are_required_to_allow_simulation(self):
        detail = observed_gate_detail()
        for column in phase3.EXPECTED_GATE_COLUMNS:
            detail[column] = True
        detail["passed_gate_count"] = 5

        result = observed_gate_result()
        result.update({
            "passed_target_count": 1,
            "passed_predictive_gate_count": 5,
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
        result["passed_predictive_gate_count"] = 4

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
        predictions.loc[
            0,
            "predicted_sleeve",
        ] = "UNKNOWN"

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
