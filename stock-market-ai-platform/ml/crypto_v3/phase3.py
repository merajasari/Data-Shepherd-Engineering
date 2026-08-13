"""Crypto V3 Phase 3: frozen dual-signal long-only portfolio diagnostics.

Consumes only frozen Crypto V3 Phase 2 development predictions plus frozen Phase 1
research data. The portfolio rule was pre-registered after reviewing Phase 2 model
quality and before inspecting any Phase 3 portfolio result:

* Gate: HGB positive-return probability > 0.50.
* Rank passing assets by Ridge predicted 7-day risk-adjusted return, descending.
* Evaluate top-3, top-5, and top-quintile equal-weight long-only portfolios.
* If no asset passes, hold 100% cash.
* Rebalance every 7 calendar days.
* Evaluate fixed 0/10/25/50 bps transaction-cost scenarios.
* Compare with BTC buy-and-hold, equal-weight non-BTC universe, and cash.

No fitting, threshold search, hyperparameter tuning, BTC V1 signal injection,
leverage, shorting, derivatives, live execution, or future-holdout evaluation occurs
in this phase. Data at or after 2026-09-01 remains untouched.
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

from ml.crypto_v3.phase1 import (
    DATASET_PATH,
    FUTURE_HOLDOUT_START_UTC,
    HORIZON_DAYS,
    RESEARCH_VERSION,
    SOURCE_PANEL_PATH,
)
from ml.crypto_v3.phase2 import (
    CLASSIFIER_MODEL_ID,
    PHASE2_ROOT,
    REGRESSOR_LINEAR_ID,
)

PHASE3_ROOT = Path("data/model/crypto_v3/phase3")
CLASSIFIER_THRESHOLD = 0.50
RANK_MODEL_ID = REGRESSOR_LINEAR_ID
VARIANTS = ("gated_top_3", "gated_top_5", "gated_top_quintile")
BENCHMARKS = ("btc_buy_and_hold", "equal_weight_non_btc_universe", "cash")
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
DAYS_PER_YEAR = 365.0
BTC_PRODUCT = "BTC-USD"


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


def load_inputs(phase2_root=PHASE2_ROOT, dataset_path=DATASET_PATH, source_panel_path=SOURCE_PANEL_PATH):
    phase2_root = Path(phase2_root)
    dataset_path = Path(dataset_path)
    source_panel_path = Path(source_panel_path)
    classifier_path = phase2_root / "classifier_predictions.parquet"
    regressor_path = phase2_root / "regressor_predictions.parquet"
    for path in (classifier_path, regressor_path, dataset_path, source_panel_path):
        if not path.exists():
            raise FileNotFoundError(path)

    clf = pd.read_parquet(classifier_path).copy()
    reg = pd.read_parquet(regressor_path).copy()
    alt = pd.read_parquet(dataset_path).copy()
    source = pd.read_parquet(source_panel_path).copy()
    for frame in (clf, reg, alt, source):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)

    clf_required = {
        "timestamp_utc", "product_id", "predicted_positive_probability",
        "model_id", "fold_id", "split",
    }
    reg_required = {
        "timestamp_utc", "product_id", "predicted_risk_adjusted_return_7d",
        "model_id", "fold_id", "split",
    }
    if clf_required - set(clf.columns):
        raise ValueError("Classifier predictions missing required columns")
    if reg_required - set(reg.columns):
        raise ValueError("Regressor predictions missing required columns")
    if not {"timestamp_utc", "product_id", "return_1d"}.issubset(alt.columns):
        raise ValueError("Crypto V3 Phase 1 dataset missing daily return columns")
    if not {"timestamp_utc", "product_id", "return_1d"}.issubset(source.columns):
        raise ValueError("Frozen source panel missing BTC benchmark return columns")

    clf = clf[
        (clf["model_id"] == CLASSIFIER_MODEL_ID)
        & (clf["split"] == "development")
        & (clf["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
    ].copy()
    reg = reg[
        (reg["model_id"] == RANK_MODEL_ID)
        & (reg["split"] == "development")
        & (reg["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
    ].copy()
    if clf.empty or reg.empty:
        raise ValueError("Frozen development predictions are required")
    key = ["timestamp_utc", "product_id", "fold_id"]
    if clf.duplicated(key).any() or reg.duplicated(key).any():
        raise ValueError("Duplicate Crypto V3 Phase 2 prediction keys")

    signals = clf[[
        "timestamp_utc", "product_id", "fold_id", "split",
        "predicted_positive_probability",
    ]].merge(
        reg[[
            "timestamp_utc", "product_id", "fold_id",
            "predicted_risk_adjusted_return_7d",
        ]],
        on=["timestamp_utc", "product_id", "fold_id"],
        how="inner",
        validate="one_to_one",
    )
    if len(signals) != len(clf) or len(signals) != len(reg):
        raise ValueError("Classifier and Ridge predictions do not align one-to-one")
    if (signals["product_id"] == BTC_PRODUCT).any():
        raise ValueError("BTC must not appear in Crypto V3 investable signals")
    signals["passes_classifier_gate"] = (
        signals["predicted_positive_probability"] > CLASSIFIER_THRESHOLD
    )
    return {
        "classifier_predictions": classifier_path,
        "regressor_predictions": regressor_path,
        "phase1_dataset": dataset_path,
        "source_panel": source_panel_path,
    }, signals.sort_values(["timestamp_utc", "product_id"]), alt, source


def rebalance_dates(timestamps):
    dates = pd.DatetimeIndex(
        pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)
    ).sort_values()
    if dates.empty:
        return pd.DatetimeIndex([])
    out = []
    due = dates[0]
    while due <= dates[-1]:
        later = dates[dates >= due]
        if len(later) == 0:
            break
        chosen = later[0]
        out.append(chosen)
        due = chosen + pd.Timedelta(days=HORIZON_DAYS)
    return pd.DatetimeIndex(list(dict.fromkeys(out)))


def selected_products(day, variant):
    passing = day[day["passes_classifier_gate"]].sort_values(
        ["predicted_risk_adjusted_return_7d", "product_id"],
        ascending=[False, True],
    )
    if passing.empty:
        return []
    if variant == "gated_top_3":
        n = 3
    elif variant == "gated_top_5":
        n = 5
    elif variant == "gated_top_quintile":
        n = max(1, len(day) // 5)
    else:
        raise ValueError(f"Unknown strategy variant: {variant}")
    return passing["product_id"].head(n).tolist()


def target_weights(day, variant):
    if variant in VARIANTS:
        selected = selected_products(day, variant)
    elif variant == "equal_weight_non_btc_universe":
        selected = sorted(day["product_id"].unique().tolist())
    elif variant == "cash":
        selected = []
    else:
        raise ValueError(f"Unsupported target-weight variant: {variant}")
    if not selected:
        return {}
    weight = 1.0 / len(selected)
    return {product: weight for product in selected}


def _current_weights(values, cash, equity):
    if equity <= 0:
        return {}, 0.0
    return ({p: float(v) / equity for p, v in values.items()}, float(cash) / equity)


def _turnover(current_assets, current_cash, target_assets):
    target_cash = max(0.0, 1.0 - sum(target_assets.values()))
    names = set(current_assets) | set(target_assets)
    asset_l1 = sum(abs(float(target_assets.get(p, 0.0)) - float(current_assets.get(p, 0.0))) for p in names)
    cash_change = abs(target_cash - float(current_cash))
    return 0.5 * (asset_l1 + cash_change)


def _trade(values, cash, equity, target, cost_bps):
    current_assets, current_cash = _current_weights(values, cash, equity)
    turnover = _turnover(current_assets, current_cash, target)
    transaction_cost = equity * turnover * float(cost_bps) / 10_000.0
    post = max(0.0, equity - transaction_cost)
    values = {p: post * w for p, w in target.items() if w > 0}
    cash = post - sum(values.values())
    return values, cash, turnover, transaction_cost


def _force_missing(values, cash, equity, available, cost_bps):
    missing = [p for p in values if p not in available]
    if not missing:
        return values, cash, 0.0, 0.0, 0
    current_assets, current_cash = _current_weights(values, cash, equity)
    target_assets = {p: w for p, w in current_assets.items() if p not in missing}
    target_cash = 1.0 - sum(target_assets.values())
    names = set(current_assets) | set(target_assets)
    asset_l1 = sum(abs(target_assets.get(p, 0.0) - current_assets.get(p, 0.0)) for p in names)
    turnover = 0.5 * (asset_l1 + abs(target_cash - current_cash))
    transaction_cost = equity * turnover * float(cost_bps) / 10_000.0
    realized = sum(values[p] for p in missing)
    values = dict(values)
    for p in missing:
        values.pop(p, None)
    cash = cash + realized - transaction_cost
    return values, cash, turnover, transaction_cost, len(missing)


def _return_map(frame):
    return {
        ts: dict(zip(g["product_id"], pd.to_numeric(g["return_1d"], errors="coerce")))
        for ts, g in frame.groupby("timestamp_utc", sort=True)
    }


def simulate_alt_strategy(signals, alt_panel, variant, cost_bps):
    signal_dates = pd.DatetimeIndex(signals["timestamp_utc"].unique()).sort_values()
    schedule = set(rebalance_dates(signal_dates))
    signal_map = {ts: g.copy() for ts, g in signals.groupby("timestamp_utc", sort=True)}
    returns = _return_map(alt_panel)
    dates = pd.DatetimeIndex(alt_panel["timestamp_utc"].unique()).sort_values()
    dates = dates[(dates >= signal_dates.min()) & (dates <= signal_dates.max())]

    values, cash, equity = {}, STARTING_EQUITY, STARTING_EQUITY
    rows = []
    for i, ts in enumerate(dates):
        previous = equity
        turnover = transaction_cost = 0.0
        forced = 0
        gross_return = 0.0
        if i > 0 and values:
            day_returns = returns.get(ts, {})
            available = {p for p, r in day_returns.items() if pd.notna(r)}
            pre = cash + sum(values.values())
            values, cash, t, c, forced = _force_missing(values, cash, pre, available, cost_bps)
            turnover += t
            transaction_cost += c
            market_pnl = 0.0
            for p in list(values):
                r = day_returns.get(p)
                if pd.notna(r):
                    before = values[p]
                    values[p] = before * (1.0 + float(r))
                    market_pnl += before * float(r)
            gross_return = market_pnl / previous if previous > 0 else np.nan
            equity = cash + sum(values.values())
        is_rebalance = ts in schedule and ts in signal_map
        passing_assets = np.nan
        if is_rebalance:
            day = signal_map[ts]
            passing_assets = int(day["passes_classifier_gate"].sum())
            target = target_weights(day, variant)
            values, cash, t, c = _trade(values, cash, equity, target, cost_bps)
            turnover += t
            transaction_cost += c
            equity = cash + sum(values.values())
        current_assets, current_cash = _current_weights(values, cash, equity)
        rows.append({
            "timestamp_utc": ts,
            "variant": variant,
            "cost_bps_round_trip": float(cost_bps),
            "is_rebalance": bool(is_rebalance),
            "passing_assets": passing_assets,
            "forced_exit_count": forced,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "gross_return": gross_return,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "gross_exposure": sum(current_assets.values()),
            "cash_weight": current_cash,
            "equity": equity,
        })
    return pd.DataFrame(rows)


def simulate_btc_benchmark(signals, source_panel, cost_bps):
    signal_dates = pd.DatetimeIndex(signals["timestamp_utc"].unique()).sort_values()
    btc = source_panel[source_panel["product_id"] == BTC_PRODUCT][["timestamp_utc", "return_1d"]].copy()
    btc = btc[(btc["timestamp_utc"] >= signal_dates.min()) & (btc["timestamp_utc"] <= signal_dates.max())]
    returns = dict(zip(btc["timestamp_utc"], pd.to_numeric(btc["return_1d"], errors="coerce")))
    equity = STARTING_EQUITY
    rows = []
    for i, ts in enumerate(pd.DatetimeIndex(btc["timestamp_utc"]).sort_values()):
        previous = equity
        turnover = transaction_cost = 0.0
        gross_return = 0.0
        if i == 0:
            turnover = 1.0
            transaction_cost = equity * float(cost_bps) / 10_000.0
            equity = max(0.0, equity - transaction_cost)
        else:
            r = returns.get(ts)
            if pd.notna(r):
                gross_return = float(r)
                equity *= 1.0 + float(r)
        rows.append({
            "timestamp_utc": ts,
            "variant": "btc_buy_and_hold",
            "cost_bps_round_trip": float(cost_bps),
            "is_rebalance": bool(i == 0),
            "passing_assets": np.nan,
            "forced_exit_count": 0,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "gross_return": gross_return,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "gross_exposure": 1.0,
            "cash_weight": 0.0,
            "equity": equity,
        })
    return pd.DataFrame(rows)


def _max_drawdown(equity):
    s = pd.Series(equity, dtype=float)
    if s.empty:
        return np.nan
    return float((s / s.cummax() - 1.0).min())


def summarize(path):
    path = path.sort_values("timestamp_utc").reset_index(drop=True)
    net = pd.to_numeric(path["net_return"], errors="coerce").iloc[1:].dropna()
    ending = float(path["equity"].iloc[-1])
    observations = max(0, len(path) - 1)
    annualized_return = ending ** (DAYS_PER_YEAR / observations) - 1.0 if observations > 0 and ending > 0 else np.nan
    vol = float(net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    rebalances = path[path["is_rebalance"]]
    passing = pd.to_numeric(rebalances["passing_assets"], errors="coerce").dropna()
    return {
        "variant": path["variant"].iloc[0],
        "cost_bps_round_trip": float(path["cost_bps_round_trip"].iloc[0]),
        "observation_count": observations,
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "annualized_return": annualized_return,
        "annualized_volatility": vol,
        "sharpe_like": sharpe,
        "maximum_drawdown": _max_drawdown(path["equity"]),
        "average_turnover_per_rebalance": float(rebalances["turnover"].mean()) if len(rebalances) else 0.0,
        "total_turnover": float(path["turnover"].sum()),
        "number_of_rebalances": int(len(rebalances)),
        "average_passing_assets": float(passing.mean()) if len(passing) else np.nan,
        "cash_rebalance_rate": float(rebalances["cash_weight"].gt(0.999999).mean()) if len(rebalances) else np.nan,
        "average_cash_weight": float(path["cash_weight"].mean()),
        "positive_period_rate": float(net.gt(0).mean()) if len(net) else np.nan,
    }


def run_phase3(phase2_root=PHASE2_ROOT, dataset_path=DATASET_PATH, source_panel_path=SOURCE_PANEL_PATH, output_root=PHASE3_ROOT):
    paths, signals, alt, source = load_inputs(phase2_root, dataset_path, source_panel_path)
    before = {name: _sha256(path) for name, path in paths.items()}
    paths_out = []
    for variant in VARIANTS + ("equal_weight_non_btc_universe", "cash"):
        for cost in ROUND_TRIP_COST_BPS:
            paths_out.append(simulate_alt_strategy(signals, alt, variant, cost))
    for cost in ROUND_TRIP_COST_BPS:
        paths_out.append(simulate_btc_benchmark(signals, source, cost))
    daily = pd.concat(paths_out, ignore_index=True)
    metrics = pd.DataFrame([
        summarize(g) for _, g in daily.groupby(["variant", "cost_bps_round_trip"], sort=True)
    ])

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    daily_path = output_root / "portfolio_daily.csv"
    metrics_path = output_root / "portfolio_metrics.csv"
    signal_path = output_root / "combined_signals.parquet"
    signals.to_parquet(signal_path, index=False)
    daily.to_csv(daily_path, index=False)
    metrics.to_csv(metrics_path, index=False)

    after = {name: _sha256(path) for name, path in paths.items()}
    if after != before:
        raise RuntimeError("Frozen Crypto V3 Phase 1/2 inputs changed during Phase 3")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "frozen_dual_signal_long_only_portfolio_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "rule": {
            "classifier_model": CLASSIFIER_MODEL_ID,
            "classifier_threshold": CLASSIFIER_THRESHOLD,
            "classifier_operator": ">",
            "rank_model": RANK_MODEL_ID,
            "rank_direction": "descending predicted risk-adjusted return",
            "if_no_assets_pass": "100% cash",
            "rebalance_days": HORIZON_DAYS,
        },
        "portfolio_variants": list(VARIANTS),
        "benchmarks": list(BENCHMARKS),
        "cost_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": (
            "development-only frozen Phase 2 signal diagnostics; no fitting, threshold search, "
            "hyperparameter tuning, BTC V1 signal, leverage, shorting, derivatives, live "
            "execution, or future-holdout evaluation"
        ),
        "inputs": {name: {"path": str(path), "sha256": before[name]} for name, path in paths.items()},
        "signal_rows": int(len(signals)),
        "gate_pass_rate": float(signals["passes_classifier_gate"].mean()),
        "outputs": {
            "combined_signals": str(signal_path),
            "portfolio_daily": str(daily_path),
            "portfolio_metrics": str(metrics_path),
        },
        "next_step": (
            "Review development-only portfolio economics versus BTC, equal-weight non-BTC, and "
            "cash across all fixed cost scenarios. Do not tune the classifier threshold, ranker, "
            "portfolio size, rebalance cadence, or future holdout based on Phase 3 results."
        ),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    ap.add_argument("--dataset", type=Path, default=DATASET_PATH)
    ap.add_argument("--source-panel", type=Path, default=SOURCE_PANEL_PATH)
    ap.add_argument("--output-root", type=Path, default=PHASE3_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase3(args.phase2_root, args.dataset, args.source_panel, args.output_root), indent=2))


if __name__ == "__main__":
    main()
