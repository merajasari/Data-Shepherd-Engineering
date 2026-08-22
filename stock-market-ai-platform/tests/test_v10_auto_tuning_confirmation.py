import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v10 import tuning_confirmation as module


class V10TuningConfirmationTests(unittest.TestCase):
    def test_fixed_winner_contract_matches_registry(self):
        winner = module._winner()

        self.assertEqual(winner["candidate_id"], module.WINNER_ID)
        for key, value in module.EXPECTED_CONFIG.items():
            self.assertEqual(winner["config"][key], value)

    def test_cost_stress_only_reduces_net_returns(self):
        periods = pd.DataFrame(
            {
                "cohort_offset": [0, 0, 1, 1],
                "gross_portfolio_return": [0.03, 0.02, 0.01, 0.04],
                "spy_return": [0.01, 0.01, 0.0, 0.02],
                "turnover": [1.0, 0.5, 1.0, 0.5],
                "entry_timestamp_utc": pd.to_datetime(
                    [
                        "2020-01-02",
                        "2020-02-03",
                        "2020-01-02",
                        "2020-02-03",
                    ],
                    utc=True,
                ),
            }
        )
        ten = module._with_cost(periods, 10)
        thirty = module._with_cost(periods, 30)

        self.assertTrue(
            (
                thirty["net_portfolio_return"]
                < ten["net_portfolio_return"]
            ).all()
        )

    def test_confirmation_fails_closed_without_runner_up(self):
        leaderboard = pd.DataFrame(
            [
                {
                    "candidate_id": module.WINNER_ID,
                    "development_rank": 1,
                    "positive_relative_fold_rate": 1.0,
                    "worst_fold_sharpe": -0.1,
                },
                {
                    "candidate_id": "RUNNER_UP",
                    "development_rank": 2,
                    "positive_relative_fold_rate": 1.0,
                    "worst_fold_sharpe": 1.0,
                },
            ]
        )
        costs = pd.DataFrame(
            [
                {
                    "cost_bps": 10,
                    "mean_relative_return": 0.02,
                    "mean_max_drawdown": -0.10,
                },
                {
                    "cost_bps": 30,
                    "mean_relative_return": 0.01,
                    "mean_max_drawdown": -0.11,
                },
            ]
        )
        years = pd.DataFrame(
            {
                "year": [2020, 2021, 2022],
                "mean_relative_return": [0.01, 0.02, 0.01],
            }
        )
        regimes = pd.DataFrame(
            {
                "regime": ["UP", "DOWN"],
                "mean_relative_return": [0.01, 0.01],
            }
        )

        decision = module.confirmation_decision(
            leaderboard,
            costs,
            years,
            regimes,
        )

        self.assertEqual(decision["status"], "NOT_CONFIRMED")
        self.assertFalse(decision["runner_up_considered"])
        self.assertFalse(decision["challenger_registered"])
        self.assertFalse(decision["candidate_promoted"])
        self.assertFalse(decision["production_modified"])
        self.assertFalse(decision["brokerage_orders"])

    def test_wrong_rank_one_fails_closed(self):
        leaderboard = pd.DataFrame(
            [
                {
                    "candidate_id": module.WINNER_ID,
                    "development_rank": 2,
                    "positive_relative_fold_rate": 1.0,
                    "worst_fold_sharpe": 1.0,
                }
            ]
        )
        empty = pd.DataFrame()
        with self.assertRaisesRegex(RuntimeError, "not rank 1"):
            module.confirmation_decision(
                leaderboard,
                empty,
                empty,
                empty,
            )


if __name__ == "__main__":
    unittest.main()
