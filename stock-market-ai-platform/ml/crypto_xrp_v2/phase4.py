"""Crypto XRP V2 Phase 4: robustness diagnostics for corrected turnover results.

Reads corrected Phase 3 outputs only. No fitting or policy tuning occurs here.
The goal is to expose fold stability, benchmark-relative behavior, drawdown, and
cost-path sensitivity before any freeze/promotion discussion.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE1_DATASET = Path("data/model/crypto_xrp_v2/phase1/xrp_primary_15m_1h.parquet")
PHASE3_ROOT = Path("data/model/crypto_xrp_v2/phase3")
SUMMARY_PATH = PHASE3_ROOT / "policy_summary.csv"
DETAIL_PATH = PHASE3_ROOT / "decision_metrics.csv"
OUTPUT_ROOT = Path("data/model/crypto_xrp_v2/phase4")
FOLD_PATH = OUTPUT_ROOT / "fold_diagnostics.csv"
COST_PATH = OUTPUT_ROOT / "cost_path_diagnostics.csv"
BENCHMARK_PATH = OUTPUT_ROOT / "benchmark_diagnostics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


def _hourly_benchmarks() -> pd.DataFrame:
    df = pd.read_parquet(PHASE1_DATASET)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    # Same non-overlapping realization grid used by corrected Phase 3.
    h = df[(df["timestamp_utc"].dt.minute == 0) & (df["timestamp_utc"].dt.second == 0)].copy()
    if h.empty:
        raise RuntimeError("No hourly benchmark rows")
    out = []
    for state, col in [("XRP", "forward_return_1h"), ("BTC", "btc_forward_return_1h"), ("CASH", None)]:
        r = np.zeros(len(h), dtype=float) if col is None else pd.to_numeric(h[col], errors="coerce").fillna(0.0).to_numpy(float)
        eq = np.cumprod(1.0 + r)
        peak = np.maximum.accumulate(eq)
        dd = eq / peak - 1.0
        out.append({
            "benchmark": f"always_{state.lower()}",
            "realized_hour_count": int(len(h)),
            "ending_equity": float(eq[-1]),
            "max_drawdown": float(dd.min()),
            "mean_return_1h": float(np.mean(r)),
        })
    return pd.DataFrame(out)


def main():
    if not SUMMARY_PATH.exists() or not DETAIL_PATH.exists():
        raise FileNotFoundError("Corrected XRP V2 Phase 3 outputs are required")
    summary = pd.read_csv(SUMMARY_PATH)
    detail = pd.read_csv(DETAIL_PATH)
    detail["timestamp_utc"] = pd.to_datetime(detail["timestamp_utc"], utc=True)

    required = {"policy_id", "cost_bps", "fold_id", "net_return_1h", "equity", "switch"}
    missing = required - set(detail.columns)
    if missing:
        raise RuntimeError(f"Phase 3 detail missing columns: {sorted(missing)}")

    fold_rows = []
    # Restrict fold compounding to actual hourly economic realization rows.
    econ = detail[pd.to_numeric(detail["net_return_1h"], errors="coerce").notna()].copy()
    for (policy, cost, fold), g in econ.groupby(["policy_id", "cost_bps", "fold_id"], sort=True):
        r = pd.to_numeric(g["net_return_1h"], errors="coerce").fillna(0.0).to_numpy(float)
        eq = np.cumprod(1.0 + r)
        peak = np.maximum.accumulate(eq)
        dd = eq / peak - 1.0
        fold_rows.append({
            "policy_id": policy,
            "cost_bps": float(cost),
            "fold_id": fold,
            "realized_hour_count": int(len(g)),
            "ending_equity": float(eq[-1]) if len(eq) else 1.0,
            "max_drawdown": float(dd.min()) if len(dd) else 0.0,
            "mean_net_return_1h": float(np.mean(r)) if len(r) else 0.0,
            "positive_fold": bool(float(eq[-1]) > 1.0) if len(eq) else False,
        })
    folds = pd.DataFrame(fold_rows)

    path_rows = []
    for policy, g in summary.groupby("policy_id", sort=True):
        g = g.sort_values("cost_bps")
        equities = g["ending_equity"].to_numpy(float)
        costs = g["cost_bps"].to_numpy(float)
        monotonic = bool(np.all(np.diff(equities) <= 1e-12))
        path_rows.append({
            "policy_id": policy,
            "cost_points": int(len(g)),
            "ending_equity_0bps": float(g.loc[g["cost_bps"].eq(0), "ending_equity"].iloc[0]) if g["cost_bps"].eq(0).any() else np.nan,
            "ending_equity_5bps": float(g.loc[g["cost_bps"].eq(5), "ending_equity"].iloc[0]) if g["cost_bps"].eq(5).any() else np.nan,
            "ending_equity_10bps": float(g.loc[g["cost_bps"].eq(10), "ending_equity"].iloc[0]) if g["cost_bps"].eq(10).any() else np.nan,
            "ending_equity_25bps": float(g.loc[g["cost_bps"].eq(25), "ending_equity"].iloc[0]) if g["cost_bps"].eq(25).any() else np.nan,
            "equity_monotonic_nonincreasing_with_cost": monotonic,
            "cost_hurdle_changes_state_path": not monotonic,
            "min_equity": float(equities.min()),
            "max_equity": float(equities.max()),
            "cost_range_bps": f"{costs.min():g}-{costs.max():g}",
        })
    cost_path = pd.DataFrame(path_rows)
    benchmarks = _hourly_benchmarks()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    folds.to_csv(FOLD_PATH, index=False)
    cost_path.to_csv(COST_PATH, index=False)
    benchmarks.to_csv(BENCHMARK_PATH, index=False)

    fold_stability = (
        folds.groupby(["policy_id", "cost_bps"], sort=True)
        .agg(fold_count=("fold_id", "nunique"), positive_fold_fraction=("positive_fold", "mean"), median_fold_equity=("ending_equity", "median"), worst_fold_drawdown=("max_drawdown", "min"))
        .reset_index()
    )
    best_5 = summary[summary["cost_bps"].eq(5)].sort_values("ending_equity", ascending=False).head(1)
    candidate = best_5.iloc[0]["policy_id"] if not best_5.empty else None
    candidate_stability = fold_stability[(fold_stability["policy_id"] == candidate) & fold_stability["cost_bps"].eq(5)] if candidate else pd.DataFrame()
    positive_fraction = float(candidate_stability["positive_fold_fraction"].iloc[0]) if not candidate_stability.empty else 0.0
    max_dd = float(best_5["max_drawdown"].iloc[0]) if not best_5.empty else -1.0

    # Conservative gate: no freeze if fold stability is weak or drawdown is extreme.
    status = "CONTINUE_DIAGNOSTICS_NO_FREEZE"
    if candidate is None:
        status = "NO_CANDIDATE"
    elif positive_fraction >= 0.75 and max_dd > -0.50 and not bool(cost_path.loc[cost_path["policy_id"].eq(candidate), "cost_hurdle_changes_state_path"].iloc[0]):
        status = "ELIGIBLE_FOR_SEPARATE_FREEZE_REVIEW"

    MANIFEST_PATH.write_text(json.dumps({
        "research_version": "crypto_xrp_v2",
        "phase": 4,
        "stage": "robustness_and_path_sensitivity_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_phase3_accounting": "corrected non-overlapping hourly economic realization with 15-minute decisions",
        "best_5bps_policy_by_aggregate_equity": candidate,
        "best_5bps_positive_fold_fraction": positive_fraction,
        "best_5bps_max_drawdown": max_dd,
        "status": status,
        "important_interpretation": "Higher cost can change the executed state path because cost is part of the switching hurdle. Therefore non-monotonic equity across cost scenarios is path sensitivity, not evidence that higher fees improve performance.",
        "no_new_model_fit": True,
        "no_policy_tuning": True,
        "frozen_xrp_v1_modified": False,
        "brokerage_orders": False,
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "next_step": "Review fold diagnostics, benchmark comparison, and path sensitivity. Do not freeze XRP V2 unless stability and drawdown gates are satisfied.",
    }, indent=2) + "\n")

    print("CRYPTO XRP V2 PHASE 4")
    print("=" * 100)
    print("BENCHMARKS")
    print(benchmarks.to_string(index=False))
    print("\nCOST PATH")
    print(cost_path.to_string(index=False))
    print("\nFOLD STABILITY")
    print(fold_stability.to_string(index=False))
    print(f"\nSTATUS: {status}")
    print("No fitting, tuning, freeze, promotion, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
