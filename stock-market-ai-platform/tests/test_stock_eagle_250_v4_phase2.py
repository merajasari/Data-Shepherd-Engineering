import unittest

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v4.phase1 import (
    CONTRACT_PATH,
    GUARD_BAND_START_UTC,
    V4_CANDIDATE,
    _sha256,
    load_contract,
)
from ml.stock_eagle_250_v4.phase2 import (
    attach_confidence_exposure,
    diagnostic_summaries,
    evaluate_gates,
    simulate_exposure,
    validate_sources,
)


def prediction_frame():
    rows = []
    timestamps = pd.date_range(
        "2026-01-02",
        periods=70,
        freq="B",
        tz="UTC",
    )
    for session_index, timestamp in enumerate(timestamps):
        fold_id = f"dev_{session_index % 14 + 1:02d}"
        for symbol_index in range(25):
            rows.append({
                "fold_id": fold_id,
                "timestamp_utc": timestamp,
                "entry_timestamp_utc_5d": timestamp,
                "target_endpoint_utc_5d": (
                    "2026-09-22T00:00:00+00:00"
                    if session_index == len(timestamps) - 1
                    else timestamp
                ),
                "symbol": f"S{symbol_index:03d}",
                "prediction_ridge_fixed_v1":
                    0.03 - symbol_index * (0.0002 + session_index * 0.000001),
            })
    return pd.DataFrame(rows)


def period_frame(predictions=None):
    predictions = prediction_frame() if predictions is None else predictions
    rows = []
    for timestamp, group in predictions.groupby("timestamp_utc", sort=True):
        ordered = group.sort_values(
            ["prediction_ridge_fixed_v1", "symbol"],
            ascending=[False, True],
        )
        selected = ordered.head(10)
        gross = 0.01
        rows.append({
            "fold_id": str(ordered.iloc[0]["fold_id"]),
            "portfolio_id": "ridge_fixed_v1",
            "timestamp_utc": timestamp,
            "entry_timestamp_utc_5d": timestamp,
            "target_endpoint_utc_5d": (
                "2026-09-22T00:00:00+00:00"
                if timestamp == predictions["timestamp_utc"].max()
                else timestamp
            ),
            "selected_symbols": ",".join(selected["symbol"]),
            "selected_count": 10,
            "gross_return": gross,
            "net_return": (
                (1.0 + gross) * (1.0 - 0.001) ** 2 - 1.0
            ),
        })
    return pd.DataFrame(rows)


def v1_metrics(periods):
    rows = []
    for fold_id, fold in periods.groupby("fold_id", sort=True):
        # Tests only require consistent schema/folds for validation.
        rows.append({
            "fold_id": fold_id,
            "candidate_id": "ridge_fixed_v1",
            "net_return": 0.01,
            "maximum_drawdown": -0.1,
            "spy_net_return": 0.0,
            "equal_weight_net_return": 0.0,
        })
    return pd.DataFrame(rows)


def phase1_manifest():
    return {
        "research_version": "stock_eagle_250_v4_confidence_conditioned_ridge",
        "candidate_id": V4_CANDIDATE,
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v4_performance_calculated": False,
        "contract_sha256": _sha256(CONTRACT_PATH),
        "gate_policy": "reuse_v2_v3_gates_without_relaxation",
    }


def passing_fold_metrics():
    rows = []
    for index in range(10):
        rows.append({
            "fold_id": f"fold_{index:02d}",
            "confidence_ready_fraction": 1.0,
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
            "mean_gross_exposure": 0.75,
        })
    return pd.DataFrame(rows)


class StockEagle250V4Phase2Test(unittest.TestCase):
    def test_source_validation_preserves_v1_top10_and_boundaries(self):
        predictions = prediction_frame()
        periods = period_frame(predictions)
        metrics = v1_metrics(periods)

        ridge, validated_metrics, confidence = validate_sources(
            predictions,
            periods,
            metrics,
            phase1_manifest(),
        )
        self.assertEqual(ridge["fold_id"].nunique(), 14)
        self.assertEqual(validated_metrics["fold_id"].nunique(), 14)
        self.assertEqual(len(confidence), predictions["timestamp_utc"].nunique())

        bad = periods.copy()
        bad.loc[0, "timestamp_utc"] = GUARD_BAND_START_UTC
        with self.assertRaisesRegex(RuntimeError, "guard band"):
            validate_sources(
                predictions,
                bad,
                metrics,
                phase1_manifest(),
            )

    def test_source_validation_rejects_changed_top10_selection(self):
        predictions = prediction_frame()
        periods = period_frame(predictions)
        metrics = v1_metrics(periods)
        periods.loc[0, "selected_symbols"] = "X,Y,Z,A,B,C,D,E,F,G"

        with self.assertRaisesRegex(RuntimeError, "selection differs"):
            validate_sources(
                predictions,
                periods,
                metrics,
                phase1_manifest(),
            )

    def test_attach_confidence_matches_fold_and_exposure_band(self):
        predictions = prediction_frame()
        periods = period_frame(predictions)
        metrics = v1_metrics(periods)
        ridge, _metrics, confidence = validate_sources(
            predictions,
            periods,
            metrics,
            phase1_manifest(),
        )
        merged = attach_confidence_exposure(ridge, confidence)

        self.assertTrue(merged["gross_exposure"].between(0.5, 1.0).all())
        self.assertTrue(
            (
                merged["confidence_fold_id"].astype(str)
                == merged["fold_id"].astype(str)
            ).all()
        )

    def test_diagnostics_support_not_ready_confidence_rows(self):
        frame = pd.DataFrame({
            "evaluation": ["v4_primary_10bps", "v4_primary_10bps"],
            "confidence_percentile": [np.nan, 0.9],
            "gross_exposure": [0.5, 0.95],
            "standardized_confidence": [0.4, 1.7],
            "gross_return": [0.01, 0.02],
            "net_return": [0.003, 0.015],
            "timestamp_utc": [
                "2026-01-02T00:00:00+00:00",
                "2026-01-05T00:00:00+00:00",
            ],
        })
        confidence, year = diagnostic_summaries(frame)

        self.assertIn("NOT_READY", set(confidence["confidence_band"]))
        self.assertIn("P80_100", set(confidence["confidence_band"]))
        self.assertEqual(int(year["periods"].sum()), 2)

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
        self.assertEqual(decision["candidate_id"], V4_CANDIDATE)
        self.assertTrue(decision["qualified_for_human_review"])
        self.assertFalse(decision["candidate_frozen"])
        self.assertFalse(decision["paper_trading_enabled"])

    def test_failed_drawdown_gate_rejects_v4_candidate(self):
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
            "REJECT_CURRENT_STOCK_EAGLE_250_V4_CANDIDATE",
        )


if __name__ == "__main__":
    unittest.main()
