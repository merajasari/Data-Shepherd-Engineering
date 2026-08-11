"""Build the V5 multi-horizon, SPY-relative research panel.

This prepares targets and cross-sectional labels only.  It does not train a
model, run a backtest, write V4 artifacts, or touch paper-trading state.
"""

import argparse
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
    return pd.read_parquet(feature_path(symbol), columns=columns).sort_values(
        "timestamp_utc"
    )


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

    benchmark = load_prices_and_features(V5_BENCHMARK_SYMBOL)[
        ["timestamp_utc", "close"]
    ].rename(columns={"close": "spy_close"})

    for horizon in FORWARD_HORIZONS:
        benchmark[f"forward_spy_return_{horizon}d"] = (
            benchmark["spy_close"].shift(-horizon) / benchmark["spy_close"] - 1
        )

    frames = []
    for symbol in available:
        frame = load_prices_and_features(symbol)
        frame.insert(0, "symbol", symbol)
        frame.insert(1, "sector", get_v5_sector(symbol))

        for horizon in FORWARD_HORIZONS:
            frame[f"forward_stock_return_{horizon}d"] = (
                frame["close"].shift(-horizon) / frame["close"] - 1
            )

        frame = frame.merge(benchmark, on="timestamp_utc", how="inner")
        for horizon in FORWARD_HORIZONS:
            frame[f"forward_relative_return_{horizon}d"] = (
                frame[f"forward_stock_return_{horizon}d"]
                - frame[f"forward_spy_return_{horizon}d"]
            )
        frames.append(frame)

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
    print(f"V5 research rows: {len(panel):,}")
    print(f"V5 research panel written: {RESEARCH_PANEL_PATH}")


if __name__ == "__main__":
    main()
