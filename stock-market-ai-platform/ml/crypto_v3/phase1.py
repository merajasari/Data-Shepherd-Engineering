"""Crypto V3 Phase 1: pre-registered altcoin absolute/risk-adjusted dataset.

Crypto V3 is a fresh research hypothesis after Crypto V2 failed as a BTC-relative
long-only ranking strategy. Phase 1 reads only the frozen Crypto V2 7-day research
panel, excludes BTC-USD from the investable universe, preserves BTC-derived context
features, and defines two new 7-day targets before modeling:

1) target_positive_absolute_7d: whether the exact observed 7-day absolute return is > 0.
2) target_risk_adjusted_return_7d: exact observed 7-day absolute return divided by
   pre-decision 30-day realized volatility (annualized), with a fixed denominator
   floor to avoid unstable scaling.

No model fitting, threshold search, portfolio simulation, BTC V1 signal injection,
leverage, shorting, derivatives, live execution, or future-holdout evaluation occurs
in this phase. Data at or after 2026-09-01 remains reserved for future validation.
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

from ml.crypto_v2.config import MODEL_ROOT as CRYPTO_V2_MODEL_ROOT
from ml.crypto_v2.prepare_dataset import REQUIRED_FEATURES

RESEARCH_VERSION = "crypto_v3"
MODEL_ROOT = Path("data/model/crypto_v3")
PHASE1_ROOT = MODEL_ROOT / "phase1"
SOURCE_PANEL_PATH = CRYPTO_V2_MODEL_ROOT / "research_panel_7d.parquet"
DATASET_PATH = PHASE1_ROOT / "research_panel_7d.parquet"
MANIFEST_PATH = PHASE1_ROOT / "manifest.json"

HORIZON_DAYS = 7
BENCHMARK_PRODUCT = "BTC-USD"
MIN_NON_BTC_ASSETS = 10
VOLATILITY_DENOMINATOR_FLOOR = 0.10
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01", tz="UTC")

MODEL_FEATURES = tuple(REQUIRED_FEATURES)
TARGET_ABSOLUTE_RETURN = "forward_return_7d"
TARGET_POSITIVE = "target_positive_absolute_7d"
TARGET_RISK_ADJUSTED = "target_risk_adjusted_return_7d"

POLICY = (
    "Crypto V3 Phase 1 reads the frozen Crypto V2 7-day research panel, excludes "
    "BTC-USD from the investable universe, retains BTC-derived context features, "
    "and defines absolute-return and ex-ante-volatility-normalized 7-day targets. "
    "The risk denominator uses only realized_volatility_30d known at decision time "
    "and a fixed 0.10 floor. No model result may alter dataset construction."
)


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


def load_source(path=SOURCE_PANEL_PATH):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path).copy()
    required = set(MODEL_FEATURES) | {
        "timestamp_utc", "product_id", "return_1d", "realized_volatility_30d",
        "forward_return_7d", "target_endpoint_utc_7d", "btc_return_7d",
        "btc_return_30d", "btc_realized_volatility_30d", "btc_regime",
        "source_provider", "source_granularity",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError("Crypto V2 7-day panel missing columns: " + ", ".join(sorted(missing)))
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["target_endpoint_utc_7d"] = pd.to_datetime(df["target_endpoint_utc_7d"], utc=True)
    if df.duplicated(["timestamp_utc", "product_id"]).any():
        raise ValueError("Duplicate source panel keys")
    return df.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def build_dataset(source, minimum_assets=MIN_NON_BTC_ASSETS):
    out = source[source["product_id"] != BENCHMARK_PRODUCT].copy()
    if (out["product_id"] == BENCHMARK_PRODUCT).any():
        raise RuntimeError("BTC must not remain in Crypto V3 investable universe")

    counts = out.groupby("timestamp_utc")["product_id"].transform("nunique")
    out = out[counts >= int(minimum_assets)].copy()
    out["eligible_non_btc_asset_count"] = out.groupby("timestamp_utc")["product_id"].transform("nunique")

    target_ok = out[TARGET_ABSOLUTE_RETURN].notna() & out["target_endpoint_utc_7d"].notna()
    out = out[target_ok].copy()
    out[TARGET_POSITIVE] = out[TARGET_ABSOLUTE_RETURN] > 0

    denom = pd.to_numeric(out["realized_volatility_30d"], errors="coerce")
    denom = denom.clip(lower=VOLATILITY_DENOMINATOR_FLOOR)
    out[TARGET_RISK_ADJUSTED] = out[TARGET_ABSOLUTE_RETURN] / denom

    if out[list(MODEL_FEATURES)].isna().any().any():
        raise ValueError("Crypto V3 dataset contains missing required pre-decision features")
    if out[[TARGET_ABSOLUTE_RETURN, TARGET_RISK_ADJUSTED]].isna().any().any():
        raise ValueError("Crypto V3 dataset contains missing targets")
    if (out["target_endpoint_utc_7d"] <= out["timestamp_utc"]).any():
        raise ValueError("Target endpoint must be strictly after decision timestamp")

    out["research_version"] = RESEARCH_VERSION
    return out.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def run_phase1(source_path=SOURCE_PANEL_PATH, output_root=PHASE1_ROOT):
    source_path = Path(source_path)
    before = _sha256(source_path)
    source = load_source(source_path)
    dataset = build_dataset(source)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_path = output_root / DATASET_PATH.name
    dataset.to_parquet(dataset_path, index=False)

    after = _sha256(source_path)
    if after != before:
        raise RuntimeError("Frozen Crypto V2 source panel changed during Crypto V3 Phase 1")

    daily_counts = dataset.groupby("timestamp_utc")["product_id"].nunique()
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "absolute_and_risk_adjusted_altcoin_dataset_construction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "policy": POLICY,
        "architecture": {
            "investable_universe": "eligible altcoins excluding BTC-USD",
            "btc_context_features_retained": True,
            "btc_v1_signal_used": False,
            "minimum_non_btc_assets": MIN_NON_BTC_ASSETS,
        },
        "targets": {
            "absolute_return": TARGET_ABSOLUTE_RETURN,
            "positive_absolute": TARGET_POSITIVE,
            "risk_adjusted_return": TARGET_RISK_ADJUSTED,
            "risk_denominator": "realized_volatility_30d known at decision time",
            "volatility_floor": VOLATILITY_DENOMINATOR_FLOOR,
        },
        "features": list(MODEL_FEATURES),
        "source": {
            "path": str(source_path),
            "sha256": before,
            "rows": int(len(source)),
        },
        "dataset": {
            "path": str(dataset_path),
            "sha256": _sha256(dataset_path),
            "rows": int(len(dataset)),
            "products": int(dataset["product_id"].nunique()),
            "start_utc": dataset["timestamp_utc"].min().isoformat(),
            "end_utc": dataset["timestamp_utc"].max().isoformat(),
            "minimum_daily_assets": int(daily_counts.min()),
            "median_daily_assets": float(daily_counts.median()),
            "maximum_daily_assets": int(daily_counts.max()),
        },
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "next_step": (
            "Validate Crypto V3 Phase 1 coverage and target construction. Then pre-register "
            "separate walk-forward positive-probability and risk-adjusted-return models before "
            "inspecting model results."
        ),
    }
    (output_root / MANIFEST_PATH.name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=SOURCE_PANEL_PATH)
    ap.add_argument("--output-root", type=Path, default=PHASE1_ROOT)
    args = ap.parse_args(argv)
    print(json.dumps(run_phase1(args.source, args.output_root), indent=2))


if __name__ == "__main__":
    main()
