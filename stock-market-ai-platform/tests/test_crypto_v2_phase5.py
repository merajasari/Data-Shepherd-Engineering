import unittest

import numpy as np
import pandas as pd

from ml.crypto_v2.phase5 import (
    ABSOLUTE_GATE_THRESHOLD,
    VARIANTS,
    selected_products,
    summarize,
)


class CryptoV2Phase5Tests(unittest.TestCase):
    def _day(self):
        return pd.DataFrame({
            "product_id": ["A-USD", "B-USD", "C-USD", "D-USD", "E-USD"],
            "predicted_absolute_return_7d": [0.02, -0.01, 0.03, 0.00, 0.01],
            "relative_rank_score": [0.5, 0.9, 0.2, 0.8, 0.4],
            "passes_absolute_gate": [True, False, True, False, True],
        })

    def test_gate_threshold_is_zero(self):
        self.assertEqual(ABSOLUTE_GATE_THRESHOLD, 0.0)

    def test_top3_selects_only_passing_assets_by_relative_rank(self):
        selected = selected_products(self._day(), "gated_top_3")
        self.assertEqual(selected, ["A-USD", "E-USD", "C-USD"])

    def test_gate_can_hold_cash(self):
        day = self._day().copy()
        day["passes_absolute_gate"] = False
        for variant in VARIANTS:
            self.assertEqual(selected_products(day, variant), [])

    def test_quintile_never_uses_failed_gate(self):
        selected = selected_products(self._day(), "gated_top_quintile")
        self.assertEqual(selected, ["A-USD"])
        self.assertNotIn("B-USD", selected)

    def test_summary_reports_cash_and_turnover_diagnostics(self):
        path = pd.DataFrame({
            "variant": ["gated_top_3"] * 3,
            "cost_bps_round_trip": [25.0] * 3,
            "is_rebalance": [True, False, True],
            "passing_asset_count": [2.0, np.nan, 0.0],
            "selected_asset_count": [2.0, np.nan, 0.0],
            "turnover": [0.5, 0.0, 0.5],
            "transaction_cost": [0.00125, 0.0, 0.00125],
            "net_return": [-0.00125, 0.02, -0.00125],
            "cash_weight": [0.0, 0.0, 1.0],
            "equity": [0.99875, 1.018725, 1.01745159375],
        })
        out = summarize(path)
        self.assertEqual(out["number_of_rebalances"], 2)
        self.assertAlmostEqual(out["cash_rebalance_rate"], 0.5)
        self.assertAlmostEqual(out["average_passing_assets"], 1.0)
        self.assertAlmostEqual(out["total_turnover"], 1.0)


if __name__ == "__main__":
    unittest.main()
