"""Apply Stock V8 Phase 4 fixed two-signal complementarity diagnostics."""

from pathlib import Path

PHASE4 = Path("ml/v8/phase4.py")


def main():
    PHASE4.parent.mkdir(parents=True, exist_ok=True)
    PHASE4.write_text(r'''"""Stock V8 Phase 4: fixed two-signal complementarity diagnostics.

Purpose
-------
Phase 3 showed that distance_from_low_20d has strong upper-tail behavior while
volume_ratio_20d has substantially better decile monotonicity and almost zero
rank correlation with distance_from_low_20d. Phase 4 asks whether a fixed,
untuned equal-rank combination improves either signal without introducing a
new search dimension.

Scientific contract
-------------------
* Reuse the Phase-3 volatility/beta-orthogonal ranked panel.
* Compare three fixed score families only:
    - DISTANCE_ONLY
    - VOLUME_ONLY
    - EQUAL_RANK_BLEND = 50% distance percentile rank + 50% volume percentile rank
* Equal 50/50 weights are pre-registered; no weight optimization.
* Target remains exact 5-session SPY-relative forward return.
* Top-5/10/20 and deciles remain diagnostics, not portfolio construction.
* Fixed chronological folds are unchanged.
* No model fitting, signal-weight tuning, Top-N optimization, transaction-cost
  tuning, portfolio simulation, candidate freeze, or holdout scoring.
* 2026-09-01+ V8 holdout remains sealed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v8.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION
from ml.v8.phase3 import _fold_id

PHASE = 4
PHASE3_PANEL = Path("data/model/v8/phase3/daily_ranked_panel.parquet")
OUTPUT_ROOT = Path("data/model/v8/phase4")
RANKED_PATH = OUTPUT_ROOT / "fixed_complementarity_ranked_panel.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "score_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_metrics.csv"
DECILE_PATH = OUTPUT_ROOT / "decile_summary.csv"
CONCENTRATION_PATH = OUTPUT_ROOT / "top10_name_concentration.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

TARGET = "forward_relative_return_5d"
TOP_NS = [5, 10, 20]
SCORE_SPECS = {
    "DISTANCE_ONLY": {"distance_from_low_20d": 1.0},
    "VOLUME_ONLY": {"volume_ratio_20d": 1.0},
    "EQUAL_RANK_BLEND": {"distance_from_low_20d": 0.5, "volume_ratio_20d": 0.5},
}


def _rank_corr(a, b):
    x = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(x) < 20 or x["a"].nunique() < 2 or x["b"].nunique() < 2:
        return np.nan
    return float(x["a"].corr(x["b"], method="spearman"))


def _build_scores():
    if not PHASE3_PANEL.exists():
        raise FileNotFoundError(f"Missing V8 Phase-3 ranked panel: {PHASE3_PANEL}. Run Phase 3 first.")
    p = pd.read_parquet(PHASE3_PANEL).copy()
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    p = p[p["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()

    wanted = ["distance_from_low_20d", "volume_ratio_20d"]
    p = p[p["signal_id"].isin(wanted)].copy()
    wide = p.pivot_table(
        index=["timestamp_utc", "symbol"],
        columns="signal_id",
        values=["percentile_rank", TARGET],
        aggfunc="first",
    )
    wide.columns = [f"{a}__{b}" for a, b in wide.columns]
    wide = wide.reset_index()

    target_cols = [c for c in wide.columns if c.startswith(TARGET + "__")]
    if not target_cols:
        raise ValueError("V8 Phase 4 could not recover target from Phase-3 panel")
    wide[TARGET] = wide[target_cols].bfill(axis=1).iloc[:, 0]

    rows = []
    for score_id, weights in SCORE_SPECS.items():
        g = wide[["timestamp_utc", "symbol", TARGET]].copy()
        score = pd.Series(0.0, index=wide.index)
        valid = pd.Series(True, index=wide.index)
        for signal, weight in weights.items():
            col = f"percentile_rank__{signal}"
            if col not in wide.columns:
                raise ValueError(f"Missing percentile rank for {signal}")
            x = pd.to_numeric(wide[col], errors="coerce")
            valid &= x.notna()
            score += weight * x
        g["score"] = score.where(valid)
        g["score_id"] = score_id
        g = g.dropna(subset=["score", TARGET])
        out = []
        for ts, day in g.groupby("timestamp_utc", sort=True):
            day = day.sort_values(["score", "symbol"], ascending=[True, True]).reset_index(drop=True)
            if len(day) < 20:
                continue
            n = len(day)
            day["rank_ascending"] = np.arange(1, n + 1)
            day["rank_descending"] = n - day["rank_ascending"] + 1
            day["decile"] = np.minimum(10, np.floor((day["rank_ascending"] - 1) * 10 / n).astype(int) + 1)
            day["fold_id"] = _fold_id(ts)
            out.append(day)
        if out:
            rows.append(pd.concat(out, ignore_index=True))
    if not rows:
        raise RuntimeError("No V8 Phase-4 score observations produced")
    return pd.concat(rows, ignore_index=True)


def _score_metrics(g):
    daily = []
    for ts, day in g.groupby("timestamp_utc", sort=True):
        day = day.sort_values("score", ascending=False)
        rec = {
            "timestamp_utc": ts,
            "ic": _rank_corr(day["score"], day[TARGET]),
            "top5": float(day.head(5)[TARGET].mean()),
            "top10": float(day.head(10)[TARGET].mean()),
            "top20": float(day.head(20)[TARGET].mean()),
            "bottom10": float(day.tail(10)[TARGET].mean()),
        }
        rec["spread"] = rec["top10"] - rec["bottom10"]
        daily.append(rec)
    x = pd.DataFrame(daily)
    return {
        "days": int(len(x)),
        "mean_ic": float(x["ic"].mean()),
        "median_ic": float(x["ic"].median()),
        "ic_hit_rate": float((x["ic"] > 0).mean()),
        "mean_top5_relative_return": float(x["top5"].mean()),
        "mean_top10_relative_return": float(x["top10"].mean()),
        "mean_top20_relative_return": float(x["top20"].mean()),
        "mean_bottom10_relative_return": float(x["bottom10"].mean()),
        "mean_top10_minus_bottom10_spread": float(x["spread"].mean()),
        "positive_top10_day_fraction": float((x["top10"] > 0).mean()),
        "positive_spread_day_fraction": float((x["spread"] > 0).mean()),
    }


def _summary(ranked):
    rows = []
    for score_id, g in ranked.groupby("score_id", sort=True):
        rec = {"score_id": score_id, **_score_metrics(g)}
        dec = _decile_summary_one(g)
        rec["decile_monotonicity_spearman"] = float(dec["decile"].corr(dec["mean_relative_return"], method="spearman"))
        rows.append(rec)
    return pd.DataFrame(rows)


def _fold_metrics(ranked):
    rows = []
    for (score_id, fold_id), g in ranked.groupby(["score_id", "fold_id"], sort=True):
        rows.append({"score_id": score_id, "fold_id": fold_id, **_score_metrics(g)})
    return pd.DataFrame(rows)


def _decile_summary_one(g):
    rows = []
    for decile, x in g.groupby("decile", sort=True):
        by_day = x.groupby("timestamp_utc")[TARGET].mean()
        rows.append({
            "decile": int(decile),
            "days": int(by_day.count()),
            "mean_relative_return": float(by_day.mean()),
            "median_relative_return": float(by_day.median()),
            "positive_day_fraction": float((by_day > 0).mean()),
        })
    return pd.DataFrame(rows)


def _deciles(ranked):
    frames = []
    for score_id, g in ranked.groupby("score_id", sort=True):
        x = _decile_summary_one(g)
        x.insert(0, "score_id", score_id)
        frames.append(x)
    return pd.concat(frames, ignore_index=True)


def _concentration(ranked):
    rows = []
    for score_id, g in ranked.groupby("score_id", sort=True):
        periods = g["timestamp_utc"].nunique()
        picks = g[g["rank_descending"] <= 10]
        counts = picks.groupby("symbol").size().sort_values(ascending=False)
        for symbol, count in counts.items():
            rows.append({
                "score_id": score_id,
                "symbol": symbol,
                "selection_periods": int(count),
                "total_periods": int(periods),
                "selection_period_fraction": float(count / periods) if periods else np.nan,
            })
    return pd.DataFrame(rows)


def main():
    ranked = _build_scores()
    summary = _summary(ranked)
    folds = _fold_metrics(ranked)
    deciles = _deciles(ranked)
    concentration = _concentration(ranked)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    ranked.to_parquet(RANKED_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    deciles.to_csv(DECILE_PATH, index=False)
    concentration.to_csv(CONCENTRATION_PATH, index=False)

    fold_gate = (
        folds.groupby("score_id")
        .agg(
            total_folds=("fold_id", "count"),
            positive_top10_folds=("mean_top10_relative_return", lambda s: int((s > 0).sum())),
            positive_spread_folds=("mean_top10_minus_bottom10_spread", lambda s: int((s > 0).sum())),
            positive_ic_folds=("mean_ic", lambda s: int((s > 0).sum())),
        )
        .reset_index()
    )

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_fixed_two_signal_complementarity_diagnostics",
        "objective": "Test whether a pre-registered equal-rank blend of distance-from-low and volume-ratio improves fixed V8 tail/ranking diagnostics without tuning weights or Top-N.",
        "score_specs": SCORE_SPECS,
        "combination_policy": "fixed percentile-rank blend; EQUAL_RANK_BLEND weights exactly 0.5/0.5",
        "neutralization_controls": ["volatility_20d", "beta_60"],
        "target": TARGET,
        "top_n_diagnostics": TOP_NS,
        "fold_policy": "same fixed chronological folds as V8 Phases 2-3",
        "fold_gate_summary": fold_gate.to_dict(orient="records"),
        "score_selected": None,
        "model_fitting": False,
        "signal_weight_tuning": False,
        "top_n_optimization": False,
        "portfolio_simulation": False,
        "candidate_frozen": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "research_safety": {
            "v4_modified": False, "v5_modified": False, "v6_modified": False,
            "v7_modified": False, "paper_portfolio_modified": False,
            "paper_journal_modified": False, "crypto_tracks_modified": False,
            "model_fitting": False, "signal_weight_tuning": False,
            "top_n_optimization": False, "threshold_optimization": False,
            "transaction_cost_tuning": False, "portfolio_simulation": False,
            "score_selected": False, "candidate_frozen": False,
            "future_holdout_scored": False, "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V8 PHASE 4")
    print("=" * 108)
    print("Fixed two-signal complementarity diagnostics")
    print("DISTANCE_ONLY vs VOLUME_ONLY vs fixed 50/50 EQUAL_RANK_BLEND")
    print()
    print("===== SCORE SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== FOLD METRICS =====")
    print(folds.to_string(index=False))
    print()
    print("===== DECILE SUMMARY =====")
    print(deciles.to_string(index=False))
    print()
    print("===== FOLD GATE SUMMARY =====")
    print(fold_gate.to_string(index=False))
    print()
    print("No fitting. No weight tuning. No Top-N optimization. No portfolio simulation. No holdout score. No orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v8/phase4.py")
    print()
    print("Stock V8 Phase 4 fixed-complementarity patch complete.")
    print("Fixed distance-only, volume-only, and equal 50/50 rank blend diagnostics only.")
    print("The 2026-09-01+ holdout remains sealed. No fitting, tuning, portfolio simulation, freeze, or orders.")


if __name__ == "__main__":
    main()
