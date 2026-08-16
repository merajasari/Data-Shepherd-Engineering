"""Crypto 15m V2 Phase 3: frozen hourly HGB regime-gate simulation.

Consumes ONLY Phase 2 out-of-sample HistGradientBoosting predictions. No model
is refit and no probability threshold is tuned. At each hourly decision the
predicted BTC / ALT / CASH sleeve is held for the next hour, then reconsidered.

Realized one-hour BTC and equal-weight ALT returns are rebuilt from the frozen
Crypto 15m V1 Phase 1 panels at the exact Phase 2 OOS decision timestamps.
XRP remains excluded from the shared universe.

Transaction costs are applied to sleeve-level turnover. This deliberately does
NOT claim to capture constituent-level turnover inside the equal-weight ALT
sleeve, so ALT implementation costs are optimistic and are disclosed as such.
Research/simulation only; no brokerage orders, leverage, shorting, or live
trading.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

PHASE2_ROOT = Path("data/model/crypto_15m_v2/phase2")
PREDICTIONS_PATH = PHASE2_ROOT / "predictions.parquet"
V1_PHASE1_ROOT = Path("data/model/crypto_15m_v1/phase1")
OUTPUT_ROOT = Path("data/model/crypto_15m_v2/phase3")

MODEL_ID = "hist_gradient_boosting"
BTC = "BTC-USD"
XRP = "XRP-USD"
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
COST_BPS = (0.0, 5.0, 10.0, 25.0, 50.0)
HOURS_PER_YEAR = 365.25 * 24.0


def _load_predictions(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    p = pd.read_parquet(path).copy()
    required = {"timestamp_utc", "model_id", "predicted_label", "fold_id"}
    missing = required - set(p.columns)
    if missing:
        raise ValueError(f"Phase 2 predictions missing columns: {sorted(missing)}")
    p["timestamp_utc"] = pd.to_datetime(p["timestamp_utc"], utc=True)
    p = p[(p["model_id"] == MODEL_ID) & (p["timestamp_utc"] < HOLDOUT)].copy()
    p = p.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last").reset_index(drop=True)
    if p.empty:
        raise ValueError("No frozen HGB OOS predictions available")
    if not set(p["predicted_label"]).issubset({"BTC", "ALT", "CASH"}):
        raise ValueError("Unexpected predicted sleeve label")
    return p


def _load_hourly_realized(root: Path, timestamps: pd.DatetimeIndex) -> pd.DataFrame:
    paths = sorted((root / "core_panel").glob("*.parquet"))
    if len(paths) != 24:
        raise RuntimeError(f"Expected 24 core panels, found {len(paths)}")

    wanted = set(pd.DatetimeIndex(timestamps))
    frames = []
    for path in paths:
        df = pd.read_parquet(path, columns=["timestamp_utc", "product_id", "forward_return_1h"])
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df[df["timestamp_utc"].isin(wanted)].copy()
        if len(df):
            frames.append(df)
    if not frames:
        raise RuntimeError("No Phase 1 realized 1h returns matched Phase 2 decisions")
    panel = pd.concat(frames, ignore_index=True)
    if XRP in set(panel["product_id"]):
        raise RuntimeError("XRP leaked into V2 Phase 3 shared universe")

    btc = panel[panel["product_id"] == BTC][["timestamp_utc", "forward_return_1h"]].rename(
        columns={"forward_return_1h": "btc_return_1h"}
    ).drop_duplicates("timestamp_utc")
    alts = panel[panel["product_id"] != BTC].copy()
    alt = alts.groupby("timestamp_utc", sort=True).agg(
        alt_return_1h=("forward_return_1h", "mean"),
        alt_asset_count=("product_id", "nunique"),
    ).reset_index()
    out = btc.merge(alt, on="timestamp_utc", how="inner", validate="one_to_one")
    return out


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else np.nan


def _annualized_return(ending: float, periods: int) -> float:
    if periods <= 0 or ending <= 0:
        return np.nan
    years = periods / HOURS_PER_YEAR
    return float(ending ** (1.0 / years) - 1.0) if years > 0 else np.nan


def _simulate(base: pd.DataFrame, cost_bps: float) -> tuple[pd.DataFrame, dict]:
    df = base.copy().sort_values("timestamp_utc").reset_index(drop=True)
    selected = np.select(
        [df["predicted_label"].eq("BTC"), df["predicted_label"].eq("ALT")],
        [df["btc_return_1h"], df["alt_return_1h"]],
        default=0.0,
    ).astype(float)

    # Sleeve-level turnover: opening allocation costs 1.0; remaining in the same
    # sleeve costs 0; switching BTC<->ALT or risky<->CASH costs 1.0.
    prev = df["predicted_label"].shift(1)
    turnover = df["predicted_label"].ne(prev).astype(float)
    if len(turnover):
        turnover.iloc[0] = 1.0

    cost_rate = cost_bps / 10000.0
    costs = turnover.to_numpy(float) * cost_rate
    net = (1.0 + selected) * (1.0 - costs) - 1.0
    equity = pd.Series(np.cumprod(1.0 + net), index=df.index)

    df["gross_return_1h"] = selected
    df["sleeve_turnover"] = turnover
    df["transaction_cost"] = costs
    df["net_return_1h"] = net
    df["equity"] = equity
    df["cost_bps_round_trip"] = cost_bps

    switches = int(turnover.sum())
    counts = df["predicted_label"].value_counts()
    metrics = {
        "variant": "v2_hgb_hourly_regime",
        "cost_bps_round_trip": cost_bps,
        "observation_count": int(len(df)),
        "ending_equity": float(equity.iloc[-1]),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "annualized_return": _annualized_return(float(equity.iloc[-1]), len(df)),
        "maximum_drawdown": _max_drawdown(equity),
        "total_sleeve_turnover": float(turnover.sum()),
        "sleeve_switch_count": switches,
        "mean_gross_return_1h": float(np.mean(selected)),
        "mean_net_return_1h": float(np.mean(net)),
        "btc_allocation_fraction": float(counts.get("BTC", 0) / len(df)),
        "alt_allocation_fraction": float(counts.get("ALT", 0) / len(df)),
        "cash_allocation_fraction": float(counts.get("CASH", 0) / len(df)),
    }
    return df, metrics


def _benchmark(base: pd.DataFrame, sleeve: str, cost_bps: float) -> dict:
    if sleeve == "BTC":
        r = base["btc_return_1h"].to_numpy(float)
        turnover = 1.0
    elif sleeve == "ALT":
        r = base["alt_return_1h"].to_numpy(float)
        turnover = 1.0
    elif sleeve == "CASH":
        r = np.zeros(len(base), dtype=float)
        turnover = 0.0
    else:
        raise ValueError(sleeve)
    if len(r) and turnover:
        r = r.copy()
        r[0] = (1.0 + r[0]) * (1.0 - cost_bps / 10000.0) - 1.0
    equity = pd.Series(np.cumprod(1.0 + r))
    return {
        "variant": f"{sleeve.lower()}_benchmark",
        "cost_bps_round_trip": cost_bps,
        "observation_count": int(len(base)),
        "ending_equity": float(equity.iloc[-1]),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "annualized_return": _annualized_return(float(equity.iloc[-1]), len(base)),
        "maximum_drawdown": _max_drawdown(equity),
        "total_sleeve_turnover": turnover,
        "sleeve_switch_count": int(turnover),
        "mean_gross_return_1h": float(np.mean(r)),
        "mean_net_return_1h": float(np.mean(r)),
        "btc_allocation_fraction": 1.0 if sleeve == "BTC" else 0.0,
        "alt_allocation_fraction": 1.0 if sleeve == "ALT" else 0.0,
        "cash_allocation_fraction": 1.0 if sleeve == "CASH" else 0.0,
    }


def run(predictions_path: Path, v1_root: Path, output_root: Path):
    predictions = _load_predictions(predictions_path)
    realized = _load_hourly_realized(v1_root, pd.DatetimeIndex(predictions["timestamp_utc"]))
    base = predictions.merge(realized, on="timestamp_utc", how="inner", validate="one_to_one")
    base = base.dropna(subset=["btc_return_1h", "alt_return_1h"]).sort_values("timestamp_utc").reset_index(drop=True)
    if base.empty:
        raise RuntimeError("No complete OOS decisions with realized 1h returns")

    output_root.mkdir(parents=True, exist_ok=True)
    metric_rows = []
    path_rows = []
    for bps in COST_BPS:
        path, metrics = _simulate(base, bps)
        path_rows.append(path)
        metric_rows.append(metrics)
        for sleeve in ("BTC", "ALT", "CASH"):
            metric_rows.append(_benchmark(base, sleeve, bps))
        print(
            f"[SUCCESS] v2_hgb_hourly_regime cost={bps:g}bps "
            f"ending={metrics['ending_equity']:.6f} "
            f"turnover={metrics['total_sleeve_turnover']:.0f} "
            f"cash={metrics['cash_allocation_fraction']:.2%}"
        )

    metrics_df = pd.DataFrame(metric_rows)
    paths_df = pd.concat(path_rows, ignore_index=True)
    metrics_df.to_csv(output_root / "portfolio_metrics.csv", index=False)
    paths_df.to_parquet(output_root / "portfolio_hourly.parquet", index=False)

    manifest = {
        "research_version": "crypto_15m_v2",
        "phase": 3,
        "stage": "frozen_hourly_regime_portfolio_simulation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_ID,
        "prediction_source": str(predictions_path),
        "realized_return_source": str(v1_root / "core_panel"),
        "decision_frequency": "1 hour",
        "holding_period": "1 hour until next regime decision",
        "cost_bps_round_trip": list(COST_BPS),
        "benchmarks": ["BTC", "equal-weight ALT", "CASH"],
        "xrp_policy": "XRP remains excluded from the shared universe and requires its own research track.",
        "cost_policy": (
            "Costs apply to sleeve-level switches only. Equal-weight ALT constituent-level rebalance turnover is not modeled, "
            "so ALT implementation cost is optimistic rather than conservative."
        ),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "policy": "frozen OOS predictions only; no refit, threshold search, leverage, shorting, derivatives, live execution, or holdout evaluation",
        "outputs": {
            "metrics": str(output_root / "portfolio_metrics.csv"),
            "path": str(output_root / "portfolio_hourly.parquet"),
            "manifest": str(output_root / "manifest.json"),
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return metrics_df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions", type=Path, default=PREDICTIONS_PATH)
    ap.add_argument("--v1-phase1-root", type=Path, default=V1_PHASE1_ROOT)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    metrics = run(args.predictions, args.v1_phase1_root, args.output_root)
    print("CRYPTO 15M V2 PHASE 3")
    print("=" * 110)
    print(metrics.to_string(index=False))
    print(f"Output: {args.output_root / 'portfolio_metrics.csv'}")
    print("Frozen HGB OOS predictions only. XRP separate. Future holdout untouched.")
    print("ALT constituent-level rebalance costs are NOT modeled; sleeve-level cost results are optimistic.")


if __name__ == "__main__":
    main()
