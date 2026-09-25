import unittest

import pandas as pd

from ml.shared_crypto_v19_relative_sleeve_router import phase3


def observed_gate_detail():
    return pd.DataFrame([
        {
            "research_version": (
                "shared_crypto_v19_relative_sleeve_router"
            ),
            "gate_median_fold_balanced_accuracy_gt_55pct": True,
            "gate_median_fold_macro_f1_gt_55pct": True,
            "gate_median_fold_mcc_gt_zero": True,
            "gate_median_fold_minimum_class_recall_gt_50pct": False,
            "passed_gate_count": 3,
            "total_gate_count": 4,
        }
    ])


def observed_gate_result():
    return {
        "target_count": 1,
        "class_count": 2,
        "total_predictive_gate_count": 4,
        "passed_predictive_gate_count": 3,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([
        {
            "research_version": (
                "shared_crypto_v19_relative_sleeve_router"
            ),
            "fold_count": 6,
            "median_fold_balanced_accuracy": 0.562273,
            "mean_fold_balanced_accuracy": 0.553469,
            "median_fold_macro_f1": 0.561170,
            "mean_fold_macro_f1": 0.541790,
            "median_fold_mcc": 0.131506,
            "mean_fold_mcc": 0.115746,
            "median_fold_minimum_class_recall": 0.371007,
            "median_fold_btc_recall": 0.752358,
            "median_fold_top3_recall": 0.371007,
            "median_fold_predicted_top3_fraction": 0.302778,
            "median_fold_actual_top3_fraction": 0.411111,
        }
    ])


class SharedCryptoV19Phase3Test(
    unittest.TestCase
):
    def test_rejects_observed_v19_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )

        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V19_RELATIVE_SLEEVE_ROUTER_HYPOTHESIS",
        )
        self.assertFalse(
            decision[
                "offline_portfolio_simulation_allowed"
            ]
        )
        self.assertEqual(
            decision[
                "passed_predictive_gate_count"
            ],
            3,
        )
        self.assertEqual(
            decision[
                "total_predictive_gate_count"
            ],
            4,
        )
        self.assertEqual(
            len(disposition),
            1,
        )

    def test_exact_failed_gate_is_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )

        self.assertEqual(
            decision["failed_gates"],
            [
                "gate_median_fold_minimum_class_recall_gt_50pct"
            ],
        )

    def test_observed_metrics_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )

        metrics = decision[
            "observed_predictive_metrics"
        ]

        self.assertAlmostEqual(
            metrics[
                "median_fold_balanced_accuracy"
            ],
            0.562273,
        )
        self.assertAlmostEqual(
            metrics[
                "median_fold_macro_f1"
            ],
            0.561170,
        )
        self.assertAlmostEqual(
            metrics[
                "median_fold_mcc"
            ],
            0.131506,
        )
        self.assertAlmostEqual(
            metrics[
                "median_fold_minimum_class_recall"
            ],
            0.371007,
        )
        self.assertAlmostEqual(
            metrics[
                "median_fold_btc_recall"
            ],
            0.752358,
        )
        self.assertAlmostEqual(
            metrics[
                "median_fold_top3_recall"
            ],
            0.371007,
        )
        self.assertLess(
            metrics[
                "median_fold_predicted_top3_fraction"
            ],
            metrics[
                "median_fold_actual_top3_fraction"
            ],
        )

    def test_all_four_gates_required_to_allow_offline_simulation(self):
        detail = observed_gate_detail()

        for column in phase3.EXPECTED_GATE_COLUMNS:
            detail[column] = True

        detail["passed_gate_count"] = 4

        result = observed_gate_result()
        result.update({
            "passed_predictive_gate_count": 4,
            "all_predictive_gates_pass": True,
            "status": "ALLOW_OFFLINE_PORTFOLIO_SIMULATION",
        })

        _, decision = phase3.adjudicate(
            detail,
            result,
            observed_summary(),
        )

        self.assertEqual(
            decision["status"],
            "QUALIFIED_FOR_OFFLINE_PORTFOLIO_SIMULATION",
        )
        self.assertTrue(
            decision[
                "offline_portfolio_simulation_allowed"
            ]
        )

    def test_inconsistent_pass_count_fails_closed(self):
        result = observed_gate_result()
        result[
            "passed_predictive_gate_count"
        ] = 2

        with self.assertRaisesRegex(
            RuntimeError,
            "passed predictive gate count",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                result,
                observed_summary(),
            )

    def test_inconsistent_status_fails_closed(self):
        result = observed_gate_result()
        result[
            "status"
        ] = "ALLOW_OFFLINE_PORTFOLIO_SIMULATION"

        with self.assertRaisesRegex(
            RuntimeError,
            "status is inconsistent",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                result,
                observed_summary(),
            )


if __name__ == "__main__":
    unittest.main()
