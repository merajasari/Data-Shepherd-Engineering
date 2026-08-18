"""Apply Stock V7 Phase 3 volatility-signal decomposition diagnostics."""

from pathlib import Path

PHASE3 = Path("ml/v7/phase3.py")


def main():
    PHASE3.parent.mkdir(parents=True, exist_ok=True)
    PHASE3.write_text(r'''"""Stock V7 Phase 3: volatility-signal decomposition and monotonicity diagnostics.

Purpose
-------
Phase 2 showed that a four-feature volatility family outperformed broader
context/full feature families. Phase 3 decomposes that signal without portfolio
construction and without touching the 2026-09-01+ V7 holdout.

Pre-registered diagnostic families
----------------------------------
* vol20_only: volatility_20d only.
* vol20_intraday: volatility_20d + intraday_range.
* current_vol_only: the Phase 2 four-feature volatility family.

Diagnostics
-----------
* expanding walk-forward cross-sectional ranking metrics using the same fixed
  Elastic Net contract as Phase 2;
* fold stability;
* volatility-decile monotonicity versus realized 5-session SPY-relative return;
* sector-neutralized daily rank IC;
* SPY market-regime stability;
* persistence of high-volatility ranks;
* concentration of Top-10 predicted selections.

Research safety
---------------
No portfolio simulation, policy tuning, family selection, candidate freeze,
holdout scoring, paper-state mutation, or brokerage orders.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.v7.config import FUTURE_HOLDOUT_START_UTC

PHASE = 3
TARGET = "forward_relative_return_5d"
ENDPOINT = "stock_target_endpoint_utc"
PANEL_PATH = Path("data/model/v7/phase1/research_panel.parquet")
SPY_PATH = Path("data/features/stocks/SPY/SPY_features.parquet")
OUTPUT_ROOT = Path("data/model/v7/phase3")
PREDICTIONS_PATH = OUTPUT_ROOT / "predictions.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "fold_metrics.csv"
DECILE_PATH = OUTPUT_ROOT / "volatility_deciles.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_metrics.csv"
CONCENTRATION_PATH = OUTPUT_ROOT / "top10_concentration.csv"
PERSISTENCE_PATH = OUTPUT_ROOT / "volatility_persistence.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

RANDOM_SEED = 42
ELASTIC_NET_ALPHA = 0.0005
ELASTIC_NET_L1_RATIO = 0.25

FEATURE_FAMILIES = {
    "vol20_only": ["volatility_20d"],
    "vol20_intraday": ["volatility_20d", "intraday_range"],
    "current_vol_only": [
        "volatility_20d",
        "volatility_5d",
        "volatility_ratio_5_20",
        "intraday_range",
    ],
}

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


def utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def make_model():
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", ElasticNet(
            alpha=ELASTIC_NET_ALPHA,
            l1_ratio=ELASTIC_NET_L1_RATIO,
            max_iter=5000,
            random_state=RANDOM_SEED,
        )),
    ])


def load_panel():
    if not PANEL_PATH.exists():
        raise FileNotFoundError(f"Missing V7 Phase 1 panel: {PANEL_PATH}")
    p = pd.read_parquet(PANEL_PATH).copy()
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    if ENDPOINT in p.columns:
        p[ENDPOINT] = pd.to_datetime(p[ENDPOINT], utc=True)
    required = {"timestamp_utc", "symbol", "sector", TARGET, *sum(FEATURE_FAMILIES.values(), [])}
    missing = sorted(required - set(p.columns))
    if missing:
        raise ValueError("V7 Phase 3 panel missing: " + ", ".join(missing))
    if ENDPOINT not in p.columns:
        # Reconstruct exact 5-session target endpoints from the 100-stock shared calendar.
        dates = pd.Index(sorted(p["timestamp_utc"].unique()))
        endpoint_map = {dates[i]: dates[i + 5] for i in range(len(dates) - 5)}
        p[ENDPOINT] = p["timestamp_utc"].map(endpoint_map)
    return p[p["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()


def masks(panel, start, end):
    start, end = utc(start), utc(end)
    usable = panel[TARGET].notna() & panel[ENDPOINT].notna()
    train = usable & (panel["timestamp_utc"] < start) & (panel[ENDPOINT] < start)
    val = usable & (panel["timestamp_utc"] >= start) & (panel["timestamp_utc"] < end)
    val &= panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC
    val &= panel[ENDPOINT] < FUTURE_HOLDOUT_START_UTC
    return train, val


def generate_predictions(panel):
    out = []
    for fold_id, start, end in FOLDS:
        train_mask, val_mask = masks(panel, start, end)
        train, val = panel.loc[train_mask], panel.loc[val_mask]
        if train.empty or val.empty:
            raise RuntimeError(f"Empty fold {fold_id}")
        print(f"{fold_id}: train={len(train):,} val={len(val):,} val_dates={val['timestamp_utc'].nunique():,}")
        for family_id, features in FEATURE_FAMILIES.items():
            m = make_model()
            m.fit(train[features], train[TARGET])
            pred = val[["timestamp_utc", "symbol", "sector", TARGET, "volatility_20d"]].copy()
            pred["predicted_score"] = m.predict(val[features])
            pred["family_id"] = family_id
            pred["fold_id"] = fold_id
            out.append(pred)
    return pd.concat(out, ignore_index=True)


def sector_neutral_ic(day):
    x = day[["sector", "predicted_score", TARGET]].dropna().copy()
    if len(x) < 20:
        return np.nan
    x["score_resid"] = x["predicted_score"] - x.groupby("sector")["predicted_score"].transform("mean")
    x["target_resid"] = x[TARGET] - x.groupby("sector")[TARGET].transform("mean")
    if x["score_resid"].nunique() < 2 or x["target_resid"].nunique() < 2:
        return np.nan
    return x["score_resid"].rank().corr(x["target_resid"].rank())


def daily_metrics(pred):
    rows = []
    for (family, fold, ts), g in pred.groupby(["family_id", "fold_id", "timestamp_utc"], sort=True):
        ordered = g.sort_values("predicted_score", ascending=False)
        ic = g["predicted_score"].corr(g[TARGET], method="spearman") if g["predicted_score"].nunique() > 1 else np.nan
        rows.append({
            "family_id": family,
            "fold_id": fold,
            "timestamp_utc": ts,
            "ic": ic,
            "sector_neutral_ic": sector_neutral_ic(g),
            "top5_return": ordered.head(5)[TARGET].mean(),
            "top10_return": ordered.head(10)[TARGET].mean(),
            "spread": ordered.head(20)[TARGET].mean() - ordered.tail(20)[TARGET].mean(),
        })
    return pd.DataFrame(rows)


def summaries(daily):
    overall = daily.groupby("family_id").agg(
        days=("timestamp_utc", "nunique"),
        mean_ic=("ic", "mean"),
        median_ic=("ic", "median"),
        ic_hit_rate=("ic", lambda s: s.gt(0).mean()),
        mean_sector_neutral_ic=("sector_neutral_ic", "mean"),
        sector_neutral_ic_hit_rate=("sector_neutral_ic", lambda s: s.gt(0).mean()),
        mean_top5_relative_return=("top5_return", "mean"),
        mean_top10_relative_return=("top10_return", "mean"),
        mean_top_minus_bottom_spread=("spread", "mean"),
    ).reset_index()
    folds = daily.groupby(["family_id", "fold_id"]).agg(
        days=("timestamp_utc", "nunique"),
        mean_ic=("ic", "mean"),
        mean_sector_neutral_ic=("sector_neutral_ic", "mean"),
        ic_hit_rate=("ic", lambda s: s.gt(0).mean()),
        mean_top10_relative_return=("top10_return", "mean"),
        mean_spread=("spread", "mean"),
    ).reset_index()
    return overall, folds


def volatility_deciles(panel):
    x = panel[["timestamp_utc", "volatility_20d", TARGET]].dropna().copy()
    x["decile"] = x.groupby("timestamp_utc")["volatility_20d"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 10, labels=False) + 1
    )
    return x.groupby("decile").agg(
        observations=(TARGET, "size"),
        mean_relative_return=(TARGET, "mean"),
        median_relative_return=(TARGET, "median"),
        positive_fraction=(TARGET, lambda s: s.gt(0).mean()),
        mean_volatility_20d=("volatility_20d", "mean"),
    ).reset_index()


def spy_regimes():
    if not SPY_PATH.exists():
        return pd.DataFrame(columns=["timestamp_utc", "spy_regime"])
    s = pd.read_parquet(SPY_PATH).copy()
    s["timestamp_utc"] = pd.to_datetime(s["timestamp_utc"], utc=True)
    if "return_20d" not in s.columns:
        return pd.DataFrame(columns=["timestamp_utc", "spy_regime"])
    s = s[["timestamp_utc", "return_20d"]].dropna()
    s["spy_regime"] = np.where(s["return_20d"] > 0.03, "UP", np.where(s["return_20d"] < -0.03, "DOWN", "FLAT"))
    return s[["timestamp_utc", "spy_regime"]]


def regime_metrics(daily):
    r = spy_regimes()
    if r.empty:
        return pd.DataFrame()
    x = daily.merge(r, on="timestamp_utc", how="left").dropna(subset=["spy_regime"])
    return x.groupby(["family_id", "spy_regime"]).agg(
        days=("timestamp_utc", "nunique"),
        mean_ic=("ic", "mean"),
        ic_hit_rate=("ic", lambda s: s.gt(0).mean()),
        mean_top10_relative_return=("top10_return", "mean"),
    ).reset_index()


def persistence(panel):
    x = panel[["timestamp_utc", "symbol", "volatility_20d"]].dropna().sort_values(["symbol", "timestamp_utc"]).copy()
    x["rank_pct"] = x.groupby("timestamp_utc")["volatility_20d"].rank(pct=True)
    rows = []
    for lag in (1, 5, 10, 20):
        shifted = x.groupby("symbol")["rank_pct"].shift(lag)
        valid = x["rank_pct"].notna() & shifted.notna()
        corr = x.loc[valid, "rank_pct"].corr(shifted[valid], method="spearman")
        top = x["rank_pct"] >= 0.90
        prev_top = shifted >= 0.90
        retention = float((top & prev_top).sum() / prev_top.sum()) if prev_top.sum() else np.nan
        rows.append({"lag_sessions": lag, "rank_spearman": corr, "top_decile_retention": retention})
    return pd.DataFrame(rows)


def concentration(pred):
    rows = []
    for family, g in pred.groupby("family_id"):
        counts = Counter()
        periods = 0
        for _, day in g.groupby("timestamp_utc"):
            periods += 1
            for s in day.nlargest(10, "predicted_score")["symbol"]:
                counts[s] += 1
        for symbol, count in counts.most_common(20):
            rows.append({
                "family_id": family,
                "symbol": symbol,
                "selection_count": count,
                "selection_period_fraction": count / periods,
            })
    return pd.DataFrame(rows)


def main():
    panel = load_panel()
    pred = generate_predictions(panel)
    daily = daily_metrics(pred)
    summary, folds = summaries(daily)
    deciles = volatility_deciles(panel)
    regimes = regime_metrics(daily)
    persist = persistence(panel)
    conc = concentration(pred)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(PREDICTIONS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    deciles.to_csv(DECILE_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    persist.to_csv(PERSISTENCE_PATH, index=False)
    conc.to_csv(CONCENTRATION_PATH, index=False)

    monotonic = bool(deciles["mean_relative_return"].corr(deciles["decile"], method="spearman") > 0.7)
    manifest = {
        "research_version": "v7",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_volatility_signal_decomposition",
        "objective": "Determine whether 20-day volatility alone explains most of V7's volatility-family ranking signal and characterize monotonicity, regime stability, persistence, and concentration.",
        "feature_families": FEATURE_FAMILIES,
        "estimator": "ElasticNet",
        "elastic_net_alpha": ELASTIC_NET_ALPHA,
        "elastic_net_l1_ratio": ELASTIC_NET_L1_RATIO,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "family_selected": None,
        "candidate_frozen": False,
        "volatility_decile_monotonicity_spearman": float(deciles["mean_relative_return"].corr(deciles["decile"], method="spearman")),
        "strong_monotonicity_flag": monotonic,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "portfolio_simulation": False,
            "portfolio_policy_tuning": False,
            "threshold_tuning": False,
            "family_selected": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V7 PHASE 3")
    print("=" * 104)
    print("Volatility signal decomposition only; no portfolio simulation")
    print()
    print("===== FAMILY SUMMARY =====")
    print(summary.sort_values("mean_ic", ascending=False).to_string(index=False))
    print()
    print("===== VOLATILITY DECILES =====")
    print(deciles.to_string(index=False))
    print()
    print("===== PERSISTENCE =====")
    print(persist.to_string(index=False))
    print()
    print("===== REGIME METRICS =====")
    print(regimes.to_string(index=False) if not regimes.empty else "No SPY regime data available")
    print()
    print("Holdout scored: False | family selected: None | candidate frozen: False | brokerage orders: False")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v7/phase3.py")
    print()
    print("Stock V7 Phase 3 volatility-decomposition patch complete.")
    print("VOL20_ONLY vs VOL20+INTRADAY vs current 4-feature volatility family.")
    print("Includes monotonicity, sector-neutral IC, SPY-regime, persistence, and concentration diagnostics.")
    print("The 2026-09-01+ V7 holdout remains sealed. No portfolio simulation or orders.")


if __name__ == "__main__":
    main()
