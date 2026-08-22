import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v10 import tuning_cycle2_evaluator as module


class V10TuningCycle2EvaluatorTests(unittest.TestCase):
    def test_folds_use_twenty_session_purge(self):
        dates = pd.bdate_range("2016-01-01", periods=2000, tz="UTC")
        folds = module.make_folds(dates)

        self.assertEqual(len(folds), 5)
        for fold in folds:
            self.assertEqual(fold["purge_sessions"], 20)
            self.assertLess(
                fold["training_end_utc"],
                fold["purge_start_utc"],
            )
            self.assertLess(
                fold["purge_end_utc"],
                fold["validation_start_utc"],
            )

    def test_exposure_uses_decision_date_spy_state(self):
        date = pd.Timestamp("2020-01-02", tz="UTC")
        trend = pd.DataFrame(
            {"spy_close": [90.0], "spy_sma200": [100.0]},
            index=pd.DatetimeIndex([date]),
        )
        config = {
            "risk_overlay": "SPY_SMA200_HALF_EXPOSURE",
            "below_sma200_target_exposure": 0.5,
            "above_sma200_target_exposure": 1.0,
        }

        self.assertEqual(
            module._target_exposure(config, date, trend),
            0.5,
        )
        trend.loc[date, "spy_close"] = 110.0
        self.assertEqual(
            module._target_exposure(config, date, trend),
            1.0,
        )

    def test_turnover_includes_exposure_change(self):
        picks = ["A", "B"]
        self.assertAlmostEqual(
            module._transition_notional(None, picks, 1.0, 2),
            1.0,
        )
        self.assertAlmostEqual(
            module._transition_notional((picks, 1.0), picks, 0.5, 2),
            0.5,
        )
        self.assertAlmostEqual(
            module._transition_notional((picks, 0.5), picks, 0.0, 2),
            0.5,
        )

    def _fold_rows(self, candidate, worst_sharpe, drawdown, relative):
        rows = []
        for fold_id in range(1, 6):
            rows.append(
                {
                    "candidate_id": candidate,
                    "fold_id": fold_id,
                    "score_id": "downside_vol_ratio_20",
                    "top_n": 15,
                    "holding_sessions": 10,
                    "risk_overlay": "SPY_SMA200_HALF_EXPOSURE",
                    "mean_cagr": 0.12,
                    "mean_sharpe": (
                        worst_sharpe if fold_id == 1 else 1.0
                    ),
                    "mean_sortino": 1.1,
                    "mean_max_drawdown": drawdown,
                    "mean_calmar": 0.8,
                    "annualized_relative_return": relative,
                    "relative_hit_rate": 0.55,
                    "mean_turnover": 0.7,
                    "mean_exposure": 0.8,
                }
            )
        return rows

    def test_leaderboard_prioritizes_only_preliminary_eligible(self):
        rows = (
            self._fold_rows("ELIGIBLE", 0.1, -0.20, 0.04)
            + self._fold_rows("FAILED", -0.1, -0.30, 0.20)
        )
        leaderboard = module.build_leaderboard(pd.DataFrame(rows))

        self.assertEqual(leaderboard.iloc[0]["candidate_id"], "ELIGIBLE")
        self.assertTrue(
            bool(leaderboard.iloc[0]["preliminary_gate_eligible"])
        )
        failed = leaderboard[leaderboard["candidate_id"] == "FAILED"].iloc[0]
        self.assertFalse(bool(failed["preliminary_gate_eligible"]))

    def test_missing_fold_fails_closed(self):
        rows = self._fold_rows("INCOMPLETE", 0.1, -0.20, 0.04)[:4]
        with self.assertRaisesRegex(RuntimeError, "does not have five"):
            module.build_leaderboard(pd.DataFrame(rows))


if __name__ == "__main__":
    unittest.main()
