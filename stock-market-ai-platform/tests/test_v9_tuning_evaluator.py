import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v9 import tuning_evaluator as module


class V9TuningEvaluatorTests(unittest.TestCase):
    def test_folds_are_chronological_and_purged(self):
        dates = pd.bdate_range(
            "2016-01-01",
            periods=2000,
            tz="UTC",
        )
        folds = module.make_folds(dates)

        self.assertEqual(len(folds), 5)
        for fold in folds:
            self.assertEqual(
                fold["purge_sessions"],
                module.PURGE_SESSIONS,
            )
            self.assertLess(
                fold["training_end_utc"],
                fold["purge_start_utc"],
            )
            self.assertLess(
                fold["purge_end_utc"],
                fold["validation_start_utc"],
            )
            self.assertLess(
                fold["validation_end_utc"],
                module.FUTURE_HOLDOUT_START_UTC,
            )

        for left, right in zip(folds, folds[1:]):
            self.assertLess(
                left["validation_end_utc"],
                right["validation_start_utc"],
            )

    def test_turnover_respects_candidate_top_n(self):
        self.assertEqual(
            module._transition_notional(None, ["A", "B", "C", "D", "E"], 5),
            1.0,
        )
        turnover = module._transition_notional(
            ["A", "B", "C", "D", "E"],
            ["A", "B", "C", "D", "F"],
            5,
        )
        self.assertAlmostEqual(turnover, 0.4)

    def test_leaderboard_uses_all_folds_and_is_development_only(self):
        rows = []
        for candidate, sharpe in [("BETTER", 1.2), ("WORSE", 0.2)]:
            for fold_id in range(1, 6):
                rows.append(
                    {
                        "candidate_id": candidate,
                        "fold_id": fold_id,
                        "score_id": "equal_weight_rank_blend",
                        "top_n": 10,
                        "holding_sessions": 5,
                        "mean_cagr": sharpe / 10,
                        "mean_sharpe": sharpe,
                        "mean_sortino": sharpe,
                        "mean_max_drawdown": -0.10,
                        "mean_calmar": sharpe,
                        "annualized_relative_return": sharpe / 20,
                        "relative_hit_rate": 0.55,
                        "mean_turnover": 0.25,
                    }
                )

        leaderboard = module.build_leaderboard(pd.DataFrame(rows))

        self.assertEqual(leaderboard.iloc[0]["candidate_id"], "BETTER")
        self.assertEqual(leaderboard.iloc[0]["development_rank"], 1)
        self.assertTrue(
            (
                leaderboard["status"]
                == "EVALUATED_DEVELOPMENT_ONLY"
            ).all()
        )

    def test_missing_fold_fails_closed(self):
        rows = pd.DataFrame(
            {
                "candidate_id": ["INCOMPLETE"] * 4,
                "score_id": ["x"] * 4,
                "top_n": [10] * 4,
                "holding_sessions": [5] * 4,
                "mean_cagr": [0.1] * 4,
                "mean_sharpe": [1.0] * 4,
                "mean_sortino": [1.0] * 4,
                "mean_max_drawdown": [-0.1] * 4,
                "mean_calmar": [1.0] * 4,
                "annualized_relative_return": [0.05] * 4,
                "relative_hit_rate": [0.5] * 4,
                "mean_turnover": [0.2] * 4,
            }
        )
        with self.assertRaisesRegex(RuntimeError, "does not have 5 folds"):
            module.build_leaderboard(rows)


if __name__ == "__main__":
    unittest.main()
