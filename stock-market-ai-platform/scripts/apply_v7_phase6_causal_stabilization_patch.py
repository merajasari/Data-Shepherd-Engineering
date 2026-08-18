"""Apply isolated Stock V7 Phase 6 causal stabilization-state diagnostics."""

from pathlib import Path

PHASE6 = Path("ml/v7/phase6.py")


def main():
    PHASE6.parent.mkdir(parents=True, exist_ok=True)
    PHASE6.write_text(r'''"""Stock V7 Phase 6: causal stabilization-state diagnostics.

Purpose
-------
Phase 5 showed that the fully-confounder-controlled V7 residual signal behaves
very differently depending on what the broad market does next after a prior
20-session SPY decline of at least 5%. Future SPY direction cannot be used in a
real decision. Phase 6 therefore asks whether information already known at the
current close can distinguish deteriorating versus stabilizing conditions.

The stabilization indicators are fixed before Phase 6 results are inspected:
* SPY current-session return > 0
* SPY trailing 5-session return > 0
* >50% of the 100-stock universe has positive current-session return
* >50% of the 100-stock universe has positive trailing 5-session return

A fixed stabilization score is the count of those four conditions:
* 0-1 = DETERIORATING
* 2   = MIXED
* 3-4 = STABILIZING

These states are explanatory diagnostics only. Phase 6 does not optimize a
threshold, select a portfolio, freeze a candidate, or score the 2026-09-01+
holdout.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v7.config import FUTURE_HOLDOUT_START_UTC
from ml.v7.phase4 import (
    TARGET,
    VOL,
    CONTROL_SETS,
    _add_beta,
    _load_panel,
    _load_spy,
    _rank_corr,
    _residualize,
)

PHASE = 6
PRIMARY_DECLINE_CUTOFF = -0.05
OUTPUT_ROOT = Path("data/model/v7/phase6")
DAILY_PATH = OUTPUT_ROOT / "daily_stabilization_diagnostics.csv"
STATE_PATH = OUTPUT_ROOT / "stabilization_state_summary.csv"
INDICATOR_PATH = OUTPUT_ROOT / "indicator_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_stability.csv"
PATH_PATH = OUTPUT_ROOT / "future_path_diagnostic.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
SPY_FEATURE_PATH = Path("data/features/stocks/SPY/SPY_features.parquet")

FOLDS = (
    ("dev_01", "2022-01-01", "2022-07-01"),
    ("dev_02", "2022-07-01", "2023-01-01"),
    ("dev_03", "2023-01-01", "2023-07-01"),
    ("dev_04", "2023-07-01", "2024-01-01"),
    ("dev_05", "2024-01-01", "2024-07-01"),
    ("dev_06", "2024-07-01", "2025-01-01"),
    ("dev_07", "2025-01-01", "2025-07-01"),
    ("dev_08", "2025-07-01", "2026-01-01"),
    ("dev_09", "2026-01-01", "2026-07-01"),
    ("dev_10", "2026-07-01", "2026-09-01"),
)


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _fold_id(ts):
    for fold_id, start, end in FOLDS:
        if _utc(start) <= ts < _utc(end):
            return fold_id
    return None


def _spy_causal_features():
    if not SPY_FEATURE_PATH.exists():
        raise FileNotFoundError(f"Missing SPY features: {SPY_FEATURE_PATH}")
    spy = pd.read_parquet(SPY_FEATURE_PATH).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in spy.columns else "timestamp"
    spy["timestamp_utc"] = pd.to_datetime(spy[ts_col], utc=True)
    required = {"timestamp_utc", "daily_return", "return_5d", "return_20d", "close"}
    missing = sorted(required - set(spy.columns))
    if missing:
        raise ValueError("SPY Phase 6 features missing columns: " + ", ".join(missing))
    spy = spy.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    spy["spy_forward_return_5d"] = spy["close"].shift(-5) / spy["close"] - 1.0
    return spy[[
        "timestamp_utc", "daily_return", "return_5d", "return_20d", "spy_forward_return_5d"
    ]].rename(columns={
        "daily_return": "spy_daily_return",
        "return_5d": "spy_return_5d",
        "return_20d": "spy_return_20d",
    })


def _build_daily():
    panel = _add_beta(_load_panel(), _load_spy())
    controls = CONTROL_SETS["full_confounders"]
    spy = _spy_causal_features()

    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        if ts >= FUTURE_HOLDOUT_START_UTC or day[TARGET].notna().sum() < 20:
            continue

        resid_signal = _residualize(day, VOL, controls)
        resid_target = _residualize(day, TARGET, controls)
        residual_ic = _rank_corr(resid_signal, resid_target)
        raw_ic = _rank_corr(day[VOL], day[TARGET])

        rows.append({
            "timestamp_utc": ts,
            "fold_id": _fold_id(ts),
            "raw_ic": raw_ic,
            "full_residual_ic": residual_ic,
            "breadth_daily_positive": float((day["daily_return"] > 0).mean()),
            "breadth_5d_positive": float((day["return_5d"] > 0).mean()),
        })

    daily = pd.DataFrame(rows).merge(spy, on="timestamp_utc", how="left", validate="one_to_one")
    daily = daily[daily["spy_return_20d"] <= PRIMARY_DECLINE_CUTOFF].copy()

    daily["ind_spy_daily_up"] = daily["spy_daily_return"] > 0
    daily["ind_spy_5d_up"] = daily["spy_return_5d"] > 0
    daily["ind_breadth_daily_majority_up"] = daily["breadth_daily_positive"] > 0.50
    daily["ind_breadth_5d_majority_up"] = daily["breadth_5d_positive"] > 0.50

    indicator_cols = [
        "ind_spy_daily_up",
        "ind_spy_5d_up",
        "ind_breadth_daily_majority_up",
        "ind_breadth_5d_majority_up",
    ]
    daily["stabilization_score"] = daily[indicator_cols].astype(int).sum(axis=1)
    daily["stabilization_state"] = np.select(
        [daily["stabilization_score"] <= 1, daily["stabilization_score"] >= 3],
        ["DETERIORATING", "STABILIZING"],
        default="MIXED",
    )

    # Future path is diagnostic only and is never used to define a causal state.
    daily["future_path"] = np.select(
        [daily["spy_forward_return_5d"] < -0.02, daily["spy_forward_return_5d"] > 0.02],
        ["NEXT_5D_DOWN", "NEXT_5D_UP"],
        default="NEXT_5D_FLAT",
    )
    return daily


def _state_summary(daily):
    return (
        daily.groupby("stabilization_state", observed=True)
        .agg(
            days=("timestamp_utc", "nunique"),
            mean_score=("stabilization_score", "mean"),
            mean_full_residual_ic=("full_residual_ic", "mean"),
            median_full_residual_ic=("full_residual_ic", "median"),
            residual_ic_hit_rate=("full_residual_ic", lambda s: s.gt(0).mean()),
            mean_raw_ic=("raw_ic", "mean"),
            mean_spy_forward_return_5d=("spy_forward_return_5d", "mean"),
            next_5d_down_fraction=("spy_forward_return_5d", lambda s: s.lt(-0.02).mean()),
            next_5d_non_down_fraction=("spy_forward_return_5d", lambda s: s.ge(-0.02).mean()),
        )
        .reset_index()
    )


def _indicator_summary(daily):
    rows = []
    indicators = [
        "ind_spy_daily_up",
        "ind_spy_5d_up",
        "ind_breadth_daily_majority_up",
        "ind_breadth_5d_majority_up",
    ]
    for indicator in indicators:
        for active in [False, True]:
            g = daily[daily[indicator] == active]
            rows.append({
                "indicator": indicator,
                "active": active,
                "days": int(len(g)),
                "mean_full_residual_ic": float(g["full_residual_ic"].mean()) if len(g) else np.nan,
                "residual_ic_hit_rate": float((g["full_residual_ic"] > 0).mean()) if len(g) else np.nan,
                "mean_spy_forward_return_5d": float(g["spy_forward_return_5d"].mean()) if len(g) else np.nan,
                "next_5d_down_fraction": float((g["spy_forward_return_5d"] < -0.02).mean()) if len(g) else np.nan,
            })
    return pd.DataFrame(rows)


def _fold_summary(daily):
    rows = []
    for state in ["DETERIORATING", "MIXED", "STABILIZING"]:
        for fold_id, _, _ in FOLDS:
            g = daily[(daily["stabilization_state"] == state) & (daily["fold_id"] == fold_id)]
            rows.append({
                "stabilization_state": state,
                "fold_id": fold_id,
                "days": int(len(g)),
                "mean_full_residual_ic": float(g["full_residual_ic"].mean()) if len(g) else np.nan,
                "residual_ic_hit_rate": float((g["full_residual_ic"] > 0).mean()) if len(g) else np.nan,
                "next_5d_down_fraction": float((g["spy_forward_return_5d"] < -0.02).mean()) if len(g) else np.nan,
            })
    return pd.DataFrame(rows)


def _future_path_summary(daily):
    return (
        daily.groupby(["stabilization_state", "future_path"], observed=True)
        .agg(
            days=("timestamp_utc", "nunique"),
            mean_full_residual_ic=("full_residual_ic", "mean"),
            residual_ic_hit_rate=("full_residual_ic", lambda s: s.gt(0).mean()),
            mean_spy_forward_return_5d=("spy_forward_return_5d", "mean"),
        )
        .reset_index()
    )


def main():
    daily = _build_daily()
    states = _state_summary(daily)
    indicators = _indicator_summary(daily)
    folds = _fold_summary(daily)
    future_paths = _future_path_summary(daily)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    states.to_csv(STATE_PATH, index=False)
    indicators.to_csv(INDICATOR_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    future_paths.to_csv(PATH_PATH, index=False)

    state_map = states.set_index("stabilization_state")
    stab = state_map.loc["STABILIZING"] if "STABILIZING" in state_map.index else None
    det = state_map.loc["DETERIORATING"] if "DETERIORATING" in state_map.index else None

    gates = {
        "at_least_20_stabilizing_days": bool(stab is not None and stab["days"] >= 20),
        "stabilizing_residual_ic_positive": bool(stab is not None and stab["mean_full_residual_ic"] > 0),
        "stabilizing_hit_rate_above_52pct": bool(stab is not None and stab["residual_ic_hit_rate"] > 0.52),
        "stabilizing_ic_exceeds_deteriorating": bool(
            stab is not None and det is not None
            and stab["mean_full_residual_ic"] > det["mean_full_residual_ic"]
        ),
        "stabilizing_future_down_fraction_below_deteriorating": bool(
            stab is not None and det is not None
            and stab["next_5d_down_fraction"] < det["next_5d_down_fraction"]
        ),
    }

    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_causal_stabilization_state_diagnostics",
        "objective": (
            "Determine whether current-close information can distinguish deteriorating "
            "from stabilizing conditions after a prior 20-session SPY decline of at least 5%, "
            "without using future market direction to form the state."
        ),
        "primary_decline_cutoff": PRIMARY_DECLINE_CUTOFF,
        "causal_indicators": [
            "SPY daily return > 0",
            "SPY trailing 5-session return > 0",
            "100-stock breadth daily-positive fraction > 50%",
            "100-stock breadth trailing-5-session-positive fraction > 50%",
        ],
        "stabilization_score_contract": {
            "DETERIORATING": "0-1 active indicators",
            "MIXED": "2 active indicators",
            "STABILIZING": "3-4 active indicators",
        },
        "future_path_used_only_for_diagnostics": True,
        "robustness_gates": gates,
        "all_robustness_gates_passed": bool(all(gates.values())),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_selection": False,
            "portfolio_simulation": False,
            "portfolio_policy_tuning": False,
            "threshold_optimization": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 6")
    print("=" * 104)
    print("Causal stabilization-state diagnostics after prior SPY 20-session decline <= -5%")
    print("No future SPY path is used to form a state")
    print()
    print("===== STABILIZATION STATES =====")
    print(states.to_string(index=False))
    print()
    print("===== INDICATOR DIAGNOSTICS =====")
    print(indicators.to_string(index=False))
    print()
    print("===== CHRONOLOGICAL FOLDS =====")
    print(folds.to_string(index=False))
    print()
    print("===== FUTURE PATH DIAGNOSTIC =====")
    print(future_paths.to_string(index=False))
    print()
    print("===== ROBUSTNESS GATES =====")
    for key, passed in gates.items():
        print(key, "PASS" if passed else "FAIL")
    print("ALL GATES:", "PASS" if all(gates.values()) else "FAIL")
    print()
    print("No portfolio simulation. No candidate freeze. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v7/phase6.py")
    print()
    print("Stock V7 Phase 6 causal stabilization-state patch complete.")
    print("Fixed causal indicators only; no future market direction is used to form the state.")
    print("The 2026-09-01+ holdout remains sealed. No portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
