"""V5 Phase 4: frozen development-only robustness diagnostics.

Audits the frozen Phase 3 portfolio across walk-forward folds and pre-registered
SPY market regimes. No model fitting, strategy tuning, threshold search, weight
optimization, cadence changes, or future-holdout evaluation occurs here.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v5.config import RESEARCH_PANEL_PATH
from ml.v5.phase1 import FUTURE_HOLDOUT_START_UTC
from ml.v5.phase3 import COST_BPS, REBALANCE_DAYS

PHASE = 4
PHASE2_PREDICTIONS_PATH = Path("data/model/v5/phase2/predictions.parquet")
PHASE3_DAILY_PATH = Path("data/model/v5/phase3/portfolio_daily.csv")
PHASE_ROOT = Path("data/model/v5/phase4")
FOLD_METRICS_PATH = PHASE_ROOT / "fold_metrics.csv"
REGIME_METRICS_PATH = PHASE_ROOT / "regime_metrics.csv"
CONCENTRATION_PATH = PHASE_ROOT / "excess_concentration.csv"
MANIFEST_PATH = PHASE_ROOT / "manifest.json"

TREND_LOOKBACK_DAYS = 60
BULL_THRESHOLD = 0.05
BEAR_THRESHOLD = -0.05
VOL_LOOKBACK_DAYS = 20
HIGH_VOL_THRESHOLD = 0.25


def validate_inputs(panel, predictions, portfolio):
    required_panel = {"timestamp_utc", "spy_close"}
    required_pred = {"timestamp_utc", "model_id", "split", "fold_id"}
    required_port = {"timestamp_utc", "spy_return_5d", "gross_return_5d", "turnover"}
    for name, frame, required in (
        ("panel", panel, required_panel),
        ("predictions", predictions, required_pred),
        ("portfolio", portfolio, required_port),
    ):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ValueError(f"V5 Phase 4 {name} missing: " + ", ".join(missing))


def build_spy_regimes(panel):
    spy = (
        panel[["timestamp_utc", "spy_close"]]
        .drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
        .reset_index(drop=True)
    )
    spy["timestamp_utc"] = pd.to_datetime(spy["timestamp_utc"], utc=True)
    spy["spy_return_1d"] = spy["spy_close"].pct_change()
    spy["spy_return_60d"] = spy["spy_close"].pct_change(TREND_LOOKBACK_DAYS)
    spy["spy_vol_20d"] = (
        spy["spy_return_1d"].rolling(VOL_LOOKBACK_DAYS, min_periods=VOL_LOOKBACK_DAYS).std()
        * np.sqrt(252.0)
    )
    spy["trend_regime"] = np.select(
        [spy["spy_return_60d"] >= BULL_THRESHOLD, spy["spy_return_60d"] <= BEAR_THRESHOLD],
        ["bull", "bear"],
        default="sideways",
    )
    spy["vol_regime"] = np.where(spy["spy_vol_20d"] >= HIGH_VOL_THRESHOLD, "high_vol", "low_vol")
    spy.loc[spy["spy_return_60d"].isna(), "trend_regime"] = "insufficient_history"
    spy.loc[spy["spy_vol_20d"].isna(), "vol_regime"] = "insufficient_history"
    return spy


def enrich_portfolio(panel, predictions, portfolio):
    p = predictions.loc[
        (predictions["model_id"] == "hist_gradient_boosting")
        & (predictions["split"] == "development"),
        ["timestamp_utc", "fold_id"],
    ].drop_duplicates("timestamp_utc")
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)

    x = portfolio.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x = x[x["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    x = x.merge(p, on="timestamp_utc", how="left", validate="one_to_one")
    x = x.merge(build_spy_regimes(panel), on="timestamp_utc", how="left", validate="one_to_one")
    if x["fold_id"].isna().any():
        raise ValueError("Portfolio rows are missing frozen Phase 2 fold IDs")
    return x


def _period_metrics(group, cost_bps):
    g = group.sort_values("timestamp_utc").copy()
    g["net_return"] = g["gross_return_5d"] - g["turnover"] * cost_bps / 10000.0
    g["excess_return"] = g["net_return"] - g["spy_return_5d"]
    periods_per_year = 252.0 / REBALANCE_DAYS
    equity = (1.0 + g["net_return"]).cumprod()
    spy_equity = (1.0 + g["spy_return_5d"]).cumprod()
    ann = equity.iloc[-1] ** (periods_per_year / len(g)) - 1.0
    spy_ann = spy_equity.iloc[-1] ** (periods_per_year / len(g)) - 1.0
    return {
        "period_count": int(len(g)),
        "ending_equity": float(equity.iloc[-1]),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "annualized_return": float(ann),
        "spy_annualized_return": float(spy_ann),
        "annualized_excess_vs_spy": float(ann - spy_ann),
        "mean_period_excess": float(g["excess_return"].mean()),
        "positive_excess_period_rate": float(g["excess_return"].gt(0).mean()),
        "average_turnover": float(g["turnover"].mean()),
        "total_turnover": float(g["turnover"].sum()),
    }


def summarize_by_fold(enriched):
    rows = []
    for cost in COST_BPS:
        for fold_id, group in enriched.groupby("fold_id", sort=True):
            rows.append({"cost_bps": cost, "fold_id": fold_id, **_period_metrics(group, cost)})
    return pd.DataFrame(rows)


def summarize_by_regime(enriched):
    rows = []
    usable = enriched[
        (enriched["trend_regime"] != "insufficient_history")
        & (enriched["vol_regime"] != "insufficient_history")
    ]
    for cost in COST_BPS:
        for (trend, vol), group in usable.groupby(["trend_regime", "vol_regime"], sort=True):
            rows.append({
                "cost_bps": cost,
                "trend_regime": trend,
                "vol_regime": vol,
                **_period_metrics(group, cost),
            })
    return pd.DataFrame(rows)


def build_concentration(fold_metrics):
    rows = []
    for cost, g in fold_metrics.groupby("cost_bps", sort=True):
        x = g.copy().sort_values("annualized_excess_vs_spy", ascending=False)
        positives = x["annualized_excess_vs_spy"].clip(lower=0.0)
        positive_total = positives.sum()
        x["positive_excess_share"] = np.where(
            positive_total > 0,
            positives / positive_total,
            0.0,
        )
        positive_fold_rate = float(x["annualized_excess_vs_spy"].gt(0).mean())
        top_share = float(x["positive_excess_share"].max()) if len(x) else np.nan
        worst = x.nsmallest(1, "annualized_excess_vs_spy").iloc[0]
        rows.append({
            "cost_bps": cost,
            "fold_count": int(len(x)),
            "positive_fold_rate": positive_fold_rate,
            "top_fold_share_of_positive_excess": top_share,
            "best_fold_id": x.iloc[0]["fold_id"],
            "best_fold_annualized_excess": float(x.iloc[0]["annualized_excess_vs_spy"]),
            "worst_fold_id": worst["fold_id"],
            "worst_fold_annualized_excess": float(worst["annualized_excess_vs_spy"]),
            "median_fold_annualized_excess": float(x["annualized_excess_vs_spy"].median()),
        })
    return pd.DataFrame(rows)


def build_manifest(enriched, fold_metrics, regime_metrics, concentration):
    return {
        "research_version": "v5",
        "phase": PHASE,
        "stage": "frozen_development_robustness_audit",
        "portfolio_source": str(PHASE3_DAILY_PATH),
        "fold_source": str(PHASE2_PREDICTIONS_PATH),
        "regime_contract": {
            "trend_lookback_trading_days": TREND_LOOKBACK_DAYS,
            "bull_if_spy_return_gte": BULL_THRESHOLD,
            "bear_if_spy_return_lte": BEAR_THRESHOLD,
            "otherwise": "sideways",
            "volatility_lookback_trading_days": VOL_LOOKBACK_DAYS,
            "high_vol_if_annualized_spy_vol_gte": HIGH_VOL_THRESHOLD,
        },
        "cost_bps": list(COST_BPS),
        "rebalance_periods": int(len(enriched)),
        "fold_count": int(enriched["fold_id"].nunique()),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": "Development-only robustness audit of the already frozen Phase 3 portfolio. No model fitting, regime filtering, threshold search, weight optimization, rebalance-cadence changes, live execution, or future-holdout evaluation.",
        "outputs": {
            "fold_metrics": str(FOLD_METRICS_PATH),
            "regime_metrics": str(REGIME_METRICS_PATH),
            "excess_concentration": str(CONCENTRATION_PATH),
        },
        "metric_rows": {
            "fold": int(len(fold_metrics)),
            "regime": int(len(regime_metrics)),
            "concentration": int(len(concentration)),
        },
        "next_step": "Review whether excess return is broad across folds and regimes, especially at 10 and 25 bps. Do not tune Phase 3 from these diagnostics or evaluate the September 2026 holdout early.",
    }


def main():
    for path in (RESEARCH_PANEL_PATH, PHASE2_PREDICTIONS_PATH, PHASE3_DAILY_PATH):
        if not Path(path).exists():
            raise FileNotFoundError(f"Required V5 Phase 4 input not found: {path}")
    panel = pd.read_parquet(RESEARCH_PANEL_PATH)
    predictions = pd.read_parquet(PHASE2_PREDICTIONS_PATH)
    portfolio = pd.read_csv(PHASE3_DAILY_PATH)
    validate_inputs(panel, predictions, portfolio)
    enriched = enrich_portfolio(panel, predictions, portfolio)
    folds = summarize_by_fold(enriched)
    regimes = summarize_by_regime(enriched)
    concentration = build_concentration(folds)
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    folds.to_csv(FOLD_METRICS_PATH, index=False)
    regimes.to_csv(REGIME_METRICS_PATH, index=False)
    concentration.to_csv(CONCENTRATION_PATH, index=False)
    manifest = build_manifest(enriched, folds, regimes, concentration)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
