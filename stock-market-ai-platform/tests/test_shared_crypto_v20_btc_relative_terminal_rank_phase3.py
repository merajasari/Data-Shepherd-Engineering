import unittest

import pandas as pd

from ml.shared_crypto_v20_btc_relative_terminal_rank import phase3


def observed_gate_detail():
    return pd.DataFrame([
        {
            "research_version": (
                "shared_crypto_v20_btc_relative_terminal_rank"
            ),
            "gate_median_fold_daily_spearman_ic_gt_005": True,
            "gate_median_fold_positive_ic_day_fraction_gt_52pct": True,
            "gate_median_fold_top3_btc_relative_terminal_excess_gt_zero": False,
            "gate_positive_fold_top3_btc_relative_terminal_excess_fraction_gte_75pct": False,
            "gate_median_fold_top3_daily_btc_win_fraction_gt_50pct": False,
            "passed_gate_count": 2,
            "total_gate_count": 5,
        }
    ])


def observed_gate_result():
    return {
        "target_count": 1,
        "total_predictive_gate_count": 5,
        "passed_predictive_gate_count": 2,
        "all_predictive_gates_pass": False,
        "status": "STOP_BEFORE_PORTFOLIO_SIMULATION",
    }


def observed_summary():
    return pd.DataFrame([
        {
            "research_version": (
                "shared_crypto_v20_btc_relative_terminal_rank"
            ),
            "fold_count": 8,
            "median_fold_daily_spearman_ic": 0.084084,
            "mean_fold_daily_spearman_ic": 0.090953,
            "median_fold_positive_ic_day_fraction": 0.644444,
            "median_fold_top3_btc_relative_terminal_excess": -0.002034,
            "mean_fold_top3_btc_relative_terminal_excess": -0.001126,
            "positive_fold_top3_btc_relative_terminal_excess_fraction": 0.25,
            "median_fold_top3_daily_btc_win_fraction": 0.408333,
        }
    ])


class SharedCryptoV20Phase3Test(
    unittest.TestCase
):
    def test_rejects_observed_v20_predictive_result(self):
        disposition, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )

        self.assertEqual(
            decision[
                "status"
            ],
            "REJECT_CURRENT_V20_BTC_RELATIVE_TERMINAL_RANK_HYPOTHESIS",
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
            2,
        )

        self.assertEqual(
            decision[
                "total_predictive_gate_count"
            ],
            5,
        )

        self.assertEqual(
            len(
                disposition
            ),
            1,
        )

    def test_exact_three_failed_gates_are_preserved(self):
        _, decision = phase3.adjudicate(
            observed_gate_detail(),
            observed_gate_result(),
            observed_summary(),
        )

        self.assertEqual(
            set(
                decision[
                    "failed_gates"
                ]
            ),
            {
                "gate_median_fold_top3_btc_relative_terminal_excess_gt_zero",
                "gate_positive_fold_top3_btc_relative_terminal_excess_fraction_gte_75pct",
                "gate_median_fold_top3_daily_btc_win_fraction_gt_50pct",
            },
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
                "median_fold_daily_spearman_ic"
            ],
            0.084084,
        )

        self.assertAlmostEqual(
            metrics[
                "median_fold_positive_ic_day_fraction"
            ],
            0.644444,
        )

        self.assertAlmostEqual(
            metrics[
                "median_fold_top3_btc_relative_terminal_excess"
            ],
            -0.002034,
        )

        self.assertAlmostEqual(
            metrics[
                "positive_fold_top3_btc_relative_terminal_excess_fraction"
            ],
            0.25,
        )

        self.assertAlmostEqual(
            metrics[
                "median_fold_top3_daily_btc_win_fraction"
            ],
            0.408333,
        )

    def test_all_five_gates_required_to_allow_offline_simulation(self):
        detail = observed_gate_detail()

        for column in (
            phase3.EXPECTED_GATE_COLUMNS
        ):
            detail[
                column
            ] = True

        detail[
            "passed_gate_count"
        ] = 5

        result = observed_gate_result()

        result.update({
            "passed_predictive_gate_count": 5,
            "all_predictive_gates_pass": True,
            "status": "ALLOW_OFFLINE_PORTFOLIO_SIMULATION",
        })

        _, decision = phase3.adjudicate(
            detail,
            result,
            observed_summary(),
        )

        self.assertEqual(
            decision[
                "status"
            ],
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
        ] = 3

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
