"""V5 Phase 3: frozen development-only 60% SPY / 40% Top-5 diagnostics.

Uses only Phase 2 out-of-fold HGB rankings. The portfolio rule is frozen before
inspection: 60% SPY plus 40% equally divided across the five highest-ranked
candidate stocks, rebalanced every 5 trading sessions. Costs are charged on
turnover. This phase does not fit models or inspect the future holdout.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v5.config import RESEARCH_PANEL_PATH
from ml.v5.phase1 import FUTURE_HOLDOUT_START_UTC

PHASE = 3
MODEL_ID = "hist_gradient_boosting"
CORE_WEIGHT = 0.60
SLEEVE_WEIGHT = 0.40
TOP_N = 5
REBALANCE_DAYS = 5
COST_BPS = (0.0, 10.0, 25.0, 50.0)

PHASE2_ROOT = Path("data/model/v5/phase2")
PREDICTIONS_PATH = PHASE2_ROOT / "predictions.parquet"
PHASE_ROOT = Path("data/model/v5/phase3")
DAILY_PATH = PHASE_ROOT / "portfolio_daily.csv"
METRICS_PATH = PHASE_ROOT / "portfolio_metrics.csv"
MANIFEST_PATH = PHASE_ROOT / "manifest.json"


def validate_inputs(panel, predictions):
    panel_required = {"timestamp_utc", "symbol", "forward_stock_return_5d", "forward_spy_return_5d"}
    pred_required = {"timestamp_utc", "symbol", "model_id", "split", "predicted_score"}
    missing_panel = sorted(panel_required - set(panel.columns))
    missing_pred = sorted(pred_required - set(predictions.columns))
    if missing_panel:
        raise ValueError("V5 Phase 3 panel missing: " + ", ".join(missing_panel))
    if missing_pred:
        raise ValueError("V5 Phase 3 predictions missing: " + ", ".join(missing_pred))


def build_rebalance_table(panel, predictions):
    p = predictions.loc[
        (predictions["model_id"] == MODEL_ID) & (predictions["split"] == "development")
    ].copy()
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    x = panel[["timestamp_utc", "symbol", "forward_stock_return_5d", "forward_spy_return_5d"]].copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x = p[["timestamp_utc", "symbol", "predicted_score"]].merge(
        x, on=["timestamp_utc", "symbol"], how="left", validate="one_to_one"
    )
    x = x[x["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    dates = pd.Index(sorted(x["timestamp_utc"].unique()))
    rebalance_dates = set(dates[::REBALANCE_DAYS])
    x = x[x["timestamp_utc"].isin(rebalance_dates)]

    rows = []
    previous = {}
    for ts, g in x.groupby("timestamp_utc", sort=True):
        g = g.dropna(subset=["predicted_score", "forward_stock_return_5d", "forward_spy_return_5d"])
        if len(g) < TOP_N:
            continue
        top = g.nlargest(TOP_N, "predicted_score")
        weights = {"SPY": CORE_WEIGHT}
        weights.update({s: SLEEVE_WEIGHT / TOP_N for s in top["symbol"]})
        turnover = sum(abs(weights.get(k, 0.0) - previous.get(k, 0.0)) for k in set(weights) | set(previous))
        if not previous:
            turnover = sum(weights.values())
        spy_return = float(top["forward_spy_return_5d"].iloc[0])
        sleeve_return = float(top["forward_stock_return_5d"].mean())
        gross_return = CORE_WEIGHT * spy_return + SLEEVE_WEIGHT * sleeve_return
        rows.append({
            "timestamp_utc": ts,
            "selected_symbols": ",".join(top["symbol"].tolist()),
            "spy_return_5d": spy_return,
            "sleeve_return_5d": sleeve_return,
            "gross_return_5d": gross_return,
            "turnover": float(turnover),
        })
        previous = weights
    return pd.DataFrame(rows)


def summarize(table):
    rows = []
    periods_per_year = 252.0 / REBALANCE_DAYS
    for cost in COST_BPS:
        t = table.copy()
        t["net_return"] = t["gross_return_5d"] - t["turnover"] * cost / 10000.0
        equity = (1.0 + t["net_return"]).cumprod()
        spy_equity = (1.0 + t["spy_return_5d"]).cumprod()
        peak = equity.cummax()
        dd = equity / peak - 1.0
        vol = t["net_return"].std(ddof=1) * np.sqrt(periods_per_year)
        ann = equity.iloc[-1] ** (periods_per_year / len(t)) - 1.0
        spy_ann = spy_equity.iloc[-1] ** (periods_per_year / len(t)) - 1.0
        rows.append({
            "variant": "spy60_hgb_top5_40",
            "cost_bps": cost,
            "period_count": len(t),
            "ending_equity": equity.iloc[-1],
            "cumulative_return": equity.iloc[-1] - 1.0,
            "annualized_return": ann,
            "annualized_volatility": vol,
            "sharpe_like": ann / vol if vol > 0 else np.nan,
            "maximum_drawdown": dd.min(),
            "average_turnover": t["turnover"].mean(),
            "total_turnover": t["turnover"].sum(),
            "spy_ending_equity": spy_equity.iloc[-1],
            "spy_annualized_return": spy_ann,
            "annualized_excess_vs_spy": ann - spy_ann,
            "positive_period_rate": t["net_return"].gt(0).mean(),
        })
    return pd.DataFrame(rows)


def build_manifest(table):
    return {
        "research_version": "v5",
        "phase": PHASE,
        "stage": "frozen_development_portfolio_diagnostics",
        "ranking_model": MODEL_ID,
        "portfolio_rule": {
            "spy_core_weight": CORE_WEIGHT,
            "top_5_sleeve_weight": SLEEVE_WEIGHT,
            "top_n": TOP_N,
            "candidate_weight_each": SLEEVE_WEIGHT / TOP_N,
            "rebalance_trading_days": REBALANCE_DAYS,
        },
        "cost_bps": list(COST_BPS),
        "rebalance_periods": int(len(table)),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": "Development-only frozen Phase 2 HGB portfolio diagnostic; no model fitting, threshold search, portfolio-weight optimization, leverage, shorting, derivatives, live execution, or future-holdout evaluation.",
        "outputs": {"portfolio_daily": str(DAILY_PATH), "portfolio_metrics": str(METRICS_PATH)},
        "next_step": "Review economics and robustness versus SPY across fixed cost scenarios. Do not alter the September 2026 future holdout based on these results.",
    }


def main():
    if not RESEARCH_PANEL_PATH.exists() or not PREDICTIONS_PATH.exists():
        raise FileNotFoundError("Run V5 dataset preparation and Phase 2 before Phase 3")
    panel = pd.read_parquet(RESEARCH_PANEL_PATH)
    predictions = pd.read_parquet(PREDICTIONS_PATH)
    validate_inputs(panel, predictions)
    table = build_rebalance_table(panel, predictions)
    if table.empty:
        raise ValueError("No V5 Phase 3 rebalance periods generated")
    metrics = summarize(table)
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    table.to_csv(DAILY_PATH, index=False)
    metrics.to_csv(METRICS_PATH, index=False)
    manifest = build_manifest(table)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
