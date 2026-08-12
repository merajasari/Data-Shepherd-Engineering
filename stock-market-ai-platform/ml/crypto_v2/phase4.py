"""Crypto V2 Phase 4: frozen-signal, cost-aware long-only portfolio diagnostics.

Consumes only frozen Phase 3 development predictions and the frozen 7-day
research panel. No fitting, retuning, regime filtering, promotion, live
execution, leverage, shorting, or derivatives are permitted in this phase.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v2.config import MODEL_ROOT, RESEARCH_VERSION

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
PRIMARY_HORIZON_DAYS = 7
PRIMARY_MODEL_ID = "hist_gradient_boosting"
CONTROL_MODEL_IDS = ("momentum", "random", "equal_score")
MODEL_IDS = (PRIMARY_MODEL_ID,) + CONTROL_MODEL_IDS
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
DAYS_PER_YEAR = 365.0
BENCHMARK_PRODUCT = "BTC-USD"

PREDICTION_REQUIRED_COLUMNS = {
    "timestamp_utc", "product_id", "predicted_score", "fold_id", "split",
    "model_id", "horizon_days",
}
PANEL_REQUIRED_COLUMNS = {"timestamp_utc", "product_id", "return_1d"}

DAILY_COLUMNS = [
    "timestamp_utc", "split", "model_id", "variant", "cost_bps_round_trip",
    "is_rebalance", "forced_exit_count", "turnover", "transaction_cost",
    "gross_return", "net_return", "gross_exposure", "cash_weight", "equity",
]
METRIC_COLUMNS = [
    "split", "model_id", "variant", "cost_bps_round_trip", "observation_count",
    "starting_equity", "ending_equity", "cumulative_return", "annualized_return",
    "annualized_volatility", "sharpe_like", "maximum_drawdown",
    "average_turnover_per_rebalance", "total_turnover", "number_of_rebalances",
    "positive_period_rate", "worst_period_return", "best_period_return",
    "average_gross_return", "average_net_return", "exposure_fraction",
]


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_inputs(phase3_root=PHASE3_ROOT, model_root=MODEL_ROOT):
    phase3_root = Path(phase3_root)
    predictions_path = phase3_root / "predictions.parquet"
    manifest_path = phase3_root / "manifest.json"
    panel_path = Path(model_root) / "research_panel_7d.parquet"
    for p in (predictions_path, panel_path):
        if not p.exists():
            raise FileNotFoundError(str(p))
    predictions = pd.read_parquet(predictions_path)
    panel = pd.read_parquet(panel_path)
    predictions["timestamp_utc"] = pd.to_datetime(predictions["timestamp_utc"], utc=True)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    missing = PREDICTION_REQUIRED_COLUMNS - set(predictions.columns)
    if missing:
        raise ValueError("Phase 3 predictions missing columns: " + ", ".join(sorted(missing)))
    missing = PANEL_REQUIRED_COLUMNS - set(panel.columns)
    if missing:
        raise ValueError("7-day panel missing columns: " + ", ".join(sorted(missing)))
    predictions = predictions[
        (predictions["horizon_days"] == PRIMARY_HORIZON_DAYS)
        & predictions["model_id"].isin(MODEL_IDS)
        & (predictions["split"] == "development")
    ].copy()
    if predictions.empty:
        raise ValueError("No frozen development 7-day predictions")
    key = ["timestamp_utc", "product_id", "fold_id", "model_id", "horizon_days"]
    if predictions.duplicated(key).any():
        raise ValueError("Duplicate Phase 3 prediction keys")
    if panel.duplicated(["timestamp_utc", "product_id"]).any():
        raise ValueError("Duplicate research-panel keys")
    return {
        "phase3_predictions": predictions_path,
        "phase3_manifest": manifest_path,
        "research_panel_7d": panel_path,
    }, predictions, panel, _read_json(manifest_path)


def rebalance_dates(timestamps, every_days=7):
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)).sort_values()
    if dates.empty:
        return dates
    out, due, last = [], dates[0], dates[-1]
    while due <= last:
        later = dates[dates >= due]
        if len(later) == 0:
            break
        chosen = later[0]
        out.append(chosen)
        due = chosen + pd.Timedelta(days=every_days)
    return pd.DatetimeIndex(list(dict.fromkeys(out)))


def target_weights(day, variant):
    if day.empty or variant == "cash":
        return {}
    ranked = day.sort_values(["predicted_score", "product_id"], ascending=[False, True])
    products = ranked["product_id"].tolist()
    if variant == "top_3_equal_weight":
        selected = products[: min(3, len(products))]
    elif variant == "top_5_equal_weight":
        selected = products[: min(5, len(products))]
    elif variant == "top_quintile_equal_weight":
        n = max(1, len(products) // 5)
        selected = products[:n]
    elif variant == "equal_weight_universe":
        selected = products
    elif variant == "btc_benchmark":
        selected = [BENCHMARK_PRODUCT] if BENCHMARK_PRODUCT in products else []
    else:
        raise ValueError(f"Unknown variant: {variant}")
    if not selected:
        return {}
    w = 1.0 / len(selected)
    return {p: w for p in selected}


def _weights(values, equity):
    if equity <= 0:
        return {}
    return {p: v / equity for p, v in values.items() if abs(v) > 1e-15}


def _turnover(current, target):
    names = set(current) | set(target)
    return 0.5 * sum(abs(float(target.get(p, 0.0)) - float(current.get(p, 0.0))) for p in names)


def _trade(values, cash, equity, target, round_trip_bps):
    turnover = _turnover(_weights(values, equity), target)
    cost = equity * turnover * float(round_trip_bps) / 10_000.0
    post = max(0.0, equity - cost)
    values = {p: post * w for p, w in target.items() if w > 0}
    cash = post - sum(values.values())
    return values, cash, turnover, cost


def _force_missing(values, cash, available, equity, round_trip_bps):
    missing = [p for p in values if p not in available]
    if not missing:
        return values, cash, 0.0, 0.0, 0
    current = _weights(values, equity)
    turnover = 0.5 * sum(abs(current.get(p, 0.0)) for p in missing)
    cost = equity * turnover * float(round_trip_bps) / 10_000.0
    realized = sum(values[p] for p in missing)
    values = dict(values)
    for p in missing:
        values.pop(p, None)
    return values, cash + realized - cost, turnover, cost, len(missing)


def simulate_strategy(predictions, panel, model_id, variant, round_trip_bps):
    signal = predictions[predictions["model_id"] == model_id].copy()
    if signal.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    # Fold boundaries are evaluation bookkeeping only. Signals are chronologically
    # stitched because every row is out-of-sample from its own development fold.
    signal_dates = pd.DatetimeIndex(signal["timestamp_utc"].unique()).sort_values()
    schedule = set(rebalance_dates(signal_dates, PRIMARY_HORIZON_DAYS))
    signal_map = {t: d.copy() for t, d in signal.groupby("timestamp_utc", sort=True)}
    panel_dates = pd.DatetimeIndex(panel["timestamp_utc"].unique()).sort_values()
    dates = panel_dates[(panel_dates >= signal_dates.min()) & (panel_dates <= signal_dates.max())]
    return_map = {
        t: dict(zip(d["product_id"], pd.to_numeric(d["return_1d"], errors="coerce")))
        for t, d in panel.groupby("timestamp_utc", sort=True)
    }
    values, cash, equity = {}, STARTING_EQUITY, STARTING_EQUITY
    rows = []
    for i, timestamp in enumerate(dates):
        previous = equity
        turnover = cost = 0.0
        forced = 0
        gross_return = 0.0
        if i > 0 and values:
            day_returns = return_map.get(timestamp, {})
            available = {p for p, r in day_returns.items() if pd.notna(r)}
            pre_equity = cash + sum(values.values())
            values, cash, t, c, forced = _force_missing(values, cash, available, pre_equity, round_trip_bps)
            turnover += t
            cost += c
            market_pnl = 0.0
            for p in list(values):
                r = day_returns.get(p)
                if pd.notna(r):
                    before = values[p]
                    values[p] = before * (1.0 + float(r))
                    market_pnl += before * float(r)
            gross_return = market_pnl / previous if previous > 0 else np.nan
            equity = cash + sum(values.values())
        is_rebalance = timestamp in schedule and timestamp in signal_map
        if is_rebalance:
            target = target_weights(signal_map[timestamp], variant)
            values, cash, t, c = _trade(values, cash, equity, target, round_trip_bps)
            turnover += t
            cost += c
            equity = cash + sum(values.values())
        current = _weights(values, equity)
        rows.append({
            "timestamp_utc": timestamp,
            "split": "development",
            "model_id": model_id,
            "variant": variant,
            "cost_bps_round_trip": float(round_trip_bps),
            "is_rebalance": bool(is_rebalance),
            "forced_exit_count": forced,
            "turnover": turnover,
            "transaction_cost": cost,
            "gross_return": gross_return,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "gross_exposure": sum(abs(w) for w in current.values()),
            "cash_weight": cash / equity if equity > 0 else np.nan,
            "equity": equity,
        })
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _max_drawdown(equity):
    s = pd.Series(equity, dtype=float)
    if s.empty:
        return np.nan
    return float((s / s.cummax() - 1.0).min())


def summarize_path(path):
    first = path.iloc[0]
    net = pd.to_numeric(path["net_return"], errors="coerce").dropna()
    gross = pd.to_numeric(path["gross_return"], errors="coerce").dropna()
    ending = float(path["equity"].iloc[-1])
    observations = max(0, len(path) - 1)
    annualized = (ending ** (DAYS_PER_YEAR / observations) - 1.0) if observations > 0 and ending > 0 else np.nan
    vol = float(net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    rebalances = path[path["is_rebalance"]]
    return {
        "split": first["split"], "model_id": first["model_id"], "variant": first["variant"],
        "cost_bps_round_trip": first["cost_bps_round_trip"], "observation_count": observations,
        "starting_equity": STARTING_EQUITY, "ending_equity": ending,
        "cumulative_return": ending - 1.0, "annualized_return": annualized,
        "annualized_volatility": vol, "sharpe_like": sharpe,
        "maximum_drawdown": _max_drawdown(path["equity"]),
        "average_turnover_per_rebalance": float(rebalances["turnover"].mean()) if len(rebalances) else 0.0,
        "total_turnover": float(path["turnover"].sum()), "number_of_rebalances": int(len(rebalances)),
        "positive_period_rate": float(net.gt(0).mean()) if len(net) else np.nan,
        "worst_period_return": float(net.min()) if len(net) else np.nan,
        "best_period_return": float(net.max()) if len(net) else np.nan,
        "average_gross_return": float(gross.mean()) if len(gross) else np.nan,
        "average_net_return": float(net.mean()) if len(net) else np.nan,
        "exposure_fraction": float(path["gross_exposure"].gt(1e-12).mean()),
    }


def _specs():
    variants = ("top_3_equal_weight", "top_5_equal_weight", "top_quintile_equal_weight")
    specs = [(m, v, False) for m in MODEL_IDS for v in variants]
    specs += [(PRIMARY_MODEL_ID, v, True) for v in ("cash", "btc_benchmark", "equal_weight_universe")]
    return specs


def run_phase4(phase3_root=PHASE3_ROOT, model_root=MODEL_ROOT, output_root=PHASE4_ROOT):
    paths, predictions, panel, phase3_manifest = load_inputs(phase3_root, model_root)
    input_hashes = {k: _sha256(v) for k, v in paths.items() if Path(v).exists()}
    paths_out = []
    for model_id, variant, is_benchmark in _specs():
        for cost in ROUND_TRIP_COST_BPS:
            path = simulate_strategy(predictions, panel, model_id, variant, cost)
            if not path.empty:
                path["is_benchmark"] = is_benchmark
                paths_out.append(path)
    daily = pd.concat(paths_out, ignore_index=True)
    metrics = []
    for _, g in daily.groupby(["model_id", "variant", "cost_bps_round_trip"], sort=True):
        metrics.append(summarize_path(g.sort_values("timestamp_utc")))
    metrics = pd.DataFrame(metrics, columns=METRIC_COLUMNS)
    turnover = (
        daily.groupby(["model_id", "variant", "cost_bps_round_trip"], as_index=False)
        .agg(number_of_rebalances=("is_rebalance", "sum"), total_turnover=("turnover", "sum"), total_transaction_cost=("transaction_cost", "sum"))
    )
    benchmark = metrics[metrics["variant"].isin(["cash", "btc_benchmark", "equal_weight_universe"])].copy()
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output_root / "portfolio_daily.csv", index=False)
    metrics.to_csv(output_root / "portfolio_metrics.csv", index=False)
    turnover.to_csv(output_root / "turnover_summary.csv", index=False)
    benchmark.to_csv(output_root / "benchmark_metrics.csv", index=False)
    if {k: _sha256(v) for k, v in paths.items() if Path(v).exists()} != input_hashes:
        raise RuntimeError("Frozen Phase 3/Phase 2 inputs changed during Phase 4")
    manifest = {
        "phase": 4,
        "research_version": RESEARCH_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "development-only portfolio diagnostics from frozen Phase 3 signals; no fitting, retuning, regime filters, promotion, live execution, leverage, shorting, or derivatives",
        "primary_strategy": {"horizon_days": 7, "model_id": PRIMARY_MODEL_ID},
        "controls": list(CONTROL_MODEL_IDS),
        "future_holdout_policy": "No data at or after the reserved 2026-09-01 future holdout start is evaluated in Phase 4.",
        "source_files": {k: {"path": str(v), "sha256": input_hashes.get(k)} for k, v in paths.items()},
        "phase3_manifest": phase3_manifest,
        "strategy_definitions": {
            "top_3_equal_weight": "long-only equal weight across the highest 3 frozen scores",
            "top_5_equal_weight": "long-only equal weight across the highest 5 frozen scores",
            "top_quintile_equal_weight": "long-only equal weight across the highest floor(N/5), minimum 1, frozen scores",
            "cash": "100% cash",
            "btc_benchmark": "100% BTC when available, otherwise cash",
            "equal_weight_universe": "equal weight across the contemporaneous Phase 3 eligible universe",
        },
        "rebalance_convention": "7 calendar days, anchored to first development signal date; realized t-1 to t return is applied before observing the completed-candle signal at t",
        "cost_scenarios_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "outputs": {
            "portfolio_daily": str(output_root / "portfolio_daily.csv"),
            "portfolio_metrics": str(output_root / "portfolio_metrics.csv"),
            "turnover_summary": str(output_root / "turnover_summary.csv"),
            "benchmark_metrics": str(output_root / "benchmark_metrics.csv"),
        },
        "next_step": "Review development-only portfolio outcomes versus BTC and equal-weight benchmarks across all pre-registered cost scenarios. Do not tune or promote on these results.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest, daily, metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE4_ROOT)
    args = parser.parse_args(argv)
    manifest, _, metrics = run_phase4(args.phase3_root, args.model_root, args.output_root)
    print(json.dumps({
        "phase": 4,
        "primary_strategy": manifest["primary_strategy"],
        "policy": manifest["policy"],
        "metric_rows": len(metrics),
        "outputs": manifest["outputs"],
        "next_step": manifest["next_step"],
    }, indent=2))


if __name__ == "__main__":
    main()
