"""Build leakage-safe Crypto V1 Silver, Gold, and research datasets."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v1.config import (
    BENCHMARK_PRODUCT, BRONZE_ROOT, CRYPTO_UNIVERSE, DEFAULT_GRANULARITY,
    FORWARD_HORIZONS_DAYS, GOLD_ROOT, LIQUIDITY_LOOKBACK_DAYS,
    MINIMUM_HISTORY_DAYS, MINIMUM_MEDIAN_DAILY_DOLLAR_VOLUME, MODEL_ROOT,
    PROVIDER_NAME, RESEARCH_VERSION, SILVER_ROOT,
)
from ml.crypto_v1.validation import validate_bronze


MOMENTUM_WINDOWS = (1, 3, 7, 14, 30)
VOLATILITY_WINDOWS = (7, 14, 30)
SMA_WINDOWS = (7, 14, 30)
REQUIRED_FEATURES = (
    "return_1d", "return_3d", "return_7d", "return_14d", "return_30d",
    "realized_volatility_7d", "realized_volatility_14d",
    "realized_volatility_30d", "average_dollar_volume_7d",
    "average_dollar_volume_30d", "volume_to_average_30d",
    "close_to_sma_7", "close_to_sma_14", "close_to_sma_30",
    "drawdown_from_high_30d", "btc_relative_return_1d",
    "btc_relative_return_3d", "btc_relative_return_7d",
    "btc_relative_return_14d", "btc_relative_return_30d",
    "correlation_to_btc_14d", "correlation_to_btc_30d",
)


def bronze_product_dirs(bronze_root=BRONZE_ROOT, provider=PROVIDER_NAME, granularity=DEFAULT_GRANULARITY):
    base = Path(bronze_root) / provider / granularity
    return [path for path in sorted(base.iterdir()) if path.is_dir()] if base.exists() else []


def build_silver(bronze_root=BRONZE_ROOT, silver_root=SILVER_ROOT,
                 provider=PROVIDER_NAME, granularity=DEFAULT_GRANULARITY):
    outputs, reports = [], []
    for product_dir in bronze_product_dirs(bronze_root, provider, granularity):
        frame, report = validate_bronze(product_dir / "candles.csv")
        silver = frame.copy()
        silver["timestamp_utc"] = pd.to_datetime(silver["timestamp_utc"], utc=True)
        for column in ("open", "high", "low", "close", "volume"):
            silver[column] = pd.to_numeric(silver[column], errors="raise").astype("float64")
        silver = (silver.drop_duplicates(["product_id", "timestamp_utc"], keep="last")
                  .sort_values(["product_id", "timestamp_utc"]).reset_index(drop=True))
        output = Path(silver_root) / provider / granularity / product_dir.name / "candles.parquet"
        output.parent.mkdir(parents=True, exist_ok=True)
        silver.to_parquet(output, index=False)
        outputs.append(output)
        reports.append(report)
    return outputs, reports


def load_silver(silver_root=SILVER_ROOT, provider=PROVIDER_NAME, granularity=DEFAULT_GRANULARITY):
    paths = sorted((Path(silver_root) / provider / granularity).glob("*/candles.parquet"))
    if not paths:
        raise FileNotFoundError("No Crypto V1 Silver candle files found")
    return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)


def build_gold_panel(silver, completed_before_utc=None):
    """Return one observed daily candle per product; never create missing rows."""
    panel = silver.copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    if (panel["granularity"] != "daily").any():
        raise ValueError("Gold research panel requires daily candles")
    if (panel["timestamp_utc"] != panel["timestamp_utc"].dt.floor("D")).any():
        raise ValueError("Daily candles must be aligned to UTC midnight")
    cutoff = pd.Timestamp(completed_before_utc or datetime.now(timezone.utc))
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    cutoff = cutoff.floor("D")
    panel = panel[panel["timestamp_utc"] < cutoff].copy()
    panel = panel.sort_values(["product_id", "timestamp_utc"]).drop_duplicates(
        ["product_id", "timestamp_utc"], keep="last")
    panel["dollar_volume"] = panel["close"] * panel["volume"]
    panel["first_available_timestamp"] = panel.groupby("product_id")["timestamp_utc"].transform("min")
    return panel[[
        "product_id", "timestamp_utc", "open", "high", "low", "close", "volume",
        "dollar_volume", "first_available_timestamp", "provider", "granularity",
    ]].reset_index(drop=True)


def _continuous_rolling(series, timestamps, window, operation, min_periods=None):
    min_periods = window if min_periods is None else min_periods
    result = getattr(series.rolling(window, min_periods=min_periods), operation)()
    span_ok = timestamps.diff(window - 1).eq(pd.Timedelta(days=window - 1))
    return result.where(span_ok)


def _exact_return(group, days):
    result = group["close"].pct_change(days)
    exact = group["timestamp_utc"].diff(days).eq(pd.Timedelta(days=days))
    return result.where(exact)


def add_features_and_eligibility(gold):
    panel = gold.sort_values(["product_id", "timestamp_utc"]).copy()
    pieces = []
    for _, group in panel.groupby("product_id", sort=False):
        group = group.copy()
        timestamps = group["timestamp_utc"]
        daily_return = _exact_return(group, 1)
        for window in MOMENTUM_WINDOWS:
            group[f"return_{window}d"] = _exact_return(group, window)
        for window in VOLATILITY_WINDOWS:
            group[f"realized_volatility_{window}d"] = _continuous_rolling(
                daily_return, timestamps, window, "std") * np.sqrt(365.0)
        for window in (7, 30):
            group[f"average_dollar_volume_{window}d"] = _continuous_rolling(
                group["dollar_volume"], timestamps, window, "mean")
        group["trailing_median_dollar_volume_30d"] = _continuous_rolling(
            group["dollar_volume"], timestamps, LIQUIDITY_LOOKBACK_DAYS, "median")
        average_volume_30 = _continuous_rolling(group["volume"], timestamps, 30, "mean")
        group["volume_to_average_30d"] = group["volume"] / average_volume_30
        group["dollar_volume_trend_7d_vs_30d"] = (
            group["average_dollar_volume_7d"] / group["average_dollar_volume_30d"] - 1)
        for window in SMA_WINDOWS:
            sma = _continuous_rolling(group["close"], timestamps, window, "mean")
            group[f"close_to_sma_{window}"] = group["close"] / sma - 1
        for window in (30, 90):
            trailing_high = _continuous_rolling(group["high"], timestamps, window, "max")
            group[f"drawdown_from_high_{window}d"] = group["close"] / trailing_high - 1
        group["history_days_available"] = (timestamps - timestamps.iloc[0]).dt.days + 1
        group["has_minimum_history"] = group["history_days_available"] >= MINIMUM_HISTORY_DAYS
        group["has_required_trailing_windows"] = group[list(REQUIRED_FEATURES[:15])].notna().all(axis=1)
        group["meets_liquidity_threshold"] = (
            group["trailing_median_dollar_volume_30d"] >= MINIMUM_MEDIAN_DAILY_DOLLAR_VOLUME)
        pieces.append(group)
    panel = pd.concat(pieces, ignore_index=True)

    btc_columns = ["timestamp_utc", "close"] + [f"return_{window}d" for window in MOMENTUM_WINDOWS]
    btc = panel.loc[panel["product_id"] == BENCHMARK_PRODUCT, btc_columns].copy()
    if btc.empty:
        raise ValueError(f"Benchmark {BENCHMARK_PRODUCT} is required")
    btc = btc.rename(columns={"close": "btc_close", **{
        f"return_{window}d": f"btc_return_{window}d" for window in MOMENTUM_WINDOWS}})
    panel = panel.merge(btc, on="timestamp_utc", how="left", validate="many_to_one")
    for window in MOMENTUM_WINDOWS:
        panel[f"btc_relative_return_{window}d"] = (
            panel[f"return_{window}d"] - panel[f"btc_return_{window}d"])

    pieces = []
    for _, group in panel.groupby("product_id", sort=False):
        group = group.sort_values("timestamp_utc").copy()
        timestamps = group["timestamp_utc"]
        asset_daily = group["return_1d"]
        btc_daily = group["btc_return_1d"]
        for window in (14, 30):
            correlation = asset_daily.rolling(window, min_periods=window).corr(btc_daily)
            group[f"correlation_to_btc_{window}d"] = correlation.where(
                timestamps.diff(window - 1).eq(pd.Timedelta(days=window - 1)))
        ratio = group["close"] / group["btc_close"]
        ratio_sma = _continuous_rolling(ratio, timestamps, 14, "mean")
        group["asset_btc_relative_strength_trend_14d"] = ratio / ratio_sma - 1
        pieces.append(group)
    panel = pd.concat(pieces, ignore_index=True)

    btc_regime = panel[panel["product_id"] == BENCHMARK_PRODUCT][[
        "timestamp_utc", "btc_return_7d", "btc_return_14d", "btc_return_30d",
        "realized_volatility_14d", "realized_volatility_30d", "close_to_sma_30",
    ]].rename(columns={
        "realized_volatility_14d": "btc_realized_volatility_14d",
        "realized_volatility_30d": "btc_realized_volatility_30d",
        "close_to_sma_30": "btc_close_to_sma_30",
    })
    panel = panel.drop(columns=["btc_return_7d", "btc_return_14d", "btc_return_30d"])
    panel = panel.merge(btc_regime, on="timestamp_utc", how="left", validate="many_to_one")
    panel["btc_regime"] = np.select(
        [(panel["btc_return_30d"] > 0) & (panel["btc_close_to_sma_30"] > 0),
         (panel["btc_return_30d"] < 0) & (panel["btc_close_to_sma_30"] < 0)],
        ["risk_on", "risk_off"], default="neutral")
    panel["has_required_trailing_windows"] &= panel[list(REQUIRED_FEATURES)].notna().all(axis=1)
    panel["is_eligible"] = (panel["has_minimum_history"] &
                            panel["has_required_trailing_windows"] &
                            panel["meets_liquidity_threshold"])
    reasons = np.select(
        [~panel["has_minimum_history"], ~panel["has_required_trailing_windows"],
         ~panel["meets_liquidity_threshold"]],
        ["insufficient_history", "incomplete_trailing_windows", "below_liquidity_threshold"],
        default="eligible")
    panel["eligibility_reason"] = reasons
    return panel.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def add_targets(panel):
    """Label decision at t with close(t+h)/close(t)-1 at the exact UTC endpoint."""
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
        result[f"target_percentile_rank_{horizon}d"] = values.groupby(result["timestamp_utc"]).rank(pct=True)
        descending = values.groupby(result["timestamp_utc"]).rank(method="first", ascending=False)
        result[f"target_top_3_{horizon}d"] = descending.le(3).where(eligible_label).astype("boolean")
        result[f"target_top_5_{horizon}d"] = descending.le(5).where(eligible_label).astype("boolean")
    return result


def build_all(bronze_root=BRONZE_ROOT, silver_root=SILVER_ROOT, gold_root=GOLD_ROOT,
              model_root=MODEL_ROOT, provider=PROVIDER_NAME, granularity=DEFAULT_GRANULARITY,
              completed_before_utc=None):
    silver_paths, reports = build_silver(bronze_root, silver_root, provider, granularity)
    gold = build_gold_panel(load_silver(silver_root, provider, granularity), completed_before_utc)
    featured = add_features_and_eligibility(gold)
    labeled = add_targets(featured)
    gold_path = Path(gold_root) / provider / granularity / "research_panel.parquet"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    labeled.to_parquet(gold_path, index=False)
    required_targets = [f"forward_return_relative_to_btc_{horizon}d" for horizon in FORWARD_HORIZONS_DAYS]
    official_mask = (labeled["is_eligible"] & labeled[list(REQUIRED_FEATURES)].notna().all(axis=1)
                     & labeled[required_targets].notna().all(axis=1))
    official = labeled.loc[official_mask].copy()
    official["research_version"] = RESEARCH_VERSION
    official["dataset_created_at_utc"] = datetime.now(timezone.utc)
    model_path = Path(model_root) / "research_panel.parquet"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    official.to_parquet(model_path, index=False)
    manifest = {
        "research_version": RESEARCH_VERSION, "provider": provider,
        "granularity": granularity, "benchmark_product": BENCHMARK_PRODUCT,
        "silver_files": [str(path) for path in silver_paths],
        "gold_path": str(gold_path), "model_path": str(model_path),
        "gold_rows": len(labeled), "official_research_rows": len(official),
        "bronze_validation": [report.as_dict() for report in reports],
        "decision_target_convention": "completed UTC close at t -> exact UTC close at t+h",
    }
    manifest_path = Path(model_root) / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default=PROVIDER_NAME)
    parser.add_argument("--granularity", default=DEFAULT_GRANULARITY, choices=("daily",))
    args = parser.parse_args()
    manifest = build_all(provider=args.provider, granularity=args.granularity)
    print(json.dumps(manifest, indent=2, default=str))


if __name__ == "__main__":
    main()
