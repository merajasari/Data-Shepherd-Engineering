import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v5.phase1 import (
    CONTRACT_PATH,
    GUARD_BAND_START_UTC,
    V5_CANDIDATE,
    _sha256,
    load_contract,
    self_drawdown_exposure_frame,
)
from ml.stock_eagle_250_v5.phase2 import (
    attach_risk_state,
    diagnostic_summaries,
    evaluate_gates,
    simulate_exposure,
    validate_sources,
)


def period_frame():
    rows = []
    timestamps = pd.date_range(
        "2026-01-02",
        periods=70,
        freq="B",
        tz="UTC",
    )
    for index, timestamp in enumerate(timestamps):
        fold_id = f"dev_{index % 14 + 1:02d}"
        gross = 0.01
        rows.append({
            "fold_id": fold_id,
            "portfolio_id": "ridge_fixed_v1",
            "timestamp_utc": (
                pd.Timestamp("2026-09-15", tz="UTC")
                if index == len(timestamps) - 1
                else timestamp
            ),
            "entry_timestamp_utc_5d": timestamp,
            "target_endpoint_utc_5d": (
                pd.Timestamp("2026-09-22", tz="UTC")
                if index == len(timestamps) - 1
                else timestamp
            ),
            "selected_symbols": "A,B,C,D,E,F,G,H,I,J",
            "selected_count": 10,
            "gross_return": gross,
            "net_return": (
                (1.0 + gross) * (1.0 - 0.001) ** 2 - 1.0
            ),
        })
    return pd.DataFrame(rows)


def v1_metrics(periods):
    rows = []
    for fold_id in sorted(periods["fold_id"].unique()):
        rows.append({
            "fold_id": fold_id,
            "candidate_id": "ridge_fixed_v1",
            "net_return": 0.0,
            "maximum_drawdown": 0.0,
            "spy_net_return": 0.0,
            "equal_weight_net_return": 0.0,
        })
    return pd.DataFrame(rows)


def phase1_manifest():
    return {
        "research_version": "stock_eagle_250_v5_self_drawdown_throttled_ridge",
        "candidate_id": V5_CANDIDATE,
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v5_performance_calculated": False,
        "contract_sha256": _sha256(CONTRACT_PATH),
        "gate_policy": "reuse_v2_v3_v4_gates_without_relaxation",
    }


def passing_fold_metrics():
    rows = []
    for index in range(10):
        rows.append({
            "fold_id": f"fold_{index:02d}",
            "mean_shadow_drawdown": -0.05,
            "worst_shadow_drawdown": -0.15,
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
            "mean_gross_exposure": 0.80,
        })
    return pd.DataFrame(rows)


class StockEagle250V5Phase2Test(unittest.TestCase):
    def test_source_validation_preserves_phase1_and_rejects_guard_band(self):
        periods = period_frame()
        metrics = v1_metrics(periods)

        ridge, validated_metrics, risk = validate_sources(
            periods,
            metrics,
            phase1_manifest(),
        )
        self.assertEqual(ridge["fold_id"].nunique(), 14)
        self.assertEqual(validated_metrics["fold_id"].nunique(), 14)
        self.assertEqual(len(risk), len(ridge))

        bad = periods.copy()
        bad.loc[0, "timestamp_utc"] = GUARD_BAND_START_UTC
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            validate_sources(
                bad,
                metrics,
                phase1_manifest(),
            )

    def test_attach_risk_state_matches_fold_and_fixed_exposure_band(self):
        periods = period_frame()
        ridge = periods.copy()
        risk = self_drawdown_exposure_frame(ridge)
        merged = attach_risk_state(ridge, risk)

        self.assertTrue(merged["gross_exposure"].between(0.5, 1.0).all())
        self.assertTrue(
            (
                merged["risk_fold_id"].astype(str)
                == merged["fold_id"].astype(str)
            ).all()
        )

    def test_partial_exposure_scales_returns_and_costs(self):
        periods = period_frame().head(1).copy()
        periods["gross_exposure"] = 0.5
        result, _ = simulate_exposure(periods, 10.0)
        expected = (
            (1.0 + 0.5 * 0.01)
            * (1.0 - 0.5 * 0.001) ** 2
            - 1.0
        )
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
        self.assertEqual(decision["status"], "QUALIFIES_FOR_HUMAN_REVIEW")
        self.assertEqual(decision["candidate_id"], V5_CANDIDATE)
        self.assertTrue(decision["qualified_for_human_review"])
        self.assertFalse(decision["development_iteration_must_stop"])
        self.assertFalse(decision["candidate_frozen"])
        self.assertFalse(decision["paper_trading_enabled"])

    def test_failed_gate_rejects_v5_and_triggers_stopping_rule(self):
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
            "REJECT_CURRENT_STOCK_EAGLE_250_V5_CANDIDATE",
        )
        self.assertTrue(decision["development_iteration_must_stop"])

    def test_drawdown_diagnostics_preserve_risk_bands(self):
        frame = pd.DataFrame({
            "evaluation": [
                "v5_primary_10bps",
                "v5_primary_10bps",
                "v5_primary_10bps",
            ],
            "shadow_drawdown": [-0.02, -0.08, -0.22],
            "gross_exposure": [0.95, 0.80, 0.50],
            "gross_return": [0.01, -0.01, 0.02],
            "net_return": [0.008, -0.009, 0.008],
            "timestamp_utc": [
                "2026-01-02T00:00:00+00:00",
                "2026-01-05T00:00:00+00:00",
                "2026-01-06T00:00:00+00:00",
            ],
        })
        drawdown, year = diagnostic_summaries(frame)

        bands = set(drawdown["shadow_drawdown_band"].astype(str))
        self.assertIn("GT_MINUS_5_TO_0", bands)
        self.assertIn("GT_MINUS_10_TO_MINUS_5", bands)
        self.assertIn("LE_MINUS_20", bands)
        self.assertEqual(int(year["periods"].sum()), 3)


if __name__ == "__main__":
    unittest.main()
