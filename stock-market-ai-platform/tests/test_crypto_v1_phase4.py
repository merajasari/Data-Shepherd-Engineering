"""Focused contracts for Crypto V1 Phase 4 cost-aware portfolio research."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.crypto_v1.phase4 import (
    BENCHMARK_PRODUCT,
    DAILY_COLUMNS,
    METRIC_COLUMNS,
    ROUND_TRIP_COST_BPS,
    TURNOVER_COLUMNS,
    _portfolio_turnover,
    rebalance_dates,
    run_phase4,
    simulate_strategy,
    target_weights,
)


def synthetic_predictions():
    dates = pd.date_range("2025-01-01", periods=22, tz="UTC")
    products = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "LTC-USD", "ADA-USD"]
    rows = []
    for split, subset in (("development", dates[:15]), ("holdout", dates[15:])):
        fold_id = "dev_01" if split == "development" else "holdout"
        for model_id in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
            for day_index, timestamp in enumerate(subset):
                for asset_index, product in enumerate(products):
                    if model_id == "equal_score":
                        score = 0.0
                    elif model_id == "random":
                        score = ((day_index * 7 + asset_index * 3) % 17) / 17
                    elif model_id == "hist_gradient_boosting":
                        score = asset_index * .1 - day_index * .001
                    else:
                        score = (len(products) - asset_index) + day_index * .001
                    rows.append({
                        "timestamp_utc": timestamp,
                        "product_id": product,
                        "actual_btc_relative_forward_return": 0.001 * (asset_index - 2),
                        "predicted_score": score,
                        "fold_id": fold_id,
                        "split": split,
                        "model_id": model_id,
                        "horizon_days": 7,
                        "btc_regime": "neutral",
                    })
    return pd.DataFrame(rows)


def synthetic_panel():
    dates = pd.date_range("2025-01-01", periods=22, tz="UTC")
    products = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "LTC-USD", "ADA-USD"]
    rows = []
    for day_index, timestamp in enumerate(dates):
        for asset_index, product in enumerate(products):
            daily = 0.0005 * (asset_index + 1) + 0.0001 * (day_index % 3)
            rows.append({
                "timestamp_utc": timestamp,
                "product_id": product,
                "return_1d": daily,
                "forward_return_7d": daily * 7,
                "forward_btc_return_7d": 0.0005 * 7,
            })
    return pd.DataFrame(rows)


class Phase4WeightAndTurnoverTests(unittest.TestCase):
    def test_equal_weights_sum_correctly_and_are_long_only(self):
        day = synthetic_predictions().query("split == 'development' and model_id == 'momentum'")
        day = day[day["timestamp_utc"] == day["timestamp_utc"].min()]
        for n in (3, 5):
            weights = target_weights(day, f"top_{n}_equal_weight", n)
            self.assertAlmostEqual(sum(weights.values()), 1.0)
            self.assertEqual(len(weights), n)
            self.assertTrue(all(value >= 0 for value in weights.values()))

    def test_no_leverage_for_research_spread(self):
        day = synthetic_predictions().query("split == 'development' and model_id == 'momentum'")
        day = day[day["timestamp_utc"] == day["timestamp_utc"].min()]
        weights = target_weights(day, "top_minus_bottom", 3)
        self.assertLessEqual(sum(abs(v) for v in weights.values()), 1.0 + 1e-12)
        self.assertAlmostEqual(sum(weights.values()), 0.0)

    def test_turnover_calculation(self):
        current = {"A": 0.5, "B": 0.5}
        target = {"B": 0.5, "C": 0.5}
        self.assertAlmostEqual(_portfolio_turnover(current, target), 0.5)
        self.assertAlmostEqual(_portfolio_turnover({}, {"A": 0.5, "B": 0.5}), 0.5)

    def test_rebalance_schedule_is_seven_calendar_days(self):
        dates = pd.date_range("2025-01-01", periods=22, tz="UTC")
        result = rebalance_dates(dates)
        self.assertEqual(result.tolist(), [dates[0], dates[7], dates[14], dates[21]])


class Phase4SimulationTests(unittest.TestCase):
    def test_transaction_cost_is_turnover_based(self):
        predictions = synthetic_predictions()
        panel = synthetic_panel()
        zero = simulate_strategy(predictions, panel, "development", "momentum", "top_3_equal_weight", 3, 0)
        costly = simulate_strategy(predictions, panel, "development", "momentum", "top_3_equal_weight", 3, 50)
        first_zero = zero[zero["is_rebalance"]].iloc[0]
        first_costly = costly[costly["is_rebalance"]].iloc[0]
        self.assertAlmostEqual(first_costly["turnover"], 0.5)
        self.assertAlmostEqual(first_costly["transaction_cost"], 1.0 * 0.5 * 50 / 10000)
        self.assertEqual(first_zero["transaction_cost"], 0.0)

    def test_costs_monotonically_reduce_ending_equity(self):
        predictions = synthetic_predictions()
        panel = synthetic_panel()
        endings = []
        for cost in ROUND_TRIP_COST_BPS:
            path = simulate_strategy(predictions, panel, "development", "momentum", "top_5_equal_weight", 5, cost)
            endings.append(path["equity"].iloc[-1])
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(endings, endings[1:])))

    def test_no_lookahead_future_scores_do_not_change_earlier_path(self):
        predictions = synthetic_predictions()
        panel = synthetic_panel()
        original = simulate_strategy(predictions, panel, "development", "momentum", "top_3_equal_weight", 3, 10)
        mutated = predictions.copy()
        cutoff = pd.Timestamp("2025-01-09", tz="UTC")
        mask = (mutated["timestamp_utc"] > cutoff) & (mutated["model_id"] == "momentum")
        mutated.loc[mask, "predicted_score"] *= -1000
        changed = simulate_strategy(mutated, panel, "development", "momentum", "top_3_equal_weight", 3, 10)
        left = original[original["timestamp_utc"] <= cutoff].reset_index(drop=True)
        right = changed[changed["timestamp_utc"] <= cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)

    def test_development_holdout_are_separate_and_restart_equity(self):
        predictions = synthetic_predictions()
        panel = synthetic_panel()
        dev = simulate_strategy(predictions, panel, "development", "momentum", "top_3_equal_weight", 3, 0)
        hold = simulate_strategy(predictions, panel, "holdout", "momentum", "top_3_equal_weight", 3, 0)
        self.assertTrue((dev["split"] == "development").all())
        self.assertTrue((hold["split"] == "holdout").all())
        self.assertEqual(hold.iloc[0]["net_return"], 0.0)
        self.assertEqual(hold.iloc[0]["timestamp_utc"], predictions.query("split == 'holdout'")["timestamp_utc"].min())

    def test_long_only_variants_never_short_or_leverage(self):
        predictions = synthetic_predictions()
        panel = synthetic_panel()
        for variant, n in (("top_3_equal_weight", 3), ("top_5_equal_weight", 5)):
            path = simulate_strategy(predictions, panel, "development", "momentum", variant, n, 0)
            self.assertTrue((path["gross_exposure"] <= 1.0 + 1e-10).all())
            self.assertTrue((path["net_exposure"] >= -1e-12).all())


class Phase4IntegrationTests(unittest.TestCase):
    def test_inputs_immutable_deterministic_and_expected_schemas(self):
        predictions = synthetic_predictions()
        panel = synthetic_panel()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase3 = root / "phase3"
            out1 = root / "out1"
            out2 = root / "out2"
            phase3.mkdir(parents=True)
            pred_path = phase3 / "predictions.parquet"
            manifest_path = phase3 / "manifest.json"
            panel_path = root / "research_panel_7d.parquet"
            # Real bytes are used for immutability checks while readers are patched.
            pred_path.write_bytes(b"frozen-phase3")
            panel_path.write_bytes(b"frozen-panel")
            manifest_path.write_text(json.dumps({"phase": 3}) + "\n")
            before = {p: p.read_bytes() for p in (pred_path, panel_path, manifest_path)}

            real_read = pd.read_parquet
            def fake_read(path, *args, **kwargs):
                path = Path(path)
                if path == pred_path:
                    return predictions.copy()
                if path == panel_path:
                    return panel.copy()
                return real_read(path, *args, **kwargs)

            with patch("ml.crypto_v1.phase4.pd.read_parquet", side_effect=fake_read):
                manifest1, frames1 = run_phase4(phase3, root, out1)
                manifest2, frames2 = run_phase4(phase3, root, out2)

            after = {p: p.read_bytes() for p in (pred_path, panel_path, manifest_path)}
            self.assertEqual(before, after)
            for name in frames1:
                pd.testing.assert_frame_equal(frames1[name], frames2[name])

            self.assertEqual(list(frames1["portfolio_daily"].columns), DAILY_COLUMNS + ["is_benchmark"])
            self.assertEqual(list(frames1["portfolio_metrics"].columns), METRIC_COLUMNS)
            self.assertEqual(list(frames1["turnover_summary"].columns), TURNOVER_COLUMNS)
            self.assertEqual(list(frames1["benchmark_metrics"].columns), METRIC_COLUMNS)
            self.assertIn("no fitting", manifest1["policy"])
            self.assertEqual(set(frames1["portfolio_daily"]["split"]), {"development", "holdout"})
            self.assertTrue((out1 / "manifest.json").exists())
            self.assertTrue((out1 / "portfolio_daily.csv").exists())
            self.assertTrue((out1 / "portfolio_metrics.csv").exists())
            self.assertTrue((out1 / "turnover_summary.csv").exists())
            self.assertTrue((out1 / "benchmark_metrics.csv").exists())


if __name__ == "__main__":
    unittest.main()
