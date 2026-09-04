"""Prospective paper-forward runner for accelerated V10 Cycle 3 evidence.

Only predictions locked after a completed session and before the next market
open are eligible. Missed decisions are never backfilled. The lane is isolated
from the original January holdout and has no brokerage interface.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.v10.cycle3_accelerated_forward_contract import (
    EXPECTED_CANDIDATE_ID,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_FROZEN_SHA256,
    FIRST_DECISION_SESSION_UTC,
    INDEPENDENT_CONFIRMATION_START_UTC,
    LAST_DECISION_SESSION_UTC,
    load_contract,
    verify_frozen_source,
)
from ml.v10.cycle3_accelerated_forward_journal import (
    AcceleratedEvidenceJournal,
    DEFAULT_JOURNAL_PATH,
    DEFAULT_ROOT,
)
from ml.v10.cycle3_holdout_runner import (
    COST_BPS,
    HOLD_SESSIONS,
    TOP_N,
    _load_market,
    _rank_for_date,
    _transition_notional,
)

NEW_YORK = ZoneInfo("America/New_York")
STATUS_PATH = DEFAULT_ROOT / "status.json"
JOURNAL_TYPE = "V10_CYCLE3_ACCELERATED_PROSPECTIVE_PAPER_FORWARD"


def _as_utc(value: datetime | pd.Timestamp) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        raise ValueError("NOW_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _parse_utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)


def _normalize_timestamp(value: object) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC").normalize()


def _closure_dates(contract: Mapping[str, object]) -> set[date]:
    calendar = contract.get("market_calendar", {})
    values = (
        calendar.get("known_full_closures_2026_utc_dates", [])
        if isinstance(calendar, Mapping)
        else []
    )
    return {date.fromisoformat(str(value)) for value in values}


def _is_market_session(day: date, closures: set[date]) -> bool:
    return day.weekday() < 5 and day not in closures


def _next_market_session(day: date, closures: set[date]) -> date:
    candidate = day + timedelta(days=1)
    while not _is_market_session(candidate, closures):
        candidate += timedelta(days=1)
    return candidate


def _session_lock_window(
    session_timestamp: object,
    closures: set[date],
) -> tuple[datetime, datetime]:
    session_day = pd.Timestamp(session_timestamp).date()
    session_close = datetime.combine(
        session_day, time(16, 5), tzinfo=NEW_YORK
    ).astimezone(timezone.utc)
    next_day = _next_market_session(session_day, closures)
    next_open = datetime.combine(
        next_day, time(9, 30), tzinfo=NEW_YORK
    ).astimezone(timezone.utc)
    return session_close, next_open


def _expected_completed_sessions(
    start: date,
    end: date,
    *,
    now: datetime,
    closures: set[date],
) -> list[date]:
    output: list[date] = []
    cursor = start
    while cursor <= end:
        if _is_market_session(cursor, closures):
            close, _ = _session_lock_window(cursor, closures)
            if now >= close:
                output.append(cursor)
        cursor += timedelta(days=1)
    return output


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _event_base(
    event_type: str,
    decision_timestamp: pd.Timestamp,
    cohort_offset: int,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "journal_type": JOURNAL_TYPE,
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "frozen_sha256": EXPECTED_FROZEN_SHA256,
        "decision_timestamp_utc": decision_timestamp.isoformat(),
        "cohort_offset": int(cohort_offset),
        "created_at_utc": created_at.isoformat(),
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "january_confirmation_modified": False,
    }


def _event_key(event: Mapping[str, object]) -> tuple[object, object, object]:
    return (
        event.get("event_type"),
        event.get("decision_timestamp_utc"),
        event.get("cohort_offset"),
    )


def _prices(
    symbols: list[str],
    frames: Mapping[str, pd.DataFrame],
    timestamp: pd.Timestamp,
) -> dict[str, float] | None:
    output: dict[str, float] = {}
    for symbol in symbols:
        frame = frames.get(symbol)
        if frame is None or timestamp not in frame.index:
            return None
        price = float(frame.loc[timestamp, "open"])
        if not np.isfinite(price) or price <= 0:
            return None
        output[symbol] = price
    return output


def _previous_entry_symbols(
    events: list[dict[str, object]],
    *,
    cohort: int,
    field: str,
) -> list[str] | None:
    prior = [
        event
        for event in events
        if event.get("event_type") == "ENTRY"
        and int(event.get("cohort_offset", -1)) == cohort
        and isinstance(event.get(field), list)
    ]
    prior.sort(key=lambda item: str(item.get("entry_timestamp_utc", "")))
    return list(prior[-1][field]) if prior else None


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + float(value)
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, 1.0 - equity / peak)
    return float(worst)


def promotion_summary(
    events: list[dict[str, object]],
    *,
    operational_failures: list[str] | None = None,
) -> dict[str, object]:
    failures = list(operational_failures or [])
    exits = [event for event in events if event.get("event_type") == "EXIT"]
    counts = {
        str(offset): sum(
            int(event.get("cohort_offset", -1)) == offset for event in exits
        )
        for offset in range(HOLD_SESSIONS)
    }
    complete_blocks = min(counts.values()) if counts else 0
    by_cohort = {
        offset: sorted(
            (
                event
                for event in exits
                if int(event.get("cohort_offset", -1)) == offset
            ),
            key=lambda item: str(item.get("exit_timestamp_utc", "")),
        )
        for offset in range(HOLD_SESSIONS)
    }
    scored_exits = [
        by_cohort[offset][block]
        for block in range(complete_blocks)
        for offset in range(HOLD_SESSIONS)
    ]
    block_rows = []
    for block in range(complete_blocks):
        block_events = [
            by_cohort[offset][block] for offset in range(HOLD_SESSIONS)
        ]
        block_rows.append(
            {
                "net_portfolio_return": float(
                    np.mean(
                        [
                            float(event["net_portfolio_return"])
                            for event in block_events
                        ]
                    )
                ),
                "v10_minus_v8_net_return": float(
                    np.mean(
                        [
                            float(event["v10_minus_v8_net_return"])
                            for event in block_events
                        ]
                    )
                ),
                "net_relative_return": float(
                    np.mean(
                        [
                            float(event["net_relative_return"])
                            for event in block_events
                        ]
                    )
                ),
            }
        )

    if block_rows:
        mean_v10 = float(
            np.mean([row["net_portfolio_return"] for row in block_rows])
        )
        mean_versus_v8 = float(
            np.mean([row["v10_minus_v8_net_return"] for row in block_rows])
        )
        mean_versus_spy = float(
            np.mean([row["net_relative_return"] for row in block_rows])
        )
        v10_drawdowns = []
        v8_drawdowns = []
        for offset in range(HOLD_SESSIONS):
            cohort_events = by_cohort[offset][:complete_blocks]
            v10_drawdowns.append(
                _max_drawdown(
                    [float(event["net_portfolio_return"]) for event in cohort_events]
                )
            )
            v8_drawdowns.append(
                _max_drawdown(
                    [
                        float(event["v8_control_net_portfolio_return"])
                        for event in cohort_events
                    ]
                )
            )
        v10_max_drawdown = max(v10_drawdowns)
        v8_max_drawdown = max(v8_drawdowns)
    else:
        mean_v10 = None
        mean_versus_v8 = None
        mean_versus_spy = None
        v10_max_drawdown = None
        v8_max_drawdown = None

    defensive = [
        event for event in scored_exits if event.get("defensive_active") is True
    ]
    mean_defensive_versus_v8 = (
        float(np.mean([float(event["v10_minus_v8_net_return"]) for event in defensive]))
        if defensive
        else None
    )
    operational_integrity = not failures
    provisional_metrics_pass = bool(
        block_rows
        and mean_v10 is not None
        and mean_v10 > 0.0
        and mean_versus_v8 is not None
        and mean_versus_v8 >= 0.0
        and mean_versus_spy is not None
        and mean_versus_spy >= 0.0
        and v10_max_drawdown is not None
        and v8_max_drawdown is not None
        and v10_max_drawdown <= v8_max_drawdown + 0.10
        and operational_integrity
    )
    stronger_metrics_pass = bool(
        provisional_metrics_pass
        and len(defensive) >= 5
        and mean_defensive_versus_v8 is not None
        and mean_defensive_versus_v8 > 0.0
    )
    provisional_eligible = complete_blocks >= 8 and provisional_metrics_pass
    stronger_eligible = complete_blocks >= 12 and stronger_metrics_pass

    if complete_blocks >= 12:
        review_status = (
            "STRONGER_LIMITED_LIVE_REVIEW_ELIGIBLE"
            if stronger_eligible
            else "STRONGER_REVIEW_BLOCKED"
        )
    elif complete_blocks >= 8:
        review_status = (
            "PROVISIONAL_PAPER_CHAMPION_REVIEW_ELIGIBLE"
            if provisional_eligible
            else "PROVISIONAL_REVIEW_BLOCKED"
        )
    else:
        review_status = "COLLECTING_PROSPECTIVE_EVIDENCE"

    return {
        "review_status": review_status,
        "completed_exits": len(exits),
        "promotion_scored_exits": len(scored_exits),
        "completed_exits_by_cohort": counts,
        "complete_five_sleeve_blocks": complete_blocks,
        "minimum_blocks_for_provisional_review": 8,
        "minimum_blocks_for_stronger_review": 12,
        "mean_net_return_after_cost": mean_v10,
        "mean_v10_minus_v8_net_return": mean_versus_v8,
        "mean_v10_minus_spy_return": mean_versus_spy,
        "v10_max_cohort_drawdown": v10_max_drawdown,
        "v8_max_cohort_drawdown": v8_max_drawdown,
        "completed_defensive_exits": len(defensive),
        "mean_defensive_v10_minus_v8_net_return": mean_defensive_versus_v8,
        "operational_integrity": operational_integrity,
        "operational_failures": failures,
        "provisional_review_eligible": provisional_eligible,
        "stronger_review_eligible": stronger_eligible,
        "automatic_promotion": False,
        "human_review_required": True,
        "overlapping_exits_are_diagnostic_not_independent": True,
    }


def run_once(
    *,
    now_utc: datetime | pd.Timestamp | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
    load_market: Callable[[], tuple[object, object, object, object]] = _load_market,
    rank_for_date: Callable[..., pd.DataFrame] = _rank_for_date,
    verify_source: Callable[[], None] = verify_frozen_source,
) -> dict[str, object]:
    contract = load_contract()
    verify_source()
    now = _as_utc(now_utc or datetime.now(timezone.utc))
    start = _parse_utc(FIRST_DECISION_SESSION_UTC)
    last_decision = _parse_utc(LAST_DECISION_SESSION_UTC)
    confirmation = _parse_utc(INDEPENDENT_CONFIRMATION_START_UTC)
    closures = _closure_dates(contract)
    journal = AcceleratedEvidenceJournal(journal_path)
    events = journal.read()
    appended = 0
    failures: list[str] = []

    if now < start:
        summary = promotion_summary(events)
        payload = {
            "status": "WAITING_FOR_ACCELERATED_BOUNDARY",
            "checked_at_utc": now.isoformat(),
            "first_decision_session_utc": FIRST_DECISION_SESSION_UTC,
            "independent_confirmation_start_utc": (
                INDEPENDENT_CONFIRMATION_START_UTC
            ),
            "contract_sha256": EXPECTED_CONTRACT_SHA256,
            "frozen_sha256": EXPECTED_FROZEN_SHA256,
            "journal_events": len(events),
            "appended_this_run": 0,
            "promotion": summary,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "v8_modified": False,
            "january_confirmation_modified": False,
        }
        _atomic_write(status_path, payload)
        return payload

    if now >= confirmation:
        summary = promotion_summary(events)
        payload = {
            "status": "ACCELERATED_WINDOW_CLOSED_JANUARY_CONFIRMATION_ACTIVE",
            "checked_at_utc": now.isoformat(),
            "first_decision_session_utc": FIRST_DECISION_SESSION_UTC,
            "last_decision_session_utc": LAST_DECISION_SESSION_UTC,
            "independent_confirmation_start_utc": (
                INDEPENDENT_CONFIRMATION_START_UTC
            ),
            "contract_sha256": EXPECTED_CONTRACT_SHA256,
            "frozen_sha256": EXPECTED_FROZEN_SHA256,
            "journal_events": len(events),
            "appended_this_run": 0,
            "promotion": summary,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "v8_modified": False,
            "january_confirmation_modified": False,
        }
        _atomic_write(status_path, payload)
        return payload

    symbols, frames, dates, date_to_idx = load_market()
    dates = [_normalize_timestamp(timestamp) for timestamp in dates]
    date_to_idx = {timestamp: index for index, timestamp in enumerate(dates)}
    observed_dates = {timestamp.date() for timestamp in dates}
    expected = _expected_completed_sessions(
        start.date(),
        min(last_decision.date(), now.date()),
        now=now,
        closures=closures,
    )
    missing_market_sessions = sorted(
        day.isoformat() for day in expected if day not in observed_dates
    )
    if missing_market_sessions:
        failures.append(
            "missing_market_sessions:" + ",".join(missing_market_sessions)
        )

    existing = {_event_key(event) for event in events}
    missed_decisions: list[str] = []
    for decision_ts in dates:
        decision_time = decision_ts.to_pydatetime()
        if decision_time < start or decision_time > last_decision:
            continue
        decision_index = date_to_idx[decision_ts]
        cohort = int(decision_index % HOLD_SESSIONS)
        key = ("DECISION", decision_ts.isoformat(), cohort)
        if key in existing:
            continue
        close, next_open = _session_lock_window(decision_ts, closures)
        if now < close:
            continue
        if now >= next_open:
            missed_decisions.append(decision_ts.date().isoformat())
            continue
        ranking = rank_for_date(
            decision_ts, symbols, frames, dates, date_to_idx
        )
        v10_rows = ranking.sort_values(
            ["score", "symbol"], ascending=[False, True]
        ).head(TOP_N)
        v8_rows = ranking.sort_values(
            ["raw", "symbol"], ascending=[False, True]
        ).head(TOP_N)
        event = _event_base("DECISION", decision_ts, cohort, now)
        event.update(
            {
                "decision_session_close_utc": close.isoformat(),
                "next_session_open_utc": next_open.isoformat(),
                "decision_locked_before_entry": True,
                "symbols": v10_rows["symbol"].tolist(),
                "top10_scores": {
                    row.symbol: float(row.score)
                    for row in v10_rows.itertuples()
                },
                "v8_control_symbols": v8_rows["symbol"].tolist(),
                "v8_control_scores": {
                    row.symbol: float(row.raw)
                    for row in v8_rows.itertuples()
                },
                "defensive_active": bool(
                    ranking["defensive_active"].iloc[0]
                ),
                "missed_decision_backfill": False,
                "v8_production_invoked": False,
                "original_v10_holdout_read": False,
            }
        )
        if journal.append(event):
            appended += 1
            existing.add(key)

    if missed_decisions:
        failures.append("missed_decisions_not_backfilled:" + ",".join(missed_decisions))

    events = journal.read()
    existing = {_event_key(event) for event in events}
    decisions = [event for event in events if event.get("event_type") == "DECISION"]
    for decision in decisions:
        decision_ts = _normalize_timestamp(decision["decision_timestamp_utc"])
        decision_index = date_to_idx.get(decision_ts)
        cohort = int(decision["cohort_offset"])
        key = ("ENTRY", decision["decision_timestamp_utc"], cohort)
        if key in existing or decision_index is None or decision_index + 1 >= len(dates):
            continue
        entry_ts = dates[decision_index + 1]
        if entry_ts.to_pydatetime() >= confirmation:
            failures.append(
                "cross_confirmation_boundary_entry_blocked:"
                + decision_ts.date().isoformat()
            )
            continue
        v10_symbols = list(decision["symbols"])
        v8_symbols = list(decision["v8_control_symbols"])
        v10_prices = _prices(v10_symbols, frames, entry_ts)
        v8_prices = _prices(v8_symbols, frames, entry_ts)
        spy_prices = _prices(["SPY"], frames, entry_ts)
        if v10_prices is None or v8_prices is None or spy_prices is None:
            failures.append(
                "missing_entry_prices:" + decision_ts.date().isoformat()
            )
            continue
        current_events = journal.read()
        prior_v10 = _previous_entry_symbols(
            current_events, cohort=cohort, field="symbols"
        )
        prior_v8 = _previous_entry_symbols(
            current_events, cohort=cohort, field="v8_control_symbols"
        )
        v10_notional = _transition_notional(prior_v10, v10_symbols)
        v8_notional = _transition_notional(prior_v8, v8_symbols)
        event = _event_base("ENTRY", decision_ts, cohort, now)
        event.update(
            {
                "symbols": v10_symbols,
                "entry_timestamp_utc": entry_ts.isoformat(),
                "entry_prices": v10_prices,
                "transition_notional": float(v10_notional),
                "modeled_cost_rate": float(v10_notional * COST_BPS / 10000.0),
                "v8_control_symbols": v8_symbols,
                "v8_control_entry_prices": v8_prices,
                "v8_control_transition_notional": float(v8_notional),
                "v8_control_modeled_cost_rate": float(
                    v8_notional * COST_BPS / 10000.0
                ),
                "spy_entry_open": float(spy_prices["SPY"]),
                "defensive_active": bool(decision["defensive_active"]),
                "v8_production_invoked": False,
                "original_v10_holdout_read": False,
            }
        )
        if journal.append(event):
            appended += 1
            existing.add(key)

    events = journal.read()
    existing = {_event_key(event) for event in events}
    entries = [event for event in events if event.get("event_type") == "ENTRY"]
    for entry in entries:
        decision_ts = _normalize_timestamp(entry["decision_timestamp_utc"])
        cohort = int(entry["cohort_offset"])
        key = ("EXIT", entry["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = _normalize_timestamp(entry["entry_timestamp_utc"])
        entry_index = date_to_idx.get(entry_ts)
        if entry_index is None or entry_index + HOLD_SESSIONS >= len(dates):
            continue
        exit_ts = dates[entry_index + HOLD_SESSIONS]
        exit_close, _ = _session_lock_window(exit_ts, closures)
        if now < exit_close:
            continue
        if exit_ts.to_pydatetime() >= confirmation:
            failures.append(
                "cross_confirmation_boundary_exit_blocked:"
                + decision_ts.date().isoformat()
            )
            continue
        v10_symbols = list(entry["symbols"])
        v8_symbols = list(entry["v8_control_symbols"])
        v10_exit = _prices(v10_symbols, frames, exit_ts)
        v8_exit = _prices(v8_symbols, frames, exit_ts)
        spy_exit = _prices(["SPY"], frames, exit_ts)
        if v10_exit is None or v8_exit is None or spy_exit is None:
            failures.append(
                "missing_exit_prices:" + decision_ts.date().isoformat()
            )
            continue
        v10_returns = [
            v10_exit[symbol] / float(entry["entry_prices"][symbol]) - 1.0
            for symbol in v10_symbols
        ]
        v8_returns = [
            v8_exit[symbol]
            / float(entry["v8_control_entry_prices"][symbol])
            - 1.0
            for symbol in v8_symbols
        ]
        v10_gross = float(np.mean(v10_returns))
        v8_gross = float(np.mean(v8_returns))
        v10_cost = float(entry["modeled_cost_rate"])
        v8_cost = float(entry["v8_control_modeled_cost_rate"])
        v10_net = float((1.0 + v10_gross) * (1.0 - v10_cost) - 1.0)
        v8_net = float((1.0 + v8_gross) * (1.0 - v8_cost) - 1.0)
        spy_return = float(
            spy_exit["SPY"] / float(entry["spy_entry_open"]) - 1.0
        )
        event = _event_base("EXIT", decision_ts, cohort, now)
        event.update(
            {
                "symbols": v10_symbols,
                "entry_timestamp_utc": entry_ts.isoformat(),
                "exit_timestamp_utc": exit_ts.isoformat(),
                "exit_prices": v10_exit,
                "gross_portfolio_return": v10_gross,
                "modeled_cost_rate": v10_cost,
                "net_portfolio_return": v10_net,
                "v8_control_symbols": v8_symbols,
                "v8_control_exit_prices": v8_exit,
                "v8_control_gross_portfolio_return": v8_gross,
                "v8_control_modeled_cost_rate": v8_cost,
                "v8_control_net_portfolio_return": v8_net,
                "v10_minus_v8_net_return": float(v10_net - v8_net),
                "spy_return": spy_return,
                "net_relative_return": float(v10_net - spy_return),
                "defensive_active": bool(entry["defensive_active"]),
                "v8_production_invoked": False,
                "original_v10_holdout_read": False,
            }
        )
        if journal.append(event):
            appended += 1
            existing.add(key)

    events = journal.read()
    summary = promotion_summary(events, operational_failures=failures)
    payload = {
        "status": summary["review_status"],
        "checked_at_utc": now.isoformat(),
        "first_decision_session_utc": FIRST_DECISION_SESSION_UTC,
        "last_decision_session_utc": LAST_DECISION_SESSION_UTC,
        "independent_confirmation_start_utc": (
            INDEPENDENT_CONFIRMATION_START_UTC
        ),
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "frozen_sha256": EXPECTED_FROZEN_SHA256,
        "journal_path": str(journal_path),
        "journal_events": len(events),
        "decisions": sum(event.get("event_type") == "DECISION" for event in events),
        "entries": sum(event.get("event_type") == "ENTRY" for event in events),
        "exits": sum(event.get("event_type") == "EXIT" for event in events),
        "appended_this_run": appended,
        "missing_market_sessions": missing_market_sessions,
        "missed_decisions_not_backfilled": missed_decisions,
        "promotion": summary,
        "automatic_promotion": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v8_production_invoked": False,
        "original_v10_holdout_read": False,
        "january_confirmation_modified": False,
    }
    _atomic_write(status_path, payload)
    return payload


def main() -> None:
    result = run_once()
    print("V10 CYCLE 3 ACCELERATED PROSPECTIVE PAPER FORWARD")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Frozen SHA: {result['frozen_sha256']}")
    print(f"Journal events: {result['journal_events']}")
    print(f"Appended this run: {result['appended_this_run']}")
    promotion = result["promotion"]
    print(
        "Completed five-sleeve blocks: "
        f"{promotion['complete_five_sleeve_blocks']}"
    )
    print(f"Promotion review: {promotion['review_status']}")
    if promotion["operational_failures"]:
        print("Operational exceptions:")
        for failure in promotion["operational_failures"]:
            print(f"  - {failure}")
    print("Automatic promotion: NO | human review required: YES")
    print("Original January confirmation: UNCHANGED")
    print("V8 modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
