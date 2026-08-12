"""Focused tests for Crypto V1 Phase 7 evidence synthesis checkpoint."""

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.crypto_v1.phase7 import (
    ASSET_PERSISTENCE_COLUMNS,
    CONCENTRATION_SUMMARY_COLUMNS,
    EVIDENCE_REGISTER_COLUMNS,
    SENSITIVITY_SUMMARY_COLUMNS,
    SIGNAL_SUMMARY_COLUMNS,
    TEMPORAL_CONSISTENCY_COLUMNS,
    asset_persistence,
    concentration_summary,
    evidence_register,
    governance_report,
    run_phase7,
    sensitivity_summary,
    signal_summary,
    temporal_consistency,
)


def control_frame():
    rows = []
    for split, obs in (("development", 100), ("holdout", 40)):
        for model in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
            for top_n in (3, 5):
                rows.append({
                    "split": split,
                    "model_id": model,
                    "top_n": top_n,
                    "observation_count": obs,
                    "mean_ic": 0.04 if split == "holdout" and model == "momentum" else -0.02,
                    "median_ic": 0.03,
                    "ic_positive_rate": 0.55,
                    "mean_top_minus_bottom_spread": 0.01 if model == "momentum" else 0.001,
                    "median_top_minus_bottom_spread": 0.005,
                    "positive_spread_rate": 0.56,
                    "mean_top_relative_return": 0.002,
                    "mean_bottom_relative_return": -0.008,
                })
    return pd.DataFrame(rows)


def bootstrap_frame():
    rows = []
    for split in ("development", "holdout"):
        for model in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
            for top_n in (3, 5):
                for metric in ("ic", "top_minus_bottom_spread"):
                    rows.append({
                        "split": split,
                        "model_id": model,
                        "top_n": top_n,
                        "metric": metric,
                        "observation_count": 20,
                        "block_length": 4,
                        "replicates": 20,
                        "seed": 1729,
                        "observed_mean": 0.01,
                        "bootstrap_mean": 0.01,
                        "bootstrap_std": 0.02,
                        "ci_lower_2_5": -0.02,
                        "ci_upper_97_5": 0.04,
                        "bootstrap_positive_rate": 0.75,
                    })
    return pd.DataFrame(rows)


def calendar_frame():
    rows = []
    for split in ("development", "holdout"):
        for model in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
            for top_n in (3, 5):
                for breakdown, periods in (
                    ("year", ["2024", "2025"]),
                    ("quarter", ["2025Q1", "2025Q2"]),
                    ("fold", ["dev_01", "dev_02"] if split == "development" else ["holdout"]),
                ):
                    for i, period in enumerate(periods):
                        rows.append({
                            "split": split, "model_id": model, "top_n": top_n,
                            "breakdown": breakdown, "period": period,
                            "observation_count": 10,
                            "mean_ic": 0.02 if i % 2 == 0 else -0.01,
                            "median_ic": 0.0, "ic_positive_rate": 0.5,
                            "mean_top_minus_bottom_spread": 0.01 if i % 2 == 0 else -0.005,
                            "median_top_minus_bottom_spread": 0.0,
                            "positive_spread_rate": 0.5,
                            "mean_top_relative_return": 0.01,
                            "mean_bottom_relative_return": 0.0,
                        })
    return pd.DataFrame(rows)


def asset_frame():
    rows = []
    for model in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
        for top_n in (3, 5):
            for i, product in enumerate(("BTC-USD", "ETH-USD", "SOL-USD")):
                rows.append({
                    "model_id": model,
                    "variant": f"top_{top_n}_equal_weight",
                    "top_n": top_n,
                    "product_id": product,
                    "development_selection_count": 10,
                    "observed_holdout_selection_count": 5,
                    "development_selection_rate": 0.5,
                    "observed_holdout_selection_rate": 0.4,
                    "development_contribution": 1.0 - i,
                    "observed_holdout_contribution": (1.0 - i) if i != 1 else -0.5,
                    "development_mean_relative_return": 0.01,
                    "observed_holdout_mean_relative_return": 0.005,
                    "development_sign": 1 if i == 0 else (0 if i == 1 else -1),
                    "observed_holdout_sign": 1 if i == 0 else -1,
                    "sign_status": ("persisted", "zero_or_negligible", "persisted")[i],
                    "contribution_change": -0.1 * (i + 1),
                    "pearson_contribution_correlation": 0.25,
                    "spearman_contribution_correlation": 0.20,
                })
    return pd.DataFrame(rows)


def loo_frame():
    rows = []
    for split in ("development", "holdout"):
        for model in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
            for top_n in (3, 5):
                for i, product in enumerate(("BTC-USD", "ETH-USD", "SOL-USD")):
                    rows.append({
                        "split": split,
                        "model_id": model,
                        "top_n": top_n,
                        "excluded_product_id": product,
                        "observation_count": 20,
                        "baseline_mean_spread": 0.01,
                        "leave_one_out_mean_spread": [0.012, 0.008, -0.002][i],
                        "spread_change": [0.002, -0.002, -0.012][i],
                        "baseline_positive_spread_rate": 0.55,
                        "leave_one_out_positive_spread_rate": 0.50,
                    })
    return pd.DataFrame(rows)


