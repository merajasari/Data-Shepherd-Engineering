"""Regression suite for the V11 Phase 2 observation runner."""
from __future__ import annotations

import copy
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_phase2_journal import Phase2EvidenceJournal
from ml.v11.intraday_phase2_observation import run_observation
from ml.v11.intraday_ranking import _canonical_sha, get_v5_data_symbols


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def synthetic_fixture() -> tuple[dict[str, object], dict[str, float]]:
    symbols = list(get_v5_data_symbols())
    start = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    series: dict[str, list[dict[str, object]]] = {}
    closes: dict[str, float] = {}
    for symbol_index, symbol in enumerate(symbols):
        prior = 100.0 + symbol_index
        closes[symbol] = prior
        rows = []
        for bar_index in range(12):
            trend = (symbol_index - 50) * 0.00008
            open_price = prior * (
                1.0 + 0.0002 * bar_index + trend * bar_index
            )
            close_price = open_price * (
                1.0 + 0.0001 + trend
            )
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp_utc": (
                        start + timedelta(minutes=5 * bar_index)
                    ).isoformat(),
                    "open": open_price,
                    "high": max(open_price, close_price) * 1.0002,
                    "low": min(open_price, close_price) * 0.9998,
                    "close": close_price,
                    "volume": 1000 + symbol_index * 10 + bar_index * 25,
                }
            )
        series[symbol] = rows
    snapshot: dict[str, object] = {
        "contract_id": "V11_INTRADAY_5MIN_RESEARCH_V1",
        "status": "COMPLETE_RESEARCH_SNAPSHOT",
        "session_date": "2026-09-01",
        "generated_at_utc": "2026-09-01T14:31:00+00:00",
        "completed_bar_utc": series["SPY"][-1]["timestamp_utc"],
        "bar_interval_minutes": 5,
        "symbol_count": 101,
        "symbols": symbols,
        "series": series,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    snapshot["series_sha256"] = _canonical_sha(series)
    return snapshot, closes


def main() -> None:
    snapshot, closes = synthetic_fixture()
    with tempfile.TemporaryDirectory(prefix="v11_phase2_observation_") as directory:
        journal_path = Path(directory) / "evidence.jsonl"
        result = run_observation(
            snapshot=snapshot,
            previous_closes=closes,
            journal_path=journal_path,
            rehearsal=True,
        )
        require(result.status == "SESSION_OBSERVATION_COMPLETE", "Complete session reaches observation")
        require(result.events_appended == 4, "Decision, entry, exit and observation append")
        require(result.total_session_events == 4, "Exactly four session events persist")
        require(len(result.selected_symbols) == 10, "Exactly ten stocks are selected")
        require(result.strategy_net_return is not None, "Net return is calculated")
        require(result.spy_return is not None, "SPY return is calculated")
        require(result.net_excess_return is not None, "SPY-relative result is calculated")
        require(result.brokerage_orders is False, "Observation has no brokerage authority")

        rows = Phase2EvidenceJournal(journal_path).read()
        require(
            [row["event_type"] for row in rows]
            == ["DECISION", "ENTRY", "EXIT", "SESSION_OBSERVATION"],
            "Lifecycle order is deterministic",
        )
        require(all(row["rehearsal"] is True for row in rows), "All rehearsal evidence is labeled")
        require(all(row["brokerage_orders"] is False for row in rows), "Every event keeps orders off")
        require(all(row["v8_modified"] is False for row in rows), "V8 remains unchanged")
        require(all(row["v10_modified"] is False for row in rows), "V10 remains unchanged")

        restart = run_observation(
            snapshot=snapshot,
            previous_closes=closes,
            journal_path=journal_path,
            rehearsal=True,
        )
        require(restart.events_appended == 0, "Restart is idempotent")
        require(restart.total_session_events == 4, "Restart creates no duplicates")

        tampered = copy.deepcopy(snapshot)
        tampered["series"][next(symbol for symbol in tampered["series"] if symbol != "SPY")][0]["close"] *= 2
        sha_failed = False
        try:
            run_observation(
                snapshot=tampered,
                previous_closes=closes,
                journal_path=Path(directory) / "tampered.jsonl",
                rehearsal=True,
            )
        except ValueError:
            sha_failed = True
        require(sha_failed, "Tampered snapshot fails closed")

        early = copy.deepcopy(snapshot)
        early["session_date"] = "2026-08-31"
        early["completed_bar_utc"] = "2026-08-31T14:25:00+00:00"
        boundary_failed = False
        try:
            run_observation(
                snapshot=early,
                previous_closes=closes,
                journal_path=Path(directory) / "early.jsonl",
                rehearsal=True,
            )
        except ValueError:
            boundary_failed = True
        require(boundary_failed, "Pre-boundary session fails closed")

        production_failed = False
        production_path = Path(directory) / "production.jsonl"
        try:
            run_observation(
                snapshot=snapshot,
                previous_closes=closes,
                journal_path=production_path,
                rehearsal=False,
            )
        except RuntimeError:
            production_failed = True
        require(production_failed, "Disabled production runner fails closed")
        require(not production_path.exists(), "Disabled runner writes no evidence")

    print("Status: PASSED")
    print("Decision -> paper entry -> paper exit -> observation: VERIFIED")
    print("Restart/idempotency/provenance/boundary safety: VERIFIED")
    print("Production activation: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
