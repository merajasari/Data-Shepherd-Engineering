"""Tests for read-only Crypto V1 Phase 3 diagnostics."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.crypto_v1.diagnostics import (
    asset_contribution_diagnostics,
    bootstrap_uncertainty,
    breadth_diagnostics,
    run_diagnostics,
    turnover_diagnostics,
    xrp_gap_sensitivity,
)
from ml.crypto_v1.phase3 import daily_metrics, summarize_metrics


def synthetic_predictions():
    dates = pd.date_range("2024-01-01", periods=4, tz="UTC")
    products_by_day = [
        ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "LTC-USD"),
        ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD"),
        ("BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "DOGE-USD"),
        ("BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "DOGE-USD"),
    ]
    rows = []
    for day_index, (timestamp, products) in enumerate(zip(dates, products_by_day)):
        for asset_index, product in enumerate(products):
            rows.append({
                "timestamp_utc": timestamp,
                "product_id": product,
                "actual_btc_relative_forward_return": (4 - asset_index) * .01 - day_index * .001,
                "predicted_score": 10 - asset_index + day_index * .01,
                "fold_id": "dev_01",
                "split": "development",
                "model_id": "ridge",
                "horizon_days": 3,
                "btc_regime": "risk_on" if day_index < 2 else "neutral",
            })
    return pd.DataFrame(rows)


class DiagnosticFunctionTests(unittest.TestCase):
    def test_turnover_detects_membership_replacement(self):
        turnover = turnover_diagnostics(synthetic_predictions())
        top_5 = turnover[turnover["top_n"] == 5].sort_values("timestamp_utc")
        self.assertEqual(top_5.iloc[0]["replacement_count"], 1)
        self.assertAlmostEqual(top_5.iloc[0]["turnover_fraction"], .2)
        self.assertEqual(top_5.iloc[-1]["replacement_count"], 0)

    def test_breadth_and_asset_contribution_are_deterministic(self):
        daily, concentration = breadth_diagnostics(synthetic_predictions())
        self.assertTrue((daily["unique_score_count"] == 5).all())
        self.assertEqual(len(concentration), 2)
        contribution = asset_contribution_diagnostics(synthetic_predictions())
        eth = contribution[
            (contribution["top_n"] == 3) & (contribution["product_id"] == "ETH-USD")
        ].iloc[0]
        self.assertEqual(eth["selection_count"], 4)
        self.assertAlmostEqual(eth["selection_rate"], 1.0)

    def test_xrp_sensitivity_separates_present_and_absent_dates(self):
        predictions = synthetic_predictions()
        daily = daily_metrics(predictions)
        result = xrp_gap_sensitivity(predictions, daily)
        present = result[result["xrp_present"]]
        absent = result[~result["xrp_present"]]
        self.assertEqual(present["day_count"].sum(), 2)
        self.assertEqual(absent["day_count"].sum(), 2)

    def test_bootstrap_is_reproducible(self):
        daily = daily_metrics(synthetic_predictions())
        first = bootstrap_uncertainty(daily, samples=100, seed=11)
        second = bootstrap_uncertainty(daily, samples=100, seed=11)
        pd.testing.assert_frame_equal(first, second)


class ReadOnlyIntegrationTests(unittest.TestCase):
    def test_run_diagnostics_does_not_change_phase3_inputs(self):
        predictions = synthetic_predictions()
        daily = daily_metrics(predictions)
        summary = summarize_metrics(predictions, daily)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "phase3"
            output = root / "diagnostics"
            root.mkdir(parents=True)
            predictions_path = root / "predictions.parquet"
            daily_path = root / "daily_metrics.csv"
            summary_path = root / "metrics_summary.csv"
            predictions.to_parquet(predictions_path, index=False)
            daily.to_csv(daily_path, index=False)
            summary.to_csv(summary_path, index=False)

            before = {
                path.name: path.read_bytes()
                for path in (predictions_path, daily_path, summary_path)
            }
            manifest, frames = run_diagnostics(
                root, output, bootstrap_samples=50, seed=7
            )
            after = {
                path.name: path.read_bytes()
                for path in (predictions_path, daily_path, summary_path)
            }

            self.assertEqual(before, after)
            self.assertEqual(
                manifest["policy"],
                "read-only diagnostics; no fitting, retuning, selection, or promotion",
            )
            self.assertTrue((output / "manifest.json").exists())
            self.assertEqual(
                set(frames),
                {
                    "stability", "breadth_daily", "selection_concentration",
                    "turnover", "asset_contribution", "xrp_gap_sensitivity",
                    "uncertainty",
                },
            )


if __name__ == "__main__":
    unittest.main()
