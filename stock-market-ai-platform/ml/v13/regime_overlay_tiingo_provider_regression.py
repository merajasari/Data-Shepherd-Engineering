"""Regression checks for the guarded V13 Tiingo input provider."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

from ml.v13.regime_overlay_contract import EXPECTED_V10_CANDIDATE, EXPECTED_V10_SHA256
from ml.v13.regime_overlay_input_snapshot_regression import raw_inputs
from ml.v13.regime_overlay_observation import EXPECTED_RANKING_STATUS, signed_payload
from ml.v13.regime_overlay_tiingo_provider import (
    COMPLETE_CONTROL_CONTEXT,
    TiingoV13Client,
    _require_contract,
    collect_signed_inputs,
)


SOURCE = Path(__file__).with_name("regime_overlay_tiingo_provider.py")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def contexts() -> tuple[dict[str, object], dict[str, object]]:
    values = raw_inputs()
    ranking = signed_payload(
        {
            "status": EXPECTED_RANKING_STATUS,
            "session_date": values["session_date"],
            "candidate_id": EXPECTED_V10_CANDIDATE,
            "frozen_spec_sha256": EXPECTED_V10_SHA256,
            "symbols": values["ranked_symbols"],
        },
        "ranking_sha256",
    )
    control = signed_payload(
        {
            "status": COMPLETE_CONTROL_CONTEXT,
            "session_date": values["session_date"],
            "candidate_id": EXPECTED_V10_CANDIDATE,
            "frozen_spec_sha256": EXPECTED_V10_SHA256,
            "v10_negative_flags": [True, True],
            "holdout_outcomes_read": False,
        },
        "control_context_sha256",
    )
    return ranking, control


class FakeClient:
    def __init__(self, *, missing_quote: str | None = None):
        values = raw_inputs()
        self.bars = values["bars_by_symbol"]
        self.previous = values["previous_closes"]
        self.missing_quote = missing_quote
        self.request_count = 0
        self.last_daily_end: str | None = None

    def get_five_minute_bars(self, symbol: str, session_date: str):
        self.request_count += 1
        return deepcopy(self.bars[symbol])

    def get_quotes(self, symbols):
        self.request_count += 1
        rows = []
        for symbol in symbols:
            if symbol == self.missing_quote:
                continue
            midpoint = float(self.previous[symbol])
            rows.append(
                {
                    "ticker": symbol,
                    "prevClose": midpoint,
                    "bidPrice": midpoint - 0.025,
                    "askPrice": midpoint + 0.025,
                }
            )
        return rows

    def get_spy_daily_closes(self, *, start_date: str, end_date: str):
        self.request_count += 1
        self.last_daily_end = end_date
        return [100.0 if index % 2 == 0 else 102.0 for index in range(21)]


def failing_transport(*args, **kwargs):
    raise URLError("https://example.invalid/?token=secret-token")


def main() -> None:
    require(len(_require_contract()) == 64, "Tiingo provider contract identity is locked")
    ranking, control = contexts()
    client = FakeClient()
    result = collect_signed_inputs(
        now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
        session_date="2026-09-03",
        ranking_snapshot=ranking,
        control_context=control,
        client=client,
    )
    require(result.status == "COMPLETE_SIGNED_INPUT_BUNDLE", "Complete provider inputs produce one signed bundle")
    require(result.request_count == 103, "Provider request budget is exactly 103")
    require(client.last_daily_end == "2026-09-02", "SPY volatility excludes the incomplete decision session")
    require(result.bundle.intraday_snapshot["symbol_count"] == 101, "Provider preserves the exact 101-symbol universe")
    require(result.bundle.regime_snapshot["v10_negative_flags"] == [True, True], "Signed negative-regime context is preserved")
    require(result.bundle.market_data_requests == 0, "Snapshot builder itself performs no additional requests")
    require(not result.brokerage_orders and not result.live_trading_enabled, "Provider has no live or brokerage authority")

    tampered = deepcopy(ranking)
    tampered["symbols"] = list(reversed(tampered["symbols"]))
    blocked = FakeClient()
    try:
        collect_signed_inputs(
            now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
            session_date="2026-09-03",
            ranking_snapshot=tampered,
            control_context=control,
            client=blocked,
        )
    except ValueError:
        require(blocked.request_count == 0, "Tampered ranking fails before any market request")
    else:
        raise AssertionError("Tampered ranking fails before any market request")

    incomplete = FakeClient(missing_quote="S099")
    try:
        collect_signed_inputs(
            now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
            session_date="2026-09-03",
            ranking_snapshot=ranking,
            control_context=control,
            client=incomplete,
        )
    except ValueError:
        require(True, "Incomplete quote batch fails closed without a snapshot")
    else:
        raise AssertionError("Incomplete quote batch fails closed without a snapshot")

    redacting = TiingoV13Client(token="secret-token", transport=failing_transport)
    try:
        redacting.get_quotes(["SPY"])
    except RuntimeError as exc:
        require("secret-token" not in str(exc), "Tiingo credential is redacted from request failures")
    else:
        raise AssertionError("Tiingo credential is redacted from request failures")

    source = SOURCE.read_text(encoding="utf-8").lower()
    for file_write in (".write_text", ".write_bytes", ".open(", "os.open("):
        require(file_write not in source, f"Provider excludes file write primitive {file_write}")
    for prohibited in ("import alpaca", "robin_stocks", "ib_insync", "launchctl", "crontab"):
        require(prohibited not in source, f"Provider excludes {prohibited}")

    print("Status: PASSED")
    print("V13 signed control context -> Tiingo inputs -> signed bundle: VERIFIED")
    print("Live requests during regression: 0")
    print("Files written: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
