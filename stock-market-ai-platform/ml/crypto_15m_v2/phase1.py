"""Crypto 15m V2 Phase 1: lower-turnover BTC / ALT / CASH regime dataset.

This is a fresh hypothesis after Crypto 15m V1 showed that a 15-minute Top-N
portfolio had excessive turnover and poor economics. V2 keeps 15-minute market
information but pre-registers a slower PRIMARY decision cadence of 1 hour and a
4-hour economic horizon. Portfolio construction is not performed in this phase.

XRP remains excluded from the shared universe and continues as a separate
research track because of its large historical discontinuity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_15m_v2 import RESEARCH_VERSION

PHASE1_V1_ROOT = Path("data/model/crypto_15m_v1/phase1")
OUTPUT_ROOT = Path("data/model/crypto_15m_v2/phase1")
DATASET_PATH = OUTPUT_ROOT / "market_allocation_1h.parquet"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

BTC = "BTC-USD"
XRP = "XRP-USD"
FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
DECISION_FREQUENCY_MINUTES = 60
PRIMARY_HORIZON = "4h"
MIN_ALT_ASSETS = 10

BTC_FEATURES = [
    "return_1bar", "return_4bar", "return_16bar", "return_96bar",
    "realized_volatility_4bar", "realized_volatility_16bar", "realized_volatility_96bar",
    "close_to_sma_16bar", "close_to_sma_96bar",
    "volume_to_average_16bar", "volume_to_average_96bar",
    "drawdown_from_high_96bar", "utc_time_sin", "utc_time_cos", "utc_dow_sin", "utc_dow_cos",
]

ALT_STATE_COLUMNS = [
    "return_1bar", "return_4bar", "return_16bar", "return_96bar",
    "btc_relative_return_4bar", "btc_relative_return_16bar",
    "realized_volatility_16bar", "realized_volatility_96bar",
    "volume_to_average_16bar", "drawdown_from_high_96bar",
]


def _load_core(root: Path) -> pd.DataFrame:
    paths = sorted((root / "core_panel").glob("*.parquet"))
    if len(paths) != 24:
        raise RuntimeError(f"Expected 24 core panels, found {len(paths)}")
    frames = []
    needed = {"timestamp_utc", "product_id", f"forward_return_{PRIMARY_HORIZON}"} | set(BTC_FEATURES) | set(ALT_STATE_COLUMNS)
    for p in paths:
        df = pd.read_parquet(p)
        missing = needed - set(df.columns)
        if missing:
            raise RuntimeError(f"{p.name} missing columns: {sorted(missing)}")
        frames.append(df[list(needed)].copy())
    out = pd.concat(frames, ignore_index=True)
    out["timestamp_utc"] = pd.to_datetime(out["timestamp_utc"], utc=True)
    out = out[out["timestamp_utc"] < FUTURE_HOLDOUT_START].copy()
    if XRP in set(out["product_id"]):
        raise RuntimeError("XRP leaked into V2 shared universe")
    return out


def _decision_grid(df: pd.DataFrame) -> pd.DataFrame:
    # Primary cadence: exactly once per hour using completed xx:00 UTC candles.
    ts = df["timestamp_utc"]
    return df[(ts.dt.minute == 0) & (ts.dt.second == 0)].copy()


def build_dataset(root: Path) -> tuple[pd.DataFrame, dict]:
    panel = _decision_grid(_load_core(root))
    btc = panel[panel["product_id"] == BTC].copy()
    alts = panel[panel["product_id"] != BTC].copy()
    if btc.empty or alts.empty:
        raise RuntimeError("BTC or ALT panel is empty")

    # BTC same-time state.
    btc_keep = ["timestamp_utc", f"forward_return_{PRIMARY_HORIZON}"] + BTC_FEATURES
    btc_state = btc[btc_keep].drop_duplicates("timestamp_utc").rename(
        columns={f"forward_return_{PRIMARY_HORIZON}": "btc_forward_return_4h", **{c: f"btc_{c}" for c in BTC_FEATURES}}
    )

    # Cross-sectional ALT state known at decision time plus equal-weight future return.
    agg_spec = {
        "alt_forward_return_4h": (f"forward_return_{PRIMARY_HORIZON}", "mean"),
        "alt_asset_count": ("product_id", "nunique"),
    }
    for c in ALT_STATE_COLUMNS:
        agg_spec[f"alt_mean_{c}"] = (c, "mean")
        agg_spec[f"alt_median_{c}"] = (c, "median")
    alt_state = alts.groupby("timestamp_utc", sort=True).agg(**agg_spec).reset_index()

    # Breadth / dispersion features.
    breadth = alts.groupby("timestamp_utc", sort=True).agg(
        alt_positive_1bar_fraction=("return_1bar", lambda s: float((s > 0).mean())),
        alt_positive_4bar_fraction=("return_4bar", lambda s: float((s > 0).mean())),
        alt_positive_16bar_fraction=("return_16bar", lambda s: float((s > 0).mean())),
        alt_return_4bar_dispersion=("return_4bar", lambda s: float(s.std(ddof=0))),
        alt_return_16bar_dispersion=("return_16bar", lambda s: float(s.std(ddof=0))),
        alt_btc_relative_4bar_positive_fraction=("btc_relative_return_4bar", lambda s: float((s > 0).mean())),
        alt_btc_relative_16bar_positive_fraction=("btc_relative_return_16bar", lambda s: float((s > 0).mean())),
    ).reset_index()

    data = btc_state.merge(alt_state, on="timestamp_utc", how="inner", validate="one_to_one").merge(
        breadth, on="timestamp_utc", how="inner", validate="one_to_one"
    )
    data = data[data["alt_asset_count"] >= MIN_ALT_ASSETS].copy()
    data["cash_forward_return_4h"] = 0.0

    # Mechanical economic label, no threshold tuning.
    returns = data[["btc_forward_return_4h", "alt_forward_return_4h", "cash_forward_return_4h"]].to_numpy(float)
    winner = np.argmax(returns, axis=1)
    labels = np.array(["BTC", "ALT", "CASH"], dtype=object)
    data["allocation_target"] = labels[winner]
    data["allocation_target_code"] = winner.astype("int8")
    data["best_forward_return_4h"] = returns[np.arange(len(data)), winner]
    data["btc_minus_alt_forward_return_4h"] = data["btc_forward_return_4h"] - data["alt_forward_return_4h"]

    target_cols = {
        "btc_forward_return_4h", "alt_forward_return_4h", "cash_forward_return_4h",
        "allocation_target", "allocation_target_code", "best_forward_return_4h", "btc_minus_alt_forward_return_4h"
    }
    feature_cols = [c for c in data.columns if c != "timestamp_utc" and c not in target_cols]
    numeric_features = [c for c in feature_cols if c != "alt_asset_count"] + ["alt_asset_count"]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=numeric_features + ["btc_forward_return_4h", "alt_forward_return_4h"])
    data = data.sort_values("timestamp_utc").reset_index(drop=True)

    counts = data["allocation_target"].value_counts().reindex(["BTC", "ALT", "CASH"], fill_value=0)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "hourly_regime_allocation_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(root),
        "primary_decision_frequency_minutes": DECISION_FREQUENCY_MINUTES,
        "primary_horizon": PRIMARY_HORIZON,
        "architecture": "hourly BTC / ALT / CASH regime gate; future phase may rank alts only when ALT is selected",
        "xrp_policy": "XRP excluded from the shared universe; dedicated XRP research remains separate.",
        "minimum_alt_assets": MIN_ALT_ASSETS,
        "feature_columns": feature_cols,
        "feature_count": len(feature_cols),
        "row_count": int(len(data)),
        "date_range": {"start": data["timestamp_utc"].min().isoformat(), "end": data["timestamp_utc"].max().isoformat()},
        "target_counts": {k: int(v) for k, v in counts.items()},
        "target_fractions": {k: float(v / len(data)) for k, v in counts.items()},
        "future_holdout_start_utc": FUTURE_HOLDOUT_START.isoformat(),
        "policy": "fresh dataset construction only; no model fitting, threshold tuning, portfolio simulation, promotion, or holdout evaluation",
        "next_step": "pre-register walk-forward regime models and compare economic allocation quality at hourly cadence before any portfolio simulation",
    }
    return data, manifest


def run(root: Path, output_root: Path) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    data, manifest = build_dataset(root)
    dataset = output_root / "market_allocation_1h.parquet"
    data.to_parquet(dataset, index=False)
    manifest["outputs"] = {"dataset": str(dataset), "manifest": str(output_root / "manifest.json")}
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase1-v1-root", type=Path, default=PHASE1_V1_ROOT)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    m = run(args.phase1_v1_root, args.output_root)
    print("CRYPTO 15M V2 PHASE 1")
    print("=" * 80)
    print(f"Rows: {m['row_count']:,}")
    print(f"Date range: {m['date_range']['start']} -> {m['date_range']['end']}")
    print(f"Features: {m['feature_count']}")
    print("Target counts:")
    for k in ("BTC", "ALT", "CASH"):
        print(f"  {k:4s} {m['target_counts'][k]:7,d} ({m['target_fractions'][k]:.2%})")
    print(f"Output: {m['outputs']['dataset']}")
    print("Primary cadence: 1 hour. Economic horizon: 4 hours.")
    print("XRP remains separate. Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
