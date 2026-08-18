"""Stock V8 Phase 3: cross-sectional tail and monotonicity diagnostics.

Purpose
-------
Phase 2 showed that the three fixed volatility/beta-orthogonal signals have
modest full-cross-section IC, while their upper-ranked baskets are often more
stable. Phase 3 tests whether the economic information is concentrated in the
upper tail and whether the signal-to-return relationship is monotonic.

Scientific contract
-------------------
* Reuse exactly the three Phase-2 signals.
* Reuse same-day cross-sectional neutralization to volatility_20d and beta_60.
* Target remains exact 5-session SPY-relative forward return.
* Deciles and Top-5/10/20 are descriptive ranking diagnostics, not portfolio
  construction or Top-N optimization.
* Fixed chronological development folds match Phase 2.
* No signal combination, signal weighting, model fitting, transaction-cost
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
from ml.v8.phase1 import _residualize

PHASE = 3
PHASE1_PANEL = Path("data/model/v8/phase1/orthogonal_signal_panel.parquet")
OUTPUT_ROOT = Path("data/model/v8/phase3")
DAILY_PATH = OUTPUT_ROOT / "daily_ranked_panel.parquet"
DECILE_PATH = OUTPUT_ROOT / "decile_summary.csv"
TAIL_PATH = OUTPUT_ROOT / "tail_summary.csv"
TAIL_FOLD_PATH = OUTPUT_ROOT / "tail_fold_metrics.csv"
PERSISTENCE_PATH = OUTPUT_ROOT / "top_decile_persistence.csv"
CONCENTRATION_PATH = OUTPUT_ROOT / "top10_name_concentration.csv"
PAIRWISE_PATH = OUTPUT_ROOT / "pairwise_rank_correlation.csv"
SECTOR_PATH = OUTPUT_ROOT / "sector_concentration.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SIGNALS = [
    "distance_from_low_20d",
    "volume_ratio_20d",
    "return_20d",
]
CONTROLS = ["volatility_20d", "beta_60"]
TARGET = "forward_relative_return_5d"
TOP_NS = [5, 10, 20]


def _fold_id(ts):
    year = pd.Timestamp(ts).year
    if year <= 2017:
        return "dev_01"
    mapping = {
        2018: "dev_02", 2019: "dev_03", 2020: "dev_04",
        2021: "dev_05", 2022: "dev_06", 2023: "dev_07",
        2024: "dev_08", 2025: "dev_09", 2026: "dev_10",
    }
    return mapping.get(year)


def _build_ranked_panel():
    if not PHASE1_PANEL.exists():
        raise FileNotFoundError(
            f"Missing V8 Phase-1 panel: {PHASE1_PANEL}. Run Phase 1 first."
        )
    panel = pd.read_parquet(PHASE1_PANEL).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    panel = panel[panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()

    required = {"timestamp_utc", "symbol", TARGET, *SIGNALS, *CONTROLS}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V8 Phase 3 panel missing columns: " + ", ".join(missing))

    out = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        day = day.copy()
        controls = day[CONTROLS].apply(pd.to_numeric, errors="coerce")
        for signal in SIGNALS:
            resid = _residualize(
                pd.to_numeric(day[signal], errors="coerce"), controls
            )
            target = pd.to_numeric(day[TARGET], errors="coerce")
            g = pd.DataFrame({
                "timestamp_utc": ts,
                "symbol": day["symbol"].astype(str).to_numpy(),
                "signal_id": signal,
                "orthogonal_signal": resid.to_numpy(),
                TARGET: target.to_numpy(),
            }).replace([np.inf, -np.inf], np.nan).dropna()
            if len(g) < 20:
                continue
            g = g.sort_values(["orthogonal_signal", "symbol"], ascending=[True, True]).reset_index(drop=True)
            n = len(g)
            g["rank_ascending"] = np.arange(1, n + 1)
            g["rank_descending"] = n - g["rank_ascending"] + 1
            g["percentile_rank"] = g["rank_ascending"] / n
            # Deterministic 10 bins, approximately equal sized. Decile 10 is highest signal.
            g["decile"] = np.minimum(10, np.floor((g["rank_ascending"] - 1) * 10 / n).astype(int) + 1)
            g["fold_id"] = _fold_id(ts)
            out.append(g)
    if not out:
        raise RuntimeError("No V8 Phase 3 ranked observations were produced")
    return pd.concat(out, ignore_index=True)


def _decile_summary(ranked):
    rows = []
    for (signal, decile), g in ranked.groupby(["signal_id", "decile"], sort=True):
        by_day = g.groupby("timestamp_utc")[TARGET].mean()
        rows.append({
            "signal_id": signal,
            "decile": int(decile),
            "days": int(by_day.count()),
            "observations": int(len(g)),
            "mean_relative_return": float(by_day.mean()),
            "median_relative_return": float(by_day.median()),
            "positive_day_fraction": float((by_day > 0).mean()),
        })
    return pd.DataFrame(rows)


def _tail_rows(ranked, fold=False):
    rows = []
    grouping = ["signal_id"] + (["fold_id"] if fold else [])
    for keys, g in ranked.groupby(grouping, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        signal = keys[0]
        fold_id = keys[1] if fold else None
        daily = []
        for ts, day in g.groupby("timestamp_utc", sort=True):
            day = day.sort_values("orthogonal_signal", ascending=False)
            rec = {"timestamp_utc": ts}
            for n in TOP_NS:
                rec[f"top{n}"] = float(day.head(n)[TARGET].mean())
            rec["bottom10"] = float(day.tail(10)[TARGET].mean())
            rec["top10_minus_bottom10"] = rec["top10"] - rec["bottom10"]
            daily.append(rec)
        x = pd.DataFrame(daily)
        rec = {
            "signal_id": signal,
            "days": int(len(x)),
            "mean_top5_relative_return": float(x["top5"].mean()),
            "mean_top10_relative_return": float(x["top10"].mean()),
            "mean_top20_relative_return": float(x["top20"].mean()),
            "mean_bottom10_relative_return": float(x["bottom10"].mean()),
            "mean_top10_minus_bottom10_spread": float(x["top10_minus_bottom10"].mean()),
            "positive_top5_day_fraction": float((x["top5"] > 0).mean()),
            "positive_top10_day_fraction": float((x["top10"] > 0).mean()),
            "positive_top20_day_fraction": float((x["top20"] > 0).mean()),
            "positive_spread_day_fraction": float((x["top10_minus_bottom10"] > 0).mean()),
        }
        if fold:
            rec["fold_id"] = fold_id
        rows.append(rec)
    return pd.DataFrame(rows)


def _persistence(ranked):
    rows = []
    for signal, g in ranked.groupby("signal_id", sort=True):
        membership = {}
        dates = sorted(g["timestamp_utc"].unique())
        for ts, day in g.groupby("timestamp_utc", sort=True):
            membership[ts] = set(day.loc[day["decile"] == 10, "symbol"].astype(str))
        for lag in [1, 5, 10, 20]:
            overlaps = []
            retained = []
            for i in range(len(dates) - lag):
                a = membership[dates[i]]
                b = membership[dates[i + lag]]
                if not a:
                    continue
                inter = len(a & b)
                overlaps.append(inter / max(1, len(a | b)))
                retained.append(inter / len(a))
            rows.append({
                "signal_id": signal,
                "lag_trading_sessions": lag,
                "pairs": int(len(overlaps)),
                "mean_jaccard": float(np.mean(overlaps)) if overlaps else np.nan,
                "mean_fraction_original_top_decile_retained": float(np.mean(retained)) if retained else np.nan,
            })
    return pd.DataFrame(rows)


def _name_concentration(ranked):
    rows = []
    for signal, g in ranked.groupby("signal_id", sort=True):
        periods = g["timestamp_utc"].nunique()
        picks = g[g["rank_descending"] <= 10]
        counts = picks.groupby("symbol").size().sort_values(ascending=False)
        for symbol, count in counts.items():
            rows.append({
                "signal_id": signal,
                "symbol": symbol,
                "selection_periods": int(count),
                "total_periods": int(periods),
                "selection_period_fraction": float(count / periods) if periods else np.nan,
            })
    return pd.DataFrame(rows)


def _pairwise_rank_correlation(ranked):
    wide = ranked.pivot_table(
        index=["timestamp_utc", "symbol"],
        columns="signal_id",
        values="percentile_rank",
        aggfunc="first",
    ).reset_index()
    rows = []
    for i, a in enumerate(SIGNALS):
        for b in SIGNALS[i + 1:]:
            daily = []
            for _, g in wide[["timestamp_utc", a, b]].dropna().groupby("timestamp_utc"):
                if len(g) >= 20:
                    daily.append(g[a].corr(g[b], method="spearman"))
            rows.append({
                "signal_a": a,
                "signal_b": b,
                "days": int(pd.Series(daily).notna().sum()),
                "mean_daily_rank_correlation": float(np.nanmean(daily)) if daily else np.nan,
                "median_daily_rank_correlation": float(np.nanmedian(daily)) if daily else np.nan,
            })
    return pd.DataFrame(rows)


def _sector_concentration(ranked):
    # Phase-1 panel intentionally contains no sector metadata. Never fabricate it.
    # If a future upstream panel adds a sector column, this function can be extended.
    return pd.DataFrame([
        {
            "available": False,
            "reason": "V8 Phase-1 orthogonal panel contains no sector metadata; sector concentration intentionally not inferred or fabricated.",
        }
    ])


def _monotonicity(deciles):
    rows = []
    for signal, g in deciles.groupby("signal_id", sort=True):
        g = g.sort_values("decile")
        rho = g["decile"].corr(g["mean_relative_return"], method="spearman")
        top = float(g.loc[g["decile"] == 10, "mean_relative_return"].iloc[0]) if (g["decile"] == 10).any() else np.nan
        bottom = float(g.loc[g["decile"] == 1, "mean_relative_return"].iloc[0]) if (g["decile"] == 1).any() else np.nan
        rows.append({
            "signal_id": signal,
            "decile_monotonicity_spearman": float(rho),
            "top_decile_mean_relative_return": top,
            "bottom_decile_mean_relative_return": bottom,
            "top_minus_bottom_decile_return": top - bottom,
        })
    return rows


def main():
    ranked = _build_ranked_panel()
    deciles = _decile_summary(ranked)
    tails = _tail_rows(ranked, fold=False)
    tail_folds = _tail_rows(ranked, fold=True)
    persistence = _persistence(ranked)
    concentration = _name_concentration(ranked)
    pairwise = _pairwise_rank_correlation(ranked)
    sectors = _sector_concentration(ranked)
    monotonicity = _monotonicity(deciles)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    ranked.to_parquet(DAILY_PATH, index=False)
    deciles.to_csv(DECILE_PATH, index=False)
    tails.to_csv(TAIL_PATH, index=False)
    tail_folds.to_csv(TAIL_FOLD_PATH, index=False)
    persistence.to_csv(PERSISTENCE_PATH, index=False)
    concentration.to_csv(CONCENTRATION_PATH, index=False)
    pairwise.to_csv(PAIRWISE_PATH, index=False)
    sectors.to_csv(SECTOR_PATH, index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_cross_sectional_tail_monotonicity_diagnostics",
        "objective": (
            "Determine whether the three fixed V8 volatility/beta-orthogonal signals have "
            "stable upper-tail economic information and monotonic cross-sectional return structure."
        ),
        "signals": SIGNALS,
        "neutralization_controls": CONTROLS,
        "target": TARGET,
        "top_n_diagnostics": TOP_NS,
        "decile_policy": "fixed ten approximately equal cross-sectional bins per signal/date; decile 10 is highest orthogonal signal",
        "fold_policy": "same fixed chronological folds as V8 Phase 2",
        "monotonicity": monotonicity,
        "sector_concentration_available": False,
        "sector_concentration_reason": sectors.iloc[0]["reason"],
        "signal_selected": None,
        "model_fitting": False,
        "signal_combination": False,
        "portfolio_simulation": False,
        "candidate_frozen": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "research_safety": {
            "v4_modified": False, "v5_modified": False, "v6_modified": False,
            "v7_modified": False, "paper_portfolio_modified": False,
            "paper_journal_modified": False, "crypto_tracks_modified": False,
            "model_fitting": False, "signal_combination": False,
            "signal_weight_tuning": False, "top_n_optimization": False,
            "threshold_optimization": False, "transaction_cost_tuning": False,
            "portfolio_simulation": False, "signal_selected": False,
            "candidate_frozen": False, "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V8 PHASE 3")
    print("=" * 108)
    print("Cross-sectional tail and monotonicity diagnostics")
    print("Three fixed Phase-2 signals; same volatility/beta neutralization; holdout sealed")
    print()
    print("===== MONOTONICITY =====")
    print(pd.DataFrame(monotonicity).to_string(index=False))
    print()
    print("===== DECILE SUMMARY =====")
    print(deciles.to_string(index=False))
    print()
    print("===== TAIL SUMMARY =====")
    print(tails.to_string(index=False))
    print()
    print("===== TAIL FOLD METRICS =====")
    print(tail_folds.to_string(index=False))
    print()
    print("===== TOP-DECILE PERSISTENCE =====")
    print(persistence.to_string(index=False))
    print()
    print("===== TOP-10 NAME CONCENTRATION =====")
    for signal in SIGNALS:
        print()
        print(signal)
        print(concentration[concentration["signal_id"] == signal].head(10).to_string(index=False))
    print()
    print("===== PAIRWISE RANK CORRELATION =====")
    print(pairwise.to_string(index=False))
    print()
    print("===== SECTOR CONCENTRATION =====")
    print(sectors.to_string(index=False))
    print()
    print("No fitting. No signal selection. No Top-N optimization. No portfolio simulation. No holdout score. No orders.")


if __name__ == "__main__":
    main()
