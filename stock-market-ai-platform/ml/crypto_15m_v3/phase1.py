"""Crypto 15m V3 Phase 1: 15-minute / 1-hour turnover-aware research dataset.

Fresh hypothesis only. Frozen Crypto 15m V2 is never modified. This phase builds
an every-15-minute BTC / ALT / CASH regime dataset with a one-hour economic
horizon and pre-registers turnover-aware switching requirements for later
simulation. No model fitting, policy tuning, portfolio simulation, holdout
inspection, or brokerage execution occurs here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_15m_v3 import RESEARCH_VERSION

SOURCE_ROOT = Path("data/model/crypto_15m_v1/phase1")
OUTPUT_ROOT = Path("data/model/crypto_15m_v3/phase1")
DATASET_PATH = OUTPUT_ROOT / "market_allocation_15m_1h.parquet"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
BTC = "BTC-USD"
XRP = "XRP-USD"
FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
DECISION_FREQUENCY_MINUTES = 15
PRIMARY_HORIZON = "1h"
MIN_ALT_ASSETS = 10

BTC_FEATURES = [
    "return_1bar", "return_2bar", "return_4bar", "return_8bar", "return_16bar", "return_32bar", "return_96bar",
    "realized_volatility_4bar", "realized_volatility_16bar", "realized_volatility_96bar",
    "close_to_sma_4bar", "close_to_sma_16bar", "close_to_sma_96bar",
    "volume_to_average_4bar", "volume_to_average_16bar", "volume_to_average_96bar",
    "drawdown_from_high_96bar", "utc_time_sin", "utc_time_cos", "utc_dow_sin", "utc_dow_cos",
]
ALT_STATE_COLUMNS = [
    "return_1bar", "return_2bar", "return_4bar", "return_8bar", "return_16bar", "return_32bar",
    "btc_relative_return_1bar", "btc_relative_return_4bar", "btc_relative_return_16bar",
    "realized_volatility_4bar", "realized_volatility_16bar", "realized_volatility_96bar",
    "volume_to_average_4bar", "volume_to_average_16bar", "drawdown_from_high_96bar",
]


def _load_core() -> pd.DataFrame:
    paths = sorted((SOURCE_ROOT / "core_panel").glob("*.parquet"))
    if len(paths) != 24:
        raise RuntimeError(f"Expected 24 core panels, found {len(paths)}")
    needed = {"timestamp_utc", "product_id", "forward_return_1h"} | set(BTC_FEATURES) | set(ALT_STATE_COLUMNS)
    frames = []
    for path in paths:
        frame = pd.read_parquet(path)
        missing = needed - set(frame.columns)
        if missing:
            raise RuntimeError(f"{path.name} missing columns: {sorted(missing)}")
        frames.append(frame[list(needed)].copy())
    data = pd.concat(frames, ignore_index=True)
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    data = data[data["timestamp_utc"] < FUTURE_HOLDOUT_START].copy()
    if XRP in set(data["product_id"]):
        raise RuntimeError("XRP leaked into shared Crypto V3 universe")
    return data


def build_dataset() -> tuple[pd.DataFrame, dict]:
    panel = _load_core()
    btc = panel[panel.product_id == BTC].copy()
    alts = panel[panel.product_id != BTC].copy()
    btc_keep = ["timestamp_utc", "forward_return_1h"] + BTC_FEATURES
    btc_state = btc[btc_keep].drop_duplicates("timestamp_utc").rename(
        columns={"forward_return_1h": "btc_forward_return_1h", **{c: f"btc_{c}" for c in BTC_FEATURES}}
    )
    agg = {"alt_forward_return_1h": ("forward_return_1h", "mean"), "alt_asset_count": ("product_id", "nunique")}
    for col in ALT_STATE_COLUMNS:
        agg[f"alt_mean_{col}"] = (col, "mean")
        agg[f"alt_median_{col}"] = (col, "median")
    alt_state = alts.groupby("timestamp_utc", sort=True).agg(**agg).reset_index()
    breadth = alts.groupby("timestamp_utc", sort=True).agg(
        alt_positive_1bar_fraction=("return_1bar", lambda s: float((s > 0).mean())),
        alt_positive_4bar_fraction=("return_4bar", lambda s: float((s > 0).mean())),
        alt_return_1bar_dispersion=("return_1bar", lambda s: float(s.std(ddof=0))),
        alt_return_4bar_dispersion=("return_4bar", lambda s: float(s.std(ddof=0))),
        alt_btc_relative_1bar_positive_fraction=("btc_relative_return_1bar", lambda s: float((s > 0).mean())),
        alt_btc_relative_4bar_positive_fraction=("btc_relative_return_4bar", lambda s: float((s > 0).mean())),
    ).reset_index()
    data = btc_state.merge(alt_state, on="timestamp_utc", validate="one_to_one").merge(breadth, on="timestamp_utc", validate="one_to_one")
    data = data[data.alt_asset_count >= MIN_ALT_ASSETS].copy()
    data["cash_forward_return_1h"] = 0.0
    returns = data[["btc_forward_return_1h", "alt_forward_return_1h", "cash_forward_return_1h"]].to_numpy(float)
    winner = np.argmax(returns, axis=1)
    labels = np.array(["BTC", "ALT", "CASH"], dtype=object)
    data["allocation_target"] = labels[winner]
    data["allocation_target_code"] = winner.astype("int8")
    data["best_forward_return_1h"] = returns[np.arange(len(data)), winner]
    data["btc_minus_alt_forward_return_1h"] = data.btc_forward_return_1h - data.alt_forward_return_1h
    target_cols = {"btc_forward_return_1h", "alt_forward_return_1h", "cash_forward_return_1h", "allocation_target", "allocation_target_code", "best_forward_return_1h", "btc_minus_alt_forward_return_1h"}
    feature_cols = [c for c in data.columns if c != "timestamp_utc" and c not in target_cols]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols + ["btc_forward_return_1h", "alt_forward_return_1h"]).sort_values("timestamp_utc").reset_index(drop=True)
    counts = data.allocation_target.value_counts().reindex(["BTC", "ALT", "CASH"], fill_value=0)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "15m_1h_turnover_aware_regime_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_frequency_minutes": DECISION_FREQUENCY_MINUTES,
        "economic_horizon": PRIMARY_HORIZON,
        "row_count": int(len(data)),
        "feature_count": len(feature_cols),
        "feature_columns": feature_cols,
        "target_counts": {k: int(v) for k, v in counts.items()},
        "date_range": {"start": data.timestamp_utc.min().isoformat(), "end": data.timestamp_utc.max().isoformat()},
        "future_holdout_start_utc": FUTURE_HOLDOUT_START.isoformat(),
        "frozen_benchmark": "crypto_15m_v2 hourly decisions / 4h horizon; unchanged",
        "turnover_contract": {
            "default_action": "HOLD_CURRENT_STATE",
            "switch_requires_positive_net_edge": True,
            "net_edge_definition": "expected benefit of proposed state over current state minus modeled round-trip cost, slippage allowance, and safety buffer",
            "confirmation_required": True,
            "hysteresis_required": True,
            "minimum_hold_required": True,
            "cost_scenarios_bps": [0, 5, 10, 25],
            "rule": "A different raw prediction alone must never trigger a switch. Later phases must demonstrate positive expected net edge after turnover costs and satisfy confirmation, hysteresis, and minimum-hold rules."
        },
        "policy": "dataset and preregistration only; no model fitting, tuning, simulation, promotion, holdout evaluation, or orders",
        "next_step": "walk-forward 15m/1h regime modeling, then turnover-aware policy evaluation against frozen V2 benchmark"
    }
    return data, manifest


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    data, manifest = build_dataset()
    data.to_parquet(DATASET_PATH, index=False)
    manifest["outputs"] = {"dataset": str(DATASET_PATH), "manifest": str(MANIFEST_PATH)}
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print("CRYPTO 15M V3 PHASE 1")
    print("=" * 80)
    print(f"Rows: {len(data):,}")
    print(f"Features: {manifest['feature_count']}")
    print("Decision cadence: 15 minutes")
    print("Economic horizon: 1 hour")
    print("Turnover contract: HOLD unless a later policy proves positive net switching edge after costs.")
    print("Frozen Crypto 15m V2 was not modified. Future holdout remains untouched.")


if __name__ == "__main__":
    main()
