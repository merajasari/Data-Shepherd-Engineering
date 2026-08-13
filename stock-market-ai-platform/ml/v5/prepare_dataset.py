"""Build the V5 multi-horizon, SPY-relative research panel.

This module prepares a point-in-time cross-sectional dataset only. It does not
train a model, run a backtest, write V4 artifacts, or touch paper-trading state.
SPY remains benchmark context and is never part of the investable candidate
cross-section.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "data-ingestion"))

from v5_symbols import (  # noqa: E402
    V5_BENCHMARK_SYMBOL,
    V5_SYMBOLS,
    get_v5_sector,
)

from ml.v5.config import (  # noqa: E402
    FORWARD_HORIZONS,
    RESEARCH_PANEL_PATH,
    V5_FEATURE_COLUMNS,
)


MANIFEST_PATH = RESEARCH_PANEL_PATH.with_name("research_panel_manifest.json")


def feature_path(symbol):
    return Path(
        f"data/features/stocks/{symbol}/{symbol}_features.parquet"
    )


def available_symbols():
    return [symbol for symbol in V5_SYMBOLS if feature_path(symbol).exists()]


def print_availability():
    available = available_symbols()
    missing = [symbol for symbol in V5_SYMBOLS if symbol not in available]
    benchmark_available = feature_path(V5_BENCHMARK_SYMBOL).exists()

    print(f"V5 candidates configured: {len(V5_SYMBOLS)}")
    print(f"Candidate feature datasets available: {len(available)}")
    print(f"Candidate feature datasets missing: {len(missing)}")
    print(f"SPY feature dataset available: {benchmark_available}")
    if missing:
        print("Missing: " + ", ".join(missing))

    return available, benchmark_available


def load_prices_and_features(symbol):
    columns = [
        "timestamp_utc",
        "close",
        *V5_FEATURE_COLUMNS,
    ]
    frame = pd.read_parquet(feature_path(symbol), columns=columns).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError(f"Duplicate timestamps in {symbol} feature history")
    return frame


def add_forward_returns(frame, prefix, horizons=FORWARD_HORIZONS):
    """Add exact row-horizon returns and their endpoint timestamps."""
    result = frame.copy()
    for horizon in horizons:
        result[f"target_endpoint_utc_{horizon}d"] = result[
            "timestamp_utc"
        ].shift(-horizon)
        result[f"forward_{prefix}_return_{horizon}d"] = (
            result["close"].shift(-horizon) / result["close"] - 1
        )
    return result


def build_benchmark_frame():
    benchmark = load_prices_and_features(V5_BENCHMARK_SYMBOL)[
        ["timestamp_utc", "close"]
    ].rename(columns={"close": "spy_close"})

    tmp = benchmark.rename(columns={"spy_close": "close"})
    tmp = add_forward_returns(tmp, "spy")
    benchmark = tmp.rename(columns={"close": "spy_close"})

    for horizon in FORWARD_HORIZONS:
        benchmark = benchmark.rename(
            columns={
                f"target_endpoint_utc_{horizon}d":
                    f"spy_target_endpoint_utc_{horizon}d"
            }
        )
    return benchmark


def build_candidate_frame(symbol, benchmark):
    frame = load_prices_and_features(symbol)
    frame.insert(0, "symbol", symbol)
    frame.insert(1, "sector", get_v5_sector(symbol))
    frame["candidate_history_rows"] = range(1, len(frame) + 1)
    frame["feature_complete"] = frame[list(V5_FEATURE_COLUMNS)].notna().all(axis=1)

    frame = add_forward_returns(frame, "stock")
    frame = frame.merge(benchmark, on="timestamp_utc", how="inner", validate="one_to_one")

    for horizon in FORWARD_HORIZONS:
        stock_endpoint = f"target_endpoint_utc_{horizon}d"
        spy_endpoint = f"spy_target_endpoint_utc_{horizon}d"
        stock_return = f"forward_stock_return_{horizon}d"
        spy_return = f"forward_spy_return_{horizon}d"
        relative = f"forward_relative_return_{horizon}d"

        endpoint_matches = frame[stock_endpoint].eq(frame[spy_endpoint])
        labeled = (
            endpoint_matches
            & frame[stock_return].notna()
            & frame[spy_return].notna()
        )
        frame[f"endpoint_matches_spy_{horizon}d"] = endpoint_matches
        frame[f"is_labeled_{horizon}d"] = labeled
        frame[relative] = (frame[stock_return] - frame[spy_return]).where(labeled)

    return frame


def validate_panel(panel, expected_symbols=None):
    expected_symbols = tuple(expected_symbols or V5_SYMBOLS)
    problems = []

    if V5_BENCHMARK_SYMBOL in set(panel["symbol"]):
        problems.append("SPY appears in the investable candidate panel")

    actual_symbols = set(panel["symbol"])
    missing = sorted(set(expected_symbols) - actual_symbols)
    unexpected = sorted(actual_symbols - set(expected_symbols))
    if missing:
        problems.append("Missing candidate symbols: " + ", ".join(missing))
    if unexpected:
        problems.append("Unexpected candidate symbols: " + ", ".join(unexpected))

    duplicate_keys = int(panel.duplicated(["timestamp_utc", "symbol"]).sum())
    if duplicate_keys:
        problems.append(f"Duplicate timestamp/symbol rows: {duplicate_keys}")

    if not panel["timestamp_utc"].is_monotonic_increasing:
        problems.append("Panel is not globally sorted by timestamp_utc")

    for horizon in FORWARD_HORIZONS:
        relative = f"forward_relative_return_{horizon}d"
        labeled = f"is_labeled_{horizon}d"
        mismatch = panel[labeled] & panel[relative].isna()
        if mismatch.any():
            problems.append(
                f"{horizon}d labeled rows with missing relative return: "
                f"{int(mismatch.sum())}"
            )

    if problems:
        raise ValueError("V5 panel validation failed:\n- " + "\n- ".join(problems))


def build_manifest(panel):
    daily_counts = panel.groupby("timestamp_utc")["symbol"].nunique()
    per_symbol = (
        panel.groupby("symbol")
        .agg(
            rows=("timestamp_utc", "size"),
            start_utc=("timestamp_utc", "min"),
            end_utc=("timestamp_utc", "max"),
            feature_complete_rows=("feature_complete", "sum"),
        )
        .reset_index()
        .sort_values("symbol")
    )

    manifest = {
        "research_version": "v5",
        "stage": "point_in_time_cross_sectional_research_panel",
        "candidate_count": int(panel["symbol"].nunique()),
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "benchmark_is_investable": False,
        "row_count": int(len(panel)),
        "date_range": {
            "start_utc": panel["timestamp_utc"].min().isoformat(),
            "end_utc": panel["timestamp_utc"].max().isoformat(),
        },
        "daily_candidate_count": {
            "minimum": int(daily_counts.min()),
            "median": float(daily_counts.median()),
            "maximum": int(daily_counts.max()),
        },
        "horizons_days": list(FORWARD_HORIZONS),
        "target_policy": (
            "forward stock return minus forward SPY return over the same exact "
            "trading-session endpoint; mismatched or unavailable endpoints remain missing"
        ),
        "feature_policy": (
            "feature_complete is true only when every registered V5 predictive feature "
            "is observed at the decision timestamp; rows are retained for auditability"
        ),
        "short_history_policy": (
            "newer/shorter listings remain in the panel only from their first observed "
            "timestamp; no backfill or synthetic pre-listing history is created"
        ),
        "symbols": [
            {
                "symbol": row.symbol,
                "rows": int(row.rows),
                "start_utc": row.start_utc.isoformat(),
                "end_utc": row.end_utc.isoformat(),
                "feature_complete_rows": int(row.feature_complete_rows),
            }
            for row in per_symbol.itertuples(index=False)
        ],
    }

    for horizon in FORWARD_HORIZONS:
        manifest[f"labeled_rows_{horizon}d"] = int(
            panel[f"is_labeled_{horizon}d"].sum()
        )
    return manifest


def build_panel(allow_partial=False):
    available, benchmark_available = print_availability()
    if not benchmark_available:
        raise FileNotFoundError("SPY features are required for relative targets")
    if not available:
        raise FileNotFoundError("No V5 candidate feature datasets are available")
    if len(available) != len(V5_SYMBOLS) and not allow_partial:
        raise RuntimeError(
            "Refusing to build a partial-universe V5 panel: "
            f"{len(available)}/{len(V5_SYMBOLS)} candidates are available. "
            "Populate the missing histories or pass --allow-partial only for "
            "pipeline development, never for a scored experiment."
        )

    benchmark = build_benchmark_frame()
    frames = [build_candidate_frame(symbol, benchmark) for symbol in available]

    panel = pd.concat(frames, ignore_index=True)
    panel = panel.sort_values(["timestamp_utc", "symbol"]).reset_index(drop=True)

    for horizon in FORWARD_HORIZONS:
        target = f"forward_relative_return_{horizon}d"
        panel[f"target_rank_{horizon}d"] = panel.groupby("timestamp_utc")[
            target
        ].rank(method="average", pct=True, ascending=True)
        panel[f"eligible_count_{horizon}d"] = panel.groupby("timestamp_utc")[
            target
        ].transform("count")

    validate_panel(panel, expected_symbols=available)
    return panel


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Report local data coverage without writing a dataset.",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow an incomplete panel for plumbing development only.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.validate_only:
        print_availability()
        return

    panel = build_panel(allow_partial=args.allow_partial)
    RESEARCH_PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(RESEARCH_PANEL_PATH, index=False)

    manifest = build_manifest(panel)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"V5 research rows: {len(panel):,}")
    print(f"V5 candidate symbols: {panel['symbol'].nunique()}")
    print(
        "V5 date range: "
        f"{panel['timestamp_utc'].min()} -> {panel['timestamp_utc'].max()}"
    )
    for horizon in FORWARD_HORIZONS:
        print(
            f"{horizon}d labeled rows: "
            f"{int(panel[f'is_labeled_{horizon}d'].sum()):,}"
        )
    print(f"V5 research panel written: {RESEARCH_PANEL_PATH}")
    print(f"V5 manifest written: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
