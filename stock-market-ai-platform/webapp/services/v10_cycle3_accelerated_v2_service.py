"""Read-only dashboard projection for accelerated V10 Cycle 3 evidence.

The service reads only the accelerated contract, status, and hash-chained
journal. It never invokes either V10 runner, reads the January holdout journal,
loads reconstructed history, modifies V8, or reaches a brokerage interface.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import fmean
import time

from ml.v10.cycle3_accelerated_forward_v2_contract import (
    CONTRACT_PATH,
    EXPECTED_CANDIDATE_ID,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_FROZEN_SHA256,
    FIRST_DECISION_SESSION_UTC,
    INDEPENDENT_CONFIRMATION_START_UTC,
    LAST_DECISION_SESSION_UTC,
    load_contract,
)
from ml.v10.cycle3_accelerated_forward_v2_journal import (
    AcceleratedEvidenceCorrupt,
    AcceleratedEvidenceJournal,
    DEFAULT_JOURNAL_PATH,
    DEFAULT_ROOT,
)


STATUS_PATH = DEFAULT_ROOT / "status.json"
DIAGNOSTIC_BACKFILL_PATH = (
    DEFAULT_ROOT / "diagnostics/2026-09-08/decision_reconstruction.json"
)
LIVE_QUOTES_PATH = Path("data/live/latest_quotes.json")
ROLLING_QUOTES_PATHS = (
    Path("data/live/iex_24h_5m_v5.json"),
    Path("data/live/iex_24h_5m.json"),
    Path("data/live/iex_24h_5m_legacy.json"),
)
CACHE_TTL_SECONDS = 10.0
NORMALIZED_STARTING_VALUE = 100_000.0
HOLDING_SLEEVES = 5
PROVISIONAL_BLOCKS = 8
STRONGER_BLOCKS = 12
_CACHE: dict[str, object] = {
    "at": 0.0,
    "signature": None,
    "payload": None,
}


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _read_status() -> tuple[dict[str, object], str | None]:
    if not STATUS_PATH.exists():
        return {}, None
    try:
        payload = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"STATUS_INVALID:{type(exc).__name__}"
    if not isinstance(payload, dict):
        return {}, "STATUS_INVALID:NOT_AN_OBJECT"
    return payload, None


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _positive_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0.0 else None


def _utc_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_market_marks(required_symbols: set[str]) -> dict[str, dict[str, object]]:
    """Read current prices from lightweight local quote caches only."""
    required = {str(symbol).upper() for symbol in required_symbols}
    marks: dict[str, dict[str, object]] = {}

    def consider(symbol: object, price: object, timestamp: object, source: str) -> None:
        ticker = str(symbol or "").upper().strip()
        parsed_price = _positive_number(price)
        parsed_time = _utc_timestamp(timestamp)
        if ticker not in required or parsed_price is None or parsed_time is None:
            return
        prior = marks.get(ticker)
        if prior is None or parsed_time > prior["timestamp"]:
            marks[ticker] = {
                "price": parsed_price,
                "timestamp": parsed_time,
                "source": source,
            }

    live = _read_json(LIVE_QUOTES_PATH)
    live_updated = live.get("updated_at")
    for symbol, quote in (live.get("quotes") or {}).items():
        if isinstance(quote, dict):
            consider(
                symbol,
                quote.get("reference_price"),
                quote.get("timestamp") or quote.get("received_at") or live_updated,
                "TIINGO_IEX_LIVE_CACHE",
            )

    for path in ROLLING_QUOTES_PATHS:
        if required.issubset(marks):
            break
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
                if _positive_number(price) is not None and _utc_timestamp(timestamp) is not None:
                    consider(symbol, price, timestamp, "TIINGO_IEX_ROLLING_CACHE")
                    break
    return marks


def _cohort(event: dict[str, object]) -> int:
    try:
        return int(event.get("cohort_offset", -1))
    except (TypeError, ValueError):
        return -1


def _identity(event: dict[str, object]) -> tuple[object, int]:
    return event.get("decision_timestamp_utc"), _cohort(event)


def _operational_curve(exits: list[dict[str, object]]) -> list[dict[str, object]]:
    wealth = {
        offset: {"v10": 1.0, "v8": 1.0, "spy": 1.0}
        for offset in range(HOLDING_SLEEVES)
    }
    active: set[int] = set()
    points: list[dict[str, object]] = []
    for event in sorted(exits, key=lambda row: str(row.get("exit_timestamp_utc") or "")):
        offset = _cohort(event)
        if offset not in wealth:
            continue
        wealth[offset]["v10"] *= 1.0 + _number(event, "net_portfolio_return")
        wealth[offset]["v8"] *= 1.0 + _number(event, "v8_control_net_portfolio_return")
        wealth[offset]["spy"] *= 1.0 + _number(event, "spy_return")
        active.add(offset)
        points.append(
            {
                "timestamp_utc": event.get("exit_timestamp_utc"),
                "v10_normalized": NORMALIZED_STARTING_VALUE
                * fmean(wealth[item]["v10"] for item in active),
                "v8_normalized": NORMALIZED_STARTING_VALUE
                * fmean(wealth[item]["v8"] for item in active),
                "spy_normalized": NORMALIZED_STARTING_VALUE
                * fmean(wealth[item]["spy"] for item in active),
            }
        )
    return points


def _current_valuation(events: list[dict[str, object]]) -> dict[str, object]:
    """Value open V10 and paired-control sleeves without creating evidence."""
    entries = [row for row in events if row.get("event_type") == "ENTRY"]
    exits = [row for row in events if row.get("event_type") == "EXIT"]
    exited = {_identity(row) for row in exits}
    open_by_cohort: dict[int, dict[str, object]] = {}
    for entry in sorted(entries, key=lambda row: str(row.get("entry_timestamp_utc") or "")):
        if _identity(entry) not in exited:
            open_by_cohort[_cohort(entry)] = entry

    required = {"SPY"}
    for entry in open_by_cohort.values():
        required.update(str(symbol).upper() for symbol in (entry.get("symbols") or []))
        required.update(
            str(symbol).upper()
            for symbol in (entry.get("v8_control_symbols") or [])
        )
    marks = _latest_market_marks(required) if open_by_cohort else {}
    wealth = {
        offset: {"v10": 1.0, "v8": 1.0, "spy": 1.0, "started": False}
        for offset in range(HOLDING_SLEEVES)
    }
    for event in sorted(exits, key=lambda row: str(row.get("exit_timestamp_utc") or "")):
        offset = _cohort(event)
        if offset not in wealth:
            continue
        wealth[offset]["v10"] *= 1.0 + _number(event, "net_portfolio_return")
        wealth[offset]["v8"] *= 1.0 + _number(event, "v8_control_net_portfolio_return")
        wealth[offset]["spy"] *= 1.0 + _number(event, "spy_return")
        wealth[offset]["started"] = True

    complete = {"v10": True, "v8": True, "spy": True}
    missing: set[str] = set()
    timestamps: list[datetime] = []
    sources: set[str] = set()
    cohort_marks: list[dict[str, object]] = []

    def sleeve_return(
        symbols: list[str], prices: object, entry_time: datetime | None
    ) -> tuple[float | None, list[str], list[dict[str, object]]]:
        price_map = prices if isinstance(prices, dict) else {}
        returns: list[float] = []
        absent: list[str] = []
        used: list[dict[str, object]] = []
        for symbol in symbols:
            entry_price = _positive_number(price_map.get(symbol))
            mark = marks.get(symbol)
            if (
                entry_price is None
                or mark is None
                or (entry_time is not None and mark["timestamp"] < entry_time)
            ):
                absent.append(symbol)
                continue
            returns.append(float(mark["price"]) / entry_price - 1.0)
            used.append(mark)
        return (fmean(returns) if symbols and len(returns) == len(symbols) else None), absent, used

    for offset, entry in sorted(open_by_cohort.items()):
        if offset not in wealth:
            continue
        wealth[offset]["started"] = True
        entry_time = _utc_timestamp(entry.get("entry_timestamp_utc"))
        v10_symbols = [str(symbol).upper() for symbol in (entry.get("symbols") or [])]
        v8_symbols = [
            str(symbol).upper() for symbol in (entry.get("v8_control_symbols") or [])
        ]
        v10_gross, v10_missing, used_v10 = sleeve_return(
            v10_symbols, entry.get("entry_prices"), entry_time
        )
        v8_gross, v8_missing, used_v8 = sleeve_return(
            v8_symbols, entry.get("v8_control_entry_prices"), entry_time
        )
        v10_return = None
        if v10_gross is None:
            complete["v10"] = False
        else:
            cost = float(entry.get("modeled_cost_rate") or 0.0)
            v10_return = (1.0 + v10_gross) * (1.0 - cost) - 1.0
            wealth[offset]["v10"] *= 1.0 + v10_return
        v8_return = None
        if v8_gross is None:
            complete["v8"] = False
        else:
            cost = float(entry.get("v8_control_modeled_cost_rate") or 0.0)
            v8_return = (1.0 + v8_gross) * (1.0 - cost) - 1.0
            wealth[offset]["v8"] *= 1.0 + v8_return

        spy_return = None
        spy_entry = _positive_number(entry.get("spy_entry_open"))
        spy_mark = marks.get("SPY")
        if (
            spy_entry is None
            or spy_mark is None
            or (entry_time is not None and spy_mark["timestamp"] < entry_time)
        ):
            complete["spy"] = False
            missing.add("SPY")
            spy_missing = ["SPY"]
            used_spy: list[dict[str, object]] = []
        else:
            spy_return = float(spy_mark["price"]) / spy_entry - 1.0
            wealth[offset]["spy"] *= 1.0 + spy_return
            spy_missing = []
            used_spy = [spy_mark]

        missing.update(v10_missing)
        missing.update(v8_missing)
        used = used_v10 + used_v8 + used_spy
        timestamps.extend(mark["timestamp"] for mark in used)
        sources.update(str(mark["source"]) for mark in used)
        cohort_marks.append(
            {
                "cohort_offset": offset,
                "entry_timestamp_utc": entry.get("entry_timestamp_utc"),
                "v10_return": v10_return,
                "v8_control_return": v8_return,
                "spy_return": spy_return,
                "missing_symbols": sorted(
                    set(v10_missing + v8_missing + spy_missing)
                ),
            }
        )

    started = [row for row in wealth.values() if row["started"]]
    realized_curve = _operational_curve(exits)
    realized = {
        "v10": float(realized_curve[-1]["v10_normalized"])
        if realized_curve else NORMALIZED_STARTING_VALUE,
        "v8": float(realized_curve[-1]["v8_normalized"])
        if realized_curve else NORMALIZED_STARTING_VALUE,
        "spy": float(realized_curve[-1]["spy_normalized"])
        if realized_curve else NORMALIZED_STARTING_VALUE,
    }
    open_count = len(open_by_cohort)

    def equity(key: str) -> float:
        if open_count and started and complete[key]:
            return NORMALIZED_STARTING_VALUE * fmean(float(row[key]) for row in started)
        return realized[key]

    values = {key: equity(key) for key in ("v10", "v8", "spy")}
    returns = {
        key: value / NORMALIZED_STARTING_VALUE - 1.0
        for key, value in values.items()
    }
    live_available = bool(open_count and started and complete["v10"])
    basis = (
        "LIVE_MARK_TO_MARKET" if live_available else
        "COMPLETED_EXITS_ONLY" if exits else
        "BASELINE_PRICE_COVERAGE_PENDING" if open_count else
        "BASELINE_NO_OPEN_COHORTS"
    )
    return {
        "starting_equity": NORMALIZED_STARTING_VALUE,
        "current_equity": values["v10"],
        "current_return": returns["v10"],
        "current_v8_equity": values["v8"],
        "current_v8_return": returns["v8"],
        "current_spy_equity": values["spy"],
        "current_spy_return": returns["spy"],
        "current_excess_vs_v8": returns["v10"] - returns["v8"]
        if live_available and complete["v8"] else None,
        "current_excess_vs_spy": returns["v10"] - returns["spy"]
        if live_available and complete["spy"] else None,
        "equity_basis": basis,
        "mark_to_market_available": live_available,
        "v8_mark_to_market_available": bool(open_count and complete["v8"]),
        "spy_mark_to_market_available": bool(open_count and complete["spy"]),
        "open_cohorts": open_count,
        "priced_open_cohorts": sum(not row["missing_symbols"] for row in cohort_marks),
        "missing_mark_symbols": sorted(missing),
        "valuation_timestamp_utc": max(timestamps).isoformat() if timestamps else None,
        "valuation_oldest_timestamp_utc": min(timestamps).isoformat() if timestamps else None,
        "valuation_sources": sorted(sources),
        "cohort_marks": cohort_marks,
        "operational_curve": realized_curve,
        "valuation_note": (
            "Read-only mark-to-market of open accelerated V10 sleeves, the "
            "paired frozen-V8 control, and SPY using cached Tiingo IEX prices. "
            "It never writes to either evidence journal."
        ),
    }


def _number(event: dict[str, object], field: str) -> float:
    try:
        value = float(event[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"EXIT_{field.upper()}_INVALID") from exc
    if not math.isfinite(value):
        raise ValueError(f"EXIT_{field.upper()}_NOT_FINITE")
    return value


def _max_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0.0:
            worst = max(worst, 1.0 - equity / peak)
    return float(worst)


def _empty_summary() -> dict[str, object]:
    return {
        "completed_exits": 0,
        "promotion_scored_exits": 0,
        "completed_exits_by_cohort": {
            str(offset): 0 for offset in range(HOLDING_SLEEVES)
        },
        "complete_five_sleeve_blocks": 0,
        "mean_net_return_after_cost": None,
        "mean_v10_minus_v8_net_return": None,
        "mean_v10_minus_spy_return": None,
        "v10_max_cohort_drawdown": None,
        "v8_max_cohort_drawdown": None,
        "completed_defensive_exits": 0,
        "mean_defensive_v10_minus_v8_net_return": None,
        "block_curve": [
            {
                "block": 0,
                "completed_at_utc": None,
                "v10_normalized": NORMALIZED_STARTING_VALUE,
                "v8_normalized": NORMALIZED_STARTING_VALUE,
                "spy_normalized": NORMALIZED_STARTING_VALUE,
            }
        ],
        "block_edges": [],
    }


def _summarize_events(events: list[dict[str, object]]) -> dict[str, object]:
    exits = [event for event in events if event.get("event_type") == "EXIT"]
    by_cohort: dict[int, list[dict[str, object]]] = {
        offset: [] for offset in range(HOLDING_SLEEVES)
    }
    for event in exits:
        try:
            cohort = int(event.get("cohort_offset", -1))
        except (TypeError, ValueError) as exc:
            raise ValueError("EXIT_COHORT_INVALID") from exc
        if cohort not in by_cohort:
            raise ValueError("EXIT_COHORT_OUT_OF_RANGE")
        by_cohort[cohort].append(event)
    for cohort_events in by_cohort.values():
        cohort_events.sort(key=lambda item: str(item.get("exit_timestamp_utc", "")))

    counts = {
        str(offset): len(by_cohort[offset])
        for offset in range(HOLDING_SLEEVES)
    }
    complete_blocks = min(counts.values()) if counts else 0
    scored_exits = [
        by_cohort[offset][block]
        for block in range(complete_blocks)
        for offset in range(HOLDING_SLEEVES)
    ]

    v10_value = NORMALIZED_STARTING_VALUE
    v8_value = NORMALIZED_STARTING_VALUE
    spy_value = NORMALIZED_STARTING_VALUE
    curve = list(_empty_summary()["block_curve"])
    edges: list[dict[str, object]] = []
    block_returns: list[dict[str, float]] = []
    for block in range(complete_blocks):
        block_events = [
            by_cohort[offset][block] for offset in range(HOLDING_SLEEVES)
        ]
        v10_return = fmean(
            _number(event, "net_portfolio_return") for event in block_events
        )
        v8_return = fmean(
            _number(event, "v8_control_net_portfolio_return")
            for event in block_events
        )
        spy_return = fmean(
            _number(event, "spy_return") for event in block_events
        )
        v10_minus_v8 = fmean(
            _number(event, "v10_minus_v8_net_return")
            for event in block_events
        )
        v10_minus_spy = fmean(
            _number(event, "net_relative_return") for event in block_events
        )
        completed_at = max(
            str(event.get("exit_timestamp_utc", "")) for event in block_events
        )
        v10_value *= 1.0 + v10_return
        v8_value *= 1.0 + v8_return
        spy_value *= 1.0 + spy_return
        block_returns.append(
            {
                "v10": v10_return,
                "v8": v8_return,
                "spy": spy_return,
                "v10_minus_v8": v10_minus_v8,
                "v10_minus_spy": v10_minus_spy,
            }
        )
        curve.append(
            {
                "block": block + 1,
                "completed_at_utc": completed_at,
                "v10_normalized": v10_value,
                "v8_normalized": v8_value,
                "spy_normalized": spy_value,
            }
        )
        edges.append(
            {
                "block": block + 1,
                "completed_at_utc": completed_at,
                "v10_minus_v8": v10_minus_v8,
                "v10_minus_spy": v10_minus_spy,
            }
        )

    if block_returns:
        mean_v10 = fmean(row["v10"] for row in block_returns)
        mean_v10_minus_v8 = fmean(
            row["v10_minus_v8"] for row in block_returns
        )
        mean_v10_minus_spy = fmean(
            row["v10_minus_spy"] for row in block_returns
        )
        v10_drawdown = max(
            _max_drawdown(
                [
                    _number(event, "net_portfolio_return")
                    for event in by_cohort[offset][:complete_blocks]
                ]
            )
            for offset in range(HOLDING_SLEEVES)
        )
        v8_drawdown = max(
            _max_drawdown(
                [
                    _number(event, "v8_control_net_portfolio_return")
                    for event in by_cohort[offset][:complete_blocks]
                ]
            )
            for offset in range(HOLDING_SLEEVES)
        )
    else:
        mean_v10 = None
        mean_v10_minus_v8 = None
        mean_v10_minus_spy = None
        v10_drawdown = None
        v8_drawdown = None

    defensive = [
        event for event in scored_exits if event.get("defensive_active") is True
    ]
    defensive_edge = (
        fmean(
            _number(event, "v10_minus_v8_net_return") for event in defensive
        )
        if defensive
        else None
    )
    return {
        "completed_exits": len(exits),
        "promotion_scored_exits": len(scored_exits),
        "completed_exits_by_cohort": counts,
        "complete_five_sleeve_blocks": complete_blocks,
        "mean_net_return_after_cost": mean_v10,
        "mean_v10_minus_v8_net_return": mean_v10_minus_v8,
        "mean_v10_minus_spy_return": mean_v10_minus_spy,
        "v10_max_cohort_drawdown": v10_drawdown,
        "v8_max_cohort_drawdown": v8_drawdown,
        "completed_defensive_exits": len(defensive),
        "mean_defensive_v10_minus_v8_net_return": defensive_edge,
        "block_curve": curve,
        "block_edges": edges,
    }


def _gate(
    gate_id: str,
    label: str,
    requirement: str,
    observed: object,
    target: str,
    passed: bool | None,
) -> dict[str, object]:
    return {
        "id": gate_id,
        "label": label,
        "requirement": requirement,
        "observed": observed,
        "target": target,
        "passed": passed,
    }


def _review_projection(
    summary: dict[str, object], operational_integrity: bool
) -> dict[str, object]:
    blocks = int(summary["complete_five_sleeve_blocks"])
    mean_v10 = summary["mean_net_return_after_cost"]
    edge_v8 = summary["mean_v10_minus_v8_net_return"]
    edge_spy = summary["mean_v10_minus_spy_return"]
    v10_drawdown = summary["v10_max_cohort_drawdown"]
    v8_drawdown = summary["v8_max_cohort_drawdown"]
    defensive_count = int(summary["completed_defensive_exits"])
    defensive_edge = summary["mean_defensive_v10_minus_v8_net_return"]
    have_blocks = blocks > 0

    provisional_metrics_pass = bool(
        have_blocks
        and float(mean_v10) > 0.0
        and float(edge_v8) >= 0.0
        and float(edge_spy) >= 0.0
        and float(v10_drawdown) <= float(v8_drawdown) + 0.10
        and operational_integrity
    )
    stronger_metrics_pass = bool(
        provisional_metrics_pass
        and defensive_count >= 5
        and defensive_edge is not None
        and float(defensive_edge) > 0.0
    )
    provisional_eligible = blocks >= PROVISIONAL_BLOCKS and provisional_metrics_pass
    stronger_eligible = blocks >= STRONGER_BLOCKS and stronger_metrics_pass
    if blocks >= STRONGER_BLOCKS:
        review_status = (
            "STRONGER_LIMITED_LIVE_REVIEW_ELIGIBLE"
            if stronger_eligible
            else "STRONGER_REVIEW_BLOCKED"
        )
    elif blocks >= PROVISIONAL_BLOCKS:
        review_status = (
            "PROVISIONAL_PAPER_CHAMPION_REVIEW_ELIGIBLE"
            if provisional_eligible
            else "PROVISIONAL_REVIEW_BLOCKED"
        )
    else:
        review_status = "COLLECTING_PROSPECTIVE_EVIDENCE"

    return {
        "review_status": review_status,
        "minimum_blocks_for_provisional_review": PROVISIONAL_BLOCKS,
        "minimum_blocks_for_stronger_review": STRONGER_BLOCKS,
        "provisional_metrics_pass": provisional_metrics_pass,
        "stronger_metrics_pass": stronger_metrics_pass,
        "provisional_review_eligible": provisional_eligible,
        "stronger_review_eligible": stronger_eligible,
        "automatic_promotion": False,
        "human_review_required": True,
        "overlapping_exits_are_diagnostic_not_independent": True,
        "promotion_gates": [
            _gate(
                "net_return",
                "Mean complete-block V10 return after modeled cost",
                "PROVISIONAL",
                mean_v10,
                "> 0.00%",
                float(mean_v10) > 0.0 if mean_v10 is not None else None,
            ),
            _gate(
                "v8_edge",
                "Mean paired V10 minus V8 edge",
                "PROVISIONAL",
                edge_v8,
                "≥ 0.00%",
                float(edge_v8) >= 0.0 if edge_v8 is not None else None,
            ),
            _gate(
                "spy_edge",
                "Mean paired V10 minus SPY edge",
                "PROVISIONAL",
                edge_spy,
                "≥ 0.00%",
                float(edge_spy) >= 0.0 if edge_spy is not None else None,
            ),
            _gate(
                "drawdown",
                "V10 cohort drawdown versus V8 control",
                "PROVISIONAL",
                (
                    float(v10_drawdown) - float(v8_drawdown)
                    if v10_drawdown is not None and v8_drawdown is not None
                    else None
                ),
                "≤ +10.00 percentage points",
                (
                    float(v10_drawdown) <= float(v8_drawdown) + 0.10
                    if v10_drawdown is not None and v8_drawdown is not None
                    else None
                ),
            ),
            _gate(
                "operations",
                "Operational integrity",
                "PROVISIONAL",
                operational_integrity,
                "PASS",
                operational_integrity,
            ),
            _gate(
                "defensive_count",
                "Completed defensive-regime exits",
                "STRONGER",
                defensive_count,
                ">= 5",
                defensive_count >= 5 if blocks >= STRONGER_BLOCKS else None,
            ),
            _gate(
                "defensive_edge",
                "Mean defensive V10 minus V8 return",
                "STRONGER",
                defensive_edge,
                "> 0.00%",
                (
                    float(defensive_edge) > 0.0
                    if blocks >= STRONGER_BLOCKS and defensive_edge is not None
                    else None
                ),
            ),
        ],
    }


def _status_matches_journal(
    status_promotion: object, summary: dict[str, object]
) -> bool:
    if not isinstance(status_promotion, dict):
        return False
    exact_fields = (
        "completed_exits",
        "promotion_scored_exits",
        "completed_exits_by_cohort",
        "complete_five_sleeve_blocks",
        "completed_defensive_exits",
    )
    return all(status_promotion.get(field) == summary.get(field) for field in exact_fields)


def get_v10_cycle3_accelerated_dashboard() -> dict[str, object]:
    """Return the accelerated evidence projection without invoking a runner."""
    now_monotonic = time.monotonic()
    signature = (
        _signature(CONTRACT_PATH),
        _signature(STATUS_PATH),
        _signature(DEFAULT_JOURNAL_PATH),
        _signature(DIAGNOSTIC_BACKFILL_PATH),
        _signature(LIVE_QUOTES_PATH),
        *(_signature(path) for path in ROLLING_QUOTES_PATHS),
    )
    cached = _CACHE.get("payload")
    if (
        isinstance(cached, dict)
        and _CACHE.get("signature") == signature
        and now_monotonic - float(_CACHE.get("at") or 0.0) < CACHE_TTL_SECONDS
    ):
        return deepcopy(cached)

    service_failures: list[str] = []
    try:
        load_contract()
        contract_verified = True
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        contract_verified = False
        service_failures.append(f"CONTRACT_INVALID:{type(exc).__name__}")

    status, status_error = _read_status()
    diagnostic_backfill = _read_json(DIAGNOSTIC_BACKFILL_PATH)
    diagnostic_backfill_valid = bool(
        diagnostic_backfill
        and diagnostic_backfill.get("classification")
        == "RETROSPECTIVE_DIAGNOSTIC_BACKFILL_NOT_PROSPECTIVE_EVIDENCE"
        and diagnostic_backfill.get("target_decision_session_utc")
        == "2026-09-08T00:00:00+00:00"
        and diagnostic_backfill.get("prospective_evidence") is False
        and diagnostic_backfill.get("promotion_eligible") is False
        and diagnostic_backfill.get("v1_journal_appended") is False
        and diagnostic_backfill.get("brokerage_orders") is False
    )
    if DIAGNOSTIC_BACKFILL_PATH.exists() and not diagnostic_backfill_valid:
        service_failures.append("DIAGNOSTIC_BACKFILL_ARTIFACT_INVALID")
    if status_error:
        service_failures.append(status_error)
    elif not status:
        service_failures.append("STATUS_NOT_PUBLISHED")

    journal_error: str | None = None
    try:
        events = AcceleratedEvidenceJournal(DEFAULT_JOURNAL_PATH).read()
    except (AcceleratedEvidenceCorrupt, OSError) as exc:
        journal_error = str(exc)
        service_failures.append(f"JOURNAL_INVALID:{journal_error}")
        events = []

    try:
        summary = _summarize_events(events)
    except (TypeError, ValueError) as exc:
        service_failures.append(f"EVIDENCE_METRICS_INVALID:{exc}")
        summary = _empty_summary()

    current_valuation = _current_valuation(events)

    status_promotion = status.get("promotion")
    if status and not _status_matches_journal(status_promotion, summary):
        service_failures.append("STATUS_JOURNAL_COUNT_MISMATCH")

    if status:
        safety_checks = {
            "contract_sha256": EXPECTED_CONTRACT_SHA256,
            "frozen_sha256": EXPECTED_FROZEN_SHA256,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "v8_modified": False,
            "january_confirmation_modified": False,
        }
        for field, expected in safety_checks.items():
            if status.get(field) != expected:
                service_failures.append(f"STATUS_{field.upper()}_MISMATCH")
    service_failures = list(dict.fromkeys(service_failures))

    status_study_failures = status.get("study_integrity_failures")
    if not isinstance(status_study_failures, list):
        status_study_failures = (
            status_promotion.get("operational_failures", [])
            if isinstance(status_promotion, dict)
            else []
        )
    status_current_failures = status.get("current_run_operational_failures", [])
    if not isinstance(status_current_failures, list):
        status_current_failures = ["STATUS_CURRENT_FAILURES_INVALID"]
    status_historical_failures = status.get("historical_integrity_failures")
    if not isinstance(status_historical_failures, list):
        status_historical_failures = [
            str(item)
            for item in status_study_failures
            if str(item).startswith("missed_decisions_not_backfilled:")
        ]

    current_run_failures = list(
        dict.fromkeys(
            service_failures + [str(item) for item in status_current_failures]
        )
    )
    historical_integrity_failures = list(
        dict.fromkeys(str(item) for item in status_historical_failures)
    )
    study_integrity_failures = list(
        dict.fromkeys(
            service_failures + [str(item) for item in status_study_failures]
        )
    )
    current_run_health = bool(status) and not current_run_failures
    if "current_run_health" in status:
        current_run_health = (
            current_run_health and status.get("current_run_health") is True
        )
    study_integrity = bool(status) and not study_integrity_failures
    if "study_integrity" in status:
        study_integrity = study_integrity and status.get("study_integrity") is True
    review = _review_projection(summary, study_integrity)
    now = datetime.now(timezone.utc)
    first_day = datetime.fromisoformat(FIRST_DECISION_SESSION_UTC).date()
    last_day = datetime.fromisoformat(LAST_DECISION_SESSION_UTC).date()
    collection_state = (
        "WAITING_FOR_FIRST_DECISION"
        if now.date() < first_day
        else "ACCELERATED_WINDOW_ACTIVE"
        if now.date() <= last_day
        else "ACCELERATED_WINDOW_CLOSED"
    )
    runner_state = str(status.get("status") or collection_state)
    complete_blocks = int(summary["complete_five_sleeve_blocks"])
    evidence_status = (
        "JOURNAL_ERROR"
        if journal_error
        else "NO_COMPLETE_FIVE_SLEEVE_BLOCKS"
        if complete_blocks == 0
        else "PROVISIONAL_REVIEW_SAMPLE_REACHED"
        if complete_blocks >= PROVISIONAL_BLOCKS
        else "COMPLETE_BLOCKS_ACCUMULATING"
    )

    payload: dict[str, object] = {
        "status": runner_state,
        "collection_state": collection_state,
        "evidence_status": evidence_status,
        "classification": "AUTHORIZED_PROSPECTIVE_PAPER_FORWARD",
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "frozen_sha256": EXPECTED_FROZEN_SHA256,
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "contract_sha_verified": contract_verified,
        "first_decision_session_utc": FIRST_DECISION_SESSION_UTC,
        "last_decision_session_utc": LAST_DECISION_SESSION_UTC,
        "independent_confirmation_start_utc": (
            INDEPENDENT_CONFIRMATION_START_UTC
        ),
        "decisions": sum(
            event.get("event_type") == "DECISION" for event in events
        ),
        "entries": sum(event.get("event_type") == "ENTRY" for event in events),
        "journal_events": len(events),
        **summary,
        **current_valuation,
        **review,
        "operational_status": (
            "CURRENT_RUN_ALERT"
            if not current_run_health
            else "CURRENT_RUN_HEALTHY_STUDY_INTEGRITY_BLOCKED"
            if not study_integrity
            else "HEALTHY"
        ),
        "current_run_status": "HEALTHY" if current_run_health else "ALERT",
        "current_run_health": current_run_health,
        "current_run_operational_failures": current_run_failures,
        "historical_integrity_failures": historical_integrity_failures,
        "study_integrity_status": "PASS" if study_integrity else "BLOCKED",
        "study_integrity": study_integrity,
        "study_integrity_failures": study_integrity_failures,
        "operational_integrity": study_integrity,
        "operational_failures": study_integrity_failures,
        "feature_backend": status.get("feature_backend"),
        "latest_source_session": status.get("latest_source_session"),
        "expected_latest_completed_session": status.get(
            "expected_latest_completed_session"
        ),
        "source_price_symbols_available": status.get(
            "source_price_symbols_available"
        ),
        "source_price_symbols_required": status.get(
            "source_price_symbols_required"
        ),
        "source_session_lag_count": status.get("source_session_lag_count"),
        "source_readiness_status": status.get("source_readiness_status"),
        "latest_lifecycle_event_type": status.get(
            "latest_lifecycle_event_type"
        ),
        "latest_lifecycle_event_at_utc": status.get(
            "latest_lifecycle_event_at_utc"
        ),
        "pending_entry_count": status.get("pending_entry_count", 0),
        "pending_entry_decision_sessions": status.get(
            "pending_entry_decision_sessions", []
        ),
        "pending_exit_count": status.get("pending_exit_count", 0),
        "pending_exit_decision_sessions": status.get(
            "pending_exit_decision_sessions", []
        ),
        "next_expected_lifecycle_event": status.get(
            "next_expected_lifecycle_event"
        ),
        "operational_checked_at_utc": status.get("checked_at_utc"),
        "diagnostic_backfill_status": (
            "RECONSTRUCTED_DIAGNOSTIC_ONLY"
            if diagnostic_backfill_valid
            else "NOT_RECONSTRUCTED"
        ),
        "diagnostic_backfill_target_session": (
            str(diagnostic_backfill.get("target_decision_session_utc", ""))[:10]
            if diagnostic_backfill_valid
            else None
        ),
        "diagnostic_backfill_artifact_sha256": (
            diagnostic_backfill.get("artifact_sha256")
            if diagnostic_backfill_valid
            else None
        ),
        "diagnostic_backfill_promotion_eligible": False,
        "diagnostic_backfill_prospective_evidence": False,
        "status_published": bool(status),
        "journal_error": journal_error,
        "scheduler_interval_seconds": 300,
        "read_only_dashboard": True,
        "runner_invoked": False,
        "historical_reconstruction_read": False,
        "january_holdout_outcomes_read": False,
        "v8_production_invoked": False,
        "v8_modified": False,
        "january_confirmation_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "method_note": (
            "Only complete five-sleeve blocks enter promotion metrics and charts. "
            "Each block contains one completed exit from cohort offsets 0 through 4. "
            "Normalized curves use a hypothetical $100,000 starting basis for display only. "
            "Overlapping exits remain diagnostic, automatic promotion is disabled, "
            "and every promotion requires human review."
        ),
    }
    _CACHE.update(
        {
            "at": now_monotonic,
            "signature": signature,
            "payload": deepcopy(payload),
        }
    )
    return payload
