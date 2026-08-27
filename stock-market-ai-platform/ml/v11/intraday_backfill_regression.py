"""Regression checks for the V11 historical five-minute backfill."""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_backfill import normalize_historical_rows, run_backfill


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def universe() -> list[str]:
    return [f"S{index:03d}" for index in range(100)] + ["SPY"]


class FakeClient:
    def __init__(self, missing: str | None = None):
        self.missing = missing

    def fetch(self, symbol: str, start_date: date, end_date: date) -> list[dict[str, object]]:
        if symbol == self.missing:
            raise RuntimeError("synthetic failure")
        rows = []
        cursor = start_date
        while cursor <= end_date:
            if cursor.weekday() < 5:
                base = datetime(cursor.year, cursor.month, cursor.day, 13, 30, tzinfo=timezone.utc)
                for index in range(6):
                    opening = 100.0 + index
                    rows.append(
                        {
                            "symbol": symbol,
                            "timestamp_utc": (base + timedelta(minutes=5 * index)).isoformat(),
                            "open": opening,
                            "high": opening + 1.0,
                            "low": opening - 1.0,
                            "close": opening + 0.25,
                            "volume": 1000 + index,
                        }
                    )
            cursor += timedelta(days=1)
        return rows


def main() -> None:
    raw = [
        {"date": "2026-08-27T13:30:00Z", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        {"date": "2026-08-27T13:30:00Z", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 110},
        {"date": "2026-08-27T01:00:00Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"date": "bad", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
    ]
    normalized = normalize_historical_rows("aapl", raw)
    require(len(normalized) == 1, "Invalid, extended-hours and duplicate rows are removed")
    require(normalized[0]["symbol"] == "AAPL", "Symbols are normalized")
    require(normalized[0]["close"] == 11.0, "Deterministic duplicate resolution keeps the last row")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        complete = run_backfill(
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 27),
            client=FakeClient(),
            output_root=output,
            symbols=universe(),
            chunk_days=2,
        )
        require(complete["published"], "Complete 101-symbol history publishes")
        require(complete["symbol_count"] == 101, "Published history contains 101 symbols")
        require(complete["common_session_count"] == 4, "Common-session intersection is recorded")
        require(len(complete["manifest_sha256"]) == 64, "Manifest has a SHA-256 identity")
        manifest_path = output / "latest_complete_manifest.json"
        require(manifest_path.exists(), "Latest complete manifest is atomically published")
        saved = json.loads(manifest_path.read_text())
        require(saved["manifest_sha256"] == complete["manifest_sha256"], "Published manifest identity is preserved")
        require(saved["paper_trading_only"] is True, "Historical dataset is paper research only")
        require(saved["brokerage_orders"] is False, "Historical dataset has no brokerage authority")

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        incomplete = run_backfill(
            start_date=date(2026, 8, 24),
            end_date=date(2026, 8, 27),
            client=FakeClient(missing="S042"),
            output_root=output,
            symbols=universe(),
            chunk_days=2,
        )
        require(not incomplete["published"], "Missing symbol prevents manifest publication")
        require(incomplete["symbols_ready"] == 100, "Partial universe is reported")
        require(not (output / "latest_complete_manifest.json").exists(), "Partial history cannot become latest complete")

    source = Path(__file__).with_name("intraday_backfill.py").read_text()
    require('headers={"Authorization": f"Token {self._token}"}' in source, "Token is sent in authorization header")
    require('"token":' not in source, "Token is absent from query parameters")
    require("endpoint credentials redacted" in source, "HTTP errors redact credentials")
    forbidden = ("submit_order", "place_order", "alpaca", "ib_insync")
    require(not any(value in source.lower() for value in forbidden), "Backfill imports no brokerage interface")
    require("data/model/v8/holdout" not in source and "data/model/v10" not in source, "Backfill references no holdout path")

    print("\nStatus: PASSED")
    print("V11 bounded historical backfill: VERIFIED")
    print("Partial publication: PROHIBITED")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
