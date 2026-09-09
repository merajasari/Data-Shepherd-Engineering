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
V8_CURRENT_RANKINGS_PATH = Path("data/live/v8_latest_rankings.json")
LIVE_QUOTES_PATH = Path("data/live/latest_quotes.json")
ROLLING_QUOTES_PATHS = (
    Path("data/live/iex_24h_5m_v5.json"),
    Path("data/live/iex_24h_5m.json"),
    Path("data/live/iex_24h_5m_legacy.json"),
)
STARTING_EQUITY = 100000.0

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
        _file_signature(V8_CURRENT_RANKINGS_PATH),
        _file_signature(LIVE_QUOTES_PATH),
        *(_file_signature(path) for path in ROLLING_QUOTES_PATHS),
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
            "symbols": list(event.get("symbols", [])),
            "net_portfolio_return": event.get("net_portfolio_return") if event_type == "EXIT" else None,
            "spy_return": event.get("spy_return") if event_type == "EXIT" else None,
            "net_relative_return": event.get("net_relative_return") if event_type == "EXIT" else None,
        })
    return sorted(rows, key=lambda row: row.get("timestamp_utc") or "")


def _as_positive_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _as_utc_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _latest_market_marks(required_symbols=None):
    """Read the newest lightweight cached price for each stock and SPY.

    This intentionally avoids historical Parquet and network calls. The live
    IEX cache supplies regular-session marks; the rolling cache preserves the
    last observed mark when the stream is quiet or the market is closed.
    """
    marks = {}
    required = {
        str(symbol).upper().strip()
        for symbol in (required_symbols or [])
        if str(symbol).strip()
    }

    def consider(symbol, price, timestamp, source):
        symbol = str(symbol or "").upper().strip()
        if required and symbol not in required:
            return
        price = _as_positive_float(price)
        timestamp = _as_utc_timestamp(timestamp)
        if not symbol or price is None or timestamp is None:
            return
        prior = marks.get(symbol)
        if prior is None or timestamp > prior["timestamp"]:
            marks[symbol] = {
                "price": price,
                "timestamp": timestamp,
                "timestamp_utc": timestamp.isoformat(),
                "source": source,
            }

    live = _read_json(LIVE_QUOTES_PATH)
    live_updated = live.get("updated_at")
    for symbol, quote in (live.get("quotes") or {}).items():
        if not isinstance(quote, dict):
            continue
        consider(
            symbol,
            quote.get("reference_price"),
            quote.get("timestamp") or quote.get("received_at") or live_updated,
            "TIINGO_IEX_LIVE_CACHE",
        )

    if required and required.issubset(marks):
        return marks

    for path in ROLLING_QUOTES_PATHS:
        payload = _read_json(path)
        payload_updated = payload.get("updated_at")
        for symbol, rows in (payload.get("series") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in reversed(rows):
                if not isinstance(row, dict):
                    continue
                price = row.get("price")
                timestamp = row.get("t") or row.get("timestamp") or payload_updated
                if _as_positive_float(price) is not None and _as_utc_timestamp(timestamp) is not None:
                    consider(symbol, price, timestamp, "TIINGO_IEX_ROLLING_CACHE")
                    break
        if required and required.issubset(marks):
            break

    return marks


def _cohort_offset(event):
    try:
        return int(event.get("cohort_offset", -1))
    except (TypeError, ValueError):
        return -1


def _entry_identity(event):
    return (event.get("decision_timestamp_utc"), _cohort_offset(event))


def _required_open_mark_symbols(entries, exits):
    exited = {_entry_identity(event) for event in exits}
    required = set()
    for entry in entries:
        if _entry_identity(entry) in exited:
            continue
        required.update(str(symbol).upper() for symbol in (entry.get("symbols") or []))
        required.add("SPY")
    return required


def _mark_to_market(entries, exits, marks):
    """Value currently open frozen-V8 cohorts without creating evidence.

    EXIT events remain the sole source for completed-cohort evidence. Cached
    prices are used only for a clearly labeled, read-only current valuation.
    """
    exited = {_entry_identity(event) for event in exits}
    open_by_cohort = {}
    for entry in sorted(entries, key=lambda row: row.get("entry_timestamp_utc") or ""):
        if _entry_identity(entry) not in exited:
            open_by_cohort[_cohort_offset(entry)] = entry

    wealth = {
        cohort: {"strategy": 1.0, "spy": 1.0, "started": False}
        for cohort in range(5)
    }
    for event in sorted(exits, key=lambda row: row.get("exit_timestamp_utc") or ""):
        cohort = _cohort_offset(event)
        if cohort not in wealth:
            continue
        strategy_return = event.get("net_portfolio_return")
        spy_return = event.get("spy_return")
        if strategy_return is None or spy_return is None:
            continue
        wealth[cohort]["strategy"] *= 1.0 + float(strategy_return)
        wealth[cohort]["spy"] *= 1.0 + float(spy_return)
        wealth[cohort]["started"] = True

    cohort_marks = []
    missing_symbols = set()
    strategy_complete = True
    spy_complete = True
    timestamps = []
    sources = set()

    for cohort, entry in sorted(open_by_cohort.items()):
        if cohort not in wealth:
            continue
        wealth[cohort]["started"] = True
        entry_time = _as_utc_timestamp(entry.get("entry_timestamp_utc"))
        symbols = [str(symbol).upper() for symbol in (entry.get("symbols") or [])]
        entry_prices = entry.get("entry_prices") or {}
        stock_returns = []
        used_marks = []
        cohort_missing = []

        for symbol in symbols:
            entry_price = _as_positive_float(entry_prices.get(symbol))
            mark = marks.get(symbol)
            if (
                entry_price is None
                or mark is None
                or (entry_time is not None and mark["timestamp"] < entry_time)
            ):
                cohort_missing.append(symbol)
                missing_symbols.add(symbol)
                continue
            stock_returns.append(mark["price"] / entry_price - 1.0)
            used_marks.append(mark)

        strategy_return = None
        if symbols and len(stock_returns) == len(symbols):
            gross_return = statistics.mean(stock_returns)
            cost_rate = float(entry.get("modeled_cost_rate") or 0.0)
            strategy_return = (1.0 + gross_return) * (1.0 - cost_rate) - 1.0
            wealth[cohort]["strategy"] *= 1.0 + strategy_return
        else:
            strategy_complete = False

        spy_return = None
        spy_entry = _as_positive_float(entry.get("spy_entry_open"))
        spy_mark = marks.get("SPY")
        if (
            spy_entry is not None
            and spy_mark is not None
            and (entry_time is None or spy_mark["timestamp"] >= entry_time)
        ):
            spy_return = spy_mark["price"] / spy_entry - 1.0
            wealth[cohort]["spy"] *= 1.0 + spy_return
            used_marks.append(spy_mark)
        else:
            spy_complete = False
            missing_symbols.add("SPY")

        timestamps.extend(mark["timestamp"] for mark in used_marks)
        sources.update(mark["source"] for mark in used_marks)
        cohort_marks.append({
            "cohort_offset": cohort,
            "decision_timestamp_utc": entry.get("decision_timestamp_utc"),
            "entry_timestamp_utc": entry.get("entry_timestamp_utc"),
            "symbol_count": len(symbols),
            "priced_symbol_count": len(stock_returns),
            "missing_symbols": cohort_missing,
            "net_mark_to_market_return": strategy_return,
            "spy_mark_to_market_return": spy_return,
        })

    started = [row for row in wealth.values() if row["started"]]
    realized_curve = _curve(exits)
    realized_equity = (
        float(realized_curve[-1]["strategy_normalized"])
        if realized_curve
        else STARTING_EQUITY
    )
    realized_spy_equity = (
        float(realized_curve[-1]["spy_normalized"])
        if realized_curve
        else STARTING_EQUITY
    )

    open_count = len(open_by_cohort)
    live_strategy_available = bool(open_count and started and strategy_complete)
    live_spy_available = bool(open_count and started and spy_complete)
    strategy_equity = (
        STARTING_EQUITY * statistics.mean(row["strategy"] for row in started)
        if live_strategy_available
        else realized_equity
    )
    spy_equity = (
        STARTING_EQUITY * statistics.mean(row["spy"] for row in started)
        if live_spy_available
        else realized_spy_equity
    )
    current_return = strategy_equity / STARTING_EQUITY - 1.0
    current_spy_return = spy_equity / STARTING_EQUITY - 1.0

    if live_strategy_available:
        basis = "LIVE_MARK_TO_MARKET"
    elif exits:
        basis = "COMPLETED_COHORTS_ONLY"
    elif open_count:
        basis = "BASELINE_PRICE_COVERAGE_PENDING"
    else:
        basis = "BASELINE_NO_OPEN_COHORTS"

    return {
        "starting_equity": STARTING_EQUITY,
        "current_equity": strategy_equity,
        "current_return": current_return,
        "current_spy_equity": spy_equity,
        "current_spy_return": current_spy_return,
        "current_excess_return": (
            current_return - current_spy_return
            if live_strategy_available and live_spy_available
            else None
        ),
        "realized_completed_equity": realized_equity,
        "realized_completed_return": realized_equity / STARTING_EQUITY - 1.0,
        "equity_basis": basis,
        "mark_to_market_available": live_strategy_available,
        "spy_mark_to_market_available": live_spy_available,
        "open_cohorts": open_count,
        "priced_open_cohorts": sum(
            row["symbol_count"] > 0 and row["priced_symbol_count"] == row["symbol_count"]
            for row in cohort_marks
        ),
        "missing_mark_symbols": sorted(missing_symbols),
        "valuation_timestamp_utc": max(timestamps).isoformat() if timestamps else None,
        "valuation_oldest_timestamp_utc": min(timestamps).isoformat() if timestamps else None,
        "valuation_sources": sorted(sources),
        "cohort_marks": cohort_marks,
        "valuation_note": (
            "Read-only mark-to-market of open V8 forward cohorts using cached "
            "Tiingo IEX reference prices. It is not completed-cohort evidence "
            "and never writes to the append-only holdout journal."
        ),
    }


def _latest_v8_rankings():
    """Serve the current 100-row JSON ranking without loading historical Parquet."""
    signature = _file_signature(V8_CURRENT_RANKINGS_PATH)
    if _rankings_cache["signature"] == signature and _rankings_cache["payload"] is not None:
        return _rankings_cache["payload"]

    source = _read_json(V8_CURRENT_RANKINGS_PATH)
    raw_rows = source.get("rankings")
    rows = []
    if isinstance(raw_rows, list) and len(raw_rows) == 100:
        for item in raw_rows:
            score = item.get("signal_score", item.get("score"))
            rows.append({
                "rank": item.get("rank"),
                "symbol": item.get("symbol"),
                "score": score,
                "signal_score": score,
                "rank_percentile": item.get("rank_percentile"),
                "selected_top10": bool(item.get("selected_top10")),
                "target_weight": item.get("target_weight", 0.10 if item.get("selected_top10") else 0.0),
            })
        rows.sort(key=lambda row: int(row.get("rank") or 10_000))

    payload = {
        "timestamp_utc": source.get("decision_date_utc") or source.get("ranking_timestamp_utc"),
        "rows": rows,
    }
    _rankings_cache.update({"signature": signature, "payload": payload})
    return payload

def _curve(exits):
    if not exits:
        return []
    by_cohort = {i: {"strategy": 1.0, "spy": 1.0} for i in range(5)}
    started_cohorts = set()
    points = []
    for event in sorted(exits, key=lambda x: x.get("exit_timestamp_utc", "")):
        cohort = int(event["cohort_offset"])
        by_cohort[cohort]["strategy"] *= 1.0 + float(event["net_portfolio_return"])
        by_cohort[cohort]["spy"] *= 1.0 + float(event["spy_return"])
        started_cohorts.add(cohort)
        active = [by_cohort[index] for index in sorted(started_cohorts)]
        points.append({
            "timestamp_utc": event["exit_timestamp_utc"],
            "strategy_normalized": STARTING_EQUITY * sum(v["strategy"] for v in active) / len(active),
            "spy_normalized": STARTING_EQUITY * sum(v["spy"] for v in active) / len(active),
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
    strategy_total = curve[-1]["strategy_normalized"] / STARTING_EQUITY - 1.0 if curve else None
    spy_total = curve[-1]["spy_normalized"] / STARTING_EQUITY - 1.0 if curve else None
    max_drawdown = None
    if curve:
        peak = STARTING_EQUITY
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
    required_marks = _required_open_mark_symbols(entries, exits)
    current_valuation = _mark_to_market(
        entries,
        exits,
        _latest_market_marks(required_marks) if required_marks else {},
    )
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
        **current_valuation,
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
