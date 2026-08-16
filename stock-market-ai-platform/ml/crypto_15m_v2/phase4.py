"""Crypto 15m V2 Phase 4: exploratory turnover-control analysis.

This phase consumes ONLY the frozen Phase 2 HistGradientBoosting out-of-sample
predictions and the same authoritative 1-hour realized returns used in Phase 3.
It does not refit a model or touch the future holdout.

IMPORTANT RESEARCH STATUS
-------------------------
Phase 3 results have already been inspected, so Phase 4 is explicitly an
EXPLORATORY execution-policy development stage, not untouched validation.
Any policy considered promising here must be frozen before later evaluation on
future data beginning 2026-09-01 UTC.

Fixed policy family
-------------------
raw_hourly       : switch immediately to each hourly predicted sleeve.
confirm_2        : new sleeve must be predicted for 2 consecutive hours.
confirm_3        : new sleeve must be predicted for 3 consecutive hours.
min_hold_4h      : after a switch, hold at least 4 hours before another switch.
min_hold_8h      : after a switch, hold at least 8 hours before another switch.
confirm2_hold4h  : 2-hour confirmation plus 4-hour minimum hold.
confirm3_hold8h  : 3-hour confirmation plus 8-hour minimum hold.

No probability threshold search is performed. XRP remains separate.
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
OUTPUT_ROOT = Path("data/model/crypto_15m_v2/phase4")

MODEL_ID = "hist_gradient_boosting"
BTC = "BTC-USD"
XRP = "XRP-USD"
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
COST_BPS = (0.0, 5.0, 10.0, 25.0, 50.0)
HOURS_PER_YEAR = 365.25 * 24.0

POLICIES = {
    "raw_hourly": {"confirm": 1, "min_hold": 0},
    "confirm_2": {"confirm": 2, "min_hold": 0},
    "confirm_3": {"confirm": 3, "min_hold": 0},
    "min_hold_4h": {"confirm": 1, "min_hold": 4},
    "min_hold_8h": {"confirm": 1, "min_hold": 8},
    "confirm2_hold4h": {"confirm": 2, "min_hold": 4},
    "confirm3_hold8h": {"confirm": 3, "min_hold": 8},
}


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
        raise RuntimeError("No frozen HGB OOS predictions found")
    if not set(p["predicted_label"]).issubset({"BTC", "ALT", "CASH"}):
        raise RuntimeError("Unexpected predicted sleeve")
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
        df = df[df["timestamp_utc"].isin(wanted)]
        if len(df):
            frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    if XRP in set(panel["product_id"]):
        raise RuntimeError("XRP leaked into Phase 4 shared universe")
    btc = panel[panel["product_id"] == BTC][["timestamp_utc", "forward_return_1h"]].rename(
        columns={"forward_return_1h": "btc_return_1h"}
    ).drop_duplicates("timestamp_utc")
    alt = (
        panel[panel["product_id"] != BTC]
        .groupby("timestamp_utc", sort=True)
        .agg(alt_return_1h=("forward_return_1h", "mean"), alt_asset_count=("product_id", "nunique"))
        .reset_index()
    )
    return btc.merge(alt, on="timestamp_utc", how="inner", validate="one_to_one")


def _apply_policy(labels: list[str], confirm: int, min_hold: int) -> list[str]:
    if not labels:
        return []
    current = labels[0]
    out = [current]
    hours_in_state = 1
    candidate = None
    candidate_count = 0

    for proposed in labels[1:]:
        if proposed == current:
            candidate = None
            candidate_count = 0
            hours_in_state += 1
            out.append(current)
            continue

        if hours_in_state < min_hold:
            candidate = None
            candidate_count = 0
            hours_in_state += 1
            out.append(current)
            continue

        if candidate == proposed:
            candidate_count += 1
        else:
            candidate = proposed
            candidate_count = 1

        if candidate_count >= confirm:
            current = proposed
            hours_in_state = 1
            candidate = None
            candidate_count = 0
        else:
            hours_in_state += 1
        out.append(current)
    return out


def _max_drawdown(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1.0).min()) if len(eq) else np.nan


def _annualized(ending: float, periods: int) -> float:
    if periods <= 0 or ending <= 0:
        return np.nan
    years = periods / HOURS_PER_YEAR
    return float(ending ** (1 / years) - 1) if years > 0 else np.nan


def _simulate(base: pd.DataFrame, policy_name: str, confirm: int, min_hold: int, cost_bps: float):
    df = base.copy().sort_values("timestamp_utc").reset_index(drop=True)
    executed = _apply_policy(df["predicted_label"].tolist(), confirm, min_hold)
    df["executed_label"] = executed

    gross = np.select(
        [df["executed_label"].eq("BTC"), df["executed_label"].eq("ALT")],
        [df["btc_return_1h"], df["alt_return_1h"]],
        default=0.0,
    ).astype(float)

    turnover = df["executed_label"].ne(df["executed_label"].shift(1)).astype(float)
    if len(turnover):
        turnover.iloc[0] = 1.0
    costs = turnover.to_numpy(float) * (cost_bps / 10000.0)
    net = (1.0 + gross) * (1.0 - costs) - 1.0
    equity = pd.Series(np.cumprod(1.0 + net), index=df.index)
    counts = df["executed_label"].value_counts()
    raw_switches = int(df["predicted_label"].ne(df["predicted_label"].shift()).sum())
    exec_switches = int(turnover.sum())

    df["policy"] = policy_name
    df["cost_bps_round_trip"] = cost_bps
    df["gross_return_1h"] = gross
    df["sleeve_turnover"] = turnover
    df["transaction_cost"] = costs
    df["net_return_1h"] = net
    df["equity"] = equity

    metrics = {
        "policy": policy_name,
        "confirmation_hours": confirm,
        "minimum_hold_hours": min_hold,
        "cost_bps_round_trip": cost_bps,
        "observation_count": int(len(df)),
        "ending_equity": float(equity.iloc[-1]),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "annualized_return": _annualized(float(equity.iloc[-1]), len(df)),
        "maximum_drawdown": _max_drawdown(equity),
        "raw_prediction_switches": raw_switches,
        "executed_switches": exec_switches,
        "switch_reduction_fraction": float(1.0 - exec_switches / raw_switches) if raw_switches else 0.0,
        "total_sleeve_turnover": float(turnover.sum()),
        "mean_gross_return_1h": float(np.mean(gross)),
        "mean_net_return_1h": float(np.mean(net)),
        "btc_allocation_fraction": float(counts.get("BTC", 0) / len(df)),
        "alt_allocation_fraction": float(counts.get("ALT", 0) / len(df)),
        "cash_allocation_fraction": float(counts.get("CASH", 0) / len(df)),
    }
    return df, metrics


def run(predictions_path: Path, v1_root: Path, output_root: Path):
    pred = _load_predictions(predictions_path)
    realized = _load_hourly_realized(v1_root, pd.DatetimeIndex(pred["timestamp_utc"]))
    base = pred.merge(realized, on="timestamp_utc", how="inner", validate="one_to_one")
    base = base.dropna(subset=["btc_return_1h", "alt_return_1h"]).sort_values("timestamp_utc").reset_index(drop=True)
    if base.empty:
        raise RuntimeError("No complete OOS decisions available")

    output_root.mkdir(parents=True, exist_ok=True)
    metrics = []
    paths = []
    for policy_name, spec in POLICIES.items():
        for bps in COST_BPS:
            path, row = _simulate(base, policy_name, spec["confirm"], spec["min_hold"], bps)
            metrics.append(row)
            paths.append(path)
            print(
                f"[SUCCESS] {policy_name:18s} cost={bps:g}bps "
                f"ending={row['ending_equity']:.6f} switches={row['executed_switches']:,} "
                f"reduction={row['switch_reduction_fraction']:.1%}"
            )

    metrics_df = pd.DataFrame(metrics).sort_values(["cost_bps_round_trip", "ending_equity"], ascending=[True, False])
    paths_df = pd.concat(paths, ignore_index=True)
    metrics_df.to_csv(output_root / "turnover_policy_metrics.csv", index=False)
    paths_df.to_parquet(output_root / "turnover_policy_paths.parquet", index=False)

    zero = metrics_df[metrics_df["cost_bps_round_trip"] == 0].copy()
    five = metrics_df[metrics_df["cost_bps_round_trip"] == 5].copy()
    summary = zero[["policy", "ending_equity", "executed_switches", "switch_reduction_fraction", "maximum_drawdown"]].rename(
        columns={"ending_equity": "ending_equity_0bps", "maximum_drawdown": "max_drawdown_0bps"}
    ).merge(
        five[["policy", "ending_equity", "maximum_drawdown"]].rename(
            columns={"ending_equity": "ending_equity_5bps", "maximum_drawdown": "max_drawdown_5bps"}
        ), on="policy", how="left"
    ).sort_values("ending_equity_5bps", ascending=False)
    summary.to_csv(output_root / "policy_summary.csv", index=False)

    manifest = {
        "research_version": "crypto_15m_v2",
        "phase": 4,
        "stage": "exploratory_turnover_control",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL_ID,
        "prediction_source": str(predictions_path),
        "realized_return_source": str(v1_root / "core_panel"),
        "policies": POLICIES,
        "cost_bps_round_trip": list(COST_BPS),
        "research_status": (
            "EXPLORATORY ONLY. Phase 3 OOS results were already inspected before these policies were defined. "
            "No Phase 4 winner may be described as untouched validation."
        ),
        "future_validation_rule": (
            "Any policy selected after Phase 4 must be frozen before evaluation on future observations beginning 2026-09-01 UTC."
        ),
        "xrp_policy": "XRP remains excluded and on a separate research track.",
        "cost_limitation": (
            "Costs model sleeve-level switches only. Equal-weight ALT constituent turnover remains unmodeled, so ALT costs are optimistic."
        ),
        "policy": "no model refit, no probability threshold search, no leverage, no shorting, no derivatives, no live execution, no future-holdout evaluation",
        "outputs": {
            "metrics": str(output_root / "turnover_policy_metrics.csv"),
            "summary": str(output_root / "policy_summary.csv"),
            "paths": str(output_root / "turnover_policy_paths.parquet"),
            "manifest": str(output_root / "manifest.json"),
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return metrics_df, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions", type=Path, default=PREDICTIONS_PATH)
    ap.add_argument("--v1-phase1-root", type=Path, default=V1_PHASE1_ROOT)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    metrics, summary = run(args.predictions, args.v1_phase1_root, args.output_root)
    print("CRYPTO 15M V2 PHASE 4")
    print("=" * 118)
    print("EXPLORATORY turnover-control policies; not untouched validation.")
    print("\nPOLICY SUMMARY")
    print(summary.to_string(index=False))
    print(f"\nOutput: {args.output_root / 'turnover_policy_metrics.csv'}")
    print("XRP remains separate. Future holdout remains untouched from 2026-09-01 UTC.")
    print("ALT constituent-level rebalance costs remain unmodeled; cost estimates are optimistic.")


if __name__ == "__main__":
    main()
