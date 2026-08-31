"""Isolated historical five-minute input backfill for V13 development.

The backfill uses the existing V11 101-symbol collector but publishes under a
V13 development-only root.  It never replaces V11's current manifest and never
touches a fresh-evidence journal, activation artifact, or brokerage surface.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from ml.v11.intraday_backfill import (
    TiingoHistoricalIntradayClient,
    run_backfill,
)
from ml.v13.regime_overlay_reconstruction import (
    DEVELOPMENT_END_DATE,
    ROOT,
    TIINGO_IEX_INTRADAY_START_DATE,
)


OUTPUT_ROOT = ROOT / "data/research/v13/development/intraday_backfills"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-days", type=int, default=900)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.chunk_days < 1:
        raise SystemExit("--chunk-days must be at least 1")
    if args.timeout_seconds < 30:
        raise SystemExit("--timeout-seconds must be at least 30")

    print("V13 RETROSPECTIVE FIVE-MINUTE DEVELOPMENT BACKFILL")
    print("=" * 84)
    print("Requested counterfactual start: 2016-08-29")
    print("Tiingo IEX five-minute availability: August 2017")
    print(
        "Fetching exact available window: "
        f"{TIINGO_IEX_INTRADAY_START_DATE} -> {DEVELOPMENT_END_DATE}"
    )
    result = run_backfill(
        start_date=TIINGO_IEX_INTRADAY_START_DATE,
        end_date=DEVELOPMENT_END_DATE,
        client=TiingoHistoricalIntradayClient(
            timeout_seconds=args.timeout_seconds
        ),
        output_root=OUTPUT_ROOT,
        chunk_days=args.chunk_days,
        workers=args.workers,
        progress=True,
    )
    print(f"Status: {result['status']}")
    print(f"Published: {result['published']}")
    print(
        f"Symbols ready: "
        f"{result.get('symbol_count', result.get('symbols_ready'))}/101"
    )
    if result.get("common_session_count") is not None:
        print(f"Common sessions: {result['common_session_count']}")
        print(
            f"Actual complete-universe window: "
            f"{result['first_common_session']} -> {result['last_common_session']}"
        )
        print(f"Manifest SHA-256: {result['manifest_sha256']}")
    for failure in result.get("failures", [])[:20]:
        print(f" - {failure}")
    print("V11 current historical manifest modified: NO")
    print("Fresh evidence modified: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if not result["published"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
