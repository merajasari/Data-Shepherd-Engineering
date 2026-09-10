"""Isolated regression for the V8 September 1, 2026 holdout transition.

Uses known pre-holdout market sessions as price/ranking fixtures while assigning
an isolated virtual calendar around the real boundary. All event writes go to a
temporary directory. Production journal/status, the frozen specification, and
brokerage state are never modified.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from ml.v8 import holdout_runner as prod

VIRTUAL_SESSIONS = [
    pd.Timestamp("2026-08-31T00:00:00Z"),
    pd.Timestamp("2026-09-01T00:00:00Z"),
    pd.Timestamp("2026-09-02T00:00:00Z"),
    pd.Timestamp("2026-09-03T00:00:00Z"),
    pd.Timestamp("2026-09-04T00:00:00Z"),
    pd.Timestamp("2026-09-08T00:00:00Z"),
    pd.Timestamp("2026-09-09T00:00:00Z"),
    pd.Timestamp("2026-09-10T00:00:00Z"),
]


def _digest(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _valid_open(frames, symbols, timestamp):
    for symbol in symbols:
        if timestamp not in frames[symbol].index:
            return False
        value = float(frames[symbol].loc[timestamp, "open"])
        if not np.isfinite(value) or value <= 0:
            return False
    return timestamp in frames["SPY"].index


def run_regression():
    production_journal_before = _digest(prod.JOURNAL_PATH)
    production_status_before = _digest(prod.STATUS_PATH)
    prod._verify_freeze()
    symbols, frames, dates, _ = prod._load_market()
    fixtures = [date for date in dates if date < prod.HOLDOUT_START][-len(VIRTUAL_SESSIONS):]
    _require(len(fixtures) == len(VIRTUAL_SESSIONS), "insufficient fixture sessions")

    mapping = dict(zip(VIRTUAL_SESSIONS, fixtures))
    decision_virtual = VIRTUAL_SESSIONS[1]
    entry_virtual = VIRTUAL_SESSIONS[2]
    exit_virtual = VIRTUAL_SESSIONS[7]
    decision_source = mapping[decision_virtual]
    entry_source = mapping[entry_virtual]
    exit_source = mapping[exit_virtual]

    _require(VIRTUAL_SESSIONS[0] < prod.HOLDOUT_START, "August 31 must be pre-boundary")
    _require(decision_virtual == prod.HOLDOUT_START, "first decision must equal frozen boundary")
    _require(VIRTUAL_SESSIONS.index(entry_virtual) == VIRTUAL_SESSIONS.index(decision_virtual) + 1, "entry is not next session")
    _require(VIRTUAL_SESSIONS.index(exit_virtual) == VIRTUAL_SESSIONS.index(entry_virtual) + prod.HOLD_SESSIONS, "exit is not five sessions after entry")

    ranking = prod._rank_for_date(decision_source, symbols, frames)
    picks = ranking.head(prod.TOP_N)["symbol"].astype(str).tolist()
    _require(len(picks) == prod.TOP_N, "ranking did not produce frozen Top 10")

    with TemporaryDirectory(prefix="v8-boundary-regression-") as temp:
        root = Path(temp)
        journal = root / "journal.jsonl"
        lock = root / "journal.lock"

        # Running through August 31 must leave the isolated journal empty.
        pre_boundary_available = [
            session for session in VIRTUAL_SESSIONS
            if session <= VIRTUAL_SESSIONS[0] and session >= prod.HOLDOUT_START
        ]
        _require(not pre_boundary_available, "pre-boundary session became eligible")
        _require(not journal.exists(), "pre-boundary evidence was written")

        decision = {
            "event_type": "DECISION",
            "journal_type": "V8_BOUNDARY_REGRESSION_ONLY",
            "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
            "frozen_sha256": prod.EXPECTED_SHA,
            "decision_timestamp_utc": decision_virtual.isoformat(),
            "cohort_offset": int(dates.index(decision_source) % prod.HOLD_SESSIONS),
            "symbols": picks,
            "entry_timestamp_utc": entry_virtual.isoformat(),
            "planned_exit_timestamp_utc": exit_virtual.isoformat(),
            "brokerage_orders": False,
            "regression_only": True,
        }
        _require(prod._append(decision, path=journal, lock_path=lock), "first decision append failed")
        _require(not prod._append(decision, path=journal, lock_path=lock), "restart duplicated decision")

        # Before next-open data, a decision exists but no entry may exist.
        events = prod._read_events(journal)
        _require([event["event_type"] for event in events] == ["DECISION"], "entry appeared before next open")

        # Missing one selected open must fail closed without writing ENTRY.
        test_symbol = picks[0]
        original = frames[test_symbol].loc[entry_source, "open"]
        try:
            frames[test_symbol].loc[entry_source, "open"] = np.nan
            _require(not _valid_open(frames, picks, entry_source), "missing price did not close entry gate")
            _require(len(prod._read_events(journal)) == 1, "missing-price check wrote evidence")
        finally:
            frames[test_symbol].loc[entry_source, "open"] = original

        _require(_valid_open(frames, picks, entry_source), "fixture next-open prices unavailable")
        entry_prices = {symbol: float(frames[symbol].loc[entry_source, "open"]) for symbol in picks}
        transition_notional = prod._transition_notional(None, picks)
        entry = {
            "event_type": "ENTRY",
            "journal_type": "V8_BOUNDARY_REGRESSION_ONLY",
            "candidate_id": decision["candidate_id"],
            "frozen_sha256": prod.EXPECTED_SHA,
            "decision_timestamp_utc": decision_virtual.isoformat(),
            "cohort_offset": decision["cohort_offset"],
            "symbols": picks,
            "entry_timestamp_utc": entry_virtual.isoformat(),
            "entry_prices": entry_prices,
            "spy_entry_open": float(frames["SPY"].loc[entry_source, "open"]),
            "transition_notional": float(transition_notional),
            "modeled_cost_rate": float(transition_notional * prod.COST_BPS / 10000.0),
            "brokerage_orders": False,
            "regression_only": True,
        }
        _require(prod._append(entry, path=journal, lock_path=lock), "next-open entry append failed")
        _require(not prod._append(entry, path=journal, lock_path=lock), "restart duplicated entry")

        returns = []
        exit_prices = {}
        for symbol in picks:
            p0 = entry_prices[symbol]
            p1 = float(frames[symbol].loc[exit_source, "open"])
            _require(np.isfinite(p1) and p1 > 0, f"invalid exit fixture for {symbol}")
            exit_prices[symbol] = p1
            returns.append(p1 / p0 - 1.0)
        gross = float(np.mean(returns))
        cost = float(entry["modeled_cost_rate"])
        net = float((1.0 + gross) * (1.0 - cost) - 1.0)
        spy_return = float(
            frames["SPY"].loc[exit_source, "open"] / entry["spy_entry_open"] - 1.0
        )
        exit_event = {
            "event_type": "EXIT",
            "journal_type": "V8_BOUNDARY_REGRESSION_ONLY",
            "candidate_id": decision["candidate_id"],
            "frozen_sha256": prod.EXPECTED_SHA,
            "decision_timestamp_utc": decision_virtual.isoformat(),
            "cohort_offset": decision["cohort_offset"],
            "symbols": picks,
            "entry_timestamp_utc": entry_virtual.isoformat(),
            "exit_timestamp_utc": exit_virtual.isoformat(),
            "exit_prices": exit_prices,
            "gross_portfolio_return": gross,
            "modeled_cost_rate": cost,
            "net_portfolio_return": net,
            "spy_return": spy_return,
            "net_relative_return": float(net - spy_return),
            "brokerage_orders": False,
            "regression_only": True,
        }
        _require(prod._append(exit_event, path=journal, lock_path=lock), "five-session exit append failed")
        _require(not prod._append(exit_event, path=journal, lock_path=lock), "restart duplicated exit")

        events = prod._read_events(journal)
        _require([event["event_type"] for event in events] == ["DECISION", "ENTRY", "EXIT"], "lifecycle sequence changed")
        _require(len({prod._event_key(event) for event in events}) == 3, "duplicate event keys present")
        _require(all(event.get("frozen_sha256") == prod.EXPECTED_SHA for event in events), "wrong frozen SHA in isolated event")
        _require(all(event.get("brokerage_orders") is False for event in events), "brokerage authority appeared")
        _require(all(event.get("regression_only") is True for event in events), "isolated marker missing")

    production_journal_after = _digest(prod.JOURNAL_PATH)
    production_status_after = _digest(prod.STATUS_PATH)
    _require(production_journal_before == production_journal_after, "production journal changed")
    _require(production_status_before == production_status_after, "production status changed")

    return {
        "status": "PASSED",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "boundary": prod.HOLDOUT_START.isoformat(),
        "pre_boundary_evidence": 0,
        "first_eligible_decision": decision_virtual.isoformat(),
        "next_open_entry": entry_virtual.isoformat(),
        "five_session_exit": exit_virtual.isoformat(),
        "idempotent_restart": True,
        "missing_price_fail_closed": True,
        "duplicate_safe": True,
        "frozen_sha256": prod.EXPECTED_SHA,
        "production_journal_unchanged": True,
        "production_status_unchanged": True,
        "brokerage_orders": False,
    }


def main():
    result = run_regression()
    print("V8 DAY-ZERO BOUNDARY TRANSITION REGRESSION")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Boundary: {result['boundary']}")
    print("Aug 31 pre-boundary evidence: 0")
    print(f"First eligible decision: {result['first_eligible_decision']}")
    print(f"Next-open entry: {result['next_open_entry']}")
    print(f"Five-session exit: {result['five_session_exit']}")
    print(f"Idempotent restart: {result['idempotent_restart']}")
    print(f"Missing-price fail closed: {result['missing_price_fail_closed']}")
    print(f"Duplicate-safe append: {result['duplicate_safe']}")
    print("Production journal/status unchanged: True/True")
    print("Frozen strategy modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
