"""Crypto V2 Phase 2 leakage-safe dataset construction.

Consumes only the frozen canonical-history artifact from Phase 1B. Missing
calendar observations remain missing; rolling features require continuous
calendar coverage and forward labels require the exact t+h UTC endpoint.
Provider provenance is retained for auditability but never used to select
sources or define a predictive feature.
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

from ml.crypto_v2.config import (
    BENCHMARK_PRODUCT,
    CANONICAL_HISTORY_PATH,
    CANONICAL_MANIFEST_PATH,
    DATASET_MANIFEST_PATH,
    DATASET_POLICY,
    DEFAULT_GRANULARITY,
    FORWARD_HORIZONS_DAYS,
    LABELED_PANEL_PATH,
    LIQUIDITY_LOOKBACK_DAYS,
    MINIMUM_HISTORY_DAYS,
    MINIMUM_MEDIAN_DAILY_DOLLAR_VOLUME,
    MODEL_ROOT,
    RESEARCH_VERSION,
)

MOMENTUM_WINDOWS = (1, 3, 7, 14, 30)
VOLATILITY_WINDOWS = (7, 14, 30)
SMA_WINDOWS = (7, 14, 30)

REQUIRED_FEATURES = (
    "return_1d",
    "return_3d",
    "return_7d",
    "return_14d",
    "return_30d",
    "realized_volatility_7d",
    "realized_volatility_14d",
    "realized_volatility_30d",
    "average_dollar_volume_7d",
    "average_dollar_volume_30d",
    "volume_to_average_30d",
    "close_to_sma_7",
    "close_to_sma_14",
    "close_to_sma_30",
    "drawdown_from_high_30d",
    "btc_relative_return_1d",
    "btc_relative_return_3d",
    "btc_relative_return_7d",
    "btc_relative_return_14d",
    "btc_relative_return_30d",
    "correlation_to_btc_14d",
    "correlation_to_btc_30d",
)

CANONICAL_REQUIRED_COLUMNS = {
    "product_id",
    "timestamp_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "source_granularity",
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit_hash():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _date_range(frame):
    if frame.empty:
        return {"start_utc": None, "end_utc": None}
    return {
        "start_utc": frame["timestamp_utc"].min().isoformat(),
        "end_utc": frame["timestamp_utc"].max().isoformat(),
    }


def load_canonical_history(path=CANONICAL_HISTORY_PATH, completed_before_utc=None):
    """Load and validate the immutable canonical daily history."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Canonical history not found: {path}")
    panel = pd.read_parquet(path)
    missing = sorted(CANONICAL_REQUIRED_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError("Canonical history missing columns: " + ", ".join(missing))

    panel = panel.copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    if panel.duplicated(["product_id", "timestamp_utc"]).any():
        raise ValueError("Canonical history contains duplicate product/timestamp rows")
    if (panel["source_granularity"] != DEFAULT_GRANULARITY).any():
        raise ValueError("Crypto V2 Phase 2 requires canonical daily history")
    if (panel["timestamp_utc"] != panel["timestamp_utc"].dt.floor("D")).any():
        raise ValueError("Canonical daily timestamps must be aligned to UTC midnight")
    for column in ("open", "high", "low", "close", "volume"):
        panel[column] = pd.to_numeric(panel[column], errors="raise").astype("float64")
    if (panel[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Canonical OHLC prices must be positive")
    if (panel["volume"] < 0).any():
        raise ValueError("Canonical volume must be non-negative")

    cutoff = pd.Timestamp(completed_before_utc or datetime.now(timezone.utc))
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    cutoff = cutoff.floor("D")
    panel = panel[panel["timestamp_utc"] < cutoff].copy()
    panel = panel.sort_values(["product_id", "timestamp_utc"], kind="stable").reset_index(drop=True)
    panel["dollar_volume"] = panel["close"] * panel["volume"]
    panel["first_available_timestamp"] = panel.groupby("product_id")["timestamp_utc"].transform("min")
    return panel


def _continuous_rolling(series, timestamps, window, operation, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    result = getattr(series.rolling(window, min_periods=min_periods), operation)()
    span_ok = timestamps.diff(window - 1).eq(pd.Timedelta(days=window - 1))
    return result.where(span_ok)


def _exact_return(group, days):
    result = group["close"].pct_change(days, fill_method=None)
    exact = group["timestamp_utc"].diff(days).eq(pd.Timedelta(days=days))
    return result.where(exact)


def add_features_and_eligibility(canonical):
    """Build trailing-only features without bridging calendar gaps."""
    pieces = []
    for _, group in canonical.groupby("product_id", sort=False):
        group = group.sort_values("timestamp_utc").copy()
        timestamps = group["timestamp_utc"]
        daily_return = _exact_return(group, 1)

        for window in MOMENTUM_WINDOWS:
            group[f"return_{window}d"] = _exact_return(group, window)
        for window in VOLATILITY_WINDOWS:
            group[f"realized_volatility_{window}d"] = _continuous_rolling(
                daily_return, timestamps, window, "std"
            ) * np.sqrt(365.0)
        for window in (7, 30):
            group[f"average_dollar_volume_{window}d"] = _continuous_rolling(
                group["dollar_volume"], timestamps, window, "mean"
            )
        group["trailing_median_dollar_volume_30d"] = _continuous_rolling(
            group["dollar_volume"], timestamps, LIQUIDITY_LOOKBACK_DAYS, "median"
        )
        average_volume_30 = _continuous_rolling(group["volume"], timestamps, 30, "mean")
        group["volume_to_average_30d"] = group["volume"] / average_volume_30
        group["dollar_volume_trend_7d_vs_30d"] = (
            group["average_dollar_volume_7d"] / group["average_dollar_volume_30d"] - 1
        )
        for window in SMA_WINDOWS:
            sma = _continuous_rolling(group["close"], timestamps, window, "mean")
            group[f"close_to_sma_{window}"] = group["close"] / sma - 1
        for window in (30, 90):
            trailing_high = _continuous_rolling(group["high"], timestamps, window, "max")
            group[f"drawdown_from_high_{window}d"] = group["close"] / trailing_high - 1

        group["history_days_available"] = (timestamps - timestamps.iloc[0]).dt.days + 1
        group["has_minimum_history"] = group["history_days_available"] >= MINIMUM_HISTORY_DAYS
        group["meets_liquidity_threshold"] = (
            group["trailing_median_dollar_volume_30d"] >= MINIMUM_MEDIAN_DAILY_DOLLAR_VOLUME
        )
        pieces.append(group)

    panel = pd.concat(pieces, ignore_index=True)
    btc_columns = ["timestamp_utc", "close"] + [f"return_{w}d" for w in MOMENTUM_WINDOWS]
    btc = panel.loc[panel["product_id"] == BENCHMARK_PRODUCT, btc_columns].copy()
    if btc.empty:
        raise ValueError(f"Benchmark {BENCHMARK_PRODUCT} is required")
    btc = btc.rename(columns={
        "close": "btc_close",
        **{f"return_{w}d": f"btc_return_{w}d" for w in MOMENTUM_WINDOWS},
    })
    panel = panel.merge(btc, on="timestamp_utc", how="left", validate="many_to_one")
    for window in MOMENTUM_WINDOWS:
        panel[f"btc_relative_return_{window}d"] = (
            panel[f"return_{window}d"] - panel[f"btc_return_{window}d"]
        )

    pieces = []
    for _, group in panel.groupby("product_id", sort=False):
        group = group.sort_values("timestamp_utc").copy()
        timestamps = group["timestamp_utc"]
        for window in (14, 30):
            correlation = group["return_1d"].rolling(window, min_periods=window).corr(
                group["btc_return_1d"]
            )
            group[f"correlation_to_btc_{window}d"] = correlation.where(
                timestamps.diff(window - 1).eq(pd.Timedelta(days=window - 1))
            )
        ratio = group["close"] / group["btc_close"]
        ratio_sma = _continuous_rolling(ratio, timestamps, 14, "mean")
        group["asset_btc_relative_strength_trend_14d"] = ratio / ratio_sma - 1
        pieces.append(group)
    panel = pd.concat(pieces, ignore_index=True)

    btc_regime = panel[panel["product_id"] == BENCHMARK_PRODUCT][[
        "timestamp_utc",
        "btc_return_7d",
        "btc_return_14d",
        "btc_return_30d",
        "realized_volatility_14d",
        "realized_volatility_30d",
        "close_to_sma_30",
    ]].rename(columns={
        "realized_volatility_14d": "btc_realized_volatility_14d",
        "realized_volatility_30d": "btc_realized_volatility_30d",
        "close_to_sma_30": "btc_close_to_sma_30",
    })
    panel = panel.drop(columns=["btc_return_7d", "btc_return_14d", "btc_return_30d"])
    panel = panel.merge(btc_regime, on="timestamp_utc", how="left", validate="many_to_one")
    panel["btc_regime"] = np.select(
        [
            (panel["btc_return_30d"] > 0) & (panel["btc_close_to_sma_30"] > 0),
            (panel["btc_return_30d"] < 0) & (panel["btc_close_to_sma_30"] < 0),
        ],
        ["risk_on", "risk_off"],
        default="neutral",
    )

    panel["has_required_trailing_windows"] = panel[list(REQUIRED_FEATURES)].notna().all(axis=1)
    panel["is_eligible"] = (
        panel["has_minimum_history"]
        & panel["has_required_trailing_windows"]
        & panel["meets_liquidity_threshold"]
    )
    panel["eligibility_reason"] = np.select(
        [
            ~panel["has_minimum_history"],
            ~panel["has_required_trailing_windows"],
            ~panel["meets_liquidity_threshold"],
        ],
        [
            "insufficient_history",
            "incomplete_trailing_windows",
            "below_liquidity_threshold",
        ],
        default="eligible",
    )
    return panel.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def add_targets(panel):
    """Attach exact-endpoint absolute and BTC-relative forward returns."""
    result = panel.copy()
    prices = result[["product_id", "timestamp_utc", "close"]]
    btc_prices = prices[prices["product_id"] == BENCHMARK_PRODUCT][["timestamp_utc", "close"]]

    for horizon in FORWARD_HORIZONS_DAYS:
        future = prices.rename(columns={"timestamp_utc": "endpoint", "close": "future_close"})
        keys = result[["product_id", "timestamp_utc", "close"]].copy()
        keys["endpoint"] = keys["timestamp_utc"] + pd.Timedelta(days=horizon)
        keys = keys.merge(future, on=["product_id", "endpoint"], how="left", validate="many_to_one")
        absolute = keys["future_close"] / keys["close"] - 1

        btc_future = btc_prices.rename(columns={"timestamp_utc": "endpoint", "close": "btc_future_close"})
        btc_keys = result[["timestamp_utc", "btc_close"]].copy()
        btc_keys["endpoint"] = btc_keys["timestamp_utc"] + pd.Timedelta(days=horizon)
        btc_keys = btc_keys.merge(btc_future, on="endpoint", how="left", validate="many_to_one")
        btc_forward = btc_keys["btc_future_close"] / btc_keys["btc_close"] - 1
        relative = absolute - btc_forward

        result[f"target_endpoint_utc_{horizon}d"] = keys["endpoint"]
        result[f"forward_return_{horizon}d"] = absolute
        result[f"forward_btc_return_{horizon}d"] = btc_forward
        result[f"forward_return_relative_to_btc_{horizon}d"] = relative

        eligible_label = result["is_eligible"] & relative.notna()
        values = relative.where(eligible_label)
        result[f"target_percentile_rank_{horizon}d"] = values.groupby(
            result["timestamp_utc"]
        ).rank(pct=True)
        descending = values.groupby(result["timestamp_utc"]).rank(
            method="first", ascending=False
        )
        result[f"target_top_3_{horizon}d"] = descending.le(3).where(eligible_label).astype("boolean")
        result[f"target_top_5_{horizon}d"] = descending.le(5).where(eligible_label).astype("boolean")
    return result


def build_horizon_research_panel(labeled, horizon, generated_at_utc=None):
    if horizon not in FORWARD_HORIZONS_DAYS:
        raise ValueError(f"Unsupported target horizon: {horizon}")
    target = f"forward_return_relative_to_btc_{horizon}d"
    mask = (
        labeled["is_eligible"]
        & labeled[list(REQUIRED_FEATURES)].notna().all(axis=1)
        & labeled[target].notna()
    )
    official = labeled.loc[mask].copy()
    values = official[target]
    official[f"target_percentile_rank_{horizon}d"] = values.groupby(
        official["timestamp_utc"]
    ).rank(pct=True)
    descending = values.groupby(official["timestamp_utc"]).rank(
        method="first", ascending=False
    )
    official[f"target_top_3_{horizon}d"] = descending.le(3).astype("boolean")
    official[f"target_top_5_{horizon}d"] = descending.le(5).astype("boolean")
    official["research_version"] = RESEARCH_VERSION
    official["dataset_created_at_utc"] = generated_at_utc or datetime.now(timezone.utc)
    return official.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def build_all(
    canonical_history_path=CANONICAL_HISTORY_PATH,
    canonical_manifest_path=CANONICAL_MANIFEST_PATH,
    model_root=MODEL_ROOT,
    completed_before_utc=None,
):
    canonical_history_path = Path(canonical_history_path)
    canonical_manifest_path = Path(canonical_manifest_path)
    if not canonical_manifest_path.exists():
        raise FileNotFoundError(f"Canonical manifest not found: {canonical_manifest_path}")

    canonical_hash_before = _sha256(canonical_history_path)
    canonical_manifest_hash_before = _sha256(canonical_manifest_path)
    canonical = load_canonical_history(canonical_history_path, completed_before_utc)
    featured = add_features_and_eligibility(canonical)
    labeled = add_targets(featured)

    model_root = Path(model_root)
    model_root.mkdir(parents=True, exist_ok=True)
    labeled_path = model_root / LABELED_PANEL_PATH.name
    labeled.to_parquet(labeled_path, index=False)

    generated_at = datetime.now(timezone.utc)
    horizon_datasets = {}
    for horizon in FORWARD_HORIZONS_DAYS:
        official = build_horizon_research_panel(labeled, horizon, generated_at)
        path = model_root / f"research_panel_{horizon}d.parquet"
        official.to_parquet(path, index=False)
        horizon_datasets[f"{horizon}d"] = {
            "path": str(path),
            "row_count": int(len(official)),
            "date_range": _date_range(official),
            "sha256": _sha256(path),
        }

    canonical_hash_after = _sha256(canonical_history_path)
    canonical_manifest_hash_after = _sha256(canonical_manifest_path)
    if (
        canonical_hash_after != canonical_hash_before
        or canonical_manifest_hash_after != canonical_manifest_hash_before
    ):
        raise RuntimeError("Frozen Phase 1B canonical artifacts changed during Phase 2")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "leakage_safe_dataset_construction",
        "generated_at_utc": generated_at.isoformat(),
        "git_commit_hash": _git_commit_hash(),
        "policy": DATASET_POLICY,
        "benchmark_product": BENCHMARK_PRODUCT,
        "target_horizons_days": list(FORWARD_HORIZONS_DAYS),
        "required_features": list(REQUIRED_FEATURES),
        "eligibility_configuration": {
            "minimum_history_days": MINIMUM_HISTORY_DAYS,
            "liquidity_lookback_days": LIQUIDITY_LOOKBACK_DAYS,
            "minimum_median_daily_dollar_volume": MINIMUM_MEDIAN_DAILY_DOLLAR_VOLUME,
        },
        "source": {
            "canonical_history": str(canonical_history_path),
            "canonical_history_sha256": canonical_hash_before,
            "canonical_manifest": str(canonical_manifest_path),
            "canonical_manifest_sha256": canonical_manifest_hash_before,
            "canonical_row_count": int(len(canonical)),
            "product_count": int(canonical["product_id"].nunique()),
            "date_range": _date_range(canonical),
        },
        "provenance_policy": (
            "source_provider and source_granularity are retained on every row for auditability; "
            "they are not included in REQUIRED_FEATURES and do not influence source selection."
        ),
        "continuity_policy": (
            "Trailing features require exact continuous calendar coverage for their full window; "
            "observed gaps are never bridged or filled."
        ),
        "decision_target_convention": "completed UTC close at t -> observed exact UTC close at t+h",
        "labeled_panel": {
            "path": str(labeled_path),
            "row_count": int(len(labeled)),
            "date_range": _date_range(labeled),
            "sha256": _sha256(labeled_path),
        },
        "horizon_datasets": horizon_datasets,
        "next_step": (
            "Validate Phase 2 row counts, coverage, exact-endpoint target behavior, and provenance; "
            "then freeze these datasets before defining Crypto V2 walk-forward model folds."
        ),
    }
    manifest_path = model_root / DATASET_MANIFEST_PATH.name
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-history", type=Path, default=CANONICAL_HISTORY_PATH)
    parser.add_argument("--canonical-manifest", type=Path, default=CANONICAL_MANIFEST_PATH)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--completed-before-utc", default=None)
    args = parser.parse_args(argv)
    manifest = build_all(
        canonical_history_path=args.canonical_history,
        canonical_manifest_path=args.canonical_manifest,
        model_root=args.model_root,
        completed_before_utc=args.completed_before_utc,
    )
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
