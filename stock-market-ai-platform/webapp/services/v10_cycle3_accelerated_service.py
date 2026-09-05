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

from ml.v10.cycle3_accelerated_forward_contract import (
    CONTRACT_PATH,
    EXPECTED_CANDIDATE_ID,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_FROZEN_SHA256,
    FIRST_DECISION_SESSION_UTC,
    INDEPENDENT_CONFIRMATION_START_UTC,
    LAST_DECISION_SESSION_UTC,
    load_contract,
)
from ml.v10.cycle3_accelerated_forward_journal import (
    AcceleratedEvidenceCorrupt,
    AcceleratedEvidenceJournal,
    DEFAULT_JOURNAL_PATH,
    DEFAULT_ROOT,
)


STATUS_PATH = DEFAULT_ROOT / "status.json"
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
                "Mean V10 return after modeled cost",
                "PROVISIONAL",
                mean_v10,
                "> 0.00%",
                float(mean_v10) > 0.0 if mean_v10 is not None else None,
            ),
            _gate(
                "v8_edge",
                "Mean paired V10 minus V8 return",
                "PROVISIONAL",
                edge_v8,
                ">= 0.00%",
                float(edge_v8) >= 0.0 if edge_v8 is not None else None,
            ),
            _gate(
                "spy_edge",
                "Mean paired V10 minus SPY return",
                "PROVISIONAL",
                edge_spy,
                ">= 0.00%",
                float(edge_spy) >= 0.0 if edge_spy is not None else None,
            ),
            _gate(
                "drawdown",
                "V10 drawdown versus V8 control",
                "PROVISIONAL",
                (
                    float(v10_drawdown) - float(v8_drawdown)
                    if v10_drawdown is not None and v8_drawdown is not None
                    else None
                ),
                "<= +10.00 percentage points",
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
    )
    cached = _CACHE.get("payload")
    if (
        isinstance(cached, dict)
        and _CACHE.get("signature") == signature
        and now_monotonic - float(_CACHE.get("at") or 0.0) < CACHE_TTL_SECONDS
    ):
        return deepcopy(cached)

    failures: list[str] = []
    try:
        load_contract()
        contract_verified = True
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        contract_verified = False
        failures.append(f"CONTRACT_INVALID:{type(exc).__name__}")

    status, status_error = _read_status()
    if status_error:
        failures.append(status_error)
    elif not status:
        failures.append("STATUS_NOT_PUBLISHED")

    journal_error: str | None = None
    try:
        events = AcceleratedEvidenceJournal(DEFAULT_JOURNAL_PATH).read()
    except (AcceleratedEvidenceCorrupt, OSError) as exc:
        journal_error = str(exc)
        failures.append(f"JOURNAL_INVALID:{journal_error}")
        events = []

    try:
        summary = _summarize_events(events)
    except (TypeError, ValueError) as exc:
        failures.append(f"EVIDENCE_METRICS_INVALID:{exc}")
        summary = _empty_summary()

    status_promotion = status.get("promotion")
    if status and not _status_matches_journal(status_promotion, summary):
        failures.append("STATUS_JOURNAL_COUNT_MISMATCH")
    if isinstance(status_promotion, dict):
        failures.extend(
            str(item) for item in status_promotion.get("operational_failures", [])
        )

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
                failures.append(f"STATUS_{field.upper()}_MISMATCH")
    failures = list(dict.fromkeys(failures))

    operational_integrity = bool(status) and not failures
    review = _review_projection(summary, operational_integrity)
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
        **review,
        "operational_status": "HEALTHY" if operational_integrity else "ALERT",
        "operational_integrity": operational_integrity,
        "operational_failures": failures,
        "operational_checked_at_utc": status.get("checked_at_utc"),
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
