"""Crypto V6 Phase 3: common-clock, cost-aware comparison against V5.

The report is deliberately non-promotional.  Even a passing development result
remains a research challenger pending explicit human review and a separately
preregistered holdout decision.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v5.config import ALL_HORIZONS_DAYS, FUTURE_HOLDOUT_START_UTC, ROUND_TRIP_COST_BPS
from ml.crypto_v5.phase3 import MODELS, TOP_COUNTS, simulate, summarize
from ml.crypto_v5.phase4 import (
    SELECTED_COST_BPS,
    SELECTED_HORIZON_DAYS,
    SELECTED_MODEL_ID,
    SELECTED_TOP_N,
    STRESS_COST_BPS,
)
from ml.crypto_v6.phase2 import FEATURE_SET_V5, FEATURE_SET_V6, OUTPUT_ROOT as PHASE2_ROOT


RESEARCH_VERSION = "crypto_v6"
OUTPUT_ROOT = PHASE2_ROOT.parent / "phase3"


def _candidate(metrics, feature_set, cost_bps):
    rows = metrics[
        (metrics["feature_set"] == feature_set)
        & (metrics["model_id"] == SELECTED_MODEL_ID)
        & (metrics["horizon_days"] == SELECTED_HORIZON_DAYS)
        & (metrics["top_n"] == SELECTED_TOP_N)
        & np.isclose(metrics["cost_bps_round_trip"], cost_bps)
    ]
    if len(rows) != 1:
        raise ValueError(f"Expected one {feature_set} candidate at {cost_bps:g} bps; found {len(rows)}")
    return rows.iloc[0]


def _finite(value):
    return None if pd.isna(value) else float(value)


def compare_candidates(metrics):
    """Apply the preregistered paired development checks without promotion."""
    v5_primary = _candidate(metrics, FEATURE_SET_V5, SELECTED_COST_BPS)
    v6_primary = _candidate(metrics, FEATURE_SET_V6, SELECTED_COST_BPS)
    v5_stress = _candidate(metrics, FEATURE_SET_V5, STRESS_COST_BPS)
    v6_stress = _candidate(metrics, FEATURE_SET_V6, STRESS_COST_BPS)
    checks = {
        "v6_beats_v5_ending_equity_primary_cost": bool(
            v6_primary["ending_equity"] > v5_primary["ending_equity"]
        ),
        "v6_beats_v5_sharpe_primary_cost": bool(
            pd.notna(v6_primary["sharpe"])
            and pd.notna(v5_primary["sharpe"])
            and v6_primary["sharpe"] > v5_primary["sharpe"]
        ),
        "v6_drawdown_not_worse_primary_cost": bool(
            v6_primary["maximum_drawdown"] >= v5_primary["maximum_drawdown"]
        ),
        "v6_beats_v5_ending_equity_stress_cost": bool(
            v6_stress["ending_equity"] > v5_stress["ending_equity"]
        ),
        "v6_profitable_stress_cost": bool(v6_stress["ending_equity"] > 1.0),
    }
    return {
        "passed_all_development_checks": all(checks.values()),
        "checks": checks,
        "primary_cost_bps": SELECTED_COST_BPS,
        "stress_cost_bps": STRESS_COST_BPS,
        "v5_primary": {
            "ending_equity": float(v5_primary["ending_equity"]),
            "sharpe": _finite(v5_primary["sharpe"]),
            "maximum_drawdown": float(v5_primary["maximum_drawdown"]),
        },
        "v6_primary": {
            "ending_equity": float(v6_primary["ending_equity"]),
            "sharpe": _finite(v6_primary["sharpe"]),
            "maximum_drawdown": float(v6_primary["maximum_drawdown"]),
        },
        "v5_stress_ending_equity": float(v5_stress["ending_equity"]),
        "v6_stress_ending_equity": float(v6_stress["ending_equity"]),
        "automatic_promotion": False,
        "dashboard_validation_status": "NOT_VALIDATED_REQUIRES_HUMAN_REVIEW",
    }


def _assert_identical_clock(periods):
    keys = ["model_id", "horizon_days", "top_n", "cost_bps_round_trip"]
    for key, group in periods.groupby(keys):
        clocks = {
            feature_set: tuple(
                group[group["feature_set"] == feature_set]["timestamp_utc"].sort_values()
            )
            for feature_set in (FEATURE_SET_V5, FEATURE_SET_V6)
        }
        if not clocks[FEATURE_SET_V5] or clocks[FEATURE_SET_V5] != clocks[FEATURE_SET_V6]:
            raise RuntimeError(f"V5/V6 portfolio clock mismatch for {key}")


def run(phase2_root=PHASE2_ROOT, output_root=OUTPUT_ROOT):
    phase2_root, output_root = Path(phase2_root), Path(output_root)
    allocation = pd.read_parquet(phase2_root / "allocation_predictions.parquet")
    ranking = pd.read_parquet(phase2_root / "ranking_predictions.parquet")
    for frame in (allocation, ranking):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
        if (frame["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
            raise RuntimeError("Crypto V6 Phase 3 refuses future-holdout rows")
    frames, metric_rows = [], []
    for feature_set in (FEATURE_SET_V5, FEATURE_SET_V6):
        feature_allocation = allocation[allocation["feature_set"] == feature_set]
        feature_ranking = ranking[ranking["feature_set"] == feature_set]
        for model in MODELS:
            for horizon in ALL_HORIZONS_DAYS:
                for top_n in TOP_COUNTS:
                    for cost in ROUND_TRIP_COST_BPS:
                        frame = simulate(feature_allocation, feature_ranking, model, horizon, top_n, cost)
                        if frame.empty:
                            raise ValueError(f"Empty {feature_set} portfolio {model}/{horizon}/{top_n}/{cost}")
                        frame.insert(0, "feature_set", feature_set)
                        summary = summarize(frame)
                        summary["feature_set"] = feature_set
                        frames.append(frame)
                        metric_rows.append(summary)
    periods = pd.concat(frames, ignore_index=True)
    metrics = pd.DataFrame(metric_rows).sort_values(
        ["horizon_days", "model_id", "top_n", "cost_bps_round_trip", "feature_set"]
    )
    _assert_identical_clock(periods)
    comparison = compare_candidates(metrics)
    output_root.mkdir(parents=True, exist_ok=True)
    periods_output = output_root / "paired_portfolio_periods.parquet"
    metrics_output = output_root / "paired_portfolio_metrics.csv"
    comparison_output = output_root / "v6_vs_v5_comparison.json"
    periods.to_parquet(periods_output, index=False)
    metrics.to_csv(metrics_output, index=False)
    comparison_output.write_text(json.dumps(comparison, indent=2) + "\n")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "v6_vs_v5_common_clock_development_comparison",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "identical_market_periods_verified": True,
        "development_result": comparison,
        "classification": (
            "DEVELOPMENT_CHALLENGER_PASSED_REQUIRES_HUMAN_REVIEW"
            if comparison["passed_all_development_checks"]
            else "DEVELOPMENT_CHALLENGER_DID_NOT_PASS"
        ),
        "dashboard_eligibility": False,
        "dashboard_reason": "V6 remains unvalidated until human review and any separately preregistered holdout step are complete.",
        "outputs": {
            "portfolio_periods": str(periods_output),
            "portfolio_metrics": str(metrics_output),
            "comparison": str(comparison_output),
        },
        "safety": {
            "crypto_v5_modified": False,
            "holdout_scored": False,
            "paper_state_modified": False,
            "dashboard_modified": False,
            "automatic_promotion": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Human review of the paired evidence; no dashboard validation or activation is automatic."
        ),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase2_root, args.output), indent=2))


if __name__ == "__main__":
    main()
