"""Quota-aware EOD refresh for the 250-stock successor data universe.

This workflow advances 250 investable stocks plus benchmark-only SPY using the
same rolling Tiingo request ledger as the legacy V8 refresh path.

It may update market-data layers and the shared Spark feature universe, but it
does not invoke V8 or V10 inference, holdout runners, confirmation cycles,
model fitting, model scoring, candidate freezing, or brokerage orders.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"

if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

from feature_source import get_feature_backend  # noqa: E402
from ml.run_v5_data_refresh import (  # noqa: E402
    REQUEST_LEDGER_PATH,
    QuotaTrackingTiingoClient,
    available_request_budget,
    configured_hourly_request_limit,
    prune_request_ledger,
)
from tiingo_stock250_incremental import (  # noqa: E402
    DATA_SYMBOL_COUNT,
    INVESTABLE_CANDIDATE_COUNT,
    run_incremental_refresh,
)
from silver_pipeline import process_stock as process_silver_stock  # noqa: E402
from gold_pipeline import process_stock as process_gold_stock  # noqa: E402


DEFAULT_HOURLY_REQUEST_LIMIT = 45


def run_command(args: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DATA_INGESTION)

    print(
        "$ " + " ".join(args),
        flush=True,
    )

    subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


def propagate_price_layers(symbols) -> None:
    """Advance Silver and Gold only for symbols changed in Bronze."""

    ordered = list(
        dict.fromkeys(
            symbols or []
        )
    )

    if not ordered:
        return

    print(
        "Propagating "
        f"{len(ordered)} refreshed symbol(s) "
        "into Silver/Gold."
    )

    for symbol in ordered:
        bronze_dir = (
            PROJECT_ROOT
            / "data/bronze/stocks"
            / symbol
        )

        silver_dir = (
            PROJECT_ROOT
            / "data/silver/stocks"
            / symbol
        )

        process_silver_stock(
            bronze_dir
        )

        process_gold_stock(
            silver_dir
        )


def rebuild_and_validate_spark_features() -> None:
    """Atomically rebuild the shared Spark features and validate all outputs."""

    if get_feature_backend() != "spark":
        raise RuntimeError(
            "Stock-250 successor refresh currently requires "
            "FEATURE_BACKEND=spark"
        )

    python = sys.executable

    run_command(
        [
            python,
            "-u",
            "data-ingestion/feature_pipeline.py",
        ]
    )

    run_command(
        [
            python,
            "-u",
            "data-ingestion/"
            "validate_spark_feature_outputs.py",
        ]
    )


def run_stock250_refresh(
    hourly_request_limit: int = DEFAULT_HOURLY_REQUEST_LIMIT,
    max_requests: int | None = None,
    ledger_path: Path = REQUEST_LEDGER_PATH,
    client=None,
) -> str:
    """Advance the Stock-250 data universe without invoking any model."""

    available, used = available_request_budget(
        hourly_limit=hourly_request_limit,
        path=ledger_path,
    )

    if max_requests is not None:
        if max_requests < 1:
            raise ValueError(
                "max_requests must be at least 1 when provided"
            )

        available = min(
            available,
            max_requests,
        )

    print(
        "STOCK-250 DATA REFRESH"
    )

    print(
        "Investable candidates: "
        f"{INVESTABLE_CANDIDATE_COUNT}"
    )

    print(
        "Data symbols: "
        f"{DATA_SYMBOL_COUNT}"
    )

    print(
        "Rolling 60m Tiingo usage before run: "
        f"{used}/{hourly_request_limit}"
    )

    print(
        "Available request budget now: "
        f"{available}"
    )

    if available < 1:
        prune_request_ledger(
            path=ledger_path
        )

        print(
            "No Tiingo REST budget available. "
            "No data or model state changed."
        )

        return "quota_wait"

    tracked_client = QuotaTrackingTiingoClient(
        client=client,
        ledger_path=ledger_path,
    )

    state = run_incremental_refresh(
        max_requests=available,
        client=tracked_client,
    )

    prune_request_ledger(
        path=ledger_path
    )

    print(
        "Target EOD session: "
        f"{state['target_date_utc']}"
    )

    print(
        "Tiingo requests used this run: "
        f"{state['requests_used']}"
    )

    print(
        "Bronze universe complete: "
        f"{state['complete']}"
    )

    propagate_price_layers(
        state.get(
            "updated_symbols",
            [],
        )
    )

    if not state["complete"]:
        print(
            "Stock-250 Bronze catch-up is partial. "
            "Spark rebuild deferred until all 251 symbols "
            "reach one common target session."
        )

        print(
            "V8 modified: NO"
        )

        print(
            "V10 modified: NO"
        )

        print(
            "Brokerage orders: OFF"
        )

        return "bronze_partial"

    rebuild_and_validate_spark_features()

    print(
        "Stock-250 Bronze/Silver/Gold/Spark "
        "refresh completed."
    )

    print(
        "V8 modified: NO"
    )

    print(
        "V10 modified: NO"
    )

    print(
        "Holdout evidence modified: NO"
    )

    print(
        "Brokerage orders: OFF"
    )

    return "rebuilt"


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--hourly-request-limit",
        type=int,
        default=configured_hourly_request_limit(),
    )

    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
    )

    return parser.parse_args()


def main():
    args = parse_args()

    run_stock250_refresh(
        hourly_request_limit=
            args.hourly_request_limit,
        max_requests=args.max_requests,
    )


if __name__ == "__main__":
    main()
