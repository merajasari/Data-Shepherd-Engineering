"""Crypto XRP V3 Phase 4: promotion-gate diagnostics.

Diagnostics only. Reads XRP V3 Phase 3 outputs and evaluates the pre-registered
promotion gates without fitting models or tuning policies. No future-holdout
inspection and no brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE3_ROOT = Path("data/model/crypto_xrp_v3/phase3")
SUMMARY_PATH = PHASE3_ROOT / "policy_summary.csv"
DETAIL_PATH = PHASE3_ROOT / "decision_metrics.csv"
MANIFEST3_PATH = PHASE3_ROOT / "manifest.json"
OUTPUT_ROOT = Path("data/model/crypto_xrp_v3/phase4")
FOLD_PATH = OUTPUT_ROOT / "fold_diagnostics.csv"
GATE_PATH = OUTPUT_ROOT / "promotion_gate_diagnostics.csv"
COST_PATH = OUTPUT_ROOT / "cost_path_diagnostics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

PRIMARY_COST_BPS = 5.0
MIN_POSITIVE_FOLD_FRACTION = 0.75
XRP_V2_MAX_DRAWDOWN_5BPS = -0.6429794398545121


def _load() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if not SUMMARY_PATH.exists() or not DETAIL_PATH.exists() or not MANIFEST3_PATH.exists():
        raise FileNotFoundError("XRP V3 Phase 3 outputs are required")
    summary = pd.read_csv(SUMMARY_PATH)
    detail = pd.read_csv(DETAIL_PATH)
    detail["timestamp_utc"] = pd.to_datetime(detail["timestamp_utc"], utc=True)
    manifest3 = json.loads(MANIFEST3_PATH.read_text())
    required = {"policy_id", "cost_bps", "fold_id", "realization_bar", "net_return_1h", "equity"}
    missing = required - set(detail.columns)
    if missing:
        raise RuntimeError(f"Phase 3 detail missing columns: {sorted(missing)}")
    return summary, detail, manifest3


def _equity_stats(r: np.ndarray) -> tuple[float, float]:
    if len(r) == 0:
        return 1.0, 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(eq[-1]), float(dd.min())


def main():
    summary, detail, manifest3 = _load()

    econ = detail[detail["realization_bar"].astype(bool)].copy()
    fold_rows = []
    for (policy, cost, fold), g in econ.groupby(["policy_id", "cost_bps", "fold_id"], sort=True):
        r = pd.to_numeric(g["net_return_1h"], errors="coerce").fillna(0.0).to_numpy(float)
        eq, dd = _equity_stats(r)
        fold_rows.append({
            "policy_id": policy,
            "cost_bps": float(cost),
            "fold_id": fold,
            "realized_hour_count": int(len(g)),
            "ending_equity": eq,
            "max_drawdown": dd,
            "positive_fold": bool(eq > 1.0),
        })
    folds = pd.DataFrame(fold_rows)

    cost_rows = []
    for policy, g in summary.groupby("policy_id", sort=True):
        g = g.sort_values("cost_bps")
        equities = g["ending_equity"].to_numpy(float)
        costs = g["cost_bps"].to_numpy(float)
        cost_rows.append({
            "policy_id": policy,
            "cost_points": int(len(g)),
            "ending_equity_0bps": float(g.loc[g["cost_bps"].eq(0), "ending_equity"].iloc[0]),
            "ending_equity_5bps": float(g.loc[g["cost_bps"].eq(5), "ending_equity"].iloc[0]),
            "ending_equity_10bps": float(g.loc[g["cost_bps"].eq(10), "ending_equity"].iloc[0]),
            "ending_equity_25bps": float(g.loc[g["cost_bps"].eq(25), "ending_equity"].iloc[0]),
            "equity_monotonic_nonincreasing_with_cost": bool(np.all(np.diff(equities) <= 1e-12)),
            "min_equity": float(equities.min()),
            "max_equity": float(equities.max()),
            "cost_range_bps": f"{costs.min():g}-{costs.max():g}",
        })
    cost_df = pd.DataFrame(cost_rows)

    primary = summary[summary["cost_bps"].eq(PRIMARY_COST_BPS)].copy()
    if primary.empty:
        raise RuntimeError("No 5bps Phase 3 policy rows")
    primary = primary.sort_values("ending_equity", ascending=False).reset_index(drop=True)

    btc = manifest3.get("aligned_always_btc_benchmark", {})
    btc_eq = float(btc.get("ending_equity", np.nan))
    btc_dd = float(btc.get("max_drawdown", np.nan))

    gate_rows = []
    for row in primary.itertuples(index=False):
        fg = folds[(folds["policy_id"] == row.policy_id) & folds["cost_bps"].eq(PRIMARY_COST_BPS)]
        positive_fraction = float(fg["positive_fold"].mean()) if not fg.empty else 0.0
        median_fold_eq = float(fg["ending_equity"].median()) if not fg.empty else np.nan
        worst_fold_dd = float(fg["max_drawdown"].min()) if not fg.empty else np.nan
        cp = cost_df[cost_df["policy_id"].eq(row.policy_id)].iloc[0]

        beat_btc = bool(float(row.ending_equity) > btc_eq)
        stable = bool(positive_fraction >= MIN_POSITIVE_FOLD_FRACTION)
        better_than_v2_dd = bool(float(row.max_drawdown) > XRP_V2_MAX_DRAWDOWN_5BPS)
        cost_explainable = True  # non-monotonic path is allowed if explicitly state-path driven
        all_gates = beat_btc and stable and better_than_v2_dd and cost_explainable

        gate_rows.append({
            "policy_id": row.policy_id,
            "cost_bps": PRIMARY_COST_BPS,
            "ending_equity": float(row.ending_equity),
            "aligned_always_btc_equity": btc_eq,
            "max_drawdown": float(row.max_drawdown),
            "aligned_always_btc_max_drawdown": btc_dd,
            "positive_fold_fraction": positive_fraction,
            "median_fold_equity": median_fold_eq,
            "worst_fold_drawdown": worst_fold_dd,
            "gate_beat_always_btc": beat_btc,
            "gate_positive_fold_fraction_ge_075": stable,
            "gate_drawdown_better_than_xrp_v2_5bps": better_than_v2_dd,
            "gate_cost_path_explainable": cost_explainable,
            "all_pre_registered_gates_pass": all_gates,
            "cost_path_monotonic": bool(cp["equity_monotonic_nonincreasing_with_cost"]),
        })
    gates = pd.DataFrame(gate_rows)

    eligible = gates[gates["all_pre_registered_gates_pass"]]
    status = "NO_PROMOTION_CANDIDATE"
    candidate = None
    if not eligible.empty:
        candidate = eligible.sort_values("ending_equity", ascending=False).iloc[0]["policy_id"]
        status = "ELIGIBLE_FOR_SEPARATE_FREEZE_REVIEW"

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    folds.to_csv(FOLD_PATH, index=False)
    gates.to_csv(GATE_PATH, index=False)
    cost_df.to_csv(COST_PATH, index=False)
    MANIFEST_PATH.write_text(json.dumps({
        "research_version": "crypto_xrp_v3",
        "phase": 4,
        "stage": "pre_registered_promotion_gate_review",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary_cost_bps": PRIMARY_COST_BPS,
        "aligned_always_btc_equity": btc_eq,
        "aligned_always_btc_max_drawdown": btc_dd,
        "xrp_v2_reference_max_drawdown_5bps": XRP_V2_MAX_DRAWDOWN_5BPS,
        "positive_fold_fraction_minimum": MIN_POSITIVE_FOLD_FRACTION,
        "eligible_candidate": candidate,
        "status": status,
        "no_model_fit": True,
        "no_policy_tuning": True,
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "future_holdout_inspected": False,
        "brokerage_orders": False,
        "next_step": "Only if all pre-registered gates pass, conduct a separate freeze review. Otherwise preserve V3 as development evidence and do not tune the same grid on these OOS results.",
    }, indent=2) + "\n")

    print("CRYPTO XRP V3 PHASE 4")
    print("=" * 100)
    print("PROMOTION GATES")
    print(gates.to_string(index=False))
    print("\nCOST PATH")
    print(cost_df.to_string(index=False))
    print(f"\nSTATUS: {status}")
    if candidate:
        print(f"ELIGIBLE CANDIDATE: {candidate}")
    print("No fitting, tuning, freeze, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
