from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.v11 import phase1
from ml.v11.discovery_registry import build_registry


class V11Phase1Tests(unittest.TestCase):
    def test_base_frame_computes_features_without_target_leakage(self):
        rows = 90
        timestamps = pd.date_range("2025-01-02", periods=rows, freq="B", tz="UTC")
        close = pd.Series(np.linspace(100.0, 145.0, rows))
        source = pd.DataFrame(
            {
                "timestamp_utc": timestamps,
                "open": close - 0.25,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.linspace(1_000_000, 1_500_000, rows),
            }
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "features.parquet"
            source.to_parquet(path, index=False)
            frame = phase1._base_frame(path, "TEST")

        self.assertEqual(len(frame), rows)
        self.assertEqual(frame["symbol"].unique().tolist(), ["TEST"])
        for signal in (
            "range_compression_5_20",
            "close_location_value_20",
            "volume_return_correlation_20",
        ):
            self.assertIn(signal, frame.columns)
        self.assertTrue(frame["forward_return_5d"].tail(5).isna().all())
        expected = close.iloc[5] / close.iloc[0] - 1.0
        self.assertAlmostEqual(frame.loc[0, "forward_return_5d"], expected)

    def test_residualization_removes_frozen_control_exposure(self):
        rows = phase1.MIN_ASSETS + 20
        index = pd.RangeIndex(rows)
        controls = pd.DataFrame(
            {
                control: np.linspace(0.1 + offset, 1.1 + offset, rows)
                ** (1 + (offset % 2))
                for offset, control in enumerate(phase1.CONTROLS)
            },
            index=index,
        )
        coefficients = np.arange(1, len(phase1.CONTROLS) + 1, dtype=float)
        signal = pd.Series(
            2.5 + controls.to_numpy() @ coefficients,
            index=index,
        )
        residual = phase1._residualize(signal, controls)
        self.assertEqual(residual.notna().sum(), rows)
        self.assertLess(float(residual.abs().max()), 1e-9)

    def test_residualization_fails_closed_below_minimum_assets(self):
        rows = phase1.MIN_ASSETS - 1
        controls = pd.DataFrame(
            np.ones((rows, len(phase1.CONTROLS))),
            columns=phase1.CONTROLS,
        )
        residual = phase1._residualize(pd.Series(np.arange(rows)), controls)
        self.assertTrue(residual.isna().all())

    def test_benjamini_hochberg_is_monotone_in_p_value_order(self):
        p_values = pd.Series([0.01, 0.04, 0.03, 0.20, np.nan])
        adjusted = phase1._benjamini_hochberg(p_values)
        expected = [0.04, 0.05333333333333334, 0.05333333333333334, 0.20]
        np.testing.assert_allclose(adjusted.iloc[:4], expected)
        self.assertTrue(np.isnan(adjusted.iloc[4]))
        ordered = adjusted[p_values.sort_values().index].dropna()
        self.assertTrue(ordered.is_monotonic_increasing)

    def test_contract_verification_fails_closed_on_drift(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "signal_registry.json"
            path.write_text(json.dumps(build_registry()))
            with patch.object(phase1, "REGISTRY_PATH", path):
                self.assertEqual(
                    phase1._verify_contract()["contract_sha256"],
                    build_registry()["contract_sha256"],
                )

            payload = build_registry()
            payload["signals"][0]["direction_hypothesis"] = "mutated"
            path.write_text(json.dumps(payload))
            with patch.object(phase1, "REGISTRY_PATH", path):
                with self.assertRaisesRegex(RuntimeError, "frozen contract"):
                    phase1._verify_contract()

    def test_panel_excludes_future_holdout_rows(self):
        timestamps = pd.to_datetime(
            ["2026-10-30T00:00:00Z", "2026-11-02T00:00:00Z"],
            utc=True,
        )
        spy = pd.DataFrame({"timestamp_utc": timestamps})
        stock = pd.DataFrame({"timestamp_utc": timestamps})

        with (
            patch.object(phase1, "_feature_files", return_value={"SPY": "spy", "AAPL": "aapl"}),
            patch.object(
                phase1,
                "_base_frame",
                side_effect=lambda path, symbol: spy.copy() if symbol == "SPY" else stock.copy(),
            ),
            patch.object(
                phase1,
                "_symbol_panel",
                return_value=pd.DataFrame(
                    {
                        "timestamp_utc": timestamps,
                        "symbol": ["AAPL", "AAPL"],
                    }
                ),
            ),
        ):
            panel = phase1.build_panel()

        self.assertEqual(len(panel), 1)
        self.assertLess(
            panel["timestamp_utc"].max(),
            phase1.FUTURE_HOLDOUT_START_UTC,
        )


if __name__ == "__main__":
    unittest.main()
