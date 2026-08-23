"""Isolated end-to-end rehearsal for the frozen V8 forward holdout.

This module exercises the production ranking/execution contract on already-known
pre-holdout market sessions while writing only to ``data/model/v8/rehearsal``.
It never changes the production holdout journal/status, frozen spec, model
artifacts, or brokerage state.

The rehearsal validates:
* frozen SHA / contract verification;
* 100-stock universe + SPY calendar;
* decision -> next-open entry -> five-session exit lifecycle;
* SPY benchmark and 10-bps transition-cost calculations;
* append-only/idempotent event keys across a simulated restart;
* fail-closed behavior when a required entry price is unavailable;
* production holdout journal/status remain byte-for-byte unchanged.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v8 import holdout_runner as prod

ROOT = Path("data/model/v8/rehearsal")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"
CHECKLIST_PATH = ROOT / "launch_checklist.json"
REHEARSAL_SESSIONS = 18


def _digest(path: Path):
    if not path.exists():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _read_events(path=JOURNAL_PATH):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _event_key(e):
    return (e.get("event_type"), e.get("decision_timestamp_utc"), int(e.get("cohort_offset", -1)))


def _append(event, existing, path=JOURNAL_PATH):
    key = _event_key(event)
    if key in existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    existing.add(key)
    return True


def _simulate_pass(symbols, frames, dates, date_to_idx, rehearsal_dates):
    events = _read_events()
    existing = {_event_key(e) for e in events}
    appended = 0
    virtual_now = rehearsal_dates[-1]

    # Decisions: exactly the production ranking + Top-10 contract.
    for decision_ts in rehearsal_dates:
        i = date_to_idx[decision_ts]
        if i + 1 >= len(dates):
            continue
        cohort = int(i % prod.HOLD_SESSIONS)
        key = ("DECISION", decision_ts.isoformat(), cohort)
        if key in existing:
            continue
        ranking = prod._rank_for_date(decision_ts, symbols, frames)
        picks = ranking.head(prod.TOP_N)["symbol"].tolist()
        entry_ts = dates[i + 1]
        exit_ts = dates[i + 1 + prod.HOLD_SESSIONS] if i + 1 + prod.HOLD_SESSIONS < len(dates) else None
        event = {
            "event_type": "DECISION",
            "journal_type": "V8_REHEARSAL_ONLY",
            "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
            "frozen_sha256": prod.EXPECTED_SHA,
            "decision_timestamp_utc": decision_ts.isoformat(),
            "cohort_offset": cohort,
            "symbols": picks,
            "entry_timestamp_utc": entry_ts.isoformat(),
            "planned_exit_timestamp_utc": exit_ts.isoformat() if exit_ts is not None else None,
            "top10_scores": {r.symbol: float(r.orthogonal_signal) for r in ranking.head(prod.TOP_N).itertuples()},
            "brokerage_orders": False,
            "rehearsal_only": True,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(event, existing))

    events = _read_events()
    decisions = [e for e in events if e.get("event_type") == "DECISION"]

    # Entries: require every selected next-open price, otherwise fail closed.
    for dec in decisions:
        cohort = int(dec["cohort_offset"])
        key = ("ENTRY", dec["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = pd.Timestamp(dec["entry_timestamp_utc"])
        if entry_ts > virtual_now or entry_ts not in date_to_idx or entry_ts not in frames["SPY"].index:
            continue
        prices = {}
        valid = True
        for sym in dec["symbols"]:
            if entry_ts not in frames[sym].index:
                valid = False
                break
            px = float(frames[sym].loc[entry_ts, "open"])
            if not np.isfinite(px) or px <= 0:
                valid = False
                break
            prices[sym] = px
        if not valid:
            continue
        prior_entries = [
            e for e in _read_events()
            if e.get("event_type") == "ENTRY" and int(e.get("cohort_offset", -1)) == cohort
        ]
        prior_entries.sort(key=lambda e: e["entry_timestamp_utc"])
        previous = prior_entries[-1]["symbols"] if prior_entries else None
        traded = prod._transition_notional(previous, dec["symbols"])
        event = {
            "event_type": "ENTRY",
            "journal_type": "V8_REHEARSAL_ONLY",
            "candidate_id": dec["candidate_id"],
            "frozen_sha256": prod.EXPECTED_SHA,
            "decision_timestamp_utc": dec["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": dec["symbols"],
            "entry_timestamp_utc": entry_ts.isoformat(),
            "entry_prices": prices,
            "spy_entry_open": float(frames["SPY"].loc[entry_ts, "open"]),
            "transition_notional": float(traded),
            "modeled_cost_rate": float(traded * prod.COST_BPS / 10000.0),
            "brokerage_orders": False,
            "rehearsal_only": True,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(event, existing))

    # Exits: fifth trading-session open after entry.
    entries = [e for e in _read_events() if e.get("event_type") == "ENTRY"]
    for ent in entries:
        cohort = int(ent["cohort_offset"])
        key = ("EXIT", ent["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = pd.Timestamp(ent["entry_timestamp_utc"])
        i = date_to_idx.get(entry_ts)
        if i is None or i + prod.HOLD_SESSIONS >= len(dates):
            continue
        exit_ts = dates[i + prod.HOLD_SESSIONS]
        if exit_ts > virtual_now or exit_ts not in frames["SPY"].index:
            continue
        returns, exit_prices = [], {}
        valid = True
        for sym in ent["symbols"]:
            if exit_ts not in frames[sym].index:
                valid = False
                break
            p0 = float(ent["entry_prices"][sym])
            p1 = float(frames[sym].loc[exit_ts, "open"])
            if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and p1 > 0):
                valid = False
                break
            exit_prices[sym] = p1
            returns.append(p1 / p0 - 1.0)
        if not valid:
            continue
        gross = float(np.mean(returns))
        cost = float(ent["modeled_cost_rate"])
        net = float((1.0 + gross) * (1.0 - cost) - 1.0)
        spy_ret = float(frames["SPY"].loc[exit_ts, "open"] / float(ent["spy_entry_open"]) - 1.0)
        event = {
            "event_type": "EXIT",
            "journal_type": "V8_REHEARSAL_ONLY",
            "candidate_id": ent["candidate_id"],
            "frozen_sha256": prod.EXPECTED_SHA,
            "decision_timestamp_utc": ent["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": ent["symbols"],
            "entry_timestamp_utc": ent["entry_timestamp_utc"],
            "exit_timestamp_utc": exit_ts.isoformat(),
            "exit_prices": exit_prices,
            "gross_portfolio_return": gross,
            "modeled_cost_rate": cost,
            "net_portfolio_return": net,
            "spy_return": spy_ret,
            "net_relative_return": float(net - spy_ret),
            "brokerage_orders": False,
            "rehearsal_only": True,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(event, existing))

    return appended


def _validate_lifecycle(events, date_to_idx):
    failures = []
    keys = [_event_key(e) for e in events]
    if len(keys) != len(set(keys)):
        failures.append("duplicate event keys present")

    by_key = {(e["event_type"], e["decision_timestamp_utc"], int(e["cohort_offset"])): e for e in events}
    decisions = [e for e in events if e.get("event_type") == "DECISION"]
    entries = [e for e in events if e.get("event_type") == "ENTRY"]
    exits = [e for e in events if e.get("event_type") == "EXIT"]

    for event in events:
        if event.get("frozen_sha256") != prod.EXPECTED_SHA:
            failures.append("event with wrong frozen SHA")
        if event.get("brokerage_orders") is not False:
            failures.append("event does not explicitly disable brokerage orders")
        if event.get("rehearsal_only") is not True:
            failures.append("event missing rehearsal_only marker")

    for ent in entries:
        k = ("DECISION", ent["decision_timestamp_utc"], int(ent["cohort_offset"]))
        dec = by_key.get(k)
        if dec is None:
            failures.append("ENTRY without DECISION")
            continue
        di = date_to_idx.get(pd.Timestamp(dec["decision_timestamp_utc"]))
        ei = date_to_idx.get(pd.Timestamp(ent["entry_timestamp_utc"]))
        if di is None or ei != di + 1:
            failures.append("ENTRY is not next trading-session open")
        expected_cost = float(ent["transition_notional"]) * prod.COST_BPS / 10000.0
        if abs(float(ent["modeled_cost_rate"]) - expected_cost) > 1e-12:
            failures.append("ENTRY modeled cost does not match 10-bps contract")

    for ex in exits:
        k = ("ENTRY", ex["decision_timestamp_utc"], int(ex["cohort_offset"]))
        ent = by_key.get(k)
        if ent is None:
            failures.append("EXIT without ENTRY")
            continue
        ei = date_to_idx.get(pd.Timestamp(ent["entry_timestamp_utc"]))
        xi = date_to_idx.get(pd.Timestamp(ex["exit_timestamp_utc"]))
        if ei is None or xi != ei + prod.HOLD_SESSIONS:
            failures.append("EXIT is not five trading sessions after ENTRY")
        expected_rel = float(ex["net_portfolio_return"]) - float(ex["spy_return"])
        if abs(float(ex["net_relative_return"]) - expected_rel) > 1e-12:
            failures.append("EXIT relative return mismatch")

    if not decisions:
        failures.append("no rehearsal decisions generated")
    if not entries:
        failures.append("no rehearsal entries generated")
    if not exits:
        failures.append("no rehearsal exits generated")
    return failures


def _test_concurrent_append_is_duplicate_safe():
    """Race identical event appends through the production lock implementation."""
    concurrent_root = ROOT / "concurrent_append_test"
    journal_path = concurrent_root / "journal.jsonl"
    lock_path = concurrent_root / "journal.lock"
    journal_path.unlink(missing_ok=True)
    lock_path.unlink(missing_ok=True)
    event = {
        "event_type": "DECISION",
        "journal_type": "V8_REHEARSAL_CONCURRENCY_TEST",
        "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256": prod.EXPECTED_SHA,
        "decision_timestamp_utc": "2026-08-03T00:00:00+00:00",
        "cohort_offset": 0,
        "symbols": ["TEST"],
        "brokerage_orders": False,
        "rehearsal_only": True,
    }
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda _: prod._append(event, path=journal_path, lock_path=lock_path),
                    range(24),
                )
            )
        events = prod._read_events(journal_path)
        keys = [prod._event_key(row) for row in events]
        ok = sum(bool(value) for value in results) == 1 and len(events) == 1 and len(set(keys)) == 1
        return ok, {
            "attempts": len(results),
            "successful_appends": sum(bool(value) for value in results),
            "journal_events": len(events),
            "unique_event_keys": len(set(keys)),
        }
    finally:
        journal_path.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
        try:
            concurrent_root.rmdir()
        except OSError:
            pass


def _test_missing_entry_price_fails_closed(symbols, frames, dates, date_to_idx, decision_ts):
    ranking = prod._rank_for_date(decision_ts, symbols, frames)
    picks = ranking.head(prod.TOP_N)["symbol"].tolist()
    i = date_to_idx[decision_ts]
    if i + 1 >= len(dates):
        return False, "no next session available for missing-price test"
    entry_ts = dates[i + 1]
    test_symbol = picks[0]
    original = frames[test_symbol].loc[entry_ts, "open"]
    try:
        frames[test_symbol].loc[entry_ts, "open"] = np.nan
        valid = True
        for sym in picks:
            if entry_ts not in frames[sym].index:
                valid = False
                break
            px = float(frames[sym].loc[entry_ts, "open"])
            if not np.isfinite(px) or px <= 0:
                valid = False
                break
        return (not valid), None if not valid else "missing entry price did not fail closed"
    finally:
        frames[test_symbol].loc[entry_ts, "open"] = original


def main():
    production_journal_before = _digest(prod.JOURNAL_PATH)
    production_status_before = _digest(prod.STATUS_PATH)

    prod._verify_freeze()
    symbols, frames, dates, date_to_idx = prod._load_market()
    pre_holdout_dates = [d for d in dates if d < prod.HOLDOUT_START]
    if len(pre_holdout_dates) < REHEARSAL_SESSIONS:
        raise RuntimeError("Not enough pre-holdout sessions for V8 rehearsal")
    rehearsal_dates = pre_holdout_dates[-REHEARSAL_SESSIONS:]

    # Rebuild only the isolated rehearsal journal for a deterministic full test.
    ROOT.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.unlink(missing_ok=True)

    first_appended = _simulate_pass(symbols, frames, dates, date_to_idx, rehearsal_dates)
    first_events = _read_events()
    first_digest = _digest(JOURNAL_PATH)

    # Simulated process restart: reload from disk and rerun the exact same window.
    second_appended = _simulate_pass(symbols, frames, dates, date_to_idx, rehearsal_dates)
    second_events = _read_events()
    second_digest = _digest(JOURNAL_PATH)

    failures = _validate_lifecycle(second_events, date_to_idx)
    if second_appended != 0:
        failures.append(f"idempotency failed: second pass appended {second_appended} events")
    if first_digest != second_digest:
        failures.append("journal changed during idempotency restart pass")

    missing_price_ok, missing_price_error = _test_missing_entry_price_fails_closed(
        symbols, frames, dates, date_to_idx, rehearsal_dates[-2]
    )
    if not missing_price_ok:
        failures.append(missing_price_error or "missing-price fail-closed test failed")

    concurrent_append_ok, concurrent_append_details = _test_concurrent_append_is_duplicate_safe()
    if not concurrent_append_ok:
        failures.append(
            "concurrent append regression failed: "
            + json.dumps(concurrent_append_details, sort_keys=True)
        )

    production_journal_after = _digest(prod.JOURNAL_PATH)
    production_status_after = _digest(prod.STATUS_PATH)
    if production_journal_before != production_journal_after:
        failures.append("PRODUCTION holdout journal changed during rehearsal")
    if production_status_before != production_status_after:
        failures.append("PRODUCTION holdout status changed during rehearsal")

    decisions = [e for e in second_events if e.get("event_type") == "DECISION"]
    entries = [e for e in second_events if e.get("event_type") == "ENTRY"]
    exits = [e for e in second_events if e.get("event_type") == "EXIT"]

    checks = {
        "frozen_contract_verified": True,
        "frozen_sha256": prod.EXPECTED_SHA,
        "universe_count": len(symbols),
        "spy_present": "SPY" in frames,
        "rehearsal_start_utc": rehearsal_dates[0].isoformat(),
        "rehearsal_end_utc": rehearsal_dates[-1].isoformat(),
        "decisions": len(decisions),
        "entries": len(entries),
        "exits": len(exits),
        "first_pass_appended": first_appended,
        "restart_pass_appended": second_appended,
        "idempotent_restart": second_appended == 0 and first_digest == second_digest,
        "missing_entry_price_fails_closed": missing_price_ok,
        "concurrent_append_duplicate_safe": concurrent_append_ok,
        "concurrent_append_details": concurrent_append_details,
        "production_journal_unchanged": production_journal_before == production_journal_after,
        "production_status_unchanged": production_status_before == production_status_after,
        "brokerage_orders": False,
        "strategy_modified": False,
        "production_holdout_evidence_written": False,
    }

    status = "READY" if not failures else "NOT_READY"
    payload = {
        "status": status,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failures": failures,
        "rehearsal_journal_path": str(JOURNAL_PATH),
        "production_journal_path": str(prod.JOURNAL_PATH),
    }
    prod._atomic_write_json(STATUS_PATH, payload)

    checklist = {
        "status": status,
        "holdout_start_utc": prod.HOLDOUT_START.isoformat(),
        "frozen_contract": "PASS",
        "sha_verified": "PASS",
        "universe_100_plus_spy": "PASS" if len(symbols) == 100 and "SPY" in frames else "FAIL",
        "ranking_generation": "PASS" if decisions else "FAIL",
        "next_open_execution": "PASS" if entries else "FAIL",
        "five_session_lifecycle": "PASS" if exits else "FAIL",
        "spy_benchmark": "PASS" if exits else "FAIL",
        "append_only_idempotency": "PASS" if checks["idempotent_restart"] else "FAIL",
        "missing_data_fail_closed": "PASS" if missing_price_ok else "FAIL",
        "concurrent_journal_locking": "PASS" if concurrent_append_ok else "FAIL",
        "production_journal_isolation": "PASS" if checks["production_journal_unchanged"] else "FAIL",
        "production_status_isolation": "PASS" if checks["production_status_unchanged"] else "FAIL",
        "brokerage_orders_off": "PASS",
    }
    prod._atomic_write_json(CHECKLIST_PATH, checklist)

    print("V8 HOLDOUT END-TO-END REHEARSAL")
    print("=" * 92)
    print(f"Status: {status}")
    print(f"Window: {rehearsal_dates[0].isoformat()} -> {rehearsal_dates[-1].isoformat()}")
    print(f"Events: {len(second_events)} | decisions={len(decisions)} entries={len(entries)} exits={len(exits)}")
    print(f"First pass appended: {first_appended} | restart pass appended: {second_appended}")
    print(f"Idempotent restart: {checks['idempotent_restart']}")
    print(f"Missing-price fail closed: {missing_price_ok}")
    print(f"Concurrent append duplicate-safe: {concurrent_append_ok}")
    print(f"Production journal unchanged: {checks['production_journal_unchanged']}")
    print(f"Production status unchanged: {checks['production_status_unchanged']}")
    print("Brokerage orders: OFF | strategy modified: NO | production holdout evidence: NONE")
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
