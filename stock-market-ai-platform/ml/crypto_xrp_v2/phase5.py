"""Crypto XRP V2 Phase 5: regime and overlay diagnostics.

Diagnostics only. No model fitting, no policy tuning, no freeze/promotion, no
future-holdout evaluation, and no brokerage orders.

This phase asks whether XRP V2 has value as an occasional overlay on BTC rather
than as a full XRP/BTC/CASH allocator. It analyzes the existing Phase 2 Ridge
scores and Phase 3 corrected 5 bps policy path by:
- BTC 1-hour return regime
- absolute XRP-vs-BTC score strength
- fold
- executed state relative to an always-BTC benchmark

All economic realization uses the same explicit realization_bar=true rows as
corrected Phase 3/4. The frozen XRP V1 candidate remains unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE1_DATASET = Path("data/model/crypto_xrp_v2/phase1/xrp_primary_15m_1h.parquet")
PHASE2_PREDICTIONS = Path("data/model/crypto_xrp_v2/phase2/predictions.parquet")
PHASE3_DETAIL = Path("data/model/crypto_xrp_v2/phase3/decision_metrics.csv")
PHASE4_BENCHMARK = Path("data/model/crypto_xrp_v2/phase4/benchmark_diagnostics.csv")
OUTPUT_ROOT = Path("data/model/crypto_xrp_v2/phase5")
REGIME_PATH = OUTPUT_ROOT / "regime_diagnostics.csv"
SCORE_PATH = OUTPUT_ROOT / "score_strength_diagnostics.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_overlay_diagnostics.csv"
STATE_PATH = OUTPUT_ROOT / "state_overlay_diagnostics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

MODEL_ID = "ridge"
POLICY_ID = "xrp_hold_c2_1h"
COST_BPS = 5.0


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _load_hourly() -> pd.DataFrame:
    data = pd.read_parquet(PHASE1_DATASET).copy()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)

    pred = pd.read_parquet(PHASE2_PREDICTIONS).copy()
    pred["timestamp_utc"] = pd.to_datetime(pred["timestamp_utc"], utc=True)
    pred = pred[pred["model_id"] == MODEL_ID].copy()

    detail = pd.read_csv(PHASE3_DETAIL)
    detail["timestamp_utc"] = pd.to_datetime(detail["timestamp_utc"], utc=True)
    required = {
        "timestamp_utc", "fold_id", "policy_id", "cost_bps", "executed_state",
        "net_return_1h", "switch", "realization_bar",
    }
    missing = required - set(detail.columns)
    if missing:
        raise RuntimeError(f"Phase 3 detail missing columns: {sorted(missing)}")

    detail = detail[
        detail["policy_id"].eq(POLICY_ID)
        & pd.to_numeric(detail["cost_bps"], errors="coerce").eq(COST_BPS)
        & _as_bool(detail["realization_bar"])
    ].copy()

    frame = (
        detail[["timestamp_utc", "fold_id", "executed_state", "net_return_1h", "switch"]]
        .merge(
            pred[["timestamp_utc", "predicted_score"]],
            on="timestamp_utc", how="inner", validate="one_to_one",
        )
        .merge(
            data[["timestamp_utc", "forward_return_1h", "btc_forward_return_1h"]],
            on="timestamp_utc", how="inner", validate="one_to_one",
        )
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )
    if frame.empty:
        raise RuntimeError("No hourly XRP V2 overlay rows available")
    if frame["timestamp_utc"].duplicated().any():
        raise RuntimeError("Duplicate realization timestamps in XRP V2 Phase 5")

    if PHASE4_BENCHMARK.exists():
        b = pd.read_csv(PHASE4_BENCHMARK)
        if not b.empty and "realized_hour_count" in b.columns:
            expected = int(b["realized_hour_count"].iloc[0])
            if len(frame) != expected:
                raise RuntimeError(
                    f"Phase 5 realization count {len(frame)} does not match Phase 4 benchmark count {expected}"
                )

    frame["strategy_return_1h"] = pd.to_numeric(frame["net_return_1h"], errors="coerce").fillna(0.0)
    frame["btc_return_1h"] = pd.to_numeric(frame["btc_forward_return_1h"], errors="coerce").fillna(0.0)
    frame["xrp_return_1h"] = pd.to_numeric(frame["forward_return_1h"], errors="coerce").fillna(0.0)
    frame["excess_vs_btc_1h"] = frame["strategy_return_1h"] - frame["btc_return_1h"]
    frame["xrp_minus_btc_realized_1h"] = frame["xrp_return_1h"] - frame["btc_return_1h"]
    frame["abs_score"] = frame["predicted_score"].abs()
    return frame


def _equity_stats(r: pd.Series) -> tuple[float, float]:
    x = pd.to_numeric(r, errors="coerce").fillna(0.0).to_numpy(float)
    if len(x) == 0:
        return 1.0, 0.0
    eq = np.cumprod(1.0 + x)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(eq[-1]), float(dd.min())


def main():
    frame = _load_hourly()

    # Regimes are descriptive only and are based on contemporaneous realized BTC
    # 1h returns; they are not intended as tradable filters.
    q33, q67 = frame["btc_return_1h"].quantile([1/3, 2/3]).tolist()
    frame["btc_regime"] = pd.cut(
        frame["btc_return_1h"],
        bins=[-np.inf, q33, q67, np.inf],
        labels=["BTC_DOWN", "BTC_FLAT", "BTC_UP"],
        include_lowest=True,
    ).astype(str)

    regime_rows = []
    for regime, g in frame.groupby("btc_regime", sort=True):
        eq, dd = _equity_stats(g["strategy_return_1h"])
        btc_eq, _ = _equity_stats(g["btc_return_1h"])
        regime_rows.append({
            "btc_regime": regime,
            "hour_count": int(len(g)),
            "strategy_ending_equity_within_regime": eq,
            "btc_ending_equity_within_regime": btc_eq,
            "mean_strategy_return_1h": float(g["strategy_return_1h"].mean()),
            "mean_btc_return_1h": float(g["btc_return_1h"].mean()),
            "mean_excess_vs_btc_1h": float(g["excess_vs_btc_1h"].mean()),
            "positive_excess_fraction": float((g["excess_vs_btc_1h"] > 0).mean()),
            "strategy_max_drawdown_within_regime": dd,
            "xrp_state_fraction": float((g["executed_state"] == "XRP").mean()),
            "cash_state_fraction": float((g["executed_state"] == "CASH").mean()),
        })
    regime_df = pd.DataFrame(regime_rows)

    # Score-strength buckets are descriptive; quantile cut points are reported so
    # they cannot silently become tuned thresholds.
    frame["score_strength_bucket"] = pd.qcut(
        frame["abs_score"], q=5, labels=False, duplicates="drop"
    )
    score_rows = []
    for bucket, g in frame.groupby("score_strength_bucket", sort=True):
        score_rows.append({
            "score_strength_bucket": int(bucket),
            "hour_count": int(len(g)),
            "min_abs_score": float(g["abs_score"].min()),
            "max_abs_score": float(g["abs_score"].max()),
            "mean_abs_score": float(g["abs_score"].mean()),
            "mean_predicted_score": float(g["predicted_score"].mean()),
            "mean_realized_xrp_minus_btc_1h": float(g["xrp_minus_btc_realized_1h"].mean()),
            "mean_strategy_excess_vs_btc_1h": float(g["excess_vs_btc_1h"].mean()),
            "positive_xrp_relative_fraction": float((g["xrp_minus_btc_realized_1h"] > 0).mean()),
            "xrp_state_fraction": float((g["executed_state"] == "XRP").mean()),
            "cash_state_fraction": float((g["executed_state"] == "CASH").mean()),
        })
    score_df = pd.DataFrame(score_rows)

    fold_rows = []
    for fold, g in frame.groupby("fold_id", sort=True):
        eq, dd = _equity_stats(g["strategy_return_1h"])
        btc_eq, btc_dd = _equity_stats(g["btc_return_1h"])
        fold_rows.append({
            "fold_id": fold,
            "hour_count": int(len(g)),
            "strategy_ending_equity": eq,
            "btc_ending_equity": btc_eq,
            "strategy_minus_btc_equity": eq - btc_eq,
            "strategy_max_drawdown": dd,
            "btc_max_drawdown": btc_dd,
            "mean_excess_vs_btc_1h": float(g["excess_vs_btc_1h"].mean()),
            "xrp_state_fraction": float((g["executed_state"] == "XRP").mean()),
            "cash_state_fraction": float((g["executed_state"] == "CASH").mean()),
            "switch_count": int(pd.Series(g["switch"]).astype(bool).sum()),
        })
    fold_df = pd.DataFrame(fold_rows)

    state_rows = []
    for state, g in frame.groupby("executed_state", sort=True):
        state_rows.append({
            "executed_state": state,
            "hour_count": int(len(g)),
            "fraction_of_hours": float(len(g) / len(frame)),
            "mean_strategy_return_1h": float(g["strategy_return_1h"].mean()),
            "mean_btc_return_1h": float(g["btc_return_1h"].mean()),
            "mean_excess_vs_btc_1h": float(g["excess_vs_btc_1h"].mean()),
            "positive_excess_fraction": float((g["excess_vs_btc_1h"] > 0).mean()),
            "mean_predicted_score": float(g["predicted_score"].mean()),
            "mean_realized_xrp_minus_btc_1h": float(g["xrp_minus_btc_realized_1h"].mean()),
        })
    state_df = pd.DataFrame(state_rows)

    overall_strategy_eq, overall_strategy_dd = _equity_stats(frame["strategy_return_1h"])
    overall_btc_eq, overall_btc_dd = _equity_stats(frame["btc_return_1h"])
    folds_beating_btc = float(
        (fold_df["strategy_ending_equity"] > fold_df["btc_ending_equity"]).mean()
    )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    regime_df.to_csv(REGIME_PATH, index=False)
    score_df.to_csv(SCORE_PATH, index=False)
    fold_df.to_csv(FOLD_PATH, index=False)
    state_df.to_csv(STATE_PATH, index=False)

    status = "OVERLAY_DIAGNOSTICS_ONLY_NO_FREEZE"
    MANIFEST_PATH.write_text(json.dumps({
        "research_version": "crypto_xrp_v2",
        "phase": 5,
        "stage": "btc_relative_overlay_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "policy_id": POLICY_ID,
        "cost_bps": COST_BPS,
        "economic_accounting": "explicit realization_bar=true rows from corrected Phase 3",
        "realized_hour_count": int(len(frame)),
        "overall_strategy_ending_equity": overall_strategy_eq,
        "overall_always_btc_ending_equity_on_same_oos_hours": overall_btc_eq,
        "overall_strategy_max_drawdown": overall_strategy_dd,
        "overall_btc_max_drawdown": overall_btc_dd,
        "fold_fraction_strategy_beats_btc": folds_beating_btc,
        "btc_regime_quantile_cutpoints": {"q33": float(q33), "q67": float(q67)},
        "status": status,
        "interpretation_rule": "These are descriptive diagnostics only. Regime and score-strength buckets must not be promoted into new thresholds on the same OOS evidence.",
        "no_new_model_fit": True,
        "no_policy_tuning": True,
        "no_new_threshold_selection": True,
        "frozen_xrp_v1_modified": False,
        "brokerage_orders": False,
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "next_step": "Use diagnostics to decide whether XRP V2 merits a fresh, separately pre-registered overlay hypothesis. Do not freeze or tune this V2 policy family on these results.",
    }, indent=2) + "\n")

    print("CRYPTO XRP V2 PHASE 5")
    print("=" * 100)
    print("REGIME DIAGNOSTICS")
    print(regime_df.to_string(index=False))
    print("\nSCORE-STRENGTH DIAGNOSTICS")
    print(score_df.to_string(index=False))
    print("\nFOLD OVERLAY DIAGNOSTICS")
    print(fold_df.to_string(index=False))
    print("\nSTATE OVERLAY DIAGNOSTICS")
    print(state_df.to_string(index=False))
    print(f"\nSTATUS: {status}")
    print("No fitting, tuning, threshold selection, freeze, promotion, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
