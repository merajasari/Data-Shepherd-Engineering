"""BTC V1 Phase 3: frozen-signal BTC/cash portfolio diagnostics.

Consumes only frozen BTC V1 Phase 2 development predictions. The primary rule
is pre-registered before inspecting portfolio results: use the frozen
hist_gradient_boosting 7-day prediction, hold BTC when predicted return > 0,
and otherwise hold cash. Rebalance every 7 calendar days on the first available
prediction date at or after the scheduled date. Compare against BTC buy-and-hold
and cash under fixed round-trip cost scenarios. No fitting, retuning, threshold
search, feature changes, leverage, shorting, derivatives, or future-holdout
evaluation are permitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.btc_v1.phase1 import MODEL_ROOT, LABELED_DATASET_PATH, RESEARCH_VERSION
from ml.btc_v1.phase2 import PHASE2_ROOT, FUTURE_HOLDOUT_START_UTC

PHASE3_ROOT = MODEL_ROOT / "phase3"
PRIMARY_MODEL_ID = "hist_gradient_boosting"
SIGNAL_THRESHOLD = 0.0
REBALANCE_DAYS = 7
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
DAYS_PER_YEAR = 365.0
VARIANTS = ("hgb_positive_else_cash", "btc_buy_and_hold", "cash")


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_inputs(phase2_root=PHASE2_ROOT, dataset_path=LABELED_DATASET_PATH):
    pred_path = Path(phase2_root) / "predictions.parquet"
    dataset_path = Path(dataset_path)
    if not pred_path.exists():
        raise FileNotFoundError(pred_path)
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)
    pred = pd.read_parquet(pred_path).copy()
    data = pd.read_parquet(dataset_path).copy()
    required_pred = {"timestamp_utc", "actual_forward_return_7d", "predicted_return_7d", "model_id", "fold_id", "split"}
    missing = required_pred - set(pred.columns)
    if missing:
        raise ValueError("BTC Phase 2 predictions missing columns: " + ", ".join(sorted(missing)))
    if not {"timestamp_utc", "return_1d"}.issubset(data.columns):
        raise ValueError("BTC Phase 1 dataset missing timestamp_utc or return_1d")
    pred["timestamp_utc"] = pd.to_datetime(pred["timestamp_utc"], utc=True)
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    pred = pred[(pred["split"] == "development") & (pred["model_id"] == PRIMARY_MODEL_ID)].copy()
    pred = pred[pred["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    if pred.empty:
        raise ValueError("No frozen BTC development predictions for primary model")
    if pred.duplicated(["timestamp_utc", "model_id"]).any():
        raise ValueError("Duplicate BTC Phase 2 prediction timestamps")
    return pred_path, dataset_path, pred.sort_values("timestamp_utc"), data.sort_values("timestamp_utc")


def rebalance_dates(timestamps, every_days=REBALANCE_DAYS):
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)).sort_values()
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


def simulate(predictions, dataset, variant, cost_bps):
    signal = predictions.set_index("timestamp_utc")["predicted_return_7d"].to_dict()
    signal_dates = pd.DatetimeIndex(predictions["timestamp_utc"].unique()).sort_values()
    schedule = set(rebalance_dates(signal_dates))
    data = dataset[(dataset["timestamp_utc"] >= signal_dates.min()) & (dataset["timestamp_utc"] <= signal_dates.max())].copy()
    returns = data.set_index("timestamp_utc")["return_1d"].to_dict()
    btc_value = 0.0
    cash = STARTING_EQUITY
    equity = STARTING_EQUITY
    rows = []
    for i, timestamp in enumerate(pd.DatetimeIndex(data["timestamp_utc"]).sort_values()):
        previous = equity
        gross_return = 0.0
        turnover = 0.0
        transaction_cost = 0.0
        if i > 0 and btc_value > 0:
            r = returns.get(timestamp)
            if pd.notna(r):
                gross_return = (btc_value * float(r)) / previous if previous > 0 else np.nan
                btc_value *= 1.0 + float(r)
                equity = cash + btc_value
        is_rebalance = timestamp in schedule
        if is_rebalance:
            if variant == "hgb_positive_else_cash":
                target_btc = 1.0 if float(signal[timestamp]) > SIGNAL_THRESHOLD else 0.0
            elif variant == "btc_buy_and_hold":
                target_btc = 1.0
            elif variant == "cash":
                target_btc = 0.0
            else:
                raise ValueError(f"Unknown variant: {variant}")
            current_btc = btc_value / equity if equity > 0 else 0.0
            turnover = abs(target_btc - current_btc)
            transaction_cost = equity * turnover * float(cost_bps) / 10_000.0
            post = max(0.0, equity - transaction_cost)
            btc_value = post * target_btc
            cash = post * (1.0 - target_btc)
            equity = post
        rows.append({
            "timestamp_utc": timestamp,
            "split": "development",
            "model_id": PRIMARY_MODEL_ID if variant == "hgb_positive_else_cash" else "benchmark",
            "variant": variant,
            "cost_bps_round_trip": float(cost_bps),
            "is_rebalance": bool(is_rebalance),
            "predicted_return_7d": signal.get(timestamp, np.nan),
            "btc_exposure": btc_value / equity if equity > 0 else np.nan,
            "cash_weight": cash / equity if equity > 0 else np.nan,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "gross_return": gross_return,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "equity": equity,
        })
    return pd.DataFrame(rows)


def _max_drawdown(equity):
    s = pd.Series(equity, dtype=float)
    return float((s / s.cummax() - 1.0).min()) if len(s) else np.nan


def summarize(path):
    net = pd.to_numeric(path["net_return"], errors="coerce").iloc[1:].dropna()
    ending = float(path["equity"].iloc[-1])
    observations = max(0, len(path) - 1)
    annualized = ending ** (DAYS_PER_YEAR / observations) - 1.0 if observations and ending > 0 else np.nan
    vol = float(net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    rebalances = path[path["is_rebalance"]]
    return {
        "variant": path["variant"].iloc[0],
        "cost_bps_round_trip": float(path["cost_bps_round_trip"].iloc[0]),
        "observation_count": observations,
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "annualized_return": annualized,
        "annualized_volatility": vol,
        "sharpe_like": sharpe,
        "maximum_drawdown": _max_drawdown(path["equity"]),
        "average_turnover_per_rebalance": float(rebalances["turnover"].mean()) if len(rebalances) else 0.0,
        "total_turnover": float(path["turnover"].sum()),
        "number_of_rebalances": int(len(rebalances)),
        "btc_exposure_rate": float(path["btc_exposure"].mean()),
        "positive_period_rate": float(net.gt(0).mean()) if len(net) else np.nan,
    }


def run_phase3(phase2_root=PHASE2_ROOT, dataset_path=LABELED_DATASET_PATH, output_root=PHASE3_ROOT):
    pred_path, dataset_path, pred, data = load_inputs(phase2_root, dataset_path)
    before = {"predictions": _sha256(pred_path), "dataset": _sha256(dataset_path)}
    paths = []
    for variant in VARIANTS:
        for cost in ROUND_TRIP_COST_BPS:
            paths.append(simulate(pred, data, variant, cost))
    daily = pd.concat(paths, ignore_index=True)
    metrics = pd.DataFrame([summarize(g.sort_values("timestamp_utc")) for _, g in daily.groupby(["variant", "cost_bps_round_trip"], sort=True)])
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    daily_path = output_root / "portfolio_daily.csv"
    metrics_path = output_root / "portfolio_metrics.csv"
    daily.to_csv(daily_path, index=False)
    metrics.to_csv(metrics_path, index=False)
    after = {"predictions": _sha256(pred_path), "dataset": _sha256(dataset_path)}
    if after != before:
        raise RuntimeError("Frozen BTC inputs changed during Phase 3")
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "frozen_signal_btc_cash_portfolio_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "primary_model_id": PRIMARY_MODEL_ID,
        "signal_rule": "predicted_return_7d > 0 => 100% BTC; otherwise 100% cash",
        "rebalance_days": REBALANCE_DAYS,
        "cost_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "policy": "development-only frozen-signal diagnostics; no fitting, retuning, threshold search, feature changes, leverage, shorting, derivatives, or future-holdout evaluation",
        "inputs": {"phase2_predictions": str(pred_path), "phase1_dataset": str(dataset_path), "sha256": before},
        "outputs": {"portfolio_daily": str(daily_path), "portfolio_metrics": str(metrics_path)},
        "next_step": "Compare frozen HGB BTC/cash strategy with BTC buy-and-hold and cash across all pre-registered costs. Do not tune on Phase 3 results."
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    ap.add_argument("--dataset", type=Path, default=LABELED_DATASET_PATH)
    ap.add_argument("--output-root", type=Path, default=PHASE3_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase3(args.phase2_root, args.dataset, args.output_root), indent=2))

if __name__ == "__main__":
    main()
