"""Stock V8 Phase 2: chronological validation of three fixed orthogonal signals.

Phase 1 identified three pre-registered follow-up signals after cross-sectional
neutralization to 20-session volatility and 60-session SPY beta:

* distance_from_low_20d
* volume_ratio_20d
* return_20d

Phase 2 performs development-only chronological validation. There is no model
fitting, signal combination, weighting search, threshold search, portfolio
simulation, candidate freeze, or holdout scoring.

The ranking score for each signal on each decision date is the same-day
cross-sectional residual after regressing the signal on volatility_20d and
beta_60. The target is the already-fixed exact 5-session stock return minus the
exact 5-session SPY return.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v8.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION
from ml.v8.phase1 import _build_panel, _rank_corr, _residualize

PHASE = 2
OUTPUT_ROOT = Path("data/model/v8/phase2")
DAILY_PATH = OUTPUT_ROOT / "daily_signal_metrics.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SIGNALS = [
    "distance_from_low_20d",
    "volume_ratio_20d",
    "return_20d",
]
TARGET = "forward_relative_return_5d"
CONTROLS = ["volatility_20d", "beta_60"]

# Fixed chronological development folds. No fold boundary is optimized from
# Phase-2 results. The final V8 holdout still begins 2026-09-01 UTC.
FOLDS = [
    ("dev_01", "2016-08-01", "2018-01-01"),
    ("dev_02", "2018-01-01", "2019-01-01"),
    ("dev_03", "2019-01-01", "2020-01-01"),
    ("dev_04", "2020-01-01", "2021-01-01"),
    ("dev_05", "2021-01-01", "2022-01-01"),
    ("dev_06", "2022-01-01", "2023-01-01"),
    ("dev_07", "2023-01-01", "2024-01-01"),
    ("dev_08", "2024-01-01", "2025-01-01"),
    ("dev_09", "2025-01-01", "2026-01-01"),
    ("dev_10", "2026-01-01", "2026-09-01"),
]


def _fold_id(ts):
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    for fold_id, start, end in FOLDS:
        if pd.Timestamp(start, tz="UTC") <= t < pd.Timestamp(end, tz="UTC"):
            return fold_id
    return None


def _daily_metrics(panel):
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        if ts >= FUTURE_HOLDOUT_START_UTC:
            continue
        fold_id = _fold_id(ts)
        if fold_id is None:
            continue
        controls = day[CONTROLS].copy()
        target = pd.to_numeric(day[TARGET], errors="coerce")

        for signal in SIGNALS:
            score = _residualize(pd.to_numeric(day[signal], errors="coerce"), controls)
            frame = pd.DataFrame({
                "score": score,
                "target": target,
            }).replace([np.inf, -np.inf], np.nan).dropna()
            if len(frame) < 20 or frame["score"].nunique() < 2:
                continue

            ranked = frame.sort_values("score", ascending=False)
            n5 = min(5, len(ranked))
            n10 = min(10, len(ranked))
            top5 = ranked.head(n5)["target"]
            top10 = ranked.head(n10)["target"]
            bottom10 = ranked.tail(n10)["target"]

            rows.append({
                "timestamp_utc": ts,
                "fold_id": fold_id,
                "signal_id": signal,
                "asset_count": int(len(frame)),
                "ic": _rank_corr(frame["score"], frame["target"]),
                "top5_mean_relative_return": float(top5.mean()),
                "top10_mean_relative_return": float(top10.mean()),
                "bottom10_mean_relative_return": float(bottom10.mean()),
                "top10_minus_bottom10_spread": float(top10.mean() - bottom10.mean()),
            })
    return pd.DataFrame(rows)


def _aggregate(g):
    return {
        "days": int(g["timestamp_utc"].nunique()),
        "mean_ic": float(g["ic"].mean()),
        "median_ic": float(g["ic"].median()),
        "ic_hit_rate": float((g["ic"] > 0).mean()),
        "mean_top5_relative_return": float(g["top5_mean_relative_return"].mean()),
        "mean_top10_relative_return": float(g["top10_mean_relative_return"].mean()),
        "mean_bottom10_relative_return": float(g["bottom10_mean_relative_return"].mean()),
        "mean_top10_minus_bottom10_spread": float(g["top10_minus_bottom10_spread"].mean()),
    }


def _fold_metrics(daily):
    rows = []
    for signal in SIGNALS:
        for fold_id, _, _ in FOLDS:
            g = daily[(daily["signal_id"] == signal) & (daily["fold_id"] == fold_id)]
            if len(g) == 0:
                rows.append({"signal_id": signal, "fold_id": fold_id, "days": 0})
                continue
            rows.append({"signal_id": signal, "fold_id": fold_id, **_aggregate(g)})
    return pd.DataFrame(rows)


def _summary(daily, folds):
    rows = []
    for signal in SIGNALS:
        g = daily[daily["signal_id"] == signal]
        fg = folds[(folds["signal_id"] == signal) & (folds["days"] > 0)].copy()
        base = _aggregate(g)
        base.update({
            "signal_id": signal,
            "positive_mean_ic_folds": int((fg["mean_ic"] > 0).sum()),
            "total_folds": int(len(fg)),
            "positive_mean_ic_fold_fraction": float((fg["mean_ic"] > 0).mean()) if len(fg) else np.nan,
            "positive_top10_return_folds": int((fg["mean_top10_relative_return"] > 0).sum()),
            "positive_spread_folds": int((fg["mean_top10_minus_bottom10_spread"] > 0).sum()),
        })
        rows.append(base)
    return pd.DataFrame(rows).sort_values("mean_ic", ascending=False)


def main():
    panel = _build_panel()
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    daily = _daily_metrics(panel)
    folds = _fold_metrics(daily)
    summary = _summary(daily, folds)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    daily.to_csv(DAILY_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_chronological_orthogonal_signal_validation",
        "objective": (
            "Chronologically validate three fixed V8 Phase-1 signals after same-day "
            "cross-sectional neutralization to volatility_20d and beta_60."
        ),
        "signals": SIGNALS,
        "neutralization_controls": CONTROLS,
        "target": TARGET,
        "chronological_folds": [
            {"fold_id": fid, "start": start, "end_exclusive": end}
            for fid, start, end in FOLDS
        ],
        "model_fitting": False,
        "signal_combination": False,
        "signal_selected": None,
        "candidate_frozen": False,
        "portfolio_simulation": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "v7_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_fitting": False,
            "signal_combination": False,
            "signal_weight_tuning": False,
            "threshold_optimization": False,
            "portfolio_simulation": False,
            "signal_selected": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V8 PHASE 2")
    print("=" * 104)
    print("Chronological validation of three fixed volatility/beta-orthogonal signals")
    print()
    print("===== METRICS SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== FOLD METRICS =====")
    print(folds.to_string(index=False))
    print()
    print("No model fitting. No signal selection. No portfolio simulation. No holdout score. No orders.")


if __name__ == "__main__":
    main()
