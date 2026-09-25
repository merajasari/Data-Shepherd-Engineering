import unittest

import pandas as pd

from ml.shared_crypto_v15_cross_sectional_rank import phase4


def observed_gates():
    return {
        "gate_median_fold_net_return_gt_zero": True,
        "gate_positive_fold_fraction_gte_80pct": False,
        "gate_median_excess_vs_always_btc_gt_zero": False,
        "gate_median_excess_vs_shared_v3_gt_zero": True,
        "gate_positive_excess_vs_shared_v3_fraction_gte_80pct": False,
        "gate_worst_maximum_drawdown_gte_minus_20pct": False,
        "gate_single_fold_profit_concentration_lte_40pct": False,
        "gate_survives_50bps_stress": True,
        "passed_gate_count": 3,
        "total_gate_count": 8,
        "status": "DO_NOT_ADVANCE",
    }


def observed_summary():
    return pd.DataFrame([
        {
            "cost_bps": 25.0,
            "fold_count": 7,
            "median_fold_net_return": 0.155340,
            "mean_fold_net_return": 0.105469,
            "positive_fold_fraction": 0.571429,
            "median_excess_vs_btc": -0.082576,
            "median_excess_vs_shared_v3": 0.084633,
            "positive_excess_vs_shared_v3_fraction": 0.714286,
            "worst_maximum_drawdown": -0.361891,
            "single_fold_profit_concentration": 0.451811,
            "mean_total_turnover": 5.685714,
            "mean_cash_weight": 0.4,
            "mean_crypto_weight": 0.6,
        },
        {
            "cost_bps": 50.0,
            "fold_count": 7,
            "median_fold_net_return": 0.150839,
            "mean_fold_net_return": 0.089804,
            "positive_fold_fraction": 0.571429,
            "median_excess_vs_btc": -0.104055,
            "median_excess_vs_shared_v3": 0.077067,
            "positive_excess_vs_shared_v3_fraction": 0.714286,
            "worst_maximum_drawdown": -0.369332,
            "single_fold_profit_concentration": 0.453971,
            "mean_total_turnover": 5.685714,
            "mean_cash_weight": 0.4,
            "mean_crypto_weight": 0.6,
        },
    ])


class SharedCryptoV15Phase4Test(
    unittest.TestCase
):
    def test_rejects_observed_v15_policy_result(self):
        disposition, decision = (
            phase4.adjudicate(
                observed_gates(),
                observed_summary(),
            )
        )

        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_V15_POLICY_FAMILY",
        )
        self.assertEqual(
            decision[
                "qualifying_candidate_count"
            ],
            0,
        )
        self.assertEqual(
            decision[
                "single_preregistered_policy"
            ][
                "passed_gate_count"
            ],
            3,
        )
        self.assertEqual(
            decision[
                "single_preregistered_policy"
            ][
                "total_gate_count"
            ],
            8,
        )
        self.assertEqual(
            len(
                disposition
            ),
            1,
        )

    def test_exact_five_failed_gates_are_preserved(self):
        _, decision = (
            phase4.adjudicate(
                observed_gates(),
                observed_summary(),
            )
        )

        failed = set(
            decision[
                "single_preregistered_policy"
            ][
                "failed_gates"
            ]
        )

        self.assertEqual(
            failed,
            {
                "gate_positive_fold_fraction_gte_80pct",
                "gate_median_excess_vs_always_btc_gt_zero",
                "gate_positive_excess_vs_shared_v3_fraction_gte_80pct",
                "gate_worst_maximum_drawdown_gte_minus_20pct",
                "gate_single_fold_profit_concentration_lte_40pct",
            },
        )

    def test_observed_portfolio_metrics_are_preserved(self):
        _, decision = (
            phase4.adjudicate(
                observed_gates(),
                observed_summary(),
            )
        )

        policy = decision[
            "single_preregistered_policy"
        ]

        self.assertAlmostEqual(
            policy[
                "median_fold_net_return"
            ],
            0.155340,
        )
        self.assertAlmostEqual(
            policy[
                "positive_fold_fraction"
            ],
            0.571429,
        )
        self.assertAlmostEqual(
            policy[
                "median_excess_vs_always_btc"
            ],
            -0.082576,
        )
        self.assertAlmostEqual(
            policy[
                "median_excess_vs_shared_v3"
            ],
            0.084633,
        )
        self.assertAlmostEqual(
            policy[
                "positive_excess_vs_shared_v3_fraction"
            ],
            0.714286,
        )
        self.assertAlmostEqual(
            policy[
                "worst_maximum_drawdown"
            ],
            -0.361891,
        )
        self.assertAlmostEqual(
            policy[
                "single_fold_profit_concentration"
            ],
            0.451811,
        )
        self.assertAlmostEqual(
            policy[
                "stress_median_fold_net_return"
            ],
            0.150839,
        )

    def test_seven_matched_folds_are_preserved(self):
        _, decision = (
            phase4.adjudicate(
                observed_gates(),
                observed_summary(),
            )
        )

        self.assertEqual(
            decision[
                "single_preregistered_policy"
            ][
                "fold_count"
            ],
            7,
        )

    def test_all_eight_passes_qualifies_for_human_review(self):
        gates = (
            observed_gates()
        )

        for key in list(
            gates
        ):
            if key.startswith(
                "gate_"
            ):
                gates[
                    key
                ] = True

        gates[
            "passed_gate_count"
        ] = 8
        gates[
            "status"
        ] = (
            "QUALIFIES_FOR_HUMAN_REVIEW"
        )

        _, decision = (
            phase4.adjudicate(
                gates,
                observed_summary(),
            )
        )

        self.assertEqual(
            decision[
                "status"
            ],
            "QUALIFIED_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(
            decision[
                "qualifying_candidate_count"
            ],
            1,
        )

    def test_inconsistent_pass_count_fails_closed(self):
        gates = (
            observed_gates()
        )
        gates[
            "passed_gate_count"
        ] = 4

        with self.assertRaisesRegex(
            RuntimeError,
            "passed gate count",
        ):
            phase4.adjudicate(
                gates,
                observed_summary(),
            )

    def test_inconsistent_status_fails_closed(self):
        gates = (
            observed_gates()
        )
        gates[
            "status"
        ] = (
            "QUALIFIES_FOR_HUMAN_REVIEW"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "status is inconsistent",
        ):
            phase4.adjudicate(
                gates,
                observed_summary(),
            )


if __name__ == "__main__":
    unittest.main()
