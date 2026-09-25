import unittest

import pandas as pd

from ml.shared_crypto_v16_risk_gated_rank import phase3


def observed_gate_detail():
    return pd.DataFrame([
        {
            "research_version": (
                "shared_crypto_v16_risk_gated_rank"
            ),
            "gate_median_fold_spearman_ic_gt_010": False,
            "gate_median_fold_balanced_accuracy_gt_55pct": False,
            "gate_median_fold_mcc_gt_zero": True,
            "gate_median_fold_minimum_class_recall_gt_50pct": False,
            "passed_gate_count": 1,
            "total_gate_count": 4,
        }
    ])


def observed_gate_result():
    return {
        "target_count": 1,
        "diagnostic_class_count": 2,
        "total_predictive_gate_count": 4,
        "passed_predictive_gate_count": 1,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([
        {
            "research_version": (
                "shared_crypto_v16_risk_gated_rank"
            ),
            "fold_count": 8,
            "median_fold_spearman_ic": 0.024487,
            "mean_fold_spearman_ic": 0.032075,
            "median_fold_balanced_accuracy": 0.500845,
            "mean_fold_balanced_accuracy": 0.502704,
            "median_fold_mcc": 0.001301,
            "mean_fold_mcc": 0.001548,
            "median_fold_minimum_class_recall": 0.123525,
            "median_fold_risk_off_recall": 0.888462,
            "median_fold_risk_on_recall": 0.123525,
            "median_fold_mae": 0.124117,
            "median_fold_rmse": 0.157349,
            "median_fold_predicted_positive_fraction": 0.122222,
            "median_fold_actual_positive_fraction": 0.344353,
        }
    ])


class SharedCryptoV16Phase3Test(
    unittest.TestCase
):
    def test_rejects_observed_v16_predictive_result(self):
        disposition, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
            )
        )

        self.assertEqual(
            decision[
                "status"
            ],
            "REJECT_CURRENT_V16_RISK_GATE_HYPOTHESIS",
        )

        self.assertFalse(
            decision[
                "portfolio_simulation_allowed"
            ]
        )

        self.assertEqual(
            decision[
                "passed_predictive_gate_count"
            ],
            1,
        )

        self.assertEqual(
            decision[
                "total_predictive_gate_count"
            ],
            4,
        )

        self.assertEqual(
            len(
                disposition
            ),
            1,
        )

    def test_exact_three_failed_gates_are_preserved(self):
        _, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
            )
        )

        self.assertEqual(
            set(
                decision[
                    "failed_gates"
                ]
            ),
            {
                "gate_median_fold_spearman_ic_gt_010",
                "gate_median_fold_balanced_accuracy_gt_55pct",
                "gate_median_fold_minimum_class_recall_gt_50pct",
            },
        )

    def test_observed_risk_bias_is_preserved(self):
        _, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
            )
        )

        metrics = decision[
            "observed_predictive_metrics"
        ]

        self.assertLess(
            metrics[
                "median_fold_spearman_ic"
            ],
            0.10,
        )

        self.assertLess(
            metrics[
                "median_fold_balanced_accuracy"
            ],
            0.55,
        )

        self.assertGreater(
            metrics[
                "median_fold_mcc"
            ],
            0.0,
        )

        self.assertLess(
            metrics[
                "median_fold_minimum_class_recall"
            ],
            0.50,
        )

        self.assertGreater(
            metrics[
                "median_fold_risk_off_recall"
            ],
            0.80,
        )

        self.assertLess(
            metrics[
                "median_fold_risk_on_recall"
            ],
            0.20,
        )

        self.assertLess(
            metrics[
                "median_fold_predicted_positive_fraction"
            ],
            metrics[
                "median_fold_actual_positive_fraction"
            ],
        )

    def test_all_four_gates_required_to_allow_simulation(self):
        detail = observed_gate_detail()

        for column in (
            phase3.EXPECTED_GATE_COLUMNS
        ):
            detail[
                column
            ] = True

        detail[
            "passed_gate_count"
        ] = 4

        result = observed_gate_result()

        result.update({
            "passed_predictive_gate_count": 4,
            "all_predictive_gates_pass": True,
            "status": "ALLOW_POLICY_SIMULATION",
        })

        _, decision = (
            phase3.adjudicate(
                detail,
                result,
                observed_summary(),
            )
        )

        self.assertEqual(
            decision[
                "status"
            ],
            "QUALIFIED_FOR_POLICY_SIMULATION",
        )

        self.assertTrue(
            decision[
                "portfolio_simulation_allowed"
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
        ] = "ALLOW_POLICY_SIMULATION"

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
