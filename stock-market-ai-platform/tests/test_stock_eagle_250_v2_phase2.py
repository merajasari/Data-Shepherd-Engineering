import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v2.phase1 import (
    CONTRACT_PATH,
    GUARD_BAND_START_UTC,
    V2_CANDIDATE,
    _sha256,
    load_contract,
)
from ml.stock_eagle_250_v2.phase2 import (
    evaluate_gates,
    load_pre_guard_spy_returns,
    simulate_exposure,
    validate_sources,
)


def period_frame():
    rows = []
    for index in range(14):
        gross = 0.01
        rows.append({
            "fold_id": f"fold_{index + 1:02d}",
            "portfolio_id": "ridge_fixed_v1",
            "timestamp_utc": "2026-09-15T00:00:00+00:00",
            "entry_timestamp_utc_5d": "2026-09-16T00:00:00+00:00",
            "target_endpoint_utc_5d": "2026-09-22T00:00:00+00:00",
            "selected_symbols": "A,B,C,D,E,F,G,H,I,J",
            "selected_count": 10,
            "gross_return": gross,
            "net_return": (
                (1.0 + gross) * (1.0 - 0.001) ** 2 - 1.0
            ),
            "gross_exposure": 1.0,
        })
    return pd.DataFrame(rows)


def v1_metrics():
    rows = []
    for index in range(14):
        gross = 0.01
        net = (1.0 + gross) * (1.0 - 0.001) ** 2 - 1.0
        rows.append({
            "fold_id": f"fold_{index + 1:02d}",
            "candidate_id": "ridge_fixed_v1",
            "net_return": net / 5.0,
            "maximum_drawdown": 0.0,
            "spy_net_return": 0.0,
            "equal_weight_net_return": 0.0,
        })
    return pd.DataFrame(rows)


def phase1_manifest():
    return {
        "research_version": "stock_eagle_250_v2_risk_controlled_ridge",
        "candidate_id": V2_CANDIDATE,
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v2_performance_calculated": False,
        "contract_sha256": _sha256(CONTRACT_PATH),
    }


def passing_fold_metrics():
    rows = []
    for index in range(10):
        rows.append({
            "fold_id": f"fold_{index:02d}",
            "primary_net_return": 0.10,
            "primary_maximum_drawdown": -0.20,
            "primary_calmar": 1.5,
            "stress_20bps_net_return": 0.08,
            "v1_ridge_net_return": 0.11,
            "v1_ridge_maximum_drawdown": -0.40,
            "v1_ridge_calmar": 1.0,
            "spy_net_return": 0.03,
            "equal_weight_net_return": 0.04,
            "excess_vs_spy": 0.07,
            "excess_vs_equal_weight": 0.06,
            "excess_vs_v1_ridge": -0.01,
            "drawdown_improvement_vs_v1_ridge": 0.20,
            "mean_gross_exposure": 0.70,
        })
    return pd.DataFrame(rows)


class StockEagle250V2Phase2Test(unittest.TestCase):
    def test_pre_guard_spy_reader_supports_string_timestamp_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spy.parquet"
            pd.DataFrame({
                "timestamp_utc": [
                    "2026-09-22T00:00:00+00:00",
                    "2026-09-23T00:00:00+00:00",
                ],
                "daily_return": [0.01, 0.02],
            }).to_parquet(path, index=False)

            result = load_pre_guard_spy_returns(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result.iloc[0]["timestamp_utc"],
            pd.Timestamp("2026-09-22T00:00:00+00:00"),
        )

    def test_pre_guard_spy_reader_supports_arrow_timestamp_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spy.parquet"
            pd.DataFrame({
                "timestamp_utc": pd.to_datetime([
                    "2026-09-22T00:00:00+00:00",
                    "2026-09-23T00:00:00+00:00",
                ], utc=True),
                "daily_return": [0.01, 0.02],
            }).to_parquet(path, index=False)

            result = load_pre_guard_spy_returns(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result.iloc[0]["timestamp_utc"],
            pd.Timestamp("2026-09-22T00:00:00+00:00"),
        )

    def test_zero_exposure_stays_in_cash(self):
        periods = period_frame().head(3).copy()
        periods["gross_exposure"] = 0.0
        result, summary = simulate_exposure(periods, 20.0)

        self.assertTrue(np.allclose(result["net_return"], 0.0))
        self.assertAlmostEqual(summary["ending_equity"], 100_000.0)
        self.assertAlmostEqual(summary["maximum_drawdown"], 0.0)

    def test_partial_exposure_scales_returns_and_costs(self):
        periods = period_frame().head(1).copy()
        periods["gross_exposure"] = 0.5
        result, _ = simulate_exposure(periods, 10.0)
        expected = (1.0 + 0.5 * 0.01) * (1.0 - 0.5 * 0.001) ** 2 - 1.0

        self.assertAlmostEqual(result.iloc[0]["net_return"], expected)
        self.assertAlmostEqual(
            result.iloc[0]["modeled_cost_rate_per_side"],
            0.0005,
        )

    def test_all_preregistered_gates_only_qualify_for_human_review(self):
        gates, _summary, decision = evaluate_gates(
            passing_fold_metrics(),
            load_contract(),
        )

        self.assertTrue(gates["passed"].all())
        self.assertEqual(
            decision["status"],
            "QUALIFIES_FOR_HUMAN_REVIEW",
        )
        self.assertTrue(decision["qualified_for_human_review"])
        self.assertFalse(decision["candidate_frozen"])
        self.assertFalse(decision["paper_trading_enabled"])

    def test_failed_drawdown_gate_rejects_candidate(self):
        metrics = passing_fold_metrics()
        metrics.loc[0, "primary_maximum_drawdown"] = -0.31
        gates, _summary, decision = evaluate_gates(
            metrics,
            load_contract(),
        )

        row = gates.set_index("gate").loc[
            "gate_worst_fold_maximum_drawdown_gte_minus_30pct"
        ]
        self.assertFalse(bool(row["passed"]))
        self.assertEqual(
            decision["status"],
            "REJECT_CURRENT_STOCK_EAGLE_250_V2_CANDIDATE",
        )

    def test_source_validation_rejects_guard_band_rows(self):
        periods = period_frame()
        metrics = v1_metrics()
        ridge, validated_metrics = validate_sources(
            periods,
            metrics,
            phase1_manifest(),
        )
        self.assertEqual(ridge["fold_id"].nunique(), 14)
        self.assertEqual(validated_metrics["fold_id"].nunique(), 14)

        periods.loc[0, "timestamp_utc"] = GUARD_BAND_START_UTC
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            validate_sources(periods, metrics, phase1_manifest())


if __name__ == "__main__":
    unittest.main()
