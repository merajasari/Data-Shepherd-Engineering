"""Regression checks for the non-activated V13 quote-recovery candidate."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from ml.v13.regime_overlay_input_snapshot_regression import raw_inputs
from ml.v13.regime_overlay_quote_recovery import (
    _require_contract,
    collect_signed_inputs_with_quote_recovery,
)
from ml.v13.regime_overlay_tiingo_provider_regression import contexts


SOURCE = Path(__file__).with_name("regime_overlay_quote_recovery.py")
ONE_SHOT = Path(__file__).with_name("regime_overlay_one_shot.py")
AUTOMATION = Path(__file__).with_name("regime_overlay_session_automation.py")
NOW = datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


class FakeClient:
    def __init__(self, quote_failures: list[tuple[str, str] | None]):
        values = raw_inputs()
        self.bars = values["bars_by_symbol"]
        self.previous = values["previous_closes"]
        self.quote_failures = list(quote_failures)
        self.request_count = 0
        self.quote_calls = 0
        self.daily_calls = 0

    def get_five_minute_bars(self, symbol: str, session_date: str):
        self.request_count += 1
        return deepcopy(self.bars[symbol])

    def get_quotes(self, symbols):
        self.request_count += 1
        self.quote_calls += 1
        failure = (
            self.quote_failures.pop(0) if self.quote_failures else None
        )
        rows = []
        for symbol in symbols:
            if failure == ("missing", symbol):
                continue
            midpoint = float(self.previous[symbol])
            bid: object = midpoint - 0.025
            ask: object = midpoint + 0.025
            if failure == ("bid", symbol):
                bid = None
            elif failure == ("ask", symbol):
                ask = None
            elif failure == ("crossed", symbol):
                bid, ask = midpoint + 0.05, midpoint - 0.05
            rows.append(
                {
                    "ticker": symbol,
                    "prevClose": midpoint,
                    "bidPrice": bid,
                    "askPrice": ask,
                }
            )
        return rows

    def get_spy_daily_closes(self, *, start_date: str, end_date: str):
        self.request_count += 1
        self.daily_calls += 1
        return [100.0 if index % 2 == 0 else 102.0 for index in range(21)]


def collect(client: FakeClient, waits: list[float]):
    ranking, control = contexts()
    return collect_signed_inputs_with_quote_recovery(
        now_utc=NOW,
        session_date="2026-09-03",
        ranking_snapshot=ranking,
        control_context=control,
        client=client,
        sleeper=waits.append,
    )


def main() -> None:
    require(
        len(_require_contract()) == 64,
        "Quote-recovery contract identity is locked",
    )

    normal = FakeClient([])
    waits: list[float] = []
    normal_result = collect(normal, waits)
    require(normal_result.request_count == 103, "Complete first batch uses 103 requests")
    require(normal.quote_calls == 1 and waits == [], "Complete first batch is never retried")

    recovered = FakeClient([("bid", "S010"), None])
    waits = []
    recovered_result = collect(recovered, waits)
    require(
        recovered_result.request_count == 104,
        "One missing bid recovers within the 104-request ceiling",
    )
    require(
        recovered.quote_calls == 2 and waits == [5.0],
        "Recovery uses exactly one full-batch retry after five seconds",
    )
    require(
        recovered_result.bundle.intraday_snapshot["symbol_count"] == 101,
        "Recovered bundle preserves the exact 101-symbol universe",
    )

    missing = FakeClient([("missing", "S099"), None])
    waits = []
    collect(missing, waits)
    require(
        missing.quote_calls == 2 and missing.request_count == 104,
        "Incomplete first symbol set uses the same bounded recovery",
    )

    persistent = FakeClient([("bid", "S010"), ("bid", "S010")])
    waits = []
    try:
        collect(persistent, waits)
    except ValueError as exc:
        require(
            str(exc) == "V13_BID_INVALID:S010"
            and getattr(exc, "market_data_requests", None) == 103,
            "Persistent missing bid fails with an auditable request count",
        )
        require(
            persistent.daily_calls == 0,
            "Second quote failure writes no downstream input bundle",
        )
    else:
        raise AssertionError("Persistent missing bid fails with an auditable request count")

    crossed = FakeClient([("crossed", "S010")])
    waits = []
    try:
        collect(crossed, waits)
    except ValueError as exc:
        require(
            str(exc) == "V13_CROSSED_QUOTE_INVALID:S010"
            and crossed.quote_calls == 1
            and waits == [],
            "Crossed quote fails immediately and is not retry-eligible",
        )
    else:
        raise AssertionError("Crossed quote fails immediately and is not retry-eligible")

    ranking, control = contexts()
    ranking["symbols"] = list(reversed(ranking["symbols"]))
    tampered = FakeClient([])
    try:
        collect_signed_inputs_with_quote_recovery(
            now_utc=NOW,
            session_date="2026-09-03",
            ranking_snapshot=ranking,
            control_context=control,
            client=tampered,
            sleeper=lambda _: None,
        )
    except ValueError:
        require(
            tampered.request_count == 0,
            "Tampered ranking fails before every market request",
        )
    else:
        raise AssertionError("Tampered ranking fails before every market request")

    production_sources = (
        ONE_SHOT.read_text(encoding="utf-8")
        + AUTOMATION.read_text(encoding="utf-8")
    )
    require(
        "regime_overlay_quote_recovery" not in production_sources,
        "Recovery candidate is not wired into production collection",
    )
    source = SOURCE.read_text(encoding="utf-8").lower()
    for primitive in (".write_text", ".write_bytes", "os.open("):
        require(primitive not in source, f"Recovery candidate excludes file write {primitive}")
    for prohibited in (
        "import alpaca",
        "robin_stocks",
        "ib_insync",
        "launchctl",
        "crontab",
    ):
        require(prohibited not in source, f"Recovery candidate excludes {prohibited}")

    print("Status: PASSED")
    print("V13 quote availability recovery: VERIFIED DEVELOPMENT ONLY")
    print("Production integration: ABSENT")
    print("Live requests during regression: 0")
    print("Evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
