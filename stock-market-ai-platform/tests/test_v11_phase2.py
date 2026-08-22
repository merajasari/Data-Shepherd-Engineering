from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.v11 import phase2
from ml.v11.phase2_registry import build_registry


class V11Phase2DiagnosticTests(unittest.TestCase):
    def test_phase2_signal_formulas_are_computed_from_completed_ohlcv(self):
        rows = 90
        close = pd.Series(np.linspace(100.0, 140.0, rows))
        frame = pd.DataFrame(
            {
                "open": close.shift(1).fillna(close.iloc[0]) * 1.01,
                "close": close,
                "volume": np.linspace(1_000_000, 2_000_000, rows),
                "return_1d": close.pct_change(),
            }
        )
        output = phase2._add_phase2_base_signals(frame)
        for signal_id in phase2.SIGNAL_IDS:
            self.assertIn(signal_id, output.columns)
        self.assertAlmostEqual(
            output.loc[1, "overnight_gap_reversal_1"],
            -0.01,
        )
        self.assertTrue(
            np.isfinite(
                output["abnormal_dollar_volume_5_60"].iloc[-1]
            )
        )
        self.assertTrue(
            np.isfinite(
                output[
                    "amihud_liquidity_improvement_5_20"
                ].iloc[-1]
            )
        )
        self.assertLessEqual(
            abs(output["signed_dollar_volume_pressure_20"].iloc[-1]),
            1.0,
        )

    def test_contract_verification_fails_closed_on_drift(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "signal_registry.json"
            path.write_text(json.dumps(build_registry()))
            with patch.object(phase2, "REGISTRY_PATH", path):
                self.assertEqual(
                    phase2._verify_contract()["contract_sha256"],
                    build_registry()["contract_sha256"],
                )

            payload = build_registry()
            payload["signals"][0]["formula"] = "mutated"
            path.write_text(json.dumps(payload))
            with patch.object(phase2, "REGISTRY_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "frozen contract"):
                    phase2._verify_contract()

    def test_panel_excludes_future_holdout_rows(self):
        timestamps = pd.to_datetime(
            ["2026-10-30T00:00:00Z", "2026-11-02T00:00:00Z"],
            utc=True,
        )
        required = (
            set(phase2.SIGNAL_IDS)
            | set(phase2.ORTHOGONALIZATION_CONTROLS)
        )
        prepared = pd.DataFrame(
            {
                "timestamp_utc": timestamps,
                "symbol": ["AAPL", "AAPL"],
                **{column: [0.1, 0.2] for column in required},
            }
        )
        prepared["forward_relative_return_5d"] = [0.01, 0.02]

        with (
            patch.object(
                phase2.phase1,
                "_feature_files",
                return_value={"SPY": "spy", "AAPL": "aapl"},
            ),
            patch.object(
                phase2.phase1,
                "_base_frame",
                return_value=pd.DataFrame(
                    {
                        "timestamp_utc": timestamps,
                        "open": [1.0, 1.0],
                        "close": [1.0, 1.0],
                        "volume": [1.0, 1.0],
                        "return_1d": [0.0, 0.0],
                    }
                ),
            ),
            patch.object(
                phase2,
                "_add_phase2_base_signals",
                side_effect=lambda frame: frame,
            ),
            patch.object(
                phase2.phase1,
                "_symbol_panel",
                return_value=prepared,
            ),
        ):
            panel = phase2.build_panel()

        self.assertEqual(len(panel), 1)
        self.assertLess(
            panel["timestamp_utc"].max(),
            phase2.FUTURE_HOLDOUT_START_UTC,
        )

    def test_summary_requires_every_preregistered_gate(self):
        base = pd.DataFrame(
            {
                "signal_id": list(phase2.SIGNAL_IDS),
                "days": [100] * len(phase2.SIGNAL_IDS),
                "mean_orthogonal_ic": [0.02] * len(phase2.SIGNAL_IDS),
                "median_orthogonal_ic": [0.02] * len(phase2.SIGNAL_IDS),
                "ic_hit_rate": [0.55] * len(phase2.SIGNAL_IDS),
                "ic_std": [0.10] * len(phase2.SIGNAL_IDS),
                "hac_lag": [5] * len(phase2.SIGNAL_IDS),
                "hac_se": [0.005] * len(phase2.SIGNAL_IDS),
                "hac_t": [4.0] * len(phase2.SIGNAL_IDS),
                "raw_p_value": [0.001] * len(phase2.SIGNAL_IDS),
                "fdr_q_value": [0.006] * len(phase2.SIGNAL_IDS),
                "passes_discovery_threshold": [True]
                * len(phase2.SIGNAL_IDS),
            }
        )
        years = pd.DataFrame(
            [
                {
                    "signal_id": signal_id,
                    "year": year,
                    "mean_orthogonal_ic": 0.01,
                }
                for signal_id in phase2.SIGNAL_IDS
                for year in range(2017, 2027)
            ]
        )
        regimes = pd.DataFrame(
            [
                {
                    "signal_id": signal_id,
                    "regime": regime,
                    "mean_orthogonal_ic": 0.005,
                }
                for signal_id in phase2.SIGNAL_IDS
                for regime in ("UP", "DOWN", "HIGH_VOL", "LOW_VOL")
            ]
        )
        with patch.object(
            phase2.phase1,
            "build_summary",
            return_value=base,
        ):
            summary = phase2.build_summary(
                pd.DataFrame(),
                years,
                regimes,
            )
        self.assertTrue(summary["passes_discovery_threshold"].all())

        base.loc[0, "mean_orthogonal_ic"] = 0.009
        with patch.object(
            phase2.phase1,
            "build_summary",
            return_value=base,
        ):
            failed = phase2.build_summary(
                pd.DataFrame(),
                years,
                regimes,
            )
        row = failed[failed["signal_id"] == base.loc[0, "signal_id"]].iloc[0]
        self.assertFalse(bool(row["mean_ic_pass"]))
        self.assertFalse(bool(row["passes_discovery_threshold"]))

    def test_regime_builder_does_not_label_pre_sma_history_as_down(self):
        timestamps = pd.date_range(
            "2020-01-01",
            periods=220,
            freq="B",
            tz="UTC",
        )
        panel = pd.DataFrame(
            {
                "timestamp_utc": timestamps,
                "spy_close": np.linspace(100.0, 150.0, len(timestamps)),
                "spy_volatility_20d": np.linspace(
                    0.01, 0.03, len(timestamps)
                ),
            }
        )
        daily = pd.DataFrame(
            {
                "timestamp_utc": np.repeat(timestamps, len(phase2.SIGNAL_IDS)),
                "signal_id": list(phase2.SIGNAL_IDS) * len(timestamps),
                "orthogonal_ic": 0.01,
            }
        )
        regimes = phase2.build_regime_stability(daily, panel)
        trend = regimes[regimes["regime_type"] == "trend_regime"]
        self.assertNotIn("UNKNOWN", trend["regime"].tolist())
        self.assertLessEqual(
            int(trend.groupby("signal_id")["days"].sum().max()),
            21,
        )


if __name__ == "__main__":
    unittest.main()
