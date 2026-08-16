"""Crypto 15m V1 Phase 3: cost-aware overlapping-vintage portfolio simulation.

Uses ONLY frozen Phase 2 Ridge out-of-sample predictions. No refitting or
threshold/model tuning occurs here. A new ranking is observed every completed
15-minute decision, while each ranking vintage is held for the frozen 4-hour
(16-bar) primary horizon. The live target portfolio is the sum of the active
1/16-capital vintages, so overlapping 4-hour signals are represented rather
than incorrectly treating every 15-minute decision as an independent 4-hour
trade.

XRP remains excluded. The future holdout begins 2026-09-01 UTC and is not used.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE1_ROOT = Path("data/model/crypto_15m_v1/phase1")
PHASE2_ROOT = Path("data/model/crypto_15m_v1/phase2")
OUTPUT_ROOT = Path("data/model/crypto_15m_v1/phase3")
FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
MODEL_ID = "ridge"
HOLD_BARS = 16
BAR_MINUTES = 15
HOLD_TIME = pd.Timedelta(minutes=HOLD_BARS * BAR_MINUTES)
TOP_NS = (3, 5)
COST_BPS = (0.0, 5.0, 10.0, 25.0, 50.0)
BARS_PER_YEAR = 365.25 * 24 * 4


def _load_predictions(root: Path) -> pd.DataFrame:
    path = root / "predictions.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    p = pd.read_parquet(path)
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    p = p[(p["model_id"] == MODEL_ID) & (p["timestamp_utc"] < FUTURE_HOLDOUT_START)].copy()
    if p.empty:
        raise ValueError("No frozen Ridge OOS predictions found")
    if "XRP-USD" in set(p["product_id"]):
        raise RuntimeError("XRP leaked into core Phase 3 predictions")
    if p.duplicated(["timestamp_utc", "product_id"]).any():
        raise RuntimeError("Duplicate timestamp/product rows in Phase 2 predictions")
    return p.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def _load_market(root: Path, products: list[str], timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    frames = []
    for product in products:
        path = root / "core_panel" / f"{product}.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_parquet(path, columns=[
            "timestamp_utc", "product_id", "forward_return_15m", "btc_forward_return_15m"
        ])
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df[df["timestamp_utc"].isin(timestamps)].copy()
        frames.append(df)
    market = pd.concat(frames, ignore_index=True)
    return market


def _max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return np.nan
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(np.nanmin(dd))


def _annualized(ending_equity: float, bars: int) -> float:
    if bars <= 0 or ending_equity <= 0:
        return np.nan
    return float(ending_equity ** (BARS_PER_YEAR / bars) - 1.0)


def _metrics(path: pd.DataFrame, variant: str, top_n: int | None, cost_bps: float) -> dict:
    ending = float(path["equity"].iloc[-1]) if len(path) else 1.0
    return {
        "variant": variant,
        "top_n": top_n,
        "cost_bps_round_trip": cost_bps,
        "bars": int(len(path)),
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "annualized_return": _annualized(ending, len(path)),
        "maximum_drawdown": _max_drawdown(path["equity"].to_numpy(float)),
        "mean_15m_return": float(path["net_return"].mean()),
        "median_15m_return": float(path["net_return"].median()),
        "positive_bar_fraction": float((path["net_return"] > 0).mean()),
        "total_turnover": float(path["turnover"].sum()),
        "mean_turnover": float(path["turnover"].mean()),
        "total_cost_fraction": float(path["cost_fraction"].sum()),
        "mean_risky_weight": float(path["risky_weight"].mean()),
        "mean_missing_return_weight": float(path["missing_return_weight"].mean()),
    }


def _simulate_topn(score_wide: pd.DataFrame, ret_wide: pd.DataFrame, top_n: int, cost_bps: float) -> pd.DataFrame:
    products = list(score_wide.columns)
    scores = score_wide.to_numpy(float)
    rets = ret_wide.reindex(index=score_wide.index, columns=products).to_numpy(float)
    timestamps = score_wide.index
    active: deque[tuple[pd.Timestamp, np.ndarray]] = deque()
    prev = np.zeros(len(products), dtype=float)
    prev_cash = 1.0
    equity = 1.0
    rows = []
    sleeve_capital = 1.0 / HOLD_BARS

    for i, ts in enumerate(timestamps):
        while active and ts - active[0][0] >= HOLD_TIME:
            active.popleft()

        row_scores = scores[i]
        valid = np.flatnonzero(np.isfinite(row_scores))
        if len(valid):
            n = min(top_n, len(valid))
            chosen_local = np.argpartition(row_scores[valid], -n)[-n:]
            chosen = valid[chosen_local]
            vintage = np.zeros(len(products), dtype=float)
            vintage[chosen] = sleeve_capital / n
            active.append((ts, vintage))

        target = np.zeros(len(products), dtype=float)
        for _, vintage in active:
            target += vintage
        risky_weight = float(target.sum())
        cash = max(0.0, 1.0 - risky_weight)

        # Full-portfolio turnover includes cash so initial deployment and
        # de-risking are measured consistently. 0.5*L1 makes a full switch
        # from one fully invested portfolio to another equal turnover=1.
        turnover = 0.5 * (float(np.abs(target - prev).sum()) + abs(cash - prev_cash))
        cost = turnover * cost_bps / 10000.0

        bar_rets = rets[i]
        observed = np.isfinite(bar_rets)
        invested_observed = target * observed
        missing_weight = float((target * (~observed)).sum())
        gross_return = float(np.nansum(invested_observed * np.nan_to_num(bar_rets, nan=0.0)))
        # Any asset weight lacking an authoritative next-bar return is held as
        # cash for that bar; no return is synthesized.
        net_return = gross_return - cost
        equity *= 1.0 + net_return
        rows.append({
            "timestamp_utc": ts,
            "gross_return": gross_return,
            "net_return": net_return,
            "turnover": turnover,
            "cost_fraction": cost,
            "risky_weight": risky_weight,
            "cash_weight": cash + missing_weight,
            "missing_return_weight": missing_weight,
            "active_vintages": len(active),
            "equity": equity,
        })
        prev = target
        prev_cash = cash
    return pd.DataFrame(rows)


def _simulate_benchmark(timestamps: pd.DatetimeIndex, returns: pd.Series, cost_bps: float, variant: str) -> pd.DataFrame:
    r = returns.reindex(timestamps).astype(float)
    equity = 1.0
    rows = []
    for i, ts in enumerate(timestamps):
        turnover = 1.0 if i == 0 else 0.0
        cost = turnover * cost_bps / 10000.0
        gross = float(r.iloc[i]) if np.isfinite(r.iloc[i]) else 0.0
        net = gross - cost
        equity *= 1.0 + net
        rows.append({
            "timestamp_utc": ts, "gross_return": gross, "net_return": net,
            "turnover": turnover, "cost_fraction": cost, "risky_weight": 1.0,
            "cash_weight": 0.0, "missing_return_weight": 0.0 if np.isfinite(r.iloc[i]) else 1.0,
            "active_vintages": 1, "equity": equity,
        })
    return pd.DataFrame(rows)


def run(phase1_root: Path, phase2_root: Path, output_root: Path) -> pd.DataFrame:
    output_root.mkdir(parents=True, exist_ok=True)
    pred = _load_predictions(phase2_root)
    products = sorted(pred["product_id"].unique())
    timestamps = pd.DatetimeIndex(sorted(pred["timestamp_utc"].unique()))
    market = _load_market(phase1_root, products, timestamps)

    score_wide = pred.pivot(index="timestamp_utc", columns="product_id", values="predicted_score").reindex(timestamps)
    ret_wide = market.pivot(index="timestamp_utc", columns="product_id", values="forward_return_15m").reindex(timestamps)

    btc_rows = market[market["product_id"] == "BTC-USD"].drop_duplicates("timestamp_utc")
    btc_returns = btc_rows.set_index("timestamp_utc")["btc_forward_return_15m"]
    equal_weight_returns = ret_wide.mean(axis=1, skipna=True)

    metric_rows = []
    path_frames = []
    for top_n in TOP_NS:
        for cost_bps in COST_BPS:
            path = _simulate_topn(score_wide, ret_wide, top_n, cost_bps)
            variant = f"ridge_top{top_n}_overlap4h"
            metric_rows.append(_metrics(path, variant, top_n, cost_bps))
            tagged = path.copy(); tagged["variant"] = variant; tagged["top_n"] = top_n; tagged["cost_bps_round_trip"] = cost_bps
            path_frames.append(tagged)
            print(f"[SUCCESS] {variant} cost={cost_bps:g}bps ending={path['equity'].iloc[-1]:.6f} turnover={path['turnover'].sum():.2f}")

    for cost_bps in COST_BPS:
        for variant, returns in (("btc_benchmark", btc_returns), ("equal_weight_core_benchmark", equal_weight_returns)):
            path = _simulate_benchmark(timestamps, returns, cost_bps, variant)
            metric_rows.append(_metrics(path, variant, None, cost_bps))
            tagged = path.copy(); tagged["variant"] = variant; tagged["top_n"] = np.nan; tagged["cost_bps_round_trip"] = cost_bps
            path_frames.append(tagged)
        cash = pd.DataFrame({
            "timestamp_utc": timestamps, "gross_return": 0.0, "net_return": 0.0,
            "turnover": 0.0, "cost_fraction": 0.0, "risky_weight": 0.0,
            "cash_weight": 1.0, "missing_return_weight": 0.0,
            "active_vintages": 0, "equity": 1.0,
        })
        metric_rows.append(_metrics(cash, "cash_benchmark", None, cost_bps))

    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(output_root / "portfolio_metrics.csv", index=False)
    pd.concat(path_frames, ignore_index=True).to_parquet(output_root / "portfolio_15m.parquet", index=False)

    manifest = {
        "phase": 3,
        "stage": "cost_aware_overlapping_portfolio_simulation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_model": MODEL_ID,
        "source_predictions": str(phase2_root / "predictions.parquet"),
        "decision_frequency_minutes": BAR_MINUTES,
        "signal_horizon_minutes": int(HOLD_TIME.total_seconds() / 60),
        "holding_vintages": HOLD_BARS,
        "top_n_rules": list(TOP_NS),
        "cost_bps_round_trip": list(COST_BPS),
        "turnover_definition": "0.5 * L1 distance across risky asset weights plus cash weight",
        "overlap_policy": "Each 15-minute decision creates a 1/16-capital vintage held for 4 hours; active vintages are aggregated into current target weights.",
        "missing_return_policy": "If a held asset lacks an authoritative next-15m return, that weight earns 0 for that bar and is reported as missing_return_weight; no price is synthesized.",
        "benchmarks": ["BTC", "equal-weight 24-asset core universe", "cash"],
        "xrp_policy": "XRP excluded; dedicated XRP research remains separate.",
        "future_holdout_start_utc": FUTURE_HOLDOUT_START.isoformat(),
        "policy": "Frozen Phase 2 Ridge OOS predictions only; no refitting, no threshold/model selection, no live trading, no holdout evaluation.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return metrics


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    ap.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    metrics = run(args.phase1_root, args.phase2_root, args.output_root)
    print("CRYPTO 15M V1 PHASE 3")
    print("=" * 100)
    show = metrics[["variant", "top_n", "cost_bps_round_trip", "ending_equity", "cumulative_return", "annualized_return", "maximum_drawdown", "total_turnover", "mean_risky_weight"]]
    print(show.to_string(index=False))
    print(f"Output: {args.output_root / 'portfolio_metrics.csv'}")
    print("Frozen Ridge OOS predictions only. XRP isolated. Future holdout untouched.")


if __name__ == "__main__":
    main()
