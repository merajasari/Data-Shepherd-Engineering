"""Regression checks for the end-to-end V13 scheduled rehearsal."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_input_snapshot_regression import raw_inputs
from ml.v13.regime_overlay_scheduled_rehearsal import (
    _require_contract,
    run_scheduled_rehearsal,
)


SOURCE = Path(__file__).with_name("regime_overlay_scheduled_rehearsal.py")
LEASE_SHA = "a" * 64


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def active(_: datetime) -> dict[str, object]:
    return {
        "valid": True,
        "active": True,
        "latest_lease_sha256": LEASE_SHA,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def inactive(now: datetime) -> dict[str, object]:
    return {**active(now), "active": False}


def main() -> None:
    require(len(_require_contract()) == 64, "Scheduled rehearsal contract identity is locked")
    with TemporaryDirectory(prefix="v13_scheduled_rehearsal_regression_") as directory:
        root = Path(directory)
        production = root / "production.jsonl"
        calls = 0

        def provider() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return raw_inputs()

        before = run_scheduled_rehearsal(
            now_utc=datetime(2026, 9, 3, 13, 50, tzinfo=timezone.utc),
            market_session_open=True,
            input_provider=provider,
            production_journal_path=production,
            activation_validator=inactive,
        )
        require(before.status == "NOT_DUE" and calls == 0, "Before-window run does not invoke input provider")

        holiday = run_scheduled_rehearsal(
            now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
            market_session_open=False,
            input_provider=provider,
            production_journal_path=production,
            activation_validator=inactive,
        )
        require(holiday.status == "MARKET_SESSION_CLOSED" and calls == 0, "Caller-supplied closed session fails closed before collection")

        try:
            run_scheduled_rehearsal(
                now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
                market_session_open=True,
                input_provider=provider,
                production_journal_path=production,
                activation_validator=inactive,
            )
        except RuntimeError:
            require(calls == 0 and not production.exists(), "Inactive lease blocks provider before collection")
        else:
            raise AssertionError("Inactive lease blocks provider before collection")

        result = run_scheduled_rehearsal(
            now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
            market_session_open=True,
            input_provider=provider,
            production_journal_path=production,
            activation_validator=active,
        )
        require(result.status == "PASSED_REHEARSAL_ONLY", "Due checkpoint completes end-to-end rehearsal")
        require(calls == 1 and result.provider_invoked, "Injected input provider is invoked exactly once")
        require(result.evaluator_invoked and result.rehearsal_events == 1, "Locked V13 evaluator records one temporary event")
        require(result.action == "APPLY_V13_INTRADAY_CONFIRMATION", "Negative high-volatility overlay is exercised")
        require(result.activation_lease_sha256 == LEASE_SHA, "Rehearsal binds the validated effective lease")
        require(not production.exists(), "Production evidence journal remains absent")
        require(result.market_data_requests == 0 and not result.scheduler_changed, "No market request or scheduler change occurs")
        require(not result.brokerage_orders, "Scheduled rehearsal has no brokerage authority")

        bad = raw_inputs()
        bad["bars_by_symbol"] = deepcopy(bad["bars_by_symbol"])
        bad["bars_by_symbol"].pop("S099")
        try:
            run_scheduled_rehearsal(
                now_utc=datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
                market_session_open=True,
                input_provider=lambda: bad,
                production_journal_path=production,
                activation_validator=active,
            )
        except ValueError:
            require(not production.exists(), "Invalid provider input fails closed without production evidence")
        else:
            raise AssertionError("Invalid provider input fails closed without production evidence")

    source = SOURCE.read_text(encoding="utf-8").lower()
    for prohibited in (
        "commit_session_decision",
        "regime_overlay_collection_apply",
        "requests.",
        "httpx",
        "urllib",
        "import alpaca",
        "robin_stocks",
        "ib_insync",
        "launchctl",
        "crontab",
    ):
        require(prohibited not in source, f"Scheduled rehearsal excludes {prohibited}")

    print("Status: PASSED")
    print("V13 injected inputs -> signed snapshots -> decision: VERIFIED TEMPORARY ONLY")
    print("Scheduler installed or changed: NO")
    print("Market data requested: NO")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
