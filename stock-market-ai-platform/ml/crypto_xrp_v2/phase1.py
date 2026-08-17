"""Crypto XRP V2 Phase 1: 15-minute / 1-hour turnover-aware dataset.

Uses the discontinuity-safe post-gap XRP population prepared by XRP V1 Phase 1.
The frozen XRP V1 Phase 6 Ridge + hyst_10_05_hold24 candidate remains unchanged
and continues as the benchmark. No model fitting, policy tuning, simulation,
future-holdout inspection, or brokerage execution occurs here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_xrp_v2 import RESEARCH_VERSION

SOURCE_PATH = Path("data/model/crypto_xrp_v1/phase1/xrp_primary.parquet")
OUTPUT_ROOT = Path("data/model/crypto_xrp_v2/phase1")
DATASET_PATH = OUTPUT_ROOT / "xrp_primary_15m_1h.parquet"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
FUTURE_HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
PRIMARY_TARGET = "btc_relative_forward_return_1h"
DECISION_FREQUENCY_MINUTES = 15
ID_COLUMNS = {"timestamp_utc", "product_id", "segment_id", "open", "high", "low", "close", "volume"}
TARGET_PREFIXES = ("forward_return_", "btc_forward_return_", "btc_relative_forward_return_")


def _load() -> tuple[pd.DataFrame, list[str]]:
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"Missing XRP V1 primary dataset: {SOURCE_PATH}")
    data = pd.read_parquet(SOURCE_PATH)
    required = {"timestamp_utc", "product_id", "segment_id", PRIMARY_TARGET, "forward_return_1h", "btc_forward_return_1h"}
    missing = required - set(data.columns)
    if missing:
        raise RuntimeError(f"XRP source missing required columns: {sorted(missing)}")
    data = data.copy()
    data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True)
    data = data[data.timestamp_utc < FUTURE_HOLDOUT_START].sort_values("timestamp_utc").drop_duplicates(["timestamp_utc", "product_id"]).reset_index(drop=True)
    if set(data.product_id.dropna().unique()) != {"XRP-USD"}:
        raise RuntimeError("XRP V2 source contains non-XRP products")
    feature_cols = [c for c in data.columns if c not in ID_COLUMNS and not c.startswith(TARGET_PREFIXES)]
    # Preserve exactly the leakage-safe feature family created by the existing XRP pipeline.
    feature_cols = [c for c in feature_cols if pd.api.types.is_numeric_dtype(data[c])]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols + [PRIMARY_TARGET]).reset_index(drop=True)
    if data.empty:
        raise RuntimeError("XRP V2 15m/1h dataset is empty")
    return data, feature_cols


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    data, features = _load()
    data.to_parquet(DATASET_PATH, index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "15m_1h_turnover_aware_xrp_dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(SOURCE_PATH),
        "population": "post-major-discontinuity XRP primary era only",
        "decision_frequency_minutes": DECISION_FREQUENCY_MINUTES,
        "primary_target": PRIMARY_TARGET,
        "economic_horizon": "1h",
        "row_count": int(len(data)),
        "feature_count": len(features),
        "feature_columns": features,
        "date_range": {"start": data.timestamp_utc.min().isoformat(), "end": data.timestamp_utc.max().isoformat()},
        "future_holdout_start_utc": FUTURE_HOLDOUT_START.isoformat(),
        "frozen_benchmark": "crypto_xrp_v1 Phase 6 Ridge / 4h decisions / 4h BTC-relative horizon / hyst_10_05_hold24; unchanged",
        "turnover_contract": {
            "default_action": "HOLD_CURRENT_STATE",
            "state_space": ["XRP", "BTC", "CASH"],
            "switch_requires_positive_net_edge": True,
            "net_edge_definition": "expected benefit of proposed state over current state minus modeled round-trip cost, slippage allowance, and safety buffer",
            "confirmation_required": True,
            "hysteresis_required": True,
            "minimum_hold_required": True,
            "cost_scenarios_bps": [0, 5, 10, 25],
            "rule": "A new 15-minute score alone must never sell or switch. Later phases must prove positive expected net edge after turnover costs and satisfy confirmation, hysteresis, and minimum-hold requirements."
        },
        "policy": "dataset and preregistration only; no fitting, tuning, simulation, promotion, future-holdout evaluation, or orders",
        "next_step": "walk-forward XRP 15m/1h modeling followed by turnover-aware state-policy evaluation against frozen XRP V1 benchmark",
        "outputs": {"dataset": str(DATASET_PATH), "manifest": str(MANIFEST_PATH)}
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print("CRYPTO XRP V2 PHASE 1")
    print("=" * 80)
    print(f"Rows: {len(data):,}")
    print(f"Features: {len(features)}")
    print("Decision cadence: 15 minutes")
    print("Economic horizon: 1 hour BTC-relative")
    print("Turnover contract: HOLD unless a later policy proves positive net switching edge after costs.")
    print("Frozen XRP V1 Phase 6 was not modified. Future holdout remains untouched.")


if __name__ == "__main__":
    main()
