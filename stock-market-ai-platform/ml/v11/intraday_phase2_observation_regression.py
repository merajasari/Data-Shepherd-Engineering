"""Regression suite for the V11 Phase 2 observation runner."""
from __future__ import annotations

import copy
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_phase2_journal import Phase2EvidenceJournal
from ml.v11.intraday_phase2_observation import run_observation
from ml.v11.intraday_ranking import (
    _canonical_sha,
    build_development_rankings,
    get_v5_data_symbols,
)


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


def decision_only_snapshot(
    snapshot: dict[str, object],
) -> dict[str, object]:
    decision = copy.deepcopy(snapshot)
    decision["series"] = {
        symbol: rows[:6]
        for symbol, rows in decision["series"].items()
    }
    decision["completed_bar_utc"] = decision["series"]["SPY"][-1][
        "timestamp_utc"
    ]
    decision["series_sha256"] = _canonical_sha(decision["series"])
    return decision


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

        expected_decision = build_development_rankings(
            decision_only_snapshot(snapshot),
            closes,
        )
        require(
            result.selected_symbols == tuple(expected_decision["top_10"]),
            "Selection uses only the six preregistered decision bars",
        )

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
        require(
            len({row["ranking_sha256"] for row in rows}) == 1
            and len({row["decision_series_sha256"] for row in rows}) == 1,
            "Every lifecycle event retains one decision-time ranking identity",
        )

        progressive_path = Path(directory) / "progressive.jsonl"
        partial = run_observation(
            snapshot=decision_only_snapshot(snapshot),
            previous_closes=closes,
            journal_path=progressive_path,
            rehearsal=True,
        )
        require(
            partial.status == "WAITING_FOR_ENTRY"
            and partial.events_appended == 1,
            "Decision-only checkpoint records exactly one prospective decision",
        )
        revised_decision = copy.deepcopy(snapshot)
        nonselected = [
            symbol
            for symbol in revised_decision["series"]
            if symbol != "SPY"
            and symbol not in partial.selected_symbols
        ]
        for symbol in nonselected[:15]:
            for bar_index in range(6):
                row = revised_decision["series"][symbol][bar_index]
                multiplier = 1.0 + 0.12 * (bar_index + 1)
                row["open"] *= multiplier
                row["high"] *= multiplier
                row["low"] *= multiplier
                row["close"] *= multiplier
                row["volume"] *= 10
        revised_decision["series_sha256"] = _canonical_sha(
            revised_decision["series"]
        )
        revised_ranking = build_development_rankings(
            decision_only_snapshot(revised_decision),
            closes,
        )
        require(
            tuple(revised_ranking["top_10"]) != partial.selected_symbols,
            "Fixture reproduces a revised decision-time ranking",
        )

        completed = run_observation(
            snapshot=revised_decision,
            previous_closes=closes,
            journal_path=progressive_path,
            rehearsal=True,
        )
        progressive_rows = Phase2EvidenceJournal(progressive_path).read()
        require(
            completed.status == "SESSION_OBSERVATION_COMPLETE"
            and completed.events_appended == 3,
            "Later snapshot completes the original decision lifecycle",
        )
        require(
            {
                tuple(row["selected_symbols"])
                for row in progressive_rows
            } == {partial.selected_symbols}
            and len({
                row["ranking_sha256"]
                for row in progressive_rows
            }) == 1
            and len({
                row["decision_series_sha256"]
                for row in progressive_rows
            }) == 1,
            "Revised source bars cannot change the recorded decision",
        )

        drift_path = Path(directory) / "drift_attempt.jsonl"
        drift_journal = Phase2EvidenceJournal(drift_path)
        unsigned_decision = {
            key: value
            for key, value in progressive_rows[0].items()
            if key not in {
                "event_id",
                "previous_record_sha256",
                "record_sha256",
            }
        }
        unsigned_entry = {
            key: value
            for key, value in progressive_rows[1].items()
            if key not in {
                "event_id",
                "previous_record_sha256",
                "record_sha256",
            }
        }
        unsigned_entry["selected_symbols"] = list(
            reversed(unsigned_entry["selected_symbols"])
        )
        drift_journal.append(unsigned_decision)
        drift_rejected = False
        try:
            drift_journal.append(unsigned_entry)
        except ValueError as exc:
            drift_rejected = (
                str(exc) == "evidence lifecycle identity drift"
            )
        require(
            drift_rejected,
            "Journal rejects lifecycle identity drift before append",
        )

        future_changed = copy.deepcopy(snapshot)
        candidate_symbols = [
            symbol
            for symbol in future_changed["series"]
            if symbol != "SPY"
        ]
        for symbol in candidate_symbols[:15]:
            for bar_index in range(6, 12):
                row = future_changed["series"][symbol][bar_index]
                multiplier = 1.0 + 0.08 * (bar_index - 5)
                row["open"] *= multiplier
                row["high"] *= multiplier
                row["low"] *= multiplier
                row["close"] *= multiplier
                row["volume"] *= 5
        future_changed["series_sha256"] = _canonical_sha(
            future_changed["series"]
        )
        future_path = Path(directory) / "future_changed.jsonl"
        future_result = run_observation(
            snapshot=future_changed,
            previous_closes=closes,
            journal_path=future_path,
            rehearsal=True,
        )
        require(
            future_result.selected_symbols == result.selected_symbols,
            "Post-decision price and volume changes cannot alter selection",
        )

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

        production_path = Path(directory) / "production.jsonl"
        production = run_observation(
            snapshot=snapshot,
            previous_closes=closes,
            journal_path=production_path,
            rehearsal=False,
        )
        require(
            production.status == "SESSION_OBSERVATION_COMPLETE",
            "Activated paper-confirmation runner completes",
        )
        production_rows = Phase2EvidenceJournal(production_path).read()
        require(
            len(production_rows) == 4,
            "Activated runner writes exactly four temporary test events",
        )
        require(
            all(row["rehearsal"] is False for row in production_rows),
            "Activated observations are labeled genuine",
        )
        require(
            all(row["brokerage_orders"] is False for row in production_rows),
            "Activated paper confirmation retains zero brokerage authority",
        )

        catch_up_path = Path(directory) / "catch_up.jsonl"
        catch_up = run_observation(
            snapshot=snapshot,
            previous_closes=closes,
            journal_path=catch_up_path,
            rehearsal=False,
            catch_up=True,
            collected_at_utc="2026-09-01T18:00:00+00:00",
        )
        catch_up_rows = Phase2EvidenceJournal(catch_up_path).read()
        require(
            catch_up.status == "SESSION_OBSERVATION_COMPLETE",
            "Wake-up catch-up reconstructs the complete session",
        )
        require(
            all(
                row["catch_up_reconstruction"] is True
                for row in catch_up_rows
            ),
            "Every reconstructed event is labeled catch-up",
        )
        require(
            all(
                row["collected_at_utc"]
                == "2026-09-01T18:00:00+00:00"
                for row in catch_up_rows
            ),
            "Catch-up preserves a separate collection timestamp",
        )

    print("Status: PASSED")
    print("Decision -> paper entry -> paper exit -> observation: VERIFIED")
    print("Restart/idempotency/provenance/boundary safety: VERIFIED")
    print("Production activation: ENABLED PAPER CONFIRMATION")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
