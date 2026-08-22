"""V11 Phase 1: development-only independent-signal diagnostics.

Computes the six Phase-0 OHLCV hypotheses, residualizes each signal
cross-sectionally against frozen V8 and exhausted V9 controls, and measures
five-session SPY-relative information coefficients. No signal is selected and
no portfolio is simulated.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import erfc, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from ml.feature_source import (
    feature_dataset_exists,
    get_feature_dataset_path,
    get_feature_root,
)
from ml.v11.discovery_registry import (
    CONTROLS,
    DISCOVERY_RULES,
    FUTURE_HOLDOUT_START_UTC,
    REGISTRY_PATH,
    RESEARCH_VERSION,
    SIGNALS,
    build_registry,
)

PHASE = 1
OUTPUT_ROOT = Path("data/model/v11/phase1")
PANEL_PATH = OUTPUT_ROOT / "signal_panel.parquet"
DAILY_IC_PATH = OUTPUT_ROOT / "daily_orthogonal_ic.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "signal_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_stability.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_stability.csv"
MULTIPLE_TESTING_PATH = OUTPUT_ROOT / "multiple_testing_results.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SIGNAL_IDS = tuple(signal["signal_id"] for signal in SIGNALS)
MIN_ASSETS = int(DISCOVERY_RULES["minimum_cross_sectional_assets"])
HAC_LAG = int(DISCOVERY_RULES["hac_lag_sessions"])
TARGET_HORIZON = 5


def _verify_contract():
    expected = build_registry()
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"Missing frozen V11 Phase-0 registry: {REGISTRY_PATH}"
        )
    actual = json.loads(REGISTRY_PATH.read_text())
    if actual != expected:
        raise RuntimeError("V11 Phase-0 registry differs from frozen contract")
    return actual


def _feature_files():
    root = get_feature_root(project_root=Path("."))
    if not root.is_dir():
        raise FileNotFoundError(f"Feature root does not exist: {root}")
    files = {}
    for symbol_root in sorted(path for path in root.iterdir() if path.is_dir()):
        symbol = symbol_root.name.upper()
        path = get_feature_dataset_path(symbol, project_root=Path("."))
        if feature_dataset_exists(path):
            files[symbol] = path
    if "SPY" not in files:
        raise FileNotFoundError("SPY feature dataset is required")
    return files


def _base_frame(path, symbol):
    source = pd.read_parquet(path).copy()
    timestamp_column = (
        "timestamp_utc" if "timestamp_utc" in source.columns else "timestamp"
    )
    required = {timestamp_column, "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"{symbol}: missing required OHLCV columns {missing}")

    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                source[timestamp_column],
                utc=True,
                errors="coerce",
            ),
            "open": pd.to_numeric(source["open"], errors="coerce"),
            "high": pd.to_numeric(source["high"], errors="coerce"),
            "low": pd.to_numeric(source["low"], errors="coerce"),
            "close": pd.to_numeric(source["close"], errors="coerce"),
            "volume": pd.to_numeric(source["volume"], errors="coerce"),
        }
    )
    frame = (
        frame.dropna(subset=["timestamp_utc"])
        .sort_values("timestamp_utc")
        .drop_duplicates("timestamp_utc", keep="last")
        .reset_index(drop=True)
    )
    frame["symbol"] = symbol
    frame["return_1d"] = frame["close"].pct_change()
    frame["return_5d"] = frame["close"].pct_change(5)
    frame["return_20d"] = frame["close"].pct_change(20)
    frame["forward_return_5d"] = (
        frame["close"].shift(-TARGET_HORIZON) / frame["close"] - 1.0
    )
    frame["volatility_20d"] = frame["return_1d"].rolling(
        20,
        min_periods=20,
    ).std(ddof=0)
    downside = frame["return_1d"].clip(upper=0).rolling(
        20,
        min_periods=20,
    ).std(ddof=0)
    frame["downside_vol_ratio_20"] = downside / frame["volatility_20d"]
    frame["distance_from_low_20d"] = (
        frame["close"]
        / frame["close"].rolling(20, min_periods=20).min()
        - 1.0
    )
    volume_5 = frame["volume"].rolling(5, min_periods=5).mean()
    volume_20 = frame["volume"].rolling(20, min_periods=20).mean()
    frame["volume_trend_5_20"] = volume_5 / volume_20 - 1.0

    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["range_compression_5_20"] = (
        true_range.rolling(5, min_periods=5).mean()
        / true_range.rolling(20, min_periods=20).mean()
        - 1.0
    )
    daily_range = frame["high"] - frame["low"]
    close_location = (
        (2.0 * frame["close"] - frame["low"] - frame["high"])
        / daily_range.replace(0, np.nan)
    )
    frame["close_location_value_20"] = close_location.rolling(
        20,
        min_periods=20,
    ).mean()
    log_volume_change = np.log(frame["volume"].where(frame["volume"] > 0)).diff()
    frame["volume_return_correlation_20"] = frame["return_1d"].rolling(
        20,
        min_periods=20,
    ).corr(log_volume_change)
    return frame


def _rolling_beta(stock_return, spy_return, mask=None, window=60, minimum=20):
    stock = stock_return.where(mask) if mask is not None else stock_return
    market = spy_return.where(mask) if mask is not None else spy_return
    covariance = stock.rolling(window, min_periods=minimum).cov(market)
    variance = market.rolling(window, min_periods=minimum).var()
    return covariance / variance.replace(0, np.nan)


def _symbol_panel(stock, spy):
    spy_columns = spy[
        [
            "timestamp_utc",
            "close",
            "return_1d",
            "return_5d",
            "return_20d",
            "forward_return_5d",
            "volatility_20d",
        ]
    ].rename(
        columns={
            "close": "spy_close",
            "return_1d": "spy_return_1d",
            "return_5d": "spy_return_5d",
            "return_20d": "spy_return_20d",
            "forward_return_5d": "spy_forward_return_5d",
            "volatility_20d": "spy_volatility_20d",
        }
    )
    frame = stock.merge(
        spy_columns,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )
    frame["beta_60"] = _rolling_beta(
        frame["return_1d"],
        frame["spy_return_1d"],
        window=60,
        minimum=40,
    )
    down_mask = frame["spy_return_1d"] < 0
    up_mask = frame["spy_return_1d"] >= 0
    downside_beta = _rolling_beta(
        frame["return_1d"],
        frame["spy_return_1d"],
        mask=down_mask,
        window=60,
        minimum=15,
    )
    upside_beta = _rolling_beta(
        frame["return_1d"],
        frame["spy_return_1d"],
        mask=up_mask,
        window=60,
        minimum=15,
    )
    frame["downside_beta_asymmetry_60"] = downside_beta - upside_beta
    frame["idiosyncratic_momentum_20"] = (
        frame["return_20d"] - frame["beta_60"] * frame["spy_return_20d"]
    )
    frame["idiosyncratic_reversal_5"] = -1.0 * (
        frame["return_5d"] - frame["beta_60"] * frame["spy_return_5d"]
    )
    frame["forward_relative_return_5d"] = (
        frame["forward_return_5d"] - frame["spy_forward_return_5d"]
    )
    return frame


def build_panel():
    files = _feature_files()
    base = {
        symbol: _base_frame(path, symbol)
        for symbol, path in files.items()
    }
    spy = base["SPY"]
    frames = [
        _symbol_panel(frame, spy)
        for symbol, frame in base.items()
        if symbol != "SPY"
    ]
    panel = pd.concat(frames, ignore_index=True)
    panel = panel[
        panel["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC
    ].copy()
    if panel.empty:
        raise RuntimeError("V11 development panel is empty")
    if panel["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("V11 panel reaches the future holdout boundary")
    return panel


def _residualize(values, controls):
    frame = pd.concat(
        [pd.Series(values, name="signal"), controls],
        axis=1,
    ).replace([np.inf, -np.inf], np.nan).dropna()
    output = pd.Series(np.nan, index=pd.Series(values).index, dtype=float)
    if len(frame) < MIN_ASSETS:
        return output
    matrix = frame[list(controls.columns)].to_numpy(float)
    matrix = np.column_stack([np.ones(len(matrix)), matrix])
    coefficients, *_ = np.linalg.lstsq(
        matrix,
        frame["signal"].to_numpy(float),
        rcond=None,
    )
    output.loc[frame.index] = (
        frame["signal"].to_numpy(float) - matrix @ coefficients
    )
    return output


def build_daily_ic(panel):
    rows = []
    for timestamp, day in panel.groupby("timestamp_utc", sort=True):
        controls = day[list(CONTROLS)]
        target = day["forward_relative_return_5d"]
        for signal_id in SIGNAL_IDS:
            residual = _residualize(day[signal_id], controls)
            valid = pd.DataFrame(
                {
                    "signal": residual,
                    "target": target,
                }
            ).replace([np.inf, -np.inf], np.nan).dropna()
            ic = (
                float(valid["signal"].corr(valid["target"], method="spearman"))
                if len(valid) >= MIN_ASSETS
                and valid["signal"].nunique() > 1
                and valid["target"].nunique() > 1
                else np.nan
            )
            rows.append(
                {
                    "timestamp_utc": timestamp,
                    "signal_id": signal_id,
                    "asset_count": int(len(valid)),
                    "orthogonal_ic": ic,
                }
            )
    return pd.DataFrame(rows)


def _hac_stats(series):
    values = (
        pd.Series(series, dtype=float)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy(float)
    )
    count = len(values)
    if count < max(30, HAC_LAG + 2):
        return {
            "days": count,
            "mean": np.nan,
            "hac_se": np.nan,
            "hac_t": np.nan,
            "p_value": np.nan,
        }
    mean = float(values.mean())
    errors = values - mean
    long_run_variance = float(np.dot(errors, errors) / count)
    maximum_lag = min(HAC_LAG, count - 1)
    for lag in range(1, maximum_lag + 1):
        weight = 1.0 - lag / (maximum_lag + 1.0)
        covariance = float(
            np.dot(errors[lag:], errors[:-lag]) / count
        )
        long_run_variance += 2.0 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    standard_error = sqrt(long_run_variance / count)
    statistic = mean / standard_error if standard_error > 0 else np.nan
    p_value = (
        erfc(abs(statistic) / sqrt(2.0))
        if np.isfinite(statistic)
        else np.nan
    )
    return {
        "days": count,
        "mean": mean,
        "hac_se": standard_error,
        "hac_t": statistic,
        "p_value": p_value,
    }


def _benjamini_hochberg(p_values):
    values = pd.Series(p_values, dtype=float)
    valid = values.dropna().sort_values()
    adjusted = pd.Series(np.nan, index=values.index, dtype=float)
    if valid.empty:
        return adjusted
    count = len(valid)
    raw = pd.Series(
        [
            min(1.0, value * count / rank)
            for rank, value in enumerate(valid, start=1)
        ],
        index=valid.index,
        dtype=float,
    )
    monotone = raw.iloc[::-1].cummin().iloc[::-1]
    adjusted.loc[monotone.index] = monotone
    return adjusted


def build_summary(daily):
    rows = []
    for signal_id, group in daily.groupby("signal_id", sort=True):
        values = group["orthogonal_ic"].dropna()
        hac = _hac_stats(values)
        rows.append(
            {
                "signal_id": signal_id,
                "days": int(len(values)),
                "mean_orthogonal_ic": float(values.mean()) if len(values) else np.nan,
                "median_orthogonal_ic": float(values.median()) if len(values) else np.nan,
                "ic_hit_rate": float((values > 0).mean()) if len(values) else np.nan,
                "ic_std": float(values.std(ddof=0)) if len(values) else np.nan,
                "hac_lag": HAC_LAG,
                "hac_se": hac["hac_se"],
                "hac_t": hac["hac_t"],
                "raw_p_value": hac["p_value"],
            }
        )
    summary = pd.DataFrame(rows)
    summary["fdr_q_value"] = _benjamini_hochberg(
        summary["raw_p_value"]
    )
    summary["passes_discovery_threshold"] = (
        (summary["mean_orthogonal_ic"] > 0)
        & (summary["fdr_q_value"] <= 0.10)
    )
    return summary.sort_values(
        ["passes_discovery_threshold", "mean_orthogonal_ic"],
        ascending=[False, False],
    ).reset_index(drop=True)


def build_year_stability(daily):
    frame = daily.copy()
    frame["year"] = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    ).dt.year
    return (
        frame.groupby(["signal_id", "year"], observed=True)
        .agg(
            days=("orthogonal_ic", "count"),
            mean_orthogonal_ic=("orthogonal_ic", "mean"),
            median_orthogonal_ic=("orthogonal_ic", "median"),
            ic_hit_rate=(
                "orthogonal_ic",
                lambda values: values.dropna().gt(0).mean()
                if values.notna().any()
                else np.nan,
            ),
        )
        .reset_index()
    )


def build_regime_stability(daily, panel):
    regime = (
        panel[
            [
                "timestamp_utc",
                "spy_close",
                "spy_return_20d",
                "spy_volatility_20d",
            ]
        ]
        .drop_duplicates("timestamp_utc")
        .sort_values("timestamp_utc")
    )
    regime["spy_sma200"] = regime["spy_close"].rolling(
        200,
        min_periods=200,
    ).mean()
    regime["trend_regime"] = np.where(
        regime["spy_close"] >= regime["spy_sma200"],
        "SPY_ABOVE_SMA200",
        "SPY_BELOW_SMA200",
    )
    median_volatility = float(regime["spy_volatility_20d"].median())
    regime["volatility_regime"] = np.where(
        regime["spy_volatility_20d"] >= median_volatility,
        "HIGH_SPY_VOLATILITY",
        "LOW_SPY_VOLATILITY",
    )
    merged = daily.merge(regime, on="timestamp_utc", how="left")
    rows = []
    for column in ("trend_regime", "volatility_regime"):
        for (signal_id, label), group in merged.groupby(
            ["signal_id", column],
            sort=True,
        ):
            values = group["orthogonal_ic"].dropna()
            rows.append(
                {
                    "signal_id": signal_id,
                    "regime_type": column,
                    "regime": label,
                    "days": int(len(values)),
                    "mean_orthogonal_ic": float(values.mean())
                    if len(values)
                    else np.nan,
                    "median_orthogonal_ic": float(values.median())
                    if len(values)
                    else np.nan,
                    "ic_hit_rate": float((values > 0).mean())
                    if len(values)
                    else np.nan,
                }
            )
    return pd.DataFrame(rows)


def main():
    contract = _verify_contract()
    panel = build_panel()
    daily = build_daily_ic(panel)
    summary = build_summary(daily)
    years = build_year_stability(daily)
    regimes = build_regime_stability(daily, panel)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(PANEL_PATH, index=False)
    daily.to_parquet(DAILY_IC_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    summary[
        [
            "signal_id",
            "raw_p_value",
            "fdr_q_value",
            "passes_discovery_threshold",
        ]
    ].to_csv(MULTIPLE_TESTING_PATH, index=False)

    passing = summary[summary["passes_discovery_threshold"]]
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "development_only_orthogonal_signal_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase0_contract_sha256": contract["contract_sha256"],
        "signal_count": len(SIGNAL_IDS),
        "panel_rows": int(len(panel)),
        "candidate_count": int(panel["symbol"].nunique()),
        "date_start_utc": panel["timestamp_utc"].min().isoformat(),
        "date_end_utc": panel["timestamp_utc"].max().isoformat(),
        "signals_passing_discovery_threshold": passing[
            "signal_id"
        ].tolist(),
        "passing_signal_count": int(len(passing)),
        "signal_selected": False,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "model_fitted": False,
        "portfolio_simulated": False,
        "candidate_frozen": False,
        "candidate_promoted": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "v9_results_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )

    print("STOCK V11 PHASE 1: INDEPENDENT SIGNAL DIAGNOSTICS")
    print("=" * 104)
    print(
        f"Panel: {manifest['panel_rows']:,} rows | "
        f"{manifest['candidate_count']} stocks"
    )
    print(
        f"Dates: {manifest['date_start_utc']} -> "
        f"{manifest['date_end_utc']}"
    )
    print(summary.to_string(index=False))
    print(
        "Signals passing predeclared discovery threshold: "
        + (
            ", ".join(manifest["signals_passing_discovery_threshold"])
            if manifest["passing_signal_count"]
            else "NONE"
        )
    )
    print(
        "No signal selection, fitting, portfolio simulation, holdout scoring, "
        "production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
