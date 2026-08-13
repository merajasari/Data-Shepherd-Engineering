import unittest

import pandas as pd

from ml.v5.phase4 import (
    build_concentration,
    build_spy_regimes,
    enrich_portfolio,
    summarize_by_fold,
)


class V5Phase4Tests(unittest.TestCase):
    def test_spy_regimes_use_trailing_data(self):
        dates = pd.date_range("2024-01-02", periods=90, freq="B", tz="UTC")
        panel = pd.DataFrame({
            "timestamp_utc": list(dates) * 2,
            "spy_close": list(range(100, 190)) * 2,
        })
        regimes = build_spy_regimes(panel)
        self.assertEqual(len(regimes), 90)
        self.assertIn("trend_regime", regimes.columns)
        self.assertIn("vol_regime", regimes.columns)
        self.assertEqual(regimes.iloc[0]["trend_regime"], "insufficient_history")

    def test_enrich_attaches_fold_and_regime(self):
        dates = pd.date_range("2025-01-02", periods=80, freq="B", tz="UTC")
        panel = pd.DataFrame({
            "timestamp_utc": list(dates),
            "spy_close": [100 + i for i in range(len(dates))],
        })
        pred = pd.DataFrame({
            "timestamp_utc": dates[60:65],
            "model_id": ["hist_gradient_boosting"] * 5,
            "split": ["development"] * 5,
            "fold_id": ["dev_01"] * 5,
        })
        portfolio = pd.DataFrame({
            "timestamp_utc": dates[60:65],
            "spy_return_5d": [0.01] * 5,
            "gross_return_5d": [0.015] * 5,
            "turnover": [0.5] * 5,
        })
        out = enrich_portfolio(panel, pred, portfolio)
        self.assertTrue(out["fold_id"].eq("dev_01").all())
        self.assertTrue(out["trend_regime"].notna().all())

    def test_fold_summary_has_each_cost_and_fold(self):
        x = pd.DataFrame({
            "timestamp_utc": pd.date_range("2025-01-02", periods=4, freq="5B", tz="UTC"),
            "fold_id": ["dev_01", "dev_01", "dev_02", "dev_02"],
            "gross_return_5d": [0.02, 0.01, -0.01, 0.03],
            "spy_return_5d": [0.01, 0.00, -0.02, 0.01],
            "turnover": [1.0, 0.5, 0.5, 0.5],
        })
        out = summarize_by_fold(x)
        self.assertEqual(set(out["fold_id"]), {"dev_01", "dev_02"})
        self.assertEqual(out["cost_bps"].nunique(), 4)

    def test_concentration_identifies_worst_fold(self):
        folds = pd.DataFrame({
            "cost_bps": [10.0, 10.0, 10.0],
            "fold_id": ["dev_01", "dev_02", "dev_03"],
            "annualized_excess_vs_spy": [0.10, -0.05, 0.02],
        })
        out = build_concentration(folds)
        self.assertEqual(out.iloc[0]["worst_fold_id"], "dev_02")
        self.assertAlmostEqual(out.iloc[0]["positive_fold_rate"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
