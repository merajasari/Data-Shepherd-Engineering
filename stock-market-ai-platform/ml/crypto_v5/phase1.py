"""Crypto V5 Phase 1: preregistered dual-layer point-in-time datasets.

This phase performs no fitting, tuning, portfolio simulation, promotion, paper
trading, or brokerage action. It freezes the V5 contract before results exist.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES
from ml.crypto_v5.config import (
    ALL_HORIZONS_DAYS, ALLOCATION_TEMPLATES, BTC_PRODUCT, CONTROL_HORIZONS_DAYS,
    FUTURE_HOLDOUT_START_UTC, MAX_TURNOVER_PER_REBALANCE, MIN_NON_BTC_ASSETS,
    MINIMUM_HOLD_DAYS, MODEL_ROOT, PHASE1_ROOT, PRIMARY_COST_BPS,
    PRIMARY_HORIZON_DAYS, RESEARCH_VERSION, ROUND_TRIP_COST_BPS, SOURCE_PANEL,
    SWITCH_CONFIDENCE_MARGIN,
)

BREADTH_WINDOWS = (7, 14, 30)


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_source(path=SOURCE_PANEL):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    required = {"timestamp_utc", "product_id", "is_eligible", "close"} | set(REQUIRED_FEATURES)
    for horizon in ALL_HORIZONS_DAYS:
        required |= {f"forward_return_{horizon}d", f"target_endpoint_utc_{horizon}d"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Crypto V5 source missing columns: " + ", ".join(missing))
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame[frame["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC].copy()
    if frame.duplicated(["timestamp_utc", "product_id"]).any():
        raise ValueError("Duplicate V5 source timestamp/product keys")
    return frame.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def _breadth(eligible):
    alt = eligible[eligible["product_id"] != BTC_PRODUCT].copy()
    grouped = alt.groupby("timestamp_utc", sort=True)
    rows = grouped.agg(
        eligible_alt_count=("product_id", "nunique"),
        median_alt_return_1d=("return_1d", "median"),
        median_alt_return_7d=("return_7d", "median"),
        median_alt_return_30d=("return_30d", "median"),
        alt_return_dispersion_7d=("return_7d", "std"),
        median_alt_volatility_30d=("realized_volatility_30d", "median"),
        median_alt_btc_relative_7d=("btc_relative_return_7d", "median"),
        median_alt_volume_ratio_30d=("volume_to_average_30d", "median"),
    ).reset_index()
    for window in BREADTH_WINDOWS:
        positive = grouped[f"return_{window}d"].apply(lambda s: float((s > 0).mean()))
        above_sma = grouped[f"close_to_sma_{window}"].apply(lambda s: float((s > 0).mean()))
        rows = rows.merge(positive.rename(f"positive_breadth_{window}d").reset_index(),
                          on="timestamp_utc", validate="one_to_one")
        rows = rows.merge(above_sma.rename(f"above_sma_breadth_{window}d").reset_index(),
                          on="timestamp_utc", validate="one_to_one")
    return rows


def build_datasets(source):
    eligible = source[source["is_eligible"].fillna(False).astype(bool)].copy()
    feature_values = eligible[list(REQUIRED_FEATURES)].replace([np.inf, -np.inf], np.nan)
    eligible = eligible.loc[feature_values.notna().all(axis=1)].copy()
    breadth = _breadth(eligible)
    breadth = breadth[breadth["eligible_alt_count"] >= MIN_NON_BTC_ASSETS].copy()

    btc = eligible[eligible["product_id"] == BTC_PRODUCT].copy()
    btc_columns = ["timestamp_utc"] + list(REQUIRED_FEATURES)
    allocation = btc[btc_columns].merge(breadth, on="timestamp_utc", validate="one_to_one")
    alt = eligible[eligible["product_id"] != BTC_PRODUCT].copy()
    for horizon in ALL_HORIZONS_DAYS:
        alt_target = alt.groupby("timestamp_utc")[f"forward_return_{horizon}d"].mean()
        btc_target = btc.set_index("timestamp_utc")[f"forward_return_{horizon}d"]
        allocation = allocation.merge(
            btc_target.rename(f"btc_forward_return_{horizon}d").reset_index(),
            on="timestamp_utc", how="left", validate="one_to_one")
        allocation = allocation.merge(
            alt_target.rename(f"alt_forward_return_{horizon}d").reset_index(),
            on="timestamp_utc", how="left", validate="one_to_one")
        allocation[f"cash_forward_return_{horizon}d"] = 0.0
    allocation = allocation.dropna().sort_values("timestamp_utc").reset_index(drop=True)

    ranking = alt.merge(breadth, on="timestamp_utc", validate="many_to_one")
    for horizon in ALL_HORIZONS_DAYS:
        target = f"forward_return_{horizon}d"
        ranking[f"forward_rank_{horizon}d"] = ranking.groupby("timestamp_utc")[target].rank(pct=True)
        vol = ranking["realized_volatility_30d"].clip(lower=0.10)
        ranking[f"risk_adjusted_forward_return_{horizon}d"] = ranking[target] / vol
    required_targets = [f"forward_return_{h}d" for h in ALL_HORIZONS_DAYS]
    ranking = ranking.dropna(subset=required_targets).sort_values(
        ["timestamp_utc", "product_id"]).reset_index(drop=True)
    if allocation.empty or ranking.empty:
        raise ValueError("Crypto V5 Phase 1 produced an empty dataset")
    return allocation, ranking


def run_phase1(source_path=SOURCE_PANEL, output_root=PHASE1_ROOT):
    source_path, output_root = Path(source_path), Path(output_root)
    before = _sha256(source_path)
    allocation, ranking = build_datasets(load_source(source_path))
    output_root.mkdir(parents=True, exist_ok=True)
    allocation_path = output_root / "allocation_dataset.parquet"
    ranking_path = output_root / "ranking_dataset.parquet"
    allocation.to_parquet(allocation_path, index=False)
    ranking.to_parquet(ranking_path, index=False)
    if _sha256(source_path) != before:
        raise RuntimeError("Crypto V5 source changed during Phase 1")
    contract = {
        "research_version": RESEARCH_VERSION,
        "primary_horizon_days": PRIMARY_HORIZON_DAYS,
        "control_horizons_days": list(CONTROL_HORIZONS_DAYS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "layers": ["market allocation expected-return/risk model", "eligible-alt ranking model"],
        "allocation_templates": ALLOCATION_TEMPLATES,
        "minimum_hold_days": MINIMUM_HOLD_DAYS,
        "switch_confidence_margin": SWITCH_CONFIDENCE_MARGIN,
        "maximum_turnover_per_rebalance": MAX_TURNOVER_PER_REBALANCE,
        "cost_scenarios_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "primary_cost_bps_round_trip": PRIMARY_COST_BPS,
        "selection_policy": "Choose architecture using development folds only; final holdout remains untouched.",
        "promotion_requirements": ["positive net return", "beats frozen V4",
            "positive risk-adjusted return", "stable across folds and regimes",
            "survives 50 bps costs", "no single-asset or single-period dependency"],
        "prohibited": ["random split", "future feature", "holdout tuning", "V4 mutation",
            "paper-state mutation", "brokerage order", "leverage", "shorting", "derivatives"],
    }
    contract_path = output_root / "preregistered_contract.json"
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    manifest = {"research_version": RESEARCH_VERSION, "phase": 1,
        "stage": "dual_layer_point_in_time_dataset", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {"path": str(source_path), "sha256": before},
        "allocation_rows": int(len(allocation)), "ranking_rows": int(len(ranking)),
        "date_range": {"start": allocation["timestamp_utc"].min().isoformat(),
                       "end": allocation["timestamp_utc"].max().isoformat()},
        "outputs": {"allocation_dataset": str(allocation_path), "ranking_dataset": str(ranking_path),
                    "contract": str(contract_path)},
        "hashes": {"allocation_dataset": _sha256(allocation_path),
                   "ranking_dataset": _sha256(ranking_path), "contract": _sha256(contract_path)},
        "safety": {"v4_modified": False, "paper_state_modified": False,
                   "holdout_scored": False, "brokerage_orders": False}}
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=SOURCE_PANEL)
    ap.add_argument("--output-root", type=Path, default=PHASE1_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase1(args.source, args.output_root), indent=2))


if __name__ == "__main__":
    main()
