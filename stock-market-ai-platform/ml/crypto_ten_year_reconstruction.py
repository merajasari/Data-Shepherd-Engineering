"""Run isolated causal Crypto V1-V4 reconstructions on ten-year canonical data.

All outputs live below data/research/crypto_ten_year/reconstruction. Existing
model, paper, journal, monitoring, holdout, and brokerage artifacts are read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.build_crypto_model_comparison import StrategySpec, build_payload
from ml.crypto_v2.prepare_dataset import build_all
from ml.crypto_v2.phase3 import run_phase3 as run_v2_phase3
from ml.crypto_v2.phase4 import run_phase4 as run_v2_phase4
from ml.crypto_v3.phase1 import run_phase1 as run_v3_phase1
from ml.crypto_v3.phase1 import MODEL_FEATURES as V3_MODEL_FEATURES
from ml.crypto_v3.phase2 import run_phase2 as run_v3_phase2
from ml.crypto_v3.phase3 import run_phase3 as run_v3_phase3
from ml.crypto_v4.phase1 import run_phase1 as run_v4_phase1
from ml.crypto_v4.phase2 import run_phase2 as run_v4_phase2
from ml.crypto_v4.phase3 import run_phase3 as run_v4_phase3

DEFAULT_HISTORY_ROOT = Path("data/research/crypto_ten_year")
DEFAULT_OUTPUT = Path("webapp/static/generated/crypto_model_comparison.json")
COMPLETED_BEFORE_UTC = "2026-09-15T00:00:00Z"


def build_v3_complete_source(source_path: Path, output_path: Path) -> dict:
    """Exclude incomplete feature rows for V3; never impute or synthesize them."""
    source = pd.read_parquet(source_path)
    feature_frame = source[list(V3_MODEL_FEATURES)].replace([np.inf, -np.inf], np.nan)
    complete = source.loc[feature_frame.notna().all(axis=1)].copy()
    if complete.empty:
        raise ValueError("No complete Crypto V3 source rows remain after eligibility filtering")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    complete.to_parquet(output_path, index=False)
    return {"source_rows": int(len(source)), "complete_rows": int(len(complete)),
            "excluded_incomplete_rows": int(len(source) - len(complete)),
            "imputed_rows": 0, "output": str(output_path)}


def build_observed_benchmarks(canonical_path: Path, output_path: Path) -> dict:
    """Build full-clock BTC/ETH buy-and-hold curves from observed closes only."""
    canonical = pd.read_parquet(canonical_path)
    canonical["timestamp_utc"] = pd.to_datetime(canonical["timestamp_utc"], utc=True)
    rows = []
    for product_id, variant in (("BTC-USD", "btc_buy_and_hold"),
                                ("ETH-USD", "eth_buy_and_hold")):
        asset = canonical.loc[canonical["product_id"] == product_id,
                              ["timestamp_utc", "close"]].dropna().sort_values("timestamp_utc")
        if asset.empty or (asset["close"] <= 0).any():
            raise ValueError(f"No valid observed canonical benchmark history for {product_id}")
        first = float(asset.iloc[0]["close"])
        asset = asset.assign(variant=variant, equity=asset["close"].astype(float) / first)
        rows.append(asset[["timestamp_utc", "variant", "equity"]])
    result = pd.concat(rows, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)
    return {"output": str(output_path), "rows": int(len(result)),
            "variants": ["btc_buy_and_hold", "eth_buy_and_hold"],
            "synthetic_rows": 0}


def reconstruction_specs(root: Path):
    v2_daily = root / "crypto_v2" / "phase4" / "portfolio_daily.csv"
    benchmarks = root / "benchmarks" / "portfolio_daily.csv"
    return (
        StrategySpec("CRYPTO_V1", "Crypto V1", v2_daily, "top_5_equal_weight",
                     "timestamp_utc", "equity", model_filter="momentum",
                     split_filter="development"),
        StrategySpec("CRYPTO_V2", "Crypto V2", v2_daily, "top_5_equal_weight",
                     "timestamp_utc", "equity", model_filter="hist_gradient_boosting",
                     split_filter="development"),
        StrategySpec("CRYPTO_V3", "Crypto V3", root / "crypto_v3" / "phase3" /
                     "portfolio_daily.csv", "gated_top_5", "timestamp_utc", "equity"),
        StrategySpec("CRYPTO_V4", "Crypto V4 allocator", root / "crypto_v4" /
                     "phase3" / "portfolio_periods.csv", "v4_hgb_allocator",
                     "timestamp_utc", "ending_equity"),
        StrategySpec("CRYPTO_V5", "Crypto V5 Ridge Top-3", root / "crypto_v5" /
                     "phase3" / "portfolio_periods.parquet", "",
                     "timestamp_utc", "ending_equity",
                     status="selected for forward paper evaluation",
                     model_filter="ridge", horizon_days=3, top_n=3,
                     observation_interval_days=3.0),
        StrategySpec("BTC", "Bitcoin buy and hold", benchmarks, "btc_buy_and_hold",
                     "timestamp_utc", "equity", status="benchmark"),
        StrategySpec("ETH", "Ethereum buy and hold", benchmarks, "eth_buy_and_hold",
                     "timestamp_utc", "equity", status="benchmark"),
    )


def refresh_comparison(history_root=DEFAULT_HISTORY_ROOT, comparison_output=DEFAULT_OUTPUT):
    """Refresh benchmarks/comparison from completed isolated model artifacts."""
    history_root, comparison_output = Path(history_root), Path(comparison_output)
    output_root = history_root / "reconstruction"
    benchmark_manifest = build_observed_benchmarks(
        history_root / "canonical" / "canonical_history.parquet",
        output_root / "benchmarks" / "portfolio_daily.csv")
    payload = build_payload(reconstruction_specs(output_root))
    comparison_output.parent.mkdir(parents=True, exist_ok=True)
    comparison_output.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return {"comparison_output": str(comparison_output),
            "comparison_series": [row["model_id"] for row in payload["series"]],
            "unavailable_series": payload["unavailable_series"],
            "benchmarks": benchmark_manifest}


def run(history_root=DEFAULT_HISTORY_ROOT, comparison_output=DEFAULT_OUTPUT):
    history_root, comparison_output = Path(history_root), Path(comparison_output)
    canonical_root = history_root / "canonical"
    canonical_path = canonical_root / "canonical_history.parquet"
    output_root = history_root / "reconstruction"
    v2_root = output_root / "crypto_v2"
    v2_p3, v2_p4 = v2_root / "phase3", v2_root / "phase4"

    dataset_manifest = build_all(
        canonical_path,
        canonical_root / "canonical_manifest.json",
        v2_root,
        COMPLETED_BEFORE_UTC,
    )
    v2_manifest, _, _, _ = run_v2_phase3(v2_root, v2_p3)
    v2_portfolio_manifest = run_v2_phase4(v2_p3, v2_root, v2_p4)[0]

    source_panel = v2_root / "labeled_panel.parquet"
    v3_root = output_root / "crypto_v3"
    v3_p1, v3_p2, v3_p3 = v3_root / "phase1", v3_root / "phase2", v3_root / "phase3"
    v3_source = v3_root / "complete_source_panel_7d.parquet"
    v3_source_filter = build_v3_complete_source(source_panel, v3_source)
    v3_dataset = v3_p1 / "research_panel_7d.parquet"
    v3_phase1_manifest = run_v3_phase1(v3_source, v3_p1)
    v3_phase2_manifest = run_v3_phase2(v3_dataset, v3_p2)
    v3_phase3_manifest = run_v3_phase3(
        v3_p2, v3_dataset, v3_source, v3_p3)

    v4_root = output_root / "crypto_v4"
    v4_p1, v4_p2, v4_p3 = v4_root / "phase1", v4_root / "phase2", v4_root / "phase3"
    v4_phase1_manifest = run_v4_phase1(source_panel, v4_p1)
    v4_phase2_manifest = run_v4_phase2(
        v4_p1 / "market_allocation_dataset.parquet", v4_p1 / "manifest.json", v4_p2)[0]
    v4_phase3_manifest = run_v4_phase3(
        v4_p1 / "market_allocation_dataset.parquet", v4_p1 / "manifest.json",
        v4_p2 / "predictions.parquet", v4_p2 / "manifest.json", v4_p3)[0]

    comparison = refresh_comparison(history_root, comparison_output)
    payload = build_payload(reconstruction_specs(output_root))
    benchmark_manifest = comparison["benchmarks"]
    manifest = {
        "stage": "crypto_ten_year_causal_reconstruction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_before_utc": COMPLETED_BEFORE_UTC,
        "canonical_history": str(canonical_path),
        "output_root": str(output_root),
        "comparison_output": str(comparison_output),
        "comparison_series": [row["model_id"] for row in payload["series"]],
        "unavailable_series": payload["unavailable_series"],
        "safety": {"existing_model_roots_modified": False, "paper_state_modified": False,
                   "future_holdout_scored": False, "brokerage_orders": False},
        "stages": {
            "v2_dataset": dataset_manifest.get("stage", "dataset"),
            "v2_models": v2_manifest.get("phase"),
            "v2_portfolios": v2_portfolio_manifest.get("phase"),
            "v3": [v3_phase1_manifest.get("phase"), v3_phase2_manifest.get("phase"),
                   v3_phase3_manifest.get("phase")],
            "v3_source_filter": v3_source_filter,
            "v4": [v4_phase1_manifest.get("phase"), v4_phase2_manifest.get("phase"),
                   v4_phase3_manifest.get("phase")],
            "benchmarks": benchmark_manifest,
        },
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-root", type=Path, default=DEFAULT_HISTORY_ROOT)
    parser.add_argument("--comparison-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--comparison-only", action="store_true",
                        help="Reuse completed model artifacts and refresh BTC/ETH comparison")
    args = parser.parse_args(argv)
    result = (refresh_comparison(args.history_root, args.comparison_output)
              if args.comparison_only else run(args.history_root, args.comparison_output))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
