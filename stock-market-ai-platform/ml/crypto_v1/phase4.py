"""Crypto V1 Phase 4: deterministic, cost-aware portfolio simulation.

Phase 4 consumes frozen Phase 3 predictions for signals and the frozen 7-day
research panel only for realized market returns required to simulate capital.
It performs no fitting, retuning, model selection, promotion, live execution,
leverage, or derivatives.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v1.config import BENCHMARK_PRODUCT, MODEL_ROOT


PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
PRIMARY_HORIZON_DAYS = 7
PRIMARY_MODEL_ID = "momentum"
CONTROL_MODEL_IDS = ("hist_gradient_boosting", "random", "equal_score")
MODEL_IDS = (PRIMARY_MODEL_ID,) + CONTROL_MODEL_IDS
TOP_COUNTS = (3, 5)
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
TRADING_DAYS_PER_YEAR = 365.0

# Phase 4 does not introduce fresh randomness. The seed is recorded only to
# identify the frozen deterministic random control inherited from Phase 3.
FROZEN_PHASE3_RANDOM_SEED = 1729

PREDICTION_REQUIRED_COLUMNS = {
    "timestamp_utc", "product_id", "predicted_score", "fold_id", "split",
    "model_id", "horizon_days",
}
PANEL_REQUIRED_COLUMNS = {
    "timestamp_utc", "product_id", "return_1d", "forward_return_7d",
    "forward_btc_return_7d",
}

DAILY_COLUMNS = [
    "timestamp_utc", "split", "model_id", "strategy_id", "variant",
    "top_n", "cost_bps_round_trip", "is_rebalance", "forced_exit_count",
    "turnover", "transaction_cost", "gross_return", "net_return",
    "gross_exposure", "net_exposure", "cash_weight", "equity",
]
METRIC_COLUMNS = [
    "split", "model_id", "strategy_id", "variant", "top_n",
    "cost_bps_round_trip", "observation_count", "starting_equity",
    "ending_equity", "cumulative_return", "annualized_return",
    "annualized_volatility", "sharpe_like", "maximum_drawdown",
    "average_turnover_per_rebalance", "total_turnover", "number_of_rebalances",
    "positive_period_rate", "worst_period_return", "best_period_return",
    "average_gross_return", "average_net_return", "exposure_fraction",
]
TURNOVER_COLUMNS = [
    "split", "model_id", "strategy_id", "variant", "top_n",
    "cost_bps_round_trip", "number_of_rebalances", "average_turnover_per_rebalance",
    "total_turnover", "total_transaction_cost",
]
BENCHMARK_COLUMNS = METRIC_COLUMNS


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_phase3_manifest(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_inputs(phase3_root=PHASE3_ROOT, model_root=MODEL_ROOT):
    """Load immutable Phase 3 predictions and frozen 7-day research returns."""
    phase3_root = Path(phase3_root)
    predictions_path = phase3_root / "predictions.parquet"
    manifest_path = phase3_root / "manifest.json"
    research_panel_path = Path(model_root) / "research_panel_7d.parquet"

    missing = [str(p) for p in (predictions_path, research_panel_path) if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing Phase 4 input(s): " + ", ".join(missing))

    predictions = pd.read_parquet(predictions_path)
    panel = pd.read_parquet(research_panel_path)
    for frame in (predictions, panel):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)

    missing_predictions = sorted(PREDICTION_REQUIRED_COLUMNS - set(predictions.columns))
    missing_panel = sorted(PANEL_REQUIRED_COLUMNS - set(panel.columns))
    if missing_predictions:
        raise ValueError("Phase 3 predictions missing columns: " + ", ".join(missing_predictions))
    if missing_panel:
        raise ValueError("7-day research panel missing columns: " + ", ".join(missing_panel))

    predictions = predictions[
        (predictions["horizon_days"] == PRIMARY_HORIZON_DAYS)
        & predictions["model_id"].isin(MODEL_IDS)
    ].copy()
    if predictions.empty:
        raise ValueError("No frozen Phase 3 7-day candidate/control predictions found")

    key = ["timestamp_utc", "product_id", "fold_id", "split", "model_id", "horizon_days"]
    if predictions.duplicated(key).any():
        raise ValueError("Duplicate Phase 3 prediction keys")
    if not set(predictions["split"].unique()).issubset({"development", "holdout"}):
        raise ValueError("Unexpected Phase 3 split")

    panel_key = ["timestamp_utc", "product_id"]
    if panel.duplicated(panel_key).any():
        raise ValueError("Duplicate 7-day research panel keys")

    paths = {
        "phase3_predictions": predictions_path,
        "phase3_manifest": manifest_path,
        "research_panel_7d": research_panel_path,
    }
    return paths, predictions, panel, _read_phase3_manifest(manifest_path)


def rebalance_dates(timestamps, every_days=PRIMARY_HORIZON_DAYS):
    """Return deterministic calendar-day rebalance dates anchored to first date."""
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)).sort_values()
    if dates.empty:
        return dates
    anchor = dates[0]
    scheduled = []
    next_due = anchor
    available = set(dates)
    last = dates[-1]
    while next_due <= last:
        if next_due in available:
            scheduled.append(next_due)
        else:
            later = dates[dates >= next_due]
            if len(later) == 0:
                break
            scheduled.append(later[0])
        next_due = scheduled[-1] + pd.Timedelta(days=every_days)
    return pd.DatetimeIndex(list(dict.fromkeys(scheduled))).sort_values()


def _rank_day(day):
    return day.sort_values(["predicted_score", "product_id"], ascending=[False, True])


def target_weights(day, variant, top_n=None):
    """Construct mechanical target weights from the signal cross-section at t."""
    if day.empty:
        return {}
    ranked = _rank_day(day)
    products = ranked["product_id"].tolist()

    if variant in {"top_3_equal_weight", "top_5_equal_weight"}:
        n = int(top_n)
        selected = products[: min(n, len(products))]
        if not selected:
            return {}
        w = 1.0 / len(selected)
        return {p: w for p in selected}

    if variant == "top_minus_bottom":
        n = min(int(top_n), len(products) // 2)
        if n <= 0:
            return {}
        top = products[:n]
        bottom = products[-n:]
        # Gross exposure is exactly 1.0: +0.5 long and -0.5 short research legs.
        w = 0.5 / n
        result = {p: w for p in top}
        for p in bottom:
            result[p] = result.get(p, 0.0) - w
        return result

    if variant == "equal_weight_universe":
        if not products:
            return {}
        w = 1.0 / len(products)
        return {p: w for p in products}

    if variant == "btc_benchmark":
        return {BENCHMARK_PRODUCT: 1.0} if BENCHMARK_PRODUCT in products else {}

    if variant == "cash":
        return {}

    raise ValueError(f"Unknown variant: {variant}")


def _portfolio_turnover(current_weights, target):
    """One-way turnover; full long-only replacement is 1.0, cash entry is 0.5."""
    names = set(current_weights) | set(target)
    return 0.5 * sum(abs(float(target.get(p, 0.0)) - float(current_weights.get(p, 0.0))) for p in names)


def _weights_from_values(values, equity):
    if equity <= 0:
        return {p: 0.0 for p in values}
    return {p: v / equity for p, v in values.items() if abs(v) > 1e-15}


def _cost_rate(round_trip_bps):
    return float(round_trip_bps) / 10_000.0


def _apply_trade(values, cash, equity, target, round_trip_bps):
    current_weights = _weights_from_values(values, equity)
    turnover = _portfolio_turnover(current_weights, target)
    cost = equity * turnover * _cost_rate(round_trip_bps)
    post_cost_equity = max(0.0, equity - cost)
    new_values = {p: post_cost_equity * w for p, w in target.items() if abs(w) > 1e-15}
    invested_net = sum(new_values.values())
    # For long-short research portfolios, cash finances the zero/net exposure.
    new_cash = post_cost_equity - invested_net
    return new_values, new_cash, turnover, cost


def _force_missing_exits(values, cash, available_products, equity, round_trip_bps):
    missing = [p for p in values if p not in available_products]
    if not missing:
        return values, cash, 0.0, 0.0, 0
    current_weights = _weights_from_values(values, equity)
    turnover = 0.5 * sum(abs(current_weights.get(p, 0.0)) for p in missing)
    cost = equity * turnover * _cost_rate(round_trip_bps)
    realized = sum(values[p] for p in missing)
    values = dict(values)
    for p in missing:
        values.pop(p, None)
    cash = cash + realized - cost
    return values, cash, turnover, cost, len(missing)


def _daily_return_map(panel):
    frame = panel[["timestamp_utc", "product_id", "return_1d"]].copy()
    frame["return_1d"] = pd.to_numeric(frame["return_1d"], errors="coerce")
    return {
        timestamp: dict(zip(day["product_id"], day["return_1d"]))
        for timestamp, day in frame.groupby("timestamp_utc", sort=True)
    }


def _signal_by_date(predictions):
    return {timestamp: day.copy() for timestamp, day in predictions.groupby("timestamp_utc", sort=True)}


def simulate_strategy(predictions, panel, split, model_id, variant, top_n, round_trip_bps):
    """Simulate one split/strategy/cost path without using future signals.

    Timestamp convention: ``return_1d`` stamped t is the already-realized
    t-1 -> t market move. Existing holdings receive that move first. A signal
    stamped t is then observed after the completed UTC daily candle and target
    weights are set at t for the next interval. Holdings otherwise drift until
    the next scheduled 7-calendar-day rebalance. If a held asset has no valid
    return observation at t, it is exited to cash at its prior marked value.
    """
    signal = predictions[(predictions["split"] == split) & (predictions["model_id"] == model_id)].copy()
    if signal.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    signal_dates = pd.DatetimeIndex(signal["timestamp_utc"].unique()).sort_values()
    schedule = set(rebalance_dates(signal_dates))
    signal_map = _signal_by_date(signal)

    panel_dates = pd.DatetimeIndex(panel["timestamp_utc"].unique()).sort_values()
    start, end = signal_dates.min(), signal_dates.max()
    dates = panel_dates[(panel_dates >= start) & (panel_dates <= end)]
    returns_by_date = _daily_return_map(panel)

    values = {}
    cash = STARTING_EQUITY
    equity = STARTING_EQUITY
    rows = []

    for index, timestamp in enumerate(dates):
        previous_equity = equity
        turnover = 0.0
        transaction_cost = 0.0
        forced_exit_count = 0
        gross_return = 0.0

        # First realize the t-1 -> t market move using only holdings that were
        # already in place before the signal stamped t can be observed.
        if index > 0 and values:
            day_returns = returns_by_date.get(timestamp, {})
            available = {p for p, r in day_returns.items() if pd.notna(r)}
            pre_force_values = dict(values)
            pre_force_equity = cash + sum(values.values())
            values, cash, forced_turnover, forced_cost, forced_exit_count = _force_missing_exits(
                values, cash, available, pre_force_equity, round_trip_bps
            )
            turnover += forced_turnover
            transaction_cost += forced_cost

            market_pnl = 0.0
            for product in list(values):
                r = day_returns.get(product)
                if pd.notna(r):
                    before = values[product]
                    values[product] = before * (1.0 + float(r))
                    market_pnl += before * float(r)
            gross_return = market_pnl / previous_equity if previous_equity > 0 else np.nan
            equity = cash + sum(values.values())

        is_rebalance = timestamp in schedule and timestamp in signal_map
        if is_rebalance:
            day = signal_map[timestamp]
            target = target_weights(day, variant, top_n)
            values, cash, reb_turnover, reb_cost = _apply_trade(
                values, cash, equity, target, round_trip_bps
            )
            turnover += reb_turnover
            transaction_cost += reb_cost
            equity = cash + sum(values.values())

        net_return = equity / previous_equity - 1.0 if previous_equity > 0 else np.nan
        current_weights = _weights_from_values(values, equity)
        gross_exposure = sum(abs(w) for w in current_weights.values())
        net_exposure = sum(current_weights.values())
        cash_weight = cash / equity if equity > 0 else np.nan

        rows.append({
            "timestamp_utc": timestamp,
            "split": split,
            "model_id": model_id,
            "strategy_id": f"{model_id}:{variant}:top{top_n if top_n is not None else 0}",
            "variant": variant,
            "top_n": top_n,
            "cost_bps_round_trip": float(round_trip_bps),
            "is_rebalance": bool(is_rebalance),
            "forced_exit_count": forced_exit_count,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "gross_return": gross_return,
            "net_return": net_return,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "cash_weight": cash_weight,
            "equity": equity,
        })

    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _maximum_drawdown(equity):
    series = pd.Series(equity, dtype=float)
    running = series.cummax()
    dd = series / running - 1.0
    return float(dd.min()) if len(dd) else np.nan


def summarize_path(path):
    if path.empty:
        return {column: np.nan for column in METRIC_COLUMNS}
    first = path.iloc[0]
    net = pd.to_numeric(path["net_return"], errors="coerce").dropna()
    gross = pd.to_numeric(path["gross_return"], errors="coerce").dropna()
    starting = STARTING_EQUITY
    ending = float(path["equity"].iloc[-1])
    cumulative = ending / starting - 1.0
    observations = max(0, len(path) - 1)
    if observations > 0 and ending > 0:
        annualized = (ending / starting) ** (TRADING_DAYS_PER_YEAR / observations) - 1.0
    else:
        annualized = np.nan
    volatility = float(net.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    mean_daily = float(net.mean()) if len(net) else np.nan
    sharpe = mean_daily / net.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR) if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    rebalances = path[path["is_rebalance"]]
    return {
        "split": first["split"],
        "model_id": first["model_id"],
        "strategy_id": first["strategy_id"],
        "variant": first["variant"],
        "top_n": first["top_n"],
        "cost_bps_round_trip": first["cost_bps_round_trip"],
        "observation_count": observations,
        "starting_equity": starting,
        "ending_equity": ending,
        "cumulative_return": cumulative,
        "annualized_return": annualized,
        "annualized_volatility": volatility,
        "sharpe_like": sharpe,
        "maximum_drawdown": _maximum_drawdown(path["equity"]),
        "average_turnover_per_rebalance": float(rebalances["turnover"].mean()) if len(rebalances) else 0.0,
        "total_turnover": float(path["turnover"].sum()),
        "number_of_rebalances": int(len(rebalances)),
        "positive_period_rate": float(net.gt(0).mean()) if len(net) else np.nan,
        "worst_period_return": float(net.min()) if len(net) else np.nan,
        "best_period_return": float(net.max()) if len(net) else np.nan,
        "average_gross_return": float(gross.mean()) if len(gross) else np.nan,
        "average_net_return": mean_daily,
        "exposure_fraction": float(path["gross_exposure"].gt(1e-12).mean()),
    }


def _strategy_specs():
    specs = []
    for model_id in MODEL_IDS:
        for top_n in TOP_COUNTS:
            specs.append((model_id, f"top_{top_n}_equal_weight", top_n, False))
            specs.append((model_id, "top_minus_bottom", top_n, False))
    # Benchmarks are attached to the primary model only to avoid duplicate paths.
    specs.extend([
        (PRIMARY_MODEL_ID, "cash", None, True),
        (PRIMARY_MODEL_ID, "btc_benchmark", None, True),
        (PRIMARY_MODEL_ID, "equal_weight_universe", None, True),
    ])
    return specs


def run_phase4(phase3_root=PHASE3_ROOT, model_root=MODEL_ROOT, output_root=PHASE4_ROOT):
    """Generate deterministic Phase 4 portfolio artifacts from frozen inputs."""
    paths, predictions, panel, phase3_manifest = load_inputs(phase3_root, model_root)
    hashable_inputs = {k: v for k, v in paths.items() if v.exists()}
    hashes_before = {name: _sha256(path) for name, path in hashable_inputs.items()}
    rows_before = {
        "phase3_predictions": len(pd.read_parquet(paths["phase3_predictions"])),
        "research_panel_7d": len(panel),
    }

    all_paths = []
    for split in ("development", "holdout"):
        if not (predictions["split"] == split).any():
            continue
        for model_id, variant, top_n, is_benchmark in _strategy_specs():
            # Benchmarks use the primary model's cross-section solely as the
            # contemporaneous available universe; they do not use scores.
            if model_id not in set(predictions.loc[predictions["split"] == split, "model_id"]):
                continue
            for cost in ROUND_TRIP_COST_BPS:
                path = simulate_strategy(
                    predictions, panel, split, model_id, variant, top_n, cost
                )
                if not path.empty:
                    path["is_benchmark"] = bool(is_benchmark)
                    all_paths.append(path)

    portfolio_daily = pd.concat(all_paths, ignore_index=True) if all_paths else pd.DataFrame(columns=DAILY_COLUMNS + ["is_benchmark"])
    metrics_rows = []
    turnover_rows = []
    if not portfolio_daily.empty:
        group_keys = ["split", "model_id", "strategy_id", "variant", "top_n", "cost_bps_round_trip"]
        for _, group in portfolio_daily.groupby(group_keys, sort=True, dropna=False):
            metric = summarize_path(group.sort_values("timestamp_utc"))
            metrics_rows.append(metric)
            rebalances = group[group["is_rebalance"]]
            turnover_rows.append({
                "split": metric["split"], "model_id": metric["model_id"],
                "strategy_id": metric["strategy_id"], "variant": metric["variant"],
                "top_n": metric["top_n"], "cost_bps_round_trip": metric["cost_bps_round_trip"],
                "number_of_rebalances": metric["number_of_rebalances"],
                "average_turnover_per_rebalance": metric["average_turnover_per_rebalance"],
                "total_turnover": metric["total_turnover"],
                "total_transaction_cost": float(group["transaction_cost"].sum()),
            })
    portfolio_metrics = pd.DataFrame(metrics_rows, columns=METRIC_COLUMNS)
    turnover_summary = pd.DataFrame(turnover_rows, columns=TURNOVER_COLUMNS)
    benchmark_metrics = portfolio_metrics[
        portfolio_metrics["variant"].isin(["cash", "btc_benchmark", "equal_weight_universe"])
    ].copy() if not portfolio_metrics.empty else pd.DataFrame(columns=BENCHMARK_COLUMNS)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "portfolio_daily": output_root / "portfolio_daily.csv",
        "portfolio_metrics": output_root / "portfolio_metrics.csv",
        "turnover_summary": output_root / "turnover_summary.csv",
        "benchmark_metrics": output_root / "benchmark_metrics.csv",
    }
    portfolio_daily.to_csv(outputs["portfolio_daily"], index=False)
    portfolio_metrics.to_csv(outputs["portfolio_metrics"], index=False)
    turnover_summary.to_csv(outputs["turnover_summary"], index=False)
    benchmark_metrics.to_csv(outputs["benchmark_metrics"], index=False)

    hashes_after = {name: _sha256(path) for name, path in hashable_inputs.items()}
    if hashes_after != hashes_before:
        raise RuntimeError("Frozen Phase 3/market inputs changed during Phase 4")

    manifest = {
        "phase": 4,
        "research_version": "crypto_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": (
            "portfolio-construction research only; no fitting, retuning, promotion, "
            "live execution, leverage, or derivatives"
        ),
        "primary_strategy": {"horizon_days": 7, "model_id": PRIMARY_MODEL_ID},
        "controls": list(CONTROL_MODEL_IDS),
        "source_phase3": {
            "root": str(Path(phase3_root)),
            "file_hashes": {k: v for k, v in hashes_before.items() if k.startswith("phase3_")},
            "row_counts": {"predictions": rows_before["phase3_predictions"]},
            "manifest": phase3_manifest,
        },
        "market_return_source": {
            "path": str(paths["research_panel_7d"]),
            "sha256": hashes_before["research_panel_7d"],
            "rows": rows_before["research_panel_7d"],
            "purpose": "realized absolute daily and 7-day returns only; never used for fitting or parameter selection",
        },
        "strategy_definitions": {
            "top_3_equal_weight": "long-only equal weights across highest 3 Phase 3 scores at scheduled rebalance",
            "top_5_equal_weight": "long-only equal weights across highest 5 Phase 3 scores at scheduled rebalance",
            "top_minus_bottom": "research-only +0.5 gross across top-N and -0.5 gross across bottom-N; gross exposure <= 1.0",
            "cash": "100% cash, zero market return",
            "btc_benchmark": "100% BTC when BTC is available, otherwise cash",
            "equal_weight_universe": "equal weight across the contemporaneous frozen Phase 3 universe",
        },
        "rebalance_convention": (
            "7 calendar days, anchored independently to each split's first signal timestamp; "
            "if a scheduled calendar date is absent, use the first later available signal date. "
            "return_1d stamped t is first applied to holdings carried from t-1; only then is the "
            "completed-candle signal stamped t observed and target weights set for the next interval. Holdings otherwise drift "
            "unchanged until the next scheduled rebalance; missing held assets are exited to cash."
        ),
        "transaction_cost_convention": (
            "Scenarios are ROUND-TRIP bps. One-way turnover is 0.5*sum(abs(target_weight-current_weight)); "
            "cost = equity * turnover * round_trip_bps / 10000. Thus initial cash entry incurs half the "
            "round-trip rate and a complete long-only replacement incurs the full round-trip rate."
        ),
        "cost_scenarios_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "randomness": {
            "new_randomness_in_phase4": False,
            "frozen_phase3_random_control_seed": FROZEN_PHASE3_RANDOM_SEED,
        },
        "split_policy": "development and holdout are simulated and reported independently; holdout never chooses Phase 4 rules",
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return manifest, {
        "portfolio_daily": portfolio_daily,
        "portfolio_metrics": portfolio_metrics,
        "turnover_summary": turnover_summary,
        "benchmark_metrics": benchmark_metrics,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE4_ROOT)
    args = parser.parse_args()
    manifest, frames = run_phase4(args.phase3_root, args.model_root, args.output_root)
    print(json.dumps({
        "manifest": manifest,
        "rows": {name: len(frame) for name, frame in frames.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
