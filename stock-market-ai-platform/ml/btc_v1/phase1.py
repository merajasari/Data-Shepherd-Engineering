"""BTC V1 Phase 1: standalone leakage-safe BTC research dataset.

Consumes the frozen Crypto V2 canonical history, selects only BTC-USD, builds
trailing-only BTC features, and attaches exact-endpoint 1d/3d/7d absolute
forward-return targets. This phase creates research data only; it performs no
model fitting, portfolio simulation, threshold tuning, or live execution.
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

from ml.crypto_v2.config import CANONICAL_HISTORY_PATH, MODEL_ROOT as CRYPTO_V2_MODEL_ROOT

RESEARCH_VERSION = "btc_v1"
PRODUCT_ID = "BTC-USD"
FORWARD_HORIZONS_DAYS = (1, 3, 7)
MODEL_ROOT = Path("data/model/btc_v1")
LABELED_DATASET_PATH = MODEL_ROOT / "labeled_dataset.parquet"
MANIFEST_PATH = MODEL_ROOT / "phase1_manifest.json"

MOMENTUM_WINDOWS = (1, 3, 7, 14, 30, 90)
VOLATILITY_WINDOWS = (7, 14, 30, 90)
SMA_WINDOWS = (7, 14, 30, 90)

REQUIRED_FEATURES = (
    "return_1d",
    "return_3d",
    "return_7d",
    "return_14d",
    "return_30d",
    "return_90d",
    "realized_volatility_7d",
    "realized_volatility_14d",
    "realized_volatility_30d",
    "realized_volatility_90d",
    "average_dollar_volume_7d",
    "average_dollar_volume_30d",
    "volume_to_average_30d",
    "close_to_sma_7",
    "close_to_sma_14",
    "close_to_sma_30",
    "close_to_sma_90",
    "drawdown_from_high_30d",
    "drawdown_from_high_90d",
)

POLICY = (
    "BTC V1 Phase 1 reads the frozen Crypto V2 canonical history and selects only BTC-USD. "
    "All features use information available at or before the decision timestamp, continuous "
    "calendar windows only, and exact observed t+h endpoints for labels. Missing observations "
    "are never filled or synthesized. Provider provenance is retained for auditability and is "
    "not a predictive feature. No model outcome may alter dataset construction."
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


def _continuous_rolling(series, timestamps, window, operation):
    result = getattr(series.rolling(window, min_periods=window), operation)()
    span_ok = timestamps.diff(window - 1).eq(pd.Timedelta(days=window - 1))
    return result.where(span_ok)


def _exact_return(frame, days):
    result = frame["close"].pct_change(days, fill_method=None)
    exact = frame["timestamp_utc"].diff(days).eq(pd.Timedelta(days=days))
    return result.where(exact)


def load_btc_history(path=CANONICAL_HISTORY_PATH, completed_before_utc=None):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    required = {
        "product_id", "timestamp_utc", "open", "high", "low", "close", "volume",
        "source_provider", "source_granularity",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("Canonical history missing columns: " + ", ".join(sorted(missing)))
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame[frame["product_id"] == PRODUCT_ID].copy()
    if frame.empty:
        raise ValueError("BTC-USD not found in canonical history")
    if frame.duplicated(["product_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate BTC canonical timestamps")
    if (frame["timestamp_utc"] != frame["timestamp_utc"].dt.floor("D")).any():
        raise ValueError("BTC V1 requires UTC-midnight daily rows")
    if (frame["source_granularity"] != "daily").any():
        raise ValueError("BTC V1 requires daily canonical rows")

    cutoff = pd.Timestamp(completed_before_utc or datetime.now(timezone.utc))
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    cutoff = cutoff.floor("D")
    frame = frame[frame["timestamp_utc"] < cutoff].copy()
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise").astype(float)
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("BTC OHLC prices must be positive")
    if (frame["volume"] < 0).any():
        raise ValueError("BTC volume must be non-negative")
    return frame


def add_features(frame):
    out = frame.copy().sort_values("timestamp_utc").reset_index(drop=True)
    ts = out["timestamp_utc"]
    out["dollar_volume"] = out["close"] * out["volume"]
    daily_return = _exact_return(out, 1)

    for window in MOMENTUM_WINDOWS:
        out[f"return_{window}d"] = _exact_return(out, window)
    for window in VOLATILITY_WINDOWS:
        out[f"realized_volatility_{window}d"] = (
            _continuous_rolling(daily_return, ts, window, "std") * np.sqrt(365.0)
        )
    for window in (7, 30):
        out[f"average_dollar_volume_{window}d"] = _continuous_rolling(
            out["dollar_volume"], ts, window, "mean"
        )
    avg_volume_30 = _continuous_rolling(out["volume"], ts, 30, "mean")
    out["volume_to_average_30d"] = out["volume"] / avg_volume_30
    for window in SMA_WINDOWS:
        sma = _continuous_rolling(out["close"], ts, window, "mean")
        out[f"close_to_sma_{window}"] = out["close"] / sma - 1.0
    for window in (30, 90):
        high = _continuous_rolling(out["high"], ts, window, "max")
        out[f"drawdown_from_high_{window}d"] = out["close"] / high - 1.0
    out["has_required_features"] = out[list(REQUIRED_FEATURES)].notna().all(axis=1)
    return out


def add_targets(frame):
    out = frame.copy()
    lookup = out[["timestamp_utc", "close"]].rename(
        columns={"timestamp_utc": "endpoint", "close": "future_close"}
    )
    for horizon in FORWARD_HORIZONS_DAYS:
        keys = out[["timestamp_utc", "close"]].copy()
        keys["endpoint"] = keys["timestamp_utc"] + pd.Timedelta(days=horizon)
        keys = keys.merge(lookup, on="endpoint", how="left", validate="many_to_one")
        out[f"target_endpoint_utc_{horizon}d"] = keys["endpoint"]
        out[f"forward_return_{horizon}d"] = keys["future_close"] / keys["close"] - 1.0
        out[f"target_positive_{horizon}d"] = out[f"forward_return_{horizon}d"].gt(0).where(
            out[f"forward_return_{horizon}d"].notna()
        ).astype("boolean")
    return out


def build_research_dataset(labeled):
    target_cols = [f"forward_return_{h}d" for h in FORWARD_HORIZONS_DAYS]
    mask = labeled["has_required_features"] & labeled[target_cols].notna().any(axis=1)
    out = labeled.loc[mask].copy()
    out["research_version"] = RESEARCH_VERSION
    return out.sort_values("timestamp_utc").reset_index(drop=True)


def run_phase1(
    canonical_history_path=CANONICAL_HISTORY_PATH,
    output_root=MODEL_ROOT,
    completed_before_utc=None,
):
    canonical_history_path = Path(canonical_history_path)
    before = _sha256(canonical_history_path)
    btc = load_btc_history(canonical_history_path, completed_before_utc)
    labeled = add_targets(add_features(btc))
    research = build_research_dataset(labeled)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_path = output_root / LABELED_DATASET_PATH.name
    research.to_parquet(dataset_path, index=False)

    after = _sha256(canonical_history_path)
    if after != before:
        raise RuntimeError("Frozen canonical history changed during BTC V1 Phase 1")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 1,
        "stage": "standalone_btc_dataset_construction",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "product_id": PRODUCT_ID,
        "policy": POLICY,
        "source": {
            "canonical_history": str(canonical_history_path),
            "canonical_history_sha256": before,
            "source_row_count": int(len(btc)),
            "source_start_utc": btc["timestamp_utc"].min().isoformat(),
            "source_end_utc": btc["timestamp_utc"].max().isoformat(),
            "providers": sorted(btc["source_provider"].dropna().unique().tolist()),
        },
        "features": list(REQUIRED_FEATURES),
        "target_horizons_days": list(FORWARD_HORIZONS_DAYS),
        "target_convention": "completed UTC close at t -> exact observed UTC close at t+h",
        "dataset": {
            "path": str(dataset_path),
            "row_count": int(len(research)),
            "start_utc": research["timestamp_utc"].min().isoformat(),
            "end_utc": research["timestamp_utc"].max().isoformat(),
            "sha256": _sha256(dataset_path),
        },
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "next_step": (
            "Validate BTC V1 Phase 1 coverage, continuity, and exact-endpoint labels. "
            "Then pre-register standalone BTC walk-forward modeling before inspecting results."
        ),
    }
    manifest_path = output_root / MANIFEST_PATH.name
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-history", type=Path, default=CANONICAL_HISTORY_PATH)
    parser.add_argument("--output-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--completed-before-utc", default=None)
    args = parser.parse_args(argv)
    manifest = run_phase1(args.canonical_history, args.output_root, args.completed_before_utc)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
