import unittest

import pandas as pd

from ml.shared_crypto_v14_path_utility_rank import phase3


def observed_gate_detail():
    return pd.DataFrame([{
        "research_version": (
            "shared_crypto_v14_path_utility_rank"
        ),
        "gate_median_fold_daily_spearman_ic_gt_005": False,
        "gate_median_fold_positive_ic_day_fraction_gt_52pct": True,
        "gate_median_fold_top3_target_utility_excess_vs_universe_gt_zero": True,
        "gate_positive_fold_top3_target_utility_excess_fraction_gte_75pct": True,
        "passed_gate_count": 3,
        "total_gate_count": 4,
    }])


def observed_gate_result():
    return {
        "target_count": 1,
        "total_predictive_gate_count": 4,
        "passed_predictive_gate_count": 3,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([{
        "research_version": (
            "shared_crypto_v14_path_utility_rank"
        ),
        "fold_count": 8,
        "median_fold_daily_spearman_ic": 0.047782,
        "mean_fold_daily_spearman_ic": 0.044174,
        "median_fold_positive_ic_day_fraction": 0.573133,
        "median_fold_top3_target_utility_excess_vs_universe": 0.005921,
        "mean_fold_top3_target_utility_excess_vs_universe": 0.004219,
        "positive_fold_top3_target_utility_excess_fraction": 0.75,
    }])


def observed_fold_metrics():
    return pd.DataFrame({
        "fold_id": [
            f"fold_{index:02d}"
            for index in range(
                1,
                9,
            )
        ],
        "median_daily_spearman_ic": [
            0.049125,
            -0.043565,
            0.101538,
            -0.020000,
            0.103462,
            0.043462,
            0.072932,
            0.046440,
        ],
        "positive_ic_day_fraction": [
            0.588889,
            0.450000,
            0.633333,
            0.466667,
            0.638889,
            0.555556,
            0.644444,
            0.557377,
        ],
        "mean_top3_target_utility_excess_vs_universe": [
            0.011317,
            -0.017264,
            0.011935,
            0.008039,
            0.016924,
            -0.002404,
            0.001400,
            0.003802,
        ],
    })


class SharedCryptoV14Phase3Test(
    unittest.TestCase
):
    def test_rejects_observed_v14_predictive_result(self):
        disposition, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
                observed_fold_metrics(),
            )
        )

        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V14_PREDICTIVE_HYPOTHESIS",
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
            3,
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

    def test_only_spearman_gate_failed(self):
        _, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
                observed_fold_metrics(),
            )
        )

        self.assertEqual(
            decision[
                "failed_gates"
            ],
            [
                "gate_median_fold_daily_spearman_ic_gt_005"
            ],
        )

    def test_observed_near_miss_and_passes_are_preserved(self):
        _, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
                observed_fold_metrics(),
            )
        )

        metrics = decision[
            "observed_predictive_metrics"
        ]

        self.assertLess(
            metrics[
                "median_fold_daily_spearman_ic"
            ],
            0.05,
        )

        self.assertGreater(
            metrics[
                "median_fold_positive_ic_day_fraction"
            ],
            0.52,
        )

        self.assertGreater(
            metrics[
                "median_fold_top3_target_utility_excess_vs_universe"
            ],
            0.0,
        )

        self.assertGreaterEqual(
            metrics[
                "positive_fold_top3_target_utility_excess_fraction"
            ],
            0.75,
        )

    def test_six_of_eight_folds_have_positive_top3_excess(self):
        _, decision = (
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
                observed_fold_metrics(),
            )
        )

        self.assertEqual(
            decision[
                "observed_fold_count"
            ],
            8,
        )

        self.assertEqual(
            decision[
                "observed_positive_top3_excess_fold_count"
            ],
            6,
        )

    def test_all_four_gates_are_required_to_allow_simulation(self):
        detail = (
            observed_gate_detail()
        )

        for column in (
            phase3.EXPECTED_GATE_COLUMNS
        ):
            detail[column] = True

        detail[
            "passed_gate_count"
        ] = 4

        result = (
            observed_gate_result()
        )

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
                observed_fold_metrics(),
            )
        )

        self.assertEqual(
            decision["status"],
            "QUALIFIED_FOR_POLICY_SIMULATION",
        )
        self.assertTrue(
            decision[
                "portfolio_simulation_allowed"
            ]
        )

    def test_inconsistent_gate_count_fails_closed(self):
        result = (
            observed_gate_result()
        )

        result[
            "passed_predictive_gate_count"
        ] = 4

        with self.assertRaisesRegex(
            RuntimeError,
            "passed predictive gate count",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                result,
                observed_summary(),
                observed_fold_metrics(),
            )

    def test_inconsistent_fold_count_fails_closed(self):
        folds = (
            observed_fold_metrics()
            .iloc[
                :7
            ]
            .copy()
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "eight walk-forward folds",
        ):
            phase3.adjudicate(
                observed_gate_detail(),
                observed_gate_result(),
                observed_summary(),
                folds,
            )


if __name__ == "__main__":
    unittest.main()
