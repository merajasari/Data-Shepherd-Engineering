import unittest

import pandas as pd

from ml.shared_crypto_v12_btc_specialist import phase3


def observed_gate_detail():
    return pd.DataFrame([{
        "research_version": "shared_crypto_v12_btc_specialist",
        "gate_stage1_median_balanced_accuracy_gt_52pct": False,
        "gate_stage1_median_mcc_gt_zero": True,
        "gate_stage2_median_balanced_accuracy_gt_52pct": True,
        "gate_stage2_median_mcc_gt_zero": True,
        "gate_combined_median_balanced_accuracy_gt_36pct": True,
        "gate_combined_median_macro_f1_gt_36pct": True,
        "gate_combined_median_accuracy_improvement_vs_train_majority_gt_zero": False,
        "gate_combined_median_multiclass_mcc_gt_zero": True,
        "gate_combined_median_minimum_class_recall_gt_20pct": True,
        "passed_gate_count": 7,
        "total_gate_count": 9,
    }])


def observed_gate_result():
    return {
        "target_count": 3,
        "stage_count": 2,
        "total_predictive_gate_count": 9,
        "passed_predictive_gate_count": 7,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([{
        "research_version": "shared_crypto_v12_btc_specialist",
        "median_stage1_balanced_accuracy": 0.509697,
        "median_stage1_mcc": 0.018746,
        "median_stage2_balanced_accuracy": 0.555379,
        "median_stage2_mcc": 0.127440,
        "median_combined_balanced_accuracy": 0.376914,
        "median_combined_macro_f1": 0.362811,
        "median_combined_accuracy_improvement_vs_train_majority": -0.011364,
        "median_combined_multiclass_mcc": 0.076087,
        "median_combined_minimum_class_recall": 0.252262,
        "median_combined_btc_recall": 0.295150,
        "median_combined_alt_recall": 0.351879,
        "median_combined_cash_recall": 0.493931,
    }])


def observed_predictions():
    return pd.DataFrame({
        "predicted_sleeve": (
            ["BTC"] * 263
            + ["ALT"] * 246
            + ["CASH"] * 444
        )
    })


class SharedCryptoV12Phase3Test(unittest.TestCase):
    def test_rejects_observed_v12_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )

        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V12_PREDICTIVE_HYPOTHESIS",
        )
        self.assertFalse(
            decision["portfolio_simulation_allowed"]
        )
        self.assertEqual(
            decision["passed_predictive_gate_count"],
            7,
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
                "gate_combined_median_accuracy_improvement_vs_train_majority_gt_zero",
            ],
        )

    def test_stage2_and_combined_improvements_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )

        metrics = decision[
            "observed_predictive_metrics"
        ]

        self.assertGreater(
            metrics[
                "median_stage2_balanced_accuracy"
            ],
            0.52,
        )
        self.assertGreater(
            metrics[
                "median_combined_balanced_accuracy"
            ],
            0.36,
        )
        self.assertGreater(
            metrics[
                "median_combined_macro_f1"
            ],
            0.36,
        )
        self.assertGreater(
            metrics[
                "median_combined_minimum_class_recall"
            ],
            0.20,
        )

    def test_observed_prediction_counts_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
            observed_predictions(),
        )

        self.assertEqual(
            decision[
                "observed_prediction_counts"
            ],
            {
                "BTC": 263,
                "ALT": 246,
                "CASH": 444,
            },
        )
        self.assertEqual(
            decision[
                "observed_prediction_rows"
            ],
            953,
        )

    def test_all_nine_gates_are_required_to_allow_simulation(self):
        detail = observed_gate_detail()
        for column in phase3.EXPECTED_GATE_COLUMNS:
            detail[column] = True
        detail[
            "passed_gate_count"
        ] = 9

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
        result[
            "passed_predictive_gate_count"
        ] = 8

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
        predictions = (
            observed_predictions().copy()
        )
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
