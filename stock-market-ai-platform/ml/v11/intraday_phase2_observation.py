"""V11 Phase 2 fixed-contract intraday observation runner.

The runner converts a complete V11 research snapshot into a deterministic
decision, paper entry, paper exit, and net SPY-relative session observation.
Production evidence writes remain impossible while the Phase 2 contract is
disabled. No brokerage interface is imported or called.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from ml.v11.intraday_phase2_contract import (
    EXPECTED_WEIGHTS,
    contract_sha256,
    load_contract,
)
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    Phase2EvidenceJournal,
)
from ml.v11.intraday_ranking import (
    BASELINE_WEIGHTS,
    _canonical_sha,
    build_development_rankings,
    load_previous_closes_from_bronze,
)

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = (
    ROOT / "data/research/v11/intraday/latest_complete_snapshot.json"
)


@dataclass(frozen=True)
class ObservationRun:
    status: str
    session_date: str
    events_available: int
    events_appended: int
    total_session_events: int
    selected_symbols: tuple[str, ...]
    strategy_net_return: float | None
    spy_return: float | None
    net_excess_return: float | None
    rehearsal: bool
    brokerage_orders: bool = False
    v8_modified: bool = False
    v10_modified: bool = False


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)


def _validate_snapshot(
    snapshot: Mapping[str, object],
    contract: Mapping[str, object],
) -> tuple[str, Mapping[str, list[Mapping[str, object]]]]:
    if snapshot.get("status") != "COMPLETE_RESEARCH_SNAPSHOT":
        raise ValueError("SNAPSHOT_NOT_COMPLETE")
    if snapshot.get("symbol_count") != 101:
        raise ValueError("SNAPSHOT_UNIVERSE_INCOMPLETE")
    series = snapshot.get("series")
    if not isinstance(series, dict) or len(series) != 101 or "SPY" not in series:
        raise ValueError("SNAPSHOT_SERIES_INVALID")
    if snapshot.get("series_sha256") != _canonical_sha(series):
        raise ValueError("SNAPSHOT_SHA_MISMATCH")
    session_date = str(snapshot.get("session_date", ""))
    boundary = _utc(contract["fresh_confirmation_start_utc"])
    if datetime.fromisoformat(session_date).date() < boundary.date():
        raise ValueError("PRE_BOUNDARY_SESSION_PROHIBITED")
    completed = _utc(snapshot["completed_bar_utc"])
    if completed.date() < boundary.date():
        raise ValueError("PRE_BOUNDARY_SNAPSHOT_PROHIBITED")
    return session_date, series


def _event(
    *,
    event_type: str,
    session_date: str,
    timestamp_utc: str,
    contract_sha: str,
    ranking_sha: str,
    selected: list[str],
    rehearsal: bool,
    catch_up: bool,
    collected_at_utc: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_type": event_type,
        "session_date": session_date,
        "timestamp_utc": timestamp_utc,
        "contract_sha256": contract_sha,
        "ranking_sha256": ranking_sha,
        "selected_symbols": selected,
        "rehearsal": rehearsal,
        "catch_up_reconstruction": catch_up,
        "collected_at_utc": collected_at_utc,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    if extra:
        payload.update(extra)
    return payload


def run_observation(
    *,
    snapshot: Mapping[str, object],
    previous_closes: Mapping[str, float],
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    rehearsal: bool = False,
    catch_up: bool = False,
    collected_at_utc: str | None = None,
) -> ObservationRun:
    contract = load_contract()
    collection_time = collected_at_utc or datetime.now(timezone.utc).isoformat()
    _utc(collection_time)
    if not rehearsal:
        if (
            contract["activation_status"]
            != "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY"
        ):
            raise RuntimeError("PHASE2_PRODUCTION_ACTIVATION_DISABLED")
    elif journal_path.resolve() == DEFAULT_JOURNAL_PATH.resolve():
        raise RuntimeError("REHEARSAL_CANNOT_WRITE_PRODUCTION_JOURNAL")

    if BASELINE_WEIGHTS != EXPECTED_WEIGHTS:
        raise RuntimeError("PHASE2_RANKING_WEIGHTS_DRIFT")
    if contract["configuration"]["weights"] != EXPECTED_WEIGHTS:
        raise RuntimeError("PHASE2_CONTRACT_WEIGHTS_DRIFT")

    session_date, series = _validate_snapshot(snapshot, contract)
    ranking = build_development_rankings(snapshot, previous_closes)
    selected = list(ranking["top_10"])
    if len(selected) != int(contract["top_n"]) or len(set(selected)) != 10:
        raise ValueError("PHASE2_SELECTION_INVALID")

    decision_index = int(contract["decision_bar_index"])
    holding_bars = int(contract["configuration"]["holding_bars"])
    entry_index = decision_index + 1
    exit_index = decision_index + holding_bars
    minimum_count = min(len(rows) for rows in series.values())
    contract_sha = contract_sha256(contract)
    ranking_sha = str(ranking["ranking_sha256"])
    events: list[dict[str, object]] = []

    decision_bar = series["SPY"][decision_index]
    decision_time = (
        _utc(decision_bar["timestamp_utc"])
        .replace(second=0, microsecond=0)
        + timedelta(minutes=5)
    )
    events.append(
        _event(
            event_type="DECISION",
            session_date=session_date,
            timestamp_utc=decision_time.isoformat(),
            contract_sha=contract_sha,
            ranking_sha=ranking_sha,
            selected=selected,
            rehearsal=rehearsal,
            catch_up=catch_up,
            collected_at_utc=collection_time,
            extra={
                "source_snapshot_sha256": snapshot["series_sha256"],
                "configuration_id": contract["configuration"]["config_id"],
                "decision_bar_index": decision_index,
            },
        )
    )

    strategy_net_return: float | None = None
    spy_return: float | None = None
    net_excess_return: float | None = None
    if minimum_count > entry_index:
        entry_time = _utc(series["SPY"][entry_index]["timestamp_utc"])
        entry_prices = {
            symbol: float(series[symbol][entry_index]["open"])
            for symbol in selected
        }
        events.append(
            _event(
                event_type="ENTRY",
                session_date=session_date,
                timestamp_utc=entry_time.isoformat(),
                contract_sha=contract_sha,
                ranking_sha=ranking_sha,
                selected=selected,
                rehearsal=rehearsal,
                extra={
                    "entry_rule": contract["entry"],
                    "entry_prices": entry_prices,
                },
            )
        )

    if minimum_count > exit_index:
        exit_bar = series["SPY"][exit_index]
        exit_time = (
            _utc(exit_bar["timestamp_utc"])
            + timedelta(minutes=5)
        )
        entry_prices = {
            symbol: float(series[symbol][entry_index]["open"])
            for symbol in selected
        }
        exit_prices = {
            symbol: float(series[symbol][exit_index]["close"])
            for symbol in selected
        }
        gross_returns = {
            symbol: exit_prices[symbol] / entry_prices[symbol] - 1.0
            for symbol in selected
        }
        strategy_gross_return = statistics.fmean(gross_returns.values())
        cost = float(
            contract["modeled_total_cost_bps_round_trip"]
        ) / 10000.0
        strategy_net_return = strategy_gross_return - cost
        spy_entry = float(series["SPY"][entry_index]["open"])
        spy_exit = float(series["SPY"][exit_index]["close"])
        spy_return = spy_exit / spy_entry - 1.0
        net_excess_return = strategy_net_return - spy_return
        events.append(
            _event(
                event_type="EXIT",
                session_date=session_date,
                timestamp_utc=exit_time.isoformat(),
                contract_sha=contract_sha,
                ranking_sha=ranking_sha,
                selected=selected,
                rehearsal=rehearsal,
                extra={
                    "holding_bars": holding_bars,
                    "exit_prices": exit_prices,
                    "gross_returns": gross_returns,
                },
            )
        )
        events.append(
            _event(
                event_type="SESSION_OBSERVATION",
                session_date=session_date,
                timestamp_utc=exit_time.isoformat(),
                contract_sha=contract_sha,
                ranking_sha=ranking_sha,
                selected=selected,
                rehearsal=rehearsal,
                extra={
                    "strategy_gross_return": strategy_gross_return,
                    "modeled_total_cost_bps_round_trip": contract[
                        "modeled_total_cost_bps_round_trip"
                    ],
                    "strategy_net_return": strategy_net_return,
                    "spy_return": spy_return,
                    "net_excess_return": net_excess_return,
                },
            )
        )

    journal = Phase2EvidenceJournal(journal_path)
    appended = sum(1 for event in events if journal.append(event))
    session_rows = [
        row for row in journal.read()
        if row["session_date"] == session_date
    ]
    status = (
        "SESSION_OBSERVATION_COMPLETE"
        if any(row["event_type"] == "SESSION_OBSERVATION" for row in session_rows)
        else "WAITING_FOR_EXIT"
        if any(row["event_type"] == "ENTRY" for row in session_rows)
        else "WAITING_FOR_ENTRY"
    )
    return ObservationRun(
        status=status,
        session_date=session_date,
        events_available=len(events),
        events_appended=appended,
        total_session_events=len(session_rows),
        selected_symbols=tuple(selected),
        strategy_net_return=strategy_net_return,
        spy_return=spy_return,
        net_excess_return=net_excess_return,
        rehearsal=rehearsal,
    )


def run_from_files(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    rehearsal: bool = False,
    catch_up: bool = False,
) -> ObservationRun:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    closes = load_previous_closes_from_bronze(
        session_date=str(snapshot["session_date"])
    )
    return run_observation(
        snapshot=snapshot,
        previous_closes=closes,
        journal_path=journal_path,
        rehearsal=rehearsal,
        catch_up=catch_up,
    )


def main() -> None:
    print("V11 PHASE 2 FRESH CONFIRMATION OBSERVATION RUNNER")
    print("=" * 80)
    try:
        result = run_from_files()
    except Exception as exc:
        print("Status: DISABLED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Production evidence written: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result.status}")
    print(f"Session: {result.session_date}")
    print(f"Events appended: {result.events_appended}")
    print(f"Session events: {result.total_session_events}")
    print(f"Top 10: {', '.join(result.selected_symbols)}")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