def concentration_frame():
    rows = []
    for split in ("development", "holdout"):
        for model in ("momentum", "hist_gradient_boosting", "random", "equal_score"):
            for top_n in (3, 5):
                rows.append({
                    "split": split,
                    "model_id": model,
                    "variant": f"top_{top_n}_equal_weight",
                    "top_n": top_n,
                    "asset_count": 3,
                    "positive_asset_count": 2,
                    "negative_asset_count": 1,
                    "zero_asset_count": 0,
                    "positive_asset_fraction": 2 / 3,
                    "total_contribution": 1.0,
                    "total_positive_contribution": 1.5,
                    "total_negative_contribution": -0.5,
                    "largest_absolute_contributor": "BTC-USD",
                    "largest_absolute_contribution_share": 0.5,
                    "positive_contribution_hhi": 0.6,
                    "absolute_contribution_hhi": 0.4,
                    "top_1_share_of_positive_contribution": 0.6,
                    "top_3_share_of_positive_contribution": 1.0,
                    "top_5_share_of_positive_contribution": 1.0,
                })
    return pd.DataFrame(rows)


class Phase7UnitTests(unittest.TestCase):
    def setUp(self):
        self.signal = signal_summary(control_frame(), bootstrap_frame())
        self.temporal = temporal_consistency(calendar_frame())
        self.persistence = asset_persistence(asset_frame())
        self.sensitivity = sensitivity_summary(loo_frame())
        self.concentration = concentration_summary(concentration_frame())

    def test_output_schemas(self):
        self.assertEqual(list(self.signal.columns), SIGNAL_SUMMARY_COLUMNS)
        self.assertEqual(list(self.temporal.columns), TEMPORAL_CONSISTENCY_COLUMNS)
        self.assertEqual(list(self.persistence.columns), ASSET_PERSISTENCE_COLUMNS)
        self.assertEqual(list(self.sensitivity.columns), SENSITIVITY_SUMMARY_COLUMNS)
        self.assertEqual(list(self.concentration.columns), CONCENTRATION_SUMMARY_COLUMNS)

    def test_signal_bootstrap_merge(self):
        row = self.signal[
            (self.signal["split"] == "holdout")
            & (self.signal["model_id"] == "momentum")
            & (self.signal["top_n"] == 3)
        ].iloc[0]
        self.assertEqual(row["ic_ci_lower_2_5"], -0.02)
        self.assertEqual(row["spread_bootstrap_positive_rate"], 0.75)

    def test_temporal_counts_are_descriptive(self):
        row = self.temporal[
            (self.temporal["split"] == "development")
            & (self.temporal["model_id"] == "momentum")
            & (self.temporal["top_n"] == 3)
            & (self.temporal["breakdown"] == "year")
        ].iloc[0]
        self.assertEqual(row["period_count"], 2)
        self.assertEqual(row["positive_mean_spread_period_count"], 1)
        self.assertEqual(row["negative_mean_spread_period_count"], 1)

    def test_sensitivity_detects_sign_flip(self):
        row = self.sensitivity[
            (self.sensitivity["split"] == "development")
            & (self.sensitivity["model_id"] == "momentum")
            & (self.sensitivity["top_n"] == 3)
        ].iloc[0]
        self.assertEqual(row["most_influential_asset"], "SOL-USD")
        self.assertEqual(row["sign_flip_count"], 1)

    def test_evidence_register_and_governance_are_non_promotional(self):
        register = evidence_register(
            self.signal, self.temporal, self.persistence,
            self.sensitivity, self.concentration,
        )
        self.assertEqual(list(register.columns), EVIDENCE_REGISTER_COLUMNS)
        self.assertTrue((register["model_id"] == "momentum").all())
        report = governance_report(
            self.signal, self.temporal, self.persistence,
            self.sensitivity, self.concentration,
        )
        self.assertEqual(report["research_disposition"], "RESEARCH_ONLY_NOT_PROMOTED")
        self.assertFalse(report["disposition_is_rule"])
        self.assertIn("descriptive only", report["observed_holdout_policy"])


class Phase7IntegrationTests(unittest.TestCase):
    def test_run_phase7_preserves_phase6_inputs_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase6 = root / "phase6"
            out = root / "phase7"
            phase6.mkdir()

            (phase6 / "manifest.json").write_text(
                json.dumps({"phase": 6, "policy": "read-only robustness"}) + "\n",
                encoding="utf-8",
            )
            pd.DataFrame({"x": [1]}).to_csv(phase6 / "rolling_stability.csv", index=False)
            calendar_frame().to_csv(phase6 / "calendar_stability.csv", index=False)
            pd.DataFrame({"x": [1]}).to_csv(phase6 / "regime_stability.csv", index=False)
            asset_frame().to_csv(phase6 / "asset_stability.csv", index=False)
            loo_frame().to_csv(phase6 / "leave_one_asset_out.csv", index=False)
            concentration_frame().to_csv(
                phase6 / "contribution_concentration.csv", index=False
            )
            bootstrap_frame().to_csv(phase6 / "bootstrap_uncertainty.csv", index=False)
            control_frame().to_csv(phase6 / "control_comparison.csv", index=False)

            tracked = sorted(phase6.iterdir())
            before = {path: path.read_bytes() for path in tracked}

            manifest, frames, report = run_phase7(phase6, out)

            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            self.assertIn("no fitting", manifest["policy"])
            self.assertEqual(report["research_disposition"], "RESEARCH_ONLY_NOT_PROMOTED")
            self.assertEqual(set(frames), {
                "signal_summary", "temporal_consistency", "asset_persistence",
                "sensitivity_summary", "concentration_summary", "evidence_register",
            })
            for name in (
                "manifest.json", "governance_report.json", "signal_summary.csv",
                "temporal_consistency.csv", "asset_persistence.csv",
                "sensitivity_summary.csv", "concentration_summary.csv",
                "evidence_register.csv",
            ):
                self.assertTrue((out / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
