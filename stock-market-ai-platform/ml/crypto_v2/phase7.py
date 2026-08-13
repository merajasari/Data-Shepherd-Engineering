"""Crypto V2 Phase 7: ex-BTC cross-sectional ranking and portfolio diagnostics.

This phase implements the pre-registered architecture split established after
Crypto V2 Phases 3-6 and BTC V1 Phases 1-3. BTC-USD is excluded from the
investable/ranked cross-section, but BTC-derived features and BTC-relative
labels remain available as market context and benchmark information.

The model is the same frozen-methodology 7-day HistGradientBoosting setup used
in Crypto V2 Phase 3, refit walk-forward on the ex-BTC universe with the same
6-month development folds and 7-day purge. Investable dates require at least
10 eligible non-BTC assets. Portfolio diagnostics are top-3, top-5, and top
quintile equal weight with fixed 0/10/25/50 bps round-trip costs. BTC is allowed
only as a benchmark, never as a Phase 7 holding. No BTC V1 signal, market gate,
threshold search, hyperparameter tuning, leverage, shorting, derivatives, live
execution, or future-holdout evaluation is permitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
from sklearn.base import clone

from ml.crypto_v2.config import MODEL_ROOT, RESEARCH_VERSION
from ml.crypto_v2.phase3 import (
    FUTURE_HOLDOUT_START_UTC,
    MIN_CROSS_SECTION_ASSETS,
    MODEL_FEATURES,
    make_folds,
    model_definitions,
    validate_fold,
)

PHASE7_ROOT = MODEL_ROOT / "phase7"
HORIZON_DAYS = 7
MODEL_ID = "hist_gradient_boosting"
BENCHMARK_PRODUCT = "BTC-USD"
INVESTABLE_MIN_ASSETS = MIN_CROSS_SECTION_ASSETS
VARIANTS = (
    "ex_btc_top_3_equal_weight",
    "ex_btc_top_5_equal_weight",
    "ex_btc_top_quintile_equal_weight",
)
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
DAYS_PER_YEAR = 365.0


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_panel(model_root=MODEL_ROOT):
    path = Path(model_root) / "research_panel_7d.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    panel = pd.read_parquet(path).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    required = set(MODEL_FEATURES) | {
        "timestamp_utc", "product_id", "return_1d",
        "forward_return_relative_to_btc_7d", "target_endpoint_utc_7d",
    }
    missing = required - set(panel.columns)
    if missing:
        raise ValueError("7-day panel missing columns: " + ", ".join(sorted(missing)))
    if panel.duplicated(["timestamp_utc", "product_id"]).any():
        raise ValueError("Duplicate research-panel keys")
    return path, panel.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def build_ex_btc_universe(panel, minimum=INVESTABLE_MIN_ASSETS):
    """Exclude BTC as a holding, then enforce breadth on non-BTC assets only."""
    out = panel[panel["product_id"] != BENCHMARK_PRODUCT].copy()
    counts = out.groupby("timestamp_utc")["product_id"].transform("nunique")
    out = out[counts >= int(minimum)].copy()
    out["eligible_ex_btc_asset_count"] = out.groupby("timestamp_utc")["product_id"].transform("nunique")
    if (out["product_id"] == BENCHMARK_PRODUCT).any():
        raise RuntimeError("BTC leaked into Phase 7 investable universe")
    return out.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def build_predictions(ex_btc):
    """Walk-forward HGB predictions using the unchanged Phase 3 methodology."""
    definition = model_definitions()[MODEL_ID]
    rows = []
    folds = make_folds(ex_btc["timestamp_utc"], HORIZON_DAYS)
    for fold in folds:
        if fold.split != "development":
            continue
        train, validation = validate_fold(fold, ex_btc)
        model = clone(definition).fit(
            train[list(MODEL_FEATURES)],
            train["forward_return_relative_to_btc_7d"],
        )
        scores = model.predict(validation[list(MODEL_FEATURES)])
        out = validation[[
            "timestamp_utc", "product_id", "forward_return_relative_to_btc_7d",
            "eligible_ex_btc_asset_count",
        ]].copy()
        out = out.rename(columns={
            "forward_return_relative_to_btc_7d": "actual_btc_relative_forward_return"
        })
        out["predicted_score"] = scores
        out["fold_id"] = fold.fold_id
        out["split"] = fold.split
        out["model_id"] = MODEL_ID
        out["horizon_days"] = HORIZON_DAYS
        grouped = out.groupby("timestamp_utc", sort=False)
        out["actual_cross_sectional_rank"] = grouped[
            "actual_btc_relative_forward_return"
        ].rank(method="average", ascending=False)
        out["predicted_cross_sectional_rank"] = grouped[
            "predicted_score"
        ].rank(method="average", ascending=False)
        rows.append(out)
    pred = pd.concat(rows, ignore_index=True).sort_values(
        ["timestamp_utc", "product_id"]
    ).reset_index(drop=True)
    if pred.empty:
        raise ValueError("No Phase 7 development predictions")
    if (pred["product_id"] == BENCHMARK_PRODUCT).any():
        raise RuntimeError("BTC appeared in Phase 7 predictions")
    if pred.duplicated(["timestamp_utc", "product_id", "fold_id"]).any():
        raise ValueError("Duplicate Phase 7 prediction keys")
    return pred


def daily_rank_metrics(predictions):
    rows = []
    for (fold_id, timestamp), day in predictions.groupby(
        ["fold_id", "timestamp_utc"], sort=True
    ):
        order = day.sort_values(
            ["predicted_score", "product_id"], ascending=[False, True]
        )
        actual = day["actual_btc_relative_forward_return"]
        predicted = day["predicted_score"]
        bucket = max(1, len(order) // 5)
        rows.append({
            "fold_id": fold_id,
            "timestamp_utc": timestamp,
            "asset_count": len(day),
            "ic": predicted.corr(actual, method="spearman") if predicted.nunique() > 1 else np.nan,
            "top_minus_bottom_spread": (
                order.head(bucket)["actual_btc_relative_forward_return"].mean()
                - order.tail(bucket)["actual_btc_relative_forward_return"].mean()
            ),
            "top_3_btc_relative_return": order.head(3)["actual_btc_relative_forward_return"].mean(),
            "top_5_btc_relative_return": order.head(5)["actual_btc_relative_forward_return"].mean(),
        })
    return pd.DataFrame(rows)


def summarize_rank_metrics(predictions, daily):
    return pd.DataFrame([{
        "model_id": MODEL_ID,
        "split": "development",
        "observation_count": int(len(predictions)),
        "day_count": int(len(daily)),
        "mean_ic": float(daily["ic"].mean()),
        "median_ic": float(daily["ic"].median()),
        "ic_hit_rate": float(daily["ic"].gt(0).mean()),
        "top_minus_bottom_spread": float(daily["top_minus_bottom_spread"].mean()),
        "top_3_btc_relative_return": float(daily["top_3_btc_relative_return"].mean()),
        "top_5_btc_relative_return": float(daily["top_5_btc_relative_return"].mean()),
    }])


def rebalance_dates(timestamps, every_days=HORIZON_DAYS):
    dates = pd.DatetimeIndex(
        pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)
    ).sort_values()
    if dates.empty:
        return dates
    out = []
    due = dates[0]
    while due <= dates[-1]:
        later = dates[dates >= due]
        if len(later) == 0:
            break
        chosen = later[0]
        out.append(chosen)
        due = chosen + pd.Timedelta(days=every_days)
    return pd.DatetimeIndex(list(dict.fromkeys(out)))


def target_products(day, variant):
    ranked = day.sort_values(
        ["predicted_score", "product_id"], ascending=[False, True]
    )
    if (ranked["product_id"] == BENCHMARK_PRODUCT).any():
        raise RuntimeError("BTC cannot be selected in Phase 7")
    if variant == "ex_btc_top_3_equal_weight":
        n = min(3, len(ranked))
    elif variant == "ex_btc_top_5_equal_weight":
        n = min(5, len(ranked))
    elif variant == "ex_btc_top_quintile_equal_weight":
        n = max(1, len(ranked) // 5)
    else:
        raise ValueError(f"Unknown Phase 7 variant: {variant}")
    return ranked["product_id"].head(n).tolist()


def _return_map(panel):
    return {
        ts: dict(zip(g["product_id"], pd.to_numeric(g["return_1d"], errors="coerce")))
        for ts, g in panel.groupby("timestamp_utc", sort=True)
    }


def simulate_strategy(predictions, full_panel, variant, cost_bps):
    signal_dates = pd.DatetimeIndex(predictions["timestamp_utc"].unique()).sort_values()
    schedule = set(rebalance_dates(signal_dates))
    signal_map = {ts: g.copy() for ts, g in predictions.groupby("timestamp_utc", sort=True)}
    returns = _return_map(full_panel)
    panel_dates = pd.DatetimeIndex(full_panel["timestamp_utc"].unique()).sort_values()
    dates = panel_dates[(panel_dates >= signal_dates.min()) & (panel_dates <= signal_dates.max())]
    values = {}
    cash = STARTING_EQUITY
    equity = STARTING_EQUITY
    rows = []
    for i, ts in enumerate(dates):
        previous = equity
        turnover = 0.0
        transaction_cost = 0.0
        if i > 0 and values:
            day_returns = returns.get(ts, {})
            missing = [p for p in values if pd.isna(day_returns.get(p, np.nan))]
            if missing:
                current = {p: v / equity for p, v in values.items()} if equity > 0 else {}
                forced_turnover = 0.5 * sum(abs(current.get(p, 0.0)) for p in missing)
                forced_cost = equity * forced_turnover * float(cost_bps) / 10_000.0
                cash += sum(values[p] for p in missing) - forced_cost
                for p in missing:
                    values.pop(p, None)
                turnover += forced_turnover
                transaction_cost += forced_cost
            for p in list(values):
                values[p] *= 1.0 + float(day_returns[p])
            equity = cash + sum(values.values())
        is_rebalance = ts in schedule and ts in signal_map
        if is_rebalance:
            selected = target_products(signal_map[ts], variant)
            target = {p: 1.0 / len(selected) for p in selected}
            if BENCHMARK_PRODUCT in target:
                raise RuntimeError("BTC cannot be held by Phase 7 strategy")
            current = {p: v / equity for p, v in values.items()} if equity > 0 else {}
            names = set(current) | set(target)
            reb_turnover = 0.5 * sum(
                abs(target.get(p, 0.0) - current.get(p, 0.0)) for p in names
            )
            reb_cost = equity * reb_turnover * float(cost_bps) / 10_000.0
            post = max(0.0, equity - reb_cost)
            values = {p: post * w for p, w in target.items()}
            cash = post - sum(values.values())
            equity = cash + sum(values.values())
            turnover += reb_turnover
            transaction_cost += reb_cost
        rows.append({
            "timestamp_utc": ts,
            "variant": variant,
            "cost_bps_round_trip": float(cost_bps),
            "is_rebalance": bool(is_rebalance),
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "cash_weight": cash / equity if equity > 0 else np.nan,
            "equity": equity,
        })
    return pd.DataFrame(rows)


def simulate_benchmark(full_panel, predictions, variant, cost_bps=0.0):
    signal_dates = pd.DatetimeIndex(predictions["timestamp_utc"].unique()).sort_values()
    panel = full_panel[
        (full_panel["timestamp_utc"] >= signal_dates.min())
        & (full_panel["timestamp_utc"] <= signal_dates.max())
    ].copy()
    if variant == "cash":
        rows = pd.DataFrame({"timestamp_utc": sorted(panel["timestamp_utc"].unique())})
        rows["variant"] = variant
        rows["cost_bps_round_trip"] = float(cost_bps)
        rows["is_rebalance"] = False
        rows["turnover"] = 0.0
        rows["transaction_cost"] = 0.0
        rows["net_return"] = 0.0
        rows["cash_weight"] = 1.0
        rows["equity"] = 1.0
        return rows
    if variant != "btc_benchmark":
        raise ValueError(variant)
    btc = panel[panel["product_id"] == BENCHMARK_PRODUCT][
        ["timestamp_utc", "return_1d"]
    ].drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
    if btc.empty:
        raise ValueError("BTC benchmark unavailable")
    equity = STARTING_EQUITY * (1.0 - float(cost_bps) / 10_000.0)
    rows = []
    for i, row in enumerate(btc.itertuples(index=False)):
        previous = equity
        if i > 0:
            equity *= 1.0 + float(row.return_1d)
        rows.append({
            "timestamp_utc": row.timestamp_utc,
            "variant": variant,
            "cost_bps_round_trip": float(cost_bps),
            "is_rebalance": i == 0,
            "turnover": 1.0 if i == 0 else 0.0,
            "transaction_cost": STARTING_EQUITY * float(cost_bps) / 10_000.0 if i == 0 else 0.0,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "cash_weight": 0.0,
            "equity": equity,
        })
    return pd.DataFrame(rows)


def summarize_portfolio(path):
    net = pd.to_numeric(path["net_return"], errors="coerce").iloc[1:].dropna()
    ending = float(path["equity"].iloc[-1])
    obs = max(0, len(path) - 1)
    annualized = ending ** (DAYS_PER_YEAR / obs) - 1.0 if obs and ending > 0 else np.nan
    vol = float(net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    running = path["equity"].cummax()
    drawdown = path["equity"] / running - 1.0
    rebalances = path[path["is_rebalance"]]
    return {
        "variant": path["variant"].iloc[0],
        "cost_bps_round_trip": float(path["cost_bps_round_trip"].iloc[0]),
        "observation_count": obs,
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "annualized_return": annualized,
        "annualized_volatility": vol,
        "sharpe_like": sharpe,
        "maximum_drawdown": float(drawdown.min()),
        "average_turnover_per_rebalance": float(rebalances["turnover"].mean()) if len(rebalances) else 0.0,
        "total_turnover": float(path["turnover"].sum()),
        "number_of_rebalances": int(len(rebalances)),
        "average_cash_weight": float(path["cash_weight"].mean()),
        "positive_period_rate": float(net.gt(0).mean()) if len(net) else np.nan,
    }


def run_phase7(model_root=MODEL_ROOT, output_root=PHASE7_ROOT):
    panel_path, full_panel = load_panel(model_root)
    before = _sha256(panel_path)
    ex_btc = build_ex_btc_universe(full_panel)
    predictions = build_predictions(ex_btc)
    daily_rank = daily_rank_metrics(predictions)
    rank_summary = summarize_rank_metrics(predictions, daily_rank)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    pred_path = output_root / "predictions.parquet"
    daily_rank_path = output_root / "daily_rank_metrics.csv"
    rank_summary_path = output_root / "rank_metrics_summary.csv"
    predictions.to_parquet(pred_path, index=False)
    daily_rank.to_csv(daily_rank_path, index=False)
    rank_summary.to_csv(rank_summary_path, index=False)

    portfolio_paths = []
    metrics = []
    for variant in VARIANTS:
        for cost in ROUND_TRIP_COST_BPS:
            path = simulate_strategy(predictions, full_panel, variant, cost)
            portfolio_paths.append(path)
            metrics.append(summarize_portfolio(path))
    for variant in ("btc_benchmark", "cash"):
        for cost in ROUND_TRIP_COST_BPS:
            path = simulate_benchmark(full_panel, predictions, variant, cost)
            portfolio_paths.append(path)
            metrics.append(summarize_portfolio(path))
    portfolio_daily = pd.concat(portfolio_paths, ignore_index=True)
    portfolio_metrics = pd.DataFrame(metrics)
    portfolio_daily_path = output_root / "portfolio_daily.csv"
    portfolio_metrics_path = output_root / "portfolio_metrics.csv"
    portfolio_daily.to_csv(portfolio_daily_path, index=False)
    portfolio_metrics.to_csv(portfolio_metrics_path, index=False)

    after = _sha256(panel_path)
    if after != before:
        raise RuntimeError("Frozen Crypto V2 Phase 2 panel changed during Phase 7")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 7,
        "stage": "ex_btc_cross_sectional_ranking_and_portfolio_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "architecture": {
            "investable_universe": "eligible Crypto V2 assets excluding BTC-USD",
            "benchmark_context": "BTC-derived features and BTC-relative labels retained",
            "btc_v1_signal_used": False,
            "minimum_non_btc_assets": INVESTABLE_MIN_ASSETS,
        },
        "model": {"horizon_days": HORIZON_DAYS, "model_id": MODEL_ID},
        "development_policy": "same Phase 3 expanding six-month folds and 7-day purge",
        "portfolio_variants": list(VARIANTS),
        "cost_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "input": {"research_panel_7d": str(panel_path), "sha256": before},
        "ex_btc_universe": {
            "rows": int(len(ex_btc)),
            "products": int(ex_btc["product_id"].nunique()),
            "start_utc": ex_btc["timestamp_utc"].min().isoformat(),
            "end_utc": ex_btc["timestamp_utc"].max().isoformat(),
        },
        "outputs": {
            "predictions": str(pred_path),
            "daily_rank_metrics": str(daily_rank_path),
            "rank_metrics_summary": str(rank_summary_path),
            "portfolio_daily": str(portfolio_daily_path),
            "portfolio_metrics": str(portfolio_metrics_path),
        },
        "policy": "BTC excluded from investable cross-section; no BTC V1 signal, market gate, threshold search, hyperparameter tuning, leverage, shorting, derivatives, live execution, or future-holdout evaluation",
        "next_step": "Compare ex-BTC development-only ranking and portfolio results with frozen Crypto V2 Phase 3/4 benchmarks. Do not tune Phase 7 based on these results.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    ap.add_argument("--output-root", type=Path, default=PHASE7_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase7(args.model_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
