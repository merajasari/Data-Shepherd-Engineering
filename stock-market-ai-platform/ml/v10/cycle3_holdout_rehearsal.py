"""Isolated end-to-end rehearsal for the frozen V10 Cycle 3 holdout."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from ml.v10.cycle3_holdout_runner import (
    CANDIDATE_ID,
    COST_BPS,
    EXPECTED_SHA,
    HOLD_SESSIONS,
    HOLDOUT_START,
    JOURNAL_PATH,
    STATUS_PATH,
    TOP_N,
    _append,
    _event_key,
    _load_market,
    _rank_for_date,
    _read_events,
    _transition_notional,
    _verify_freeze,
)

OUTPUT_ROOT = Path("data/model/v10/cycle3/rehearsal")
CHECKLIST_PATH = OUTPUT_ROOT / "launch_checklist.json"


def _sha(path):
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decision_event(decision_ts, cohort, ranking, entry_ts, exit_ts):
    picks = ranking.head(TOP_N)["symbol"].tolist()
    return {
        "event_type": "DECISION",
        "journal_type": "V10_CYCLE3_FROZEN_FORWARD_HOLDOUT_REHEARSAL",
        "candidate_id": CANDIDATE_ID,
        "frozen_sha256": EXPECTED_SHA,
        "decision_timestamp_utc": decision_ts.isoformat(),
        "cohort_offset": cohort,
        "symbols": picks,
        "entry_timestamp_utc": entry_ts.isoformat(),
        "planned_exit_timestamp_utc": (
            exit_ts.isoformat() if exit_ts is not None else None
        ),
        "defensive_active": bool(ranking["defensive_active"].iloc[0]),
        "top10_scores": {
            row.symbol: float(row.score)
            for row in ranking.head(TOP_N).itertuples()
        },
        "brokerage_orders": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _run_pass(journal_path, lock_path, decision_dates, symbols, frames, dates, date_to_idx):
    existing = {_event_key(event) for event in _read_events(journal_path)}
    appended = 0

    for decision_ts in decision_dates:
        index = date_to_idx[decision_ts]
        cohort = int(index % HOLD_SESSIONS)
        if ("DECISION", decision_ts.isoformat(), cohort) in existing:
            continue
        ranking = _rank_for_date(
            decision_ts, symbols, frames, dates, date_to_idx
        )
        entry_ts = dates[index + 1]
        exit_index = index + 1 + HOLD_SESSIONS
        exit_ts = dates[exit_index] if exit_index < len(dates) else None
        event = _decision_event(
            decision_ts, cohort, ranking, entry_ts, exit_ts
        )
        appended += int(
            _append(event, existing, path=journal_path, lock_path=lock_path)
        )

    decisions = [
        event for event in _read_events(journal_path)
        if event.get("event_type") == "DECISION"
    ]
    for decision in decisions:
        cohort = int(decision["cohort_offset"])
        key = ("ENTRY", decision["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = pd.Timestamp(decision["entry_timestamp_utc"])
        prices = {}
        valid = entry_ts in frames["SPY"].index
        for symbol in decision["symbols"]:
            if (
                entry_ts not in frames[symbol].index
                or not np.isfinite(frames[symbol].loc[entry_ts, "open"])
            ):
                valid = False
                break
            prices[symbol] = float(frames[symbol].loc[entry_ts, "open"])
        if not valid:
            continue
        prior = [
            event for event in _read_events(journal_path)
            if event.get("event_type") == "ENTRY"
            and int(event.get("cohort_offset", -1)) == cohort
        ]
        prior.sort(key=lambda event: event["entry_timestamp_utc"])
        previous = prior[-1]["symbols"] if prior else None
        traded = _transition_notional(previous, decision["symbols"])
        event = {
            "event_type": "ENTRY",
            "journal_type": "V10_CYCLE3_FROZEN_FORWARD_HOLDOUT_REHEARSAL",
            "candidate_id": CANDIDATE_ID,
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": decision["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": decision["symbols"],
            "entry_timestamp_utc": entry_ts.isoformat(),
            "entry_prices": prices,
            "spy_entry_open": float(frames["SPY"].loc[entry_ts, "open"]),
            "transition_notional": float(traded),
            "modeled_cost_rate": float(traded * COST_BPS / 10000.0),
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(
            _append(event, existing, path=journal_path, lock_path=lock_path)
        )

    entries = [
        event for event in _read_events(journal_path)
        if event.get("event_type") == "ENTRY"
    ]
    rehearsal_now = dates[-1]
    for entry in entries:
        cohort = int(entry["cohort_offset"])
        key = ("EXIT", entry["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = pd.Timestamp(entry["entry_timestamp_utc"])
        index = date_to_idx[entry_ts]
        if index + HOLD_SESSIONS >= len(dates):
            continue
        exit_ts = dates[index + HOLD_SESSIONS]
        if exit_ts > rehearsal_now:
            continue
        returns = []
        exit_prices = {}
        valid = exit_ts in frames["SPY"].index
        for symbol in entry["symbols"]:
            if exit_ts not in frames[symbol].index:
                valid = False
                break
            p0 = float(entry["entry_prices"][symbol])
            p1 = float(frames[symbol].loc[exit_ts, "open"])
            if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
                valid = False
                break
            exit_prices[symbol] = p1
            returns.append(p1 / p0 - 1.0)
        if not valid:
            continue
        gross = float(np.mean(returns))
        cost = float(entry["modeled_cost_rate"])
        net = float((1.0 + gross) * (1.0 - cost) - 1.0)
        spy_return = float(
            frames["SPY"].loc[exit_ts, "open"] / float(entry["spy_entry_open"]) - 1.0
        )
        event = {
            "event_type": "EXIT",
            "journal_type": "V10_CYCLE3_FROZEN_FORWARD_HOLDOUT_REHEARSAL",
            "candidate_id": CANDIDATE_ID,
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": entry["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": entry["symbols"],
            "entry_timestamp_utc": entry["entry_timestamp_utc"],
            "exit_timestamp_utc": exit_ts.isoformat(),
            "exit_prices": exit_prices,
            "gross_portfolio_return": gross,
            "modeled_cost_rate": cost,
            "net_portfolio_return": net,
            "spy_return": spy_return,
            "net_relative_return": float(net - spy_return),
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(
            _append(event, existing, path=journal_path, lock_path=lock_path)
        )
    return appended


def _missing_price_test(root, symbols, frames, dates, date_to_idx):
    journal = root / "missing_price.jsonl"
    lock = root / "missing_price.lock"
    decision_ts = dates[-12]
    ranking = _rank_for_date(decision_ts, symbols, frames, dates, date_to_idx)
    picked = str(ranking.iloc[0]["symbol"])
    entry_ts = dates[date_to_idx[decision_ts] + 1]
    original = frames[picked].loc[entry_ts, "open"]
    frames[picked].loc[entry_ts, "open"] = np.nan
    try:
        _run_pass(
            journal, lock, [decision_ts], symbols, frames, dates, date_to_idx
        )
        events = _read_events(journal)
    finally:
        frames[picked].loc[entry_ts, "open"] = original
    return (
        sum(event.get("event_type") == "DECISION" for event in events) == 1
        and sum(event.get("event_type") == "ENTRY" for event in events) == 0
    )


def _concurrency_test(root):
    journal = root / "concurrent.jsonl"
    lock = root / "concurrent.lock"
    event = {
        "event_type": "DECISION",
        "decision_timestamp_utc": "2026-08-01T00:00:00+00:00",
        "cohort_offset": 0,
        "candidate_id": CANDIDATE_ID,
        "frozen_sha256": EXPECTED_SHA,
        "brokerage_orders": False,
    }
    def attempt(_):
        return _append(event, path=journal, lock_path=lock)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    return sum(bool(value) for value in results) == 1 and len(_read_events(journal)) == 1


def main():
    production_journal_before = _sha(JOURNAL_PATH)
    production_status_before = _sha(STATUS_PATH)
    _verify_freeze()
    symbols, frames, dates, date_to_idx = _load_market()
    decision_dates = dates[-18:-1]

    with tempfile.TemporaryDirectory(prefix="v10_cycle3_rehearsal_") as temp:
        root = Path(temp)
        journal = root / "journal.jsonl"
        lock = root / "journal.lock"
        first = _run_pass(
            journal, lock, decision_dates, symbols, frames, dates, date_to_idx
        )
        restart = _run_pass(
            journal, lock, decision_dates, symbols, frames, dates, date_to_idx
        )
        events = _read_events(journal)
        missing_price_safe = _missing_price_test(
            root, symbols, frames, dates, date_to_idx
        )
        concurrent_safe = _concurrency_test(root)

    production_journal_after = _sha(JOURNAL_PATH)
    production_status_after = _sha(STATUS_PATH)
    counts = {
        event_type: sum(
            event.get("event_type") == event_type for event in events
        )
        for event_type in ["DECISION", "ENTRY", "EXIT"]
    }
    production_unchanged = (
        production_journal_before == production_journal_after
        and production_status_before == production_status_after
    )
    orders_off = all(event.get("brokerage_orders") is False for event in events)
    ready = all([
        first == len(events),
        restart == 0,
        counts["DECISION"] == 17,
        counts["ENTRY"] == 17,
        counts["EXIT"] == 12,
        missing_price_safe,
        concurrent_safe,
        production_unchanged,
        orders_off,
    ])

    checklist = {
        "status": "READY" if ready else "NOT_READY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_start_utc": decision_dates[0].isoformat(),
        "window_end_utc": decision_dates[-1].isoformat(),
        "events": len(events),
        "decisions": counts["DECISION"],
        "entries": counts["ENTRY"],
        "exits": counts["EXIT"],
        "first_pass_appended": first,
        "restart_pass_appended": restart,
        "idempotent_restart": restart == 0,
        "missing_price_fail_closed": missing_price_safe,
        "concurrent_append_duplicate_safe": concurrent_safe,
        "production_journal_unchanged": (
            production_journal_before == production_journal_after
        ),
        "production_status_unchanged": (
            production_status_before == production_status_after
        ),
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "frozen_sha256": EXPECTED_SHA,
        "strategy_modified": False,
        "v8_modified": False,
        "production_holdout_evidence_created": False,
        "brokerage_orders": False,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CHECKLIST_PATH.write_text(
        json.dumps(checklist, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("V10 CYCLE 3 HOLDOUT END-TO-END REHEARSAL")
    print("=" * 92)
    print(f"Status: {checklist['status']}")
    print(
        f"Window: {checklist['window_start_utc']} -> "
        f"{checklist['window_end_utc']}"
    )
    print(
        f"Events: {checklist['events']} | decisions={checklist['decisions']} "
        f"entries={checklist['entries']} exits={checklist['exits']}"
    )
    print(
        f"First pass appended: {first} | restart pass appended: {restart}"
    )
    print(f"Idempotent restart: {checklist['idempotent_restart']}")
    print(f"Missing-price fail closed: {missing_price_safe}")
    print(f"Concurrent append duplicate-safe: {concurrent_safe}")
    print(
        "Production journal/status unchanged: "
        f"{checklist['production_journal_unchanged']}/"
        f"{checklist['production_status_unchanged']}"
    )
    print("V8 modified: NO | production holdout evidence: NONE")
    print("Brokerage orders: OFF")
    raise SystemExit(0 if ready else 2)


if __name__ == "__main__":
    main()
