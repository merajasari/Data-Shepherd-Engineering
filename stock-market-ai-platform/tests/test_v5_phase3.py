import unittest

import numpy as np
import pandas as pd

from ml.v5.phase3 import build_rebalance_table, summarize


class V5Phase3Tests(unittest.TestCase):
    def _data(self):
        dates = pd.date_range("2025-01-02", periods=12, freq="B", tz="UTC")
        symbols = [f"S{i}" for i in range(6)]
        panel_rows = []
        pred_rows = []
        for d in dates:
            for i, symbol in enumerate(symbols):
                panel_rows.append({
                    "timestamp_utc": d,
                    "symbol": symbol,
                    "forward_stock_return_5d": 0.01 + i * 0.001,
                    "forward_spy_return_5d": 0.005,
                })
                pred_rows.append({
                    "timestamp_utc": d,
                    "symbol": symbol,
                    "model_id": "hist_gradient_boosting",
                    "split": "development",
                    "predicted_score": float(i),
                })
        return pd.DataFrame(panel_rows), pd.DataFrame(pred_rows)

    def test_top_five_and_weights_economics(self):
        panel, pred = self._data()
        out = build_rebalance_table(panel, pred)
        self.assertGreaterEqual(len(out), 2)
        selected = out.iloc[0]["selected_symbols"].split(",")
        self.assertEqual(set(selected), {"S1", "S2", "S3", "S4", "S5"})
        expected_sleeve = np.mean([0.011, 0.012, 0.013, 0.014, 0.015])
        expected = 0.60 * 0.005 + 0.40 * expected_sleeve
        self.assertAlmostEqual(out.iloc[0]["sleeve_return_5d"], expected_sleeve)
        self.assertAlmostEqual(out.iloc[0]["gross_return_5d"], expected)

    def test_initial_turnover_is_one(self):
        panel, pred = self._data()
        out = build_rebalance_table(panel, pred)
        self.assertAlmostEqual(out.iloc[0]["turnover"], 1.0)

    def test_unchanged_holdings_have_zero_turnover_after_initial(self):
        panel, pred = self._data()
        out = build_rebalance_table(panel, pred)
        self.assertAlmostEqual(out.iloc[1]["turnover"], 0.0)

    def test_costs_reduce_equity(self):
        panel, pred = self._data()
        metrics = summarize(build_rebalance_table(panel, pred))
        zero = metrics.loc[metrics["cost_bps"] == 0.0, "ending_equity"].iloc[0]
        fifty = metrics.loc[metrics["cost_bps"] == 50.0, "ending_equity"].iloc[0]
        self.assertGreater(zero, fifty)

    def test_future_holdout_not_used(self):
        panel, pred = self._data()
        future = pd.Timestamp("2026-09-02", tz="UTC")
        extra_panel = panel.iloc[:6].copy()
        extra_panel["timestamp_utc"] = future
        extra_pred = pred.iloc[:6].copy()
        extra_pred["timestamp_utc"] = future
        out = build_rebalance_table(
            pd.concat([panel, extra_panel], ignore_index=True),
            pd.concat([pred, extra_pred], ignore_index=True),
        )
        self.assertTrue((out["timestamp_utc"] < future).all())


if __name__ == "__main__":
    unittest.main()
