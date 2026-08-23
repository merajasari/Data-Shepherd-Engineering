"""Lightweight read-only dashboard service for the frozen V10 Cycle 3 holdout."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time

EXPECTED_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
HOLDOUT_START = "2027-01-04T00:00:00+00:00"
ROOT = Path("data/model/v10/cycle3/holdout")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"
_CACHE_TTL_SECONDS = 10.0
_cache = {"signature": None, "expires_at": 0.0, "payload": None}


def _signature(path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _read_status():
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_events():
    if not JOURNAL_PATH.exists():
        return []
    events = []
    for line_number, raw in enumerate(
        JOURNAL_PATH.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw.strip():
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            return [{"event_type": "JOURNAL_ERROR", "line": line_number}]
    return events


def _curve(exits):
    cohorts = {index: {"strategy": 1.0, "spy": 1.0} for index in range(5)}
    points = []
    for event in sorted(exits, key=lambda item: item.get("exit_timestamp_utc", "")):
        cohort = int(event.get("cohort_offset", 0))
        cohorts[cohort]["strategy"] *= 1.0 + float(event["net_portfolio_return"])
        cohorts[cohort]["spy"] *= 1.0 + float(event["spy_return"])
        active = [
            value for value in cohorts.values()
            if value["strategy"] != 1.0 or value["spy"] != 1.0
        ]
        if active:
            points.append({
                "timestamp_utc": event.get("exit_timestamp_utc"),
                "strategy_normalized": 100000.0 * sum(
                    value["strategy"] for value in active
                ) / len(active),
                "spy_normalized": 100000.0 * sum(
                    value["spy"] for value in active
                ) / len(active),
            })
    return points


def _metrics(exits, curve):
    net = [float(event["net_portfolio_return"]) for event in exits]
    spy = [float(event["spy_return"]) for event in exits]
    relative = [float(event["net_relative_return"]) for event in exits]
    count = len(net)
    strategy_total = curve[-1]["strategy_normalized"] / 100000.0 - 1.0 if curve else None
    spy_total = curve[-1]["spy_normalized"] / 100000.0 - 1.0 if curve else None
    volatility = statistics.stdev(net) if count >= 2 else None
    mean_return = statistics.mean(net) if net else None
    sharpe = (
        mean_return / volatility * math.sqrt(252.0 / 5.0)
        if volatility is not None and volatility > 0 else None
    )
    peak = 100000.0
    drawdowns = []
    for point in curve:
        peak = max(peak, float(point["strategy_normalized"]))
        drawdowns.append(float(point["strategy_normalized"]) / peak - 1.0)
    evidence = (
        "NO_COMPLETED_COHORTS" if count == 0 else
        "INSUFFICIENT_EVIDENCE" if count < 20 else
        "EARLY_EVIDENCE" if count < 60 else
        "EVIDENCE_ACCUMULATING"
    )
    return {
        "evidence_status": evidence,
        "completed_cohorts": count,
        "strategy_total_return": strategy_total,
        "spy_total_return": spy_total,
        "total_relative_return": (
            strategy_total - spy_total
            if strategy_total is not None and spy_total is not None else None
        ),
        "net_relative_hit_rate": (
            sum(value > 0 for value in relative) / len(relative) if relative else None
        ),
        "cohort_return_volatility": volatility,
        "diagnostic_annualized_sharpe": sharpe,
        "max_drawdown": min(drawdowns, default=None),
    }


def get_v10_cycle3_holdout_dashboard():
    signature = (_signature(STATUS_PATH), _signature(JOURNAL_PATH))
    now_mono = time.monotonic()
    if (
        _cache["payload"] is not None
        and _cache["signature"] == signature
        and now_mono < _cache["expires_at"]
    ):
        return _cache["payload"]

    status = _read_status()
    events = _read_events()
    journal_error = any(event.get("event_type") == "JOURNAL_ERROR" for event in events)
    decisions = [event for event in events if event.get("event_type") == "DECISION"]
    entries = [event for event in events if event.get("event_type") == "ENTRY"]
    exits = [
        event for event in events
        if event.get("event_type") == "EXIT"
        and event.get("net_portfolio_return") is not None
        and event.get("spy_return") is not None
        and event.get("net_relative_return") is not None
    ]
    curve = _curve(exits)
    now = datetime.now(timezone.utc)
    boundary = datetime.fromisoformat(HOLDOUT_START)
    state = (
        "JOURNAL_ERROR" if journal_error else
        "WAITING_FOR_HOLDOUT" if now < boundary else
        status.get("status", "ACTIVE_WAITING_FOR_COMPLETED_COHORT")
    )
    payload = {
        "candidate_id": "c3_confirm2_blend50",
        "classification": "FROZEN_FRESH_FORWARD_HOLDOUT",
        "frozen_sha256": EXPECTED_SHA,
        "holdout_start_utc": HOLDOUT_START,
        "state": state,
        "days_until_holdout": max(0, (boundary.date() - now.date()).days),
        "journal_event_count": len(events) if not journal_error else 0,
        "decisions": len(decisions),
        "entries": len(entries),
        **_metrics(exits, curve),
        "curve": curve,
        "modeled_cost_bps": 10,
        "holding_sessions": 5,
        "brokerage_orders": False,
        "v8_modified": False,
        "method_note": (
            "Only completed post-January 4, 2027 cohorts enter performance. "
            "Top 10, next-open entry, five-session hold and 10-bps modeled cost "
            "are frozen. Overlapping cohorts are diagnostic and not independent."
        ),
    }
    _cache.update({
        "signature": signature,
        "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
        "payload": payload,
    })
    return payload
