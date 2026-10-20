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

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"

if str(DATA_INGESTION) not in sys.path:
    sys.path.insert(0, str(DATA_INGESTION))

from feature_source import (  # noqa: E402
    feature_dataset_exists,
    get_feature_backend,
    get_feature_dataset_path,
)
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
    contracted_symbols,
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


def _latest_numeric_timestamp(
    path: Path,
    *,
    parquet: bool,
) -> int | None:
    if not path.exists() or path.stat().st_size == 0:
        return None

    if parquet:
        frame = pd.read_parquet(
            path,
            columns=["timestamp"],
        )
    else:
        frame = pd.read_csv(
            path,
            usecols=["timestamp"],
        )

    values = pd.to_numeric(
        frame["timestamp"],
        errors="coerce",
    ).dropna()

    if values.empty:
        return None

    return int(values.max())


def validate_price_layers(
    symbols,
    expected_timestamp_ms: int | None = None,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Require Bronze, Silver and Gold to agree for every requested symbol."""

    failures = []

    for symbol in list(
        dict.fromkeys(
            symbols or []
        )
    ):
        bronze = (
            project_root
            / "data/bronze/stocks"
            / symbol
            / f"{symbol}_prices.csv"
        )

        silver = (
            project_root
            / "data/silver/stocks"
            / symbol
            / f"{symbol}_prices.parquet"
        )

        gold = (
            project_root
            / "data/gold/stocks"
            / symbol
            / f"{symbol}_prices.parquet"
        )

        try:
            bronze_latest = _latest_numeric_timestamp(
                bronze,
                parquet=False,
            )

            silver_latest = _latest_numeric_timestamp(
                silver,
                parquet=True,
            )

            gold_latest = _latest_numeric_timestamp(
                gold,
                parquet=True,
            )

        except Exception as exc:
            failures.append(
                f"{symbol}: read error: {exc}"
            )
            continue

        if (
            bronze_latest is None
            or silver_latest is None
            or gold_latest is None
        ):
            failures.append(
                f"{symbol}: missing/empty layer "
                f"bronze={bronze_latest} "
                f"silver={silver_latest} "
                f"gold={gold_latest}"
            )
            continue

        if not (
            bronze_latest
            == silver_latest
            == gold_latest
        ):
            failures.append(
                f"{symbol}: layer mismatch "
                f"bronze={bronze_latest} "
                f"silver={silver_latest} "
                f"gold={gold_latest}"
            )
            continue

        if (
            expected_timestamp_ms is not None
            and bronze_latest < expected_timestamp_ms
        ):
            failures.append(
                f"{symbol}: latest={bronze_latest} "
                f"target={expected_timestamp_ms}"
            )

    if failures:
        raise RuntimeError(
            "Stock-250 price-layer validation failed: "
            + "; ".join(failures)
        )

    print(
        "Price-layer validation passed for "
        f"{len(list(dict.fromkeys(symbols or [])))} symbol(s)."
    )


def validate_spark_feature_freshness(
    target_timestamp_ms: int,
    project_root: Path = PROJECT_ROOT,
) -> None:
    """Require all 251 Spark feature datasets to reach the target session."""

    failures = []

    for symbol in contracted_symbols():
        path = get_feature_dataset_path(
            symbol,
            project_root=project_root,
        )

        if not feature_dataset_exists(path):
            failures.append(
                f"{symbol}: feature dataset missing"
            )
            continue

        try:
            frame = pd.read_parquet(
                path,
                columns=["timestamp_utc"],
            )

            values = pd.to_datetime(
                frame["timestamp_utc"],
                utc=True,
                errors="coerce",
            ).dropna()

            if values.empty:
                failures.append(
                    f"{symbol}: no valid feature timestamp"
                )
                continue

            latest_ms = int(
                values.max().timestamp() * 1000
            )

            if latest_ms < target_timestamp_ms:
                failures.append(
                    f"{symbol}: latest={latest_ms} "
                    f"target={target_timestamp_ms}"
                )

        except Exception as exc:
            failures.append(
                f"{symbol}: feature read error: {exc}"
            )

    if failures:
        raise RuntimeError(
            "Stock-250 Spark freshness validation failed: "
            + "; ".join(failures)
        )

    print(
        "Spark freshness validation passed: "
        "251/251 data symbols at target."
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


def rebuild_and_validate_spark_features(
    target_timestamp_ms: int,
) -> None:
    """Atomically rebuild and prove freshness of all Spark outputs."""

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

    validate_spark_feature_freshness(
        target_timestamp_ms,
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

    updated_symbols = state.get(
        "updated_symbols",
        [],
    )

    propagate_price_layers(
        updated_symbols
    )

    validate_price_layers(
        updated_symbols
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

    validate_price_layers(
        contracted_symbols(),
        expected_timestamp_ms=
            state["target_timestamp_ms"],
    )

    rebuild_and_validate_spark_features(
        state["target_timestamp_ms"],
    )

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
