"""Isolated historical five-minute input backfill for V13 development.

The backfill uses the existing V11 101-symbol collector but publishes under a
V13 development-only root.  It never replaces V11's current manifest and never
touches a fresh-evidence journal, activation artifact, or brokerage surface.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time
from zoneinfo import ZoneInfo

from ml.v11.intraday_backfill import (
    TiingoHistoricalIntradayClient,
    _atomic_json_write,
    _canonical_sha,
    run_backfill,
)
from ml.v13.regime_overlay_reconstruction import (
    DEVELOPMENT_END_DATE,
    ROOT,
    TIINGO_IEX_INTRADAY_START_DATE,
)


OUTPUT_ROOT = ROOT / "data/research/v13/development/intraday_backfills"
NEW_YORK = ZoneInfo("America/New_York")
REQUIRED_BAR_TIMES = {
    time(9, 30),
    time(9, 35),
    time(9, 40),
    time(9, 45),
    time(9, 50),
    time(9, 55),
    time(15, 55),
}
SAMPLING_POLICY = "OPENING_SIX_COMPLETED_BARS_PLUS_1555_SESSION_CLOSE"


class CompactV13HistoricalClient:
    """Retain only the bars required by the locked V13 rule."""

    def __init__(self, *, timeout_seconds: int):
        self._client = TiingoHistoricalIntradayClient(
            timeout_seconds=timeout_seconds
        )

    def fetch(self, symbol, start_date, end_date) -> list[dict[str, object]]:
        rows = self._client.fetch(symbol, start_date, end_date)
        compact = []
        for row in rows:
            try:
                stamp = datetime.fromisoformat(
                    str(row["timestamp_utc"])
                ).astimezone(NEW_YORK)
            except (KeyError, TypeError, ValueError):
                continue
            if stamp.time().replace(tzinfo=None) in REQUIRED_BAR_TIMES:
                compact.append(row)
        return compact


def _publish_sampling_contract(result: dict[str, object]) -> dict[str, object]:
    if result.get("published") is not True:
        return result
    result["sampling_policy"] = SAMPLING_POLICY
    result["bars_retained_per_complete_session"] = 7
    result["retained_bar_times_eastern"] = [
        "09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "15:55"
    ]
    result["full_session_bars_retained"] = False
    result["v13_development_only"] = True
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = _canonical_sha(result)
    run_id = f"{result['start_date']}_{result['end_date']}"
    _atomic_json_write(OUTPUT_ROOT / run_id / "manifest.json", result)
    _atomic_json_write(OUTPUT_ROOT / "latest_complete_manifest.json", result)
    return result


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
        client=CompactV13HistoricalClient(timeout_seconds=args.timeout_seconds),
        output_root=OUTPUT_ROOT,
        chunk_days=args.chunk_days,
        workers=args.workers,
        progress=True,
    )
    result = _publish_sampling_contract(result)
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
        print("Retained bars/session: 7 (09:30-09:55 and 15:55 Eastern)")
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
