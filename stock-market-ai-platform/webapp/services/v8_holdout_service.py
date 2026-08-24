"""Read-only V8 frozen holdout dashboard service.

The dashboard hits this endpoint from several independent visual modules. Keep
all expensive parquet work cached in-process so concurrent page initialization
does not repeatedly deserialize the same frozen ranking panel.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import statistics
import time


EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
HOLDOUT_START = datetime(2026, 9, 1, tzinfo=timezone.utc)
ROOT = Path("data/model/v8/holdout")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"
READINESS_PATH = Path("data/model/v8/readiness/status.json")
MONITOR_ALERT_PATH = Path("data/model/v8/monitor/alert_state.json")
V8_RANKED_PATH = Path("data/model/v8/phase4/fixed_complementarity_ranked_panel.parquet")

# A dashboard page currently has multiple independently loaded V8 widgets.  A
# short response cache collapses those requests into one filesystem pass per
# Gunicorn worker, while file signatures still invalidate immediately whenever
# readiness, status, journal, or ranking artifacts change.
_DASHBOARD_TTL_SECONDS = 10.0
_dashboard_cache = {"signature": None, "expires_at": 0.0, "payload": None}
_rankings_cache = {"signature": None, "payload": None}


def _file_signature(path: Path):
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _dashboard_signature():
    return (
        _file_signature(STATUS_PATH),
        _file_signature(READINESS_PATH),
        _file_signature(JOURNAL_PATH),
        _file_signature(MONITOR_ALERT_PATH),
    )


def _read_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _events():
    out = []
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _event_time(event):
    event_type = event.get("event_type")
    if event_type == "EXIT":
        return event.get("exit_timestamp_utc")
    if event_type == "ENTRY":
        return event.get("entry_timestamp_utc")
    return event.get("decision_timestamp_utc")


def _event_history(events):
    rows = []
    for event in events:
        event_type = event.get("event_type")
        if event_type not in {"DECISION", "ENTRY", "EXIT"}:
            continue
        rows.append({
            "event_type": event_type,
            "timestamp_utc": _event_time(event),
            "decision_timestamp_utc": event.get("decision_timestamp_utc"),
            "cohort_offset": event.get("cohort_offset"),
            "symbol_count": len(event.get("symbols", [])),
            "net_portfolio_return": event.get("net_portfolio_return") if event_type == "EXIT" else None,
            "spy_return": event.get("spy_return") if event_type == "EXIT" else None,
            "net_relative_return": event.get("net_relative_return") if event_type == "EXIT" else None,
        })
    return sorted(rows, key=lambda row: row.get("timestamp_utc") or "")


def _latest_v8_rankings():
    """Avoid loading the large historical Phase-4 Parquet in web workers.

    The lightweight readiness artifact is the source for the current frozen
    Top-10 snapshot. Full historical ranking data remains available to offline
    research jobs, but is intentionally excluded from request-time serving.
    """
    return {"timestamp_utc": None, "rows": []}

def _curve(exits):
    if not exits:
        return []
    by_cohort = {i: {"strategy": 1.0, "spy": 1.0} for i in range(5)}
    points = []
    for event in sorted(exits, key=lambda x: x.get("exit_timestamp_utc", "")):
        cohort = int(event["cohort_offset"])
        by_cohort[cohort]["strategy"] *= 1.0 + float(event["net_portfolio_return"])
        by_cohort[cohort]["spy"] *= 1.0 + float(event["spy_return"])
        active = [
            value for value in by_cohort.values()
            if value["strategy"] != 1.0 or value["spy"] != 1.0
        ]
        points.append({
            "timestamp_utc": event["exit_timestamp_utc"],
            "strategy_normalized": 100000.0 * sum(v["strategy"] for v in active) / len(active),
            "spy_normalized": 100000.0 * sum(v["spy"] for v in active) / len(active),
        })
    return points


def _performance_metrics(exits, curve):
    """Diagnostic metrics from genuine completed forward cohorts only."""
    net_returns = [
        float(event["net_portfolio_return"])
        for event in exits
        if event.get("net_portfolio_return") is not None
    ]
    spy_returns = [
        float(event["spy_return"])
        for event in exits
        if event.get("spy_return") is not None
    ]
    relative_returns = [
        float(event["net_relative_return"])
        for event in exits
        if event.get("net_relative_return") is not None
    ]

    completed = len(net_returns)
    strategy_total = curve[-1]["strategy_normalized"] / 100000.0 - 1.0 if curve else None
    spy_total = curve[-1]["spy_normalized"] / 100000.0 - 1.0 if curve else None
    max_drawdown = None
    if curve:
        peak = 100000.0
        drawdowns = []
        for point in curve:
            wealth = float(point["strategy_normalized"])
            peak = max(peak, wealth)
            drawdowns.append(wealth / peak - 1.0)
        max_drawdown = min(drawdowns, default=0.0)

    volatility = statistics.stdev(net_returns) if completed >= 2 else None
    mean_return = statistics.mean(net_returns) if net_returns else None
    # Each observation is a five-session completed cohort. This is diagnostic,
    # not an independence or statistical-significance claim.
    sharpe = (
        mean_return / volatility * math.sqrt(252.0 / 5.0)
        if volatility is not None and volatility > 0
        else None
    )

    if completed == 0:
        evidence_status = "NO_COMPLETED_COHORTS"
    elif completed < 20:
        evidence_status = "INSUFFICIENT_EVIDENCE"
    elif completed < 60:
        evidence_status = "EARLY_EVIDENCE"
    else:
        evidence_status = "EVIDENCE_ACCUMULATING"

    return {
        "evidence_status": evidence_status,
        "minimum_completed_cohorts_for_early_read": 20,
        "completed_cohorts": completed,
        "strategy_total_return": strategy_total,
        "spy_total_return": spy_total,
        "total_relative_return": (
            strategy_total - spy_total
            if strategy_total is not None and spy_total is not None
            else None
        ),
        "mean_net_portfolio_return": mean_return,
        "mean_net_relative_return": (
            statistics.mean(relative_returns) if relative_returns else None
        ),
        "net_relative_hit_rate": (
            sum(value > 0 for value in relative_returns) / len(relative_returns)
            if relative_returns
            else None
        ),
        "cohort_return_volatility": volatility,
        "diagnostic_annualized_sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "metric_note": (
            "Metrics use completed five-session forward cohorts after modeled "
            "10-bps trading costs. Overlapping cohorts are not independent."
        ),
    }


def _first_present(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _launch_operations(status, readiness, events, now):
    monitor = _read_json(MONITOR_ALERT_PATH)
    checked_raw = monitor.get("checked_at_utc")
    monitor_fresh = False
    if checked_raw:
        try:
            checked = datetime.fromisoformat(str(checked_raw).replace("Z", "+00:00"))
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            monitor_fresh = (now - checked.astimezone(timezone.utc)).total_seconds() <= 15 * 60
        except Exception:
            monitor_fresh = False

    last_success = _first_present(
        status,
        "completed_at_utc",
        "updated_at_utc",
        "checked_at_utc",
        "last_success_utc",
        "last_run_utc",
    ) or readiness.get("updated_at_utc")
    if now < HOLDOUT_START:
        next_expected = HOLDOUT_START.isoformat()
    else:
        latest_decision = next(
            (event.get("decision_timestamp_utc") for event in reversed(events)
             if event.get("event_type") == "DECISION"),
            None,
        )
        next_expected = "NEXT_ELIGIBLE_MARKET_CLOSE" if latest_decision else "FIRST_ELIGIBLE_MARKET_CLOSE"

    journal_parent = JOURNAL_PATH.parent
    return {
        "frozen_sha_verified": readiness.get("frozen_sha256") == EXPECTED_SHA
        and bool((readiness.get("checks") or {}).get("frozen_contract_verified")),
        "scheduler_healthy": monitor.get("status") == "HEALTHY" and monitor_fresh,
        "monitor_status": monitor.get("status", "UNKNOWN"),
        "monitor_checked_at_utc": checked_raw,
        "monitor_failures": monitor.get("failures", []),
        "market_data_current": readiness.get("status") == "READY",
        "journal_writable": journal_parent.exists() and os.access(journal_parent, os.W_OK),
        "journal_duplicate_safe": len({
            (e.get("event_type"), e.get("decision_timestamp_utc"), e.get("cohort_offset"))
            for e in events
        }) == len(events),
        "last_successful_orchestration_utc": last_success,
        "next_expected_decision": next_expected,
        "brokerage_orders": False,
        "request_time_historical_parquet_load": False,
        "response_cache_ttl_seconds": _DASHBOARD_TTL_SECONDS,
    }


def get_v8_holdout_dashboard():
    signature = _dashboard_signature()
    now_monotonic = time.monotonic()
    if (
        _dashboard_cache["payload"] is not None
        and _dashboard_cache["signature"] == signature
        and now_monotonic < _dashboard_cache["expires_at"]
    ):
        return _dashboard_cache["payload"]

    now = datetime.now(timezone.utc)
    status = _read_json(STATUS_PATH)
    readiness = _read_json(READINESS_PATH)
    events = _events()
    decisions = [e for e in events if e.get("event_type") == "DECISION"]
    entries = [e for e in events if e.get("event_type") == "ENTRY"]
    exits = [e for e in events if e.get("event_type") == "EXIT"]
    rel = [float(e["net_relative_return"]) for e in exits if e.get("net_relative_return") is not None]
    latest_rankings = _latest_v8_rankings()
    curve = _curve(exits)
    performance = _performance_metrics(exits, curve)
    checks = readiness.get("checks") or {}
    rehearsal_details = checks.get("ranking_top10_details") or []
    rehearsal_symbols = checks.get("ranking_top10") or []

    if rehearsal_details:
        latest_top10 = rehearsal_details[:10]
    elif rehearsal_symbols:
        score_by_symbol = {row["symbol"]: row.get("score") for row in latest_rankings["rows"]}
        latest_top10 = [
            {
                "rank": i + 1,
                "symbol": symbol,
                "score": score_by_symbol.get(symbol),
                "selected_top10": True,
                "target_weight": 0.10,
            }
            for i, symbol in enumerate(rehearsal_symbols[:10])
        ]
    else:
        latest_top10 = latest_rankings["rows"][:10]

    if now < HOLDOUT_START:
        state = "WAITING_FOR_HOLDOUT"
    elif not exits:
        state = status.get("status", "ACTIVE_WAITING_FOR_COMPLETED_COHORT")
    else:
        state = "ACTIVE"

    payload = {
        "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256": EXPECTED_SHA,
        "frozen_sha_verified": readiness.get("frozen_sha256") == EXPECTED_SHA and bool(checks.get("frozen_contract_verified")),
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "state": state,
        "days_until_holdout": max(0, int((HOLDOUT_START - now).total_seconds() // 86400) + (1 if now < HOLDOUT_START else 0)),
        "readiness_status": readiness.get("status", "UNKNOWN"),
        "readiness_updated_at_utc": readiness.get("updated_at_utc"),
        "readiness_failures": readiness.get("failures", []),
        "readiness_warnings": readiness.get("warnings", []),
        "feature_common_latest_utc": checks.get("feature_common_latest_utc"),
        "gold_common_latest_utc": checks.get("gold_common_latest_utc"),
        "ranking_timestamp_utc": checks.get("ranking_timestamp_utc"),
        "ranking_eligible_count": checks.get("ranking_eligible_count"),
        "journal_path": str(JOURNAL_PATH),
        "journal_event_count": len(events),
        "decisions": len(decisions),
        "entries": len(entries),
        "completed_cohorts": len(exits),
        **performance,
        "latest_exit": exits[-1] if exits else None,
        "curve": curve,
        "event_history": _event_history(events),
        "launch_operations": _launch_operations(status, readiness, events, now),
        "latest_research_top10_timestamp_utc": checks.get("ranking_timestamp_utc") or latest_rankings["timestamp_utc"],
        "latest_research_top10": latest_top10,
        "latest_research_top10_note": "Latest frozen-model readiness rehearsal; not forward holdout evidence." if (rehearsal_details or rehearsal_symbols) else "Latest eligible frozen-model development snapshot; not forward holdout evidence.",
        "latest_research_rankings_timestamp_utc": latest_rankings["timestamp_utc"],
        "latest_research_rankings": latest_rankings["rows"],
        "brokerage_orders": False,
        "strategy_modified": False,
    }

    _dashboard_cache["signature"] = signature
    _dashboard_cache["expires_at"] = time.monotonic() + _DASHBOARD_TTL_SECONDS
    _dashboard_cache["payload"] = payload
    return payload
