"""Keep the Stock V5 data layers current without model fitting.

Each invocation advances Bronze data toward the newest completed Tiingo EOD
session within the configured hourly request budget. If all 101 V5 data symbols
are current, Silver, Gold, and feature datasets are rebuilt only when they are
behind the completed EOD target.

This module does not fit models, tune parameters, build research targets, place
orders, or evaluate the future holdout.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"
sys.path.insert(0, str(DATA_INGESTION))

from tiingo_v5_incremental import DEFAULT_MAX_REQUESTS, run_incremental_refresh  # noqa: E402
from v5_symbols import get_v5_data_symbols  # noqa: E402


def feature_path(symbol):
    return PROJECT_ROOT / f"data/features/stocks/{symbol}/{symbol}_features.parquet"


def feature_latest_timestamp_ms(symbol):
    path = feature_path(symbol)
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_parquet(path, columns=["timestamp_utc"])
    if frame.empty:
        return None
    values = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
    if values.empty:
        return None
    return int(values.max().timestamp() * 1000)


def stale_feature_symbols(target_timestamp):
    out = []
    for symbol in get_v5_data_symbols():
        latest = feature_latest_timestamp_ms(symbol)
        if latest is None or latest < target_timestamp:
            out.append(symbol)
    return out


def run_command(args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DATA_INGESTION)
    print("$ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=PROJECT_ROOT, env=env, check=True)


def rebuild_data_layers():
    python = sys.executable
    run_command([python, "-u", "data-ingestion/silver_pipeline.py"])
    run_command([python, "-u", "data-ingestion/gold_pipeline.py"])
    run_command([python, "-u", "data-ingestion/feature_pipeline.py"])


def run_data_refresh(max_requests=DEFAULT_MAX_REQUESTS):
    state = run_incremental_refresh(max_requests=max_requests)

    print("V5 DATA REFRESH")
    print(f"Target EOD session: {state['target_date_utc']}")
    print(f"Tiingo requests used: {state['requests_used']}/{state['max_requests']}")
    print(f"Bronze complete: {state['complete']}")

    if not state["complete"]:
        print(
            "Bronze universe is still catching up within the hourly Tiingo quota; "
            "downstream layers are intentionally deferred until every symbol is current."
        )
        return "bronze_partial"

    stale = stale_feature_symbols(state["target_timestamp_ms"])
    if stale:
        print(f"Features behind target for {len(stale)} symbol(s); rebuilding data layers.")
        rebuild_data_layers()
        stale = stale_feature_symbols(state["target_timestamp_ms"])
        if stale:
            raise RuntimeError(
                "Feature refresh did not reach target for: " + ", ".join(stale)
            )
        return "rebuilt"

    print("Features already match the latest completed EOD session.")
    return "current"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help="Total Tiingo request budget for this hourly run.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    run_data_refresh(max_requests=args.max_requests)


if __name__ == "__main__":
    main()
