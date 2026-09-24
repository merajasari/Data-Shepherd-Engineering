"""Regression checks for atomic V11 five-minute collection."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_collector import collect_complete_snapshot


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def bars(symbol: str, *, count: int = 6, shift_last: bool = False) -> list[dict[str, object]]:
    start = datetime(2026, 8, 27, 13, 30, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        stamp = start + timedelta(minutes=5 * index)
        if shift_last and index == count - 1:
            stamp += timedelta(minutes=5)
        opening = 100.0 + index
        rows.append(
            {
                "symbol": symbol,
                "timestamp_utc": stamp.isoformat(),
                "open": opening,
                "high": opening + 1.0,
                "low": opening - 1.0,
                "close": opening + 0.25,
                "volume": 1000 + index,
            }
        )
    return rows


class FormingBarClient:
    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        rows = bars(symbol, count=13)
        session_start = datetime(2026, 9, 8, 13, 30, tzinfo=timezone.utc)
        for index, row in enumerate(rows):
            row["timestamp_utc"] = (
                session_start + timedelta(minutes=5 * index)
            ).isoformat()
        return rows


class MalformedTrailingBarClient(FormingBarClient):
    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        rows = super().get_five_minute_bars(symbol, session_date)
        rows[-1]["timestamp_utc"] = "not-a-timestamp"
        return rows


class FinalSessionClient:
    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        return bars(symbol, count=78)


class FakeClient:
    def __init__(self, *, missing: str | None = None, misaligned: str | None = None):
        self.missing = missing
        self.misaligned = misaligned

    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        if symbol == self.missing:
            raise RuntimeError("synthetic failure")
        return bars(symbol, shift_last=symbol == self.misaligned)


class ConcurrentProbeClient(FakeClient):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def get_five_minute_bars(self, symbol: str, session_date: str) -> list[dict[str, object]]:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.01)
            return super().get_five_minute_bars(symbol, session_date)
        finally:
            with self._lock:
                self.active -= 1


def universe() -> list[str]:
    return [f"S{index:03d}" for index in range(100)] + ["SPY"]


def main() -> None:
    now = datetime(2026, 8, 27, 14, 1, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "latest.json"
        complete = collect_complete_snapshot(
            now_utc=now,
            session_date="2026-08-27",
            client=FakeClient(),
            output_path=output,
            symbols=universe(),
        )
        require(complete.published, "Complete 101-symbol snapshot publishes")
        require(output.exists(), "Complete snapshot is atomically persisted")
        payload = json.loads(output.read_text())
        require(payload["symbol_count"] == 101, "Published universe contains 101 symbols")
        require(len(payload["series_sha256"]) == 64, "Published series has a SHA-256 identity")
        require(payload["paper_trading_only"] is True, "Published snapshot is paper only")
        require(payload["brokerage_orders"] is False, "Published snapshot has no brokerage authority")

        probe = ConcurrentProbeClient()
        concurrent = collect_complete_snapshot(
            now_utc=now,
            session_date="2026-08-27",
            client=probe,
            output_path=output,
            symbols=universe(),
        )
        require(concurrent.published, "Concurrent 101-symbol collection still publishes atomically")
        require(probe.max_active > 1, "Universe requests overlap instead of running serially")

        before = output.read_bytes()

        catch_up_now = datetime(2026, 9, 8, 14, 34, 15, tzinfo=timezone.utc)
        forming = collect_complete_snapshot(
            now_utc=catch_up_now,
            session_date="2026-09-08",
            client=FormingBarClient(),
            output_path=output,
            symbols=universe(),
        )
        require(
            forming.published,
            "Catch-up ignores the trailing still-forming five-minute bar",
        )
        forming_payload = json.loads(output.read_text())
        require(
            forming.completed_bar_utc.endswith("14:25:00+00:00"),
            "Catch-up publishes through the latest completed 10:25 Eastern bar",
        )
        require(
            forming.trimmed_incomplete_bars == 101
            and forming_payload["trimmed_incomplete_bars"] == 101,
            "Exactly one trailing forming bar per symbol is excluded",
        )
        require(
            {len(rows) for rows in forming_payload["series"].values()} == {12},
            "Published catch-up snapshot contains completed bars only",
        )

        before = output.read_bytes()
        malformed = collect_complete_snapshot(
            now_utc=catch_up_now,
            session_date="2026-09-08",
            client=MalformedTrailingBarClient(),
            output_path=output,
            symbols=universe(),
        )
        require(
            not malformed.published,
            "Malformed trailing timestamps remain fail-closed",
        )
        require(
            any(reason.startswith("TIMESTAMP_INVALID:") for reason in malformed.reasons),
            "Malformed timestamp rejection remains explicit",
        )
        require(
            output.read_bytes() == before,
            "Malformed data cannot replace the last complete snapshot",
        )

        missing = collect_complete_snapshot(
            now_utc=now,
            session_date="2026-08-27",
            client=FakeClient(missing="S042"),
            output_path=output,
            symbols=universe(),
        )
        require(not missing.published, "Missing symbol prevents publication")
        require("COMPLETE_UNIVERSE_NOT_AVAILABLE" in missing.reasons, "Incomplete universe is explicit")
        require(output.read_bytes() == before, "Failed collection cannot replace last complete snapshot")

        misaligned = collect_complete_snapshot(
            now_utc=now + timedelta(minutes=5),
            session_date="2026-08-27",
            client=FakeClient(misaligned="S077"),
            output_path=output,
            symbols=universe(),
            maximum_age_seconds=720,
        )
        require(not misaligned.published, "Misaligned completed bar prevents publication")
        require("LATEST_BAR_NOT_ALIGNED" in misaligned.reasons, "Cross-sectional timestamp mismatch is explicit")
        require(output.read_bytes() == before, "Misalignment cannot mutate complete snapshot")

        after_close = collect_complete_snapshot(
            now_utc=datetime(2026, 8, 27, 21, 0, tzinfo=timezone.utc),
            session_date="2026-08-27",
            client=FinalSessionClient(),
            output_path=output,
            symbols=universe(),
        )
        require(after_close.published, "Same-day final session snapshot publishes after close")
        after_close_payload = json.loads(output.read_text())
        require(
            after_close_payload["freshness_mode"] == "FINAL_SESSION_SNAPSHOT",
            "After-close publication is labeled final session",
        )
        require(
            after_close.completed_bar_utc.endswith("19:55:00+00:00"),
            "After-close publication requires the 15:55 Eastern bar",
        )

        incomplete_close = collect_complete_snapshot(
            now_utc=datetime(2026, 8, 27, 21, 0, tzinfo=timezone.utc),
            session_date="2026-08-27",
            client=FakeClient(),
            output_path=output,
            symbols=universe(),
        )
        require(not incomplete_close.published, "Opening-only data cannot publish after close")
        require(
            "FINAL_SESSION_BAR_MISSING" in incomplete_close.reasons,
            "Missing 15:55 final bar is explicit",
        )

        partial_universe = collect_complete_snapshot(
            now_utc=now,
            session_date="2026-08-27",
            client=FakeClient(),
            output_path=output,
            symbols=universe()[:-1],
        )
        require(not partial_universe.published, "100-symbol universe fails closed")
        require("UNIVERSE_CONTRACT_VIOLATION" in partial_universe.reasons, "Universe violation is explicit")

    source = Path(__file__).with_name("intraday_collector.py").read_text()
    require("headers={\"Authorization\": f\"Token {self._token}\"}" in source, "Token is sent by authorization header")
    require("\"token\":" not in source, "Token is never placed in query parameters")
    require("endpoint credentials redacted" in source, "Request errors redact credentials")
    forbidden = ("submit_order", "place_order", "alpaca", "ib_insync")
    require(not any(value in source.lower() for value in forbidden), "Collector imports no brokerage interface")
    require("data/model/v8/holdout" not in source and "data/model/v10" not in source, "Collector references no holdout path")

    print("\nStatus: PASSED")
    print("Atomic 101-symbol V11 collector: VERIFIED")
    print("Partial publication: PROHIBITED")
    print("Live credentials exposed: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
