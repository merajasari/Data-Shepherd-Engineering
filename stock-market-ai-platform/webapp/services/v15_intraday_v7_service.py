"""Lightweight read-only dashboard service for V15 V7 intraday paper shadow."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT = PROJECT_ROOT / "data/research/v15/prospective_v7"
STATUS_PATH = ROOT / "operational_status.json"
JOURNAL_PATH = ROOT / "journal.jsonl"
MODEL_PATH = ROOT / "model_snapshot.json"
CONTRACT_PATH = PROJECT_ROOT / "ml/v15/intraday_prospective_v7_contract.json"
CONTRACT_SHA_PATH = PROJECT_ROOT / "ml/v15/intraday_prospective_v7_contract.sha256"
STARTING_EQUITY = 100000.0
_CACHE_TTL_SECONDS = 10.0
_cache: dict[str, object] = {
    "signature": None,
    "expires_at": 0.0,
    "payload": None,
}


def _signature(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _read_events(
    contract: Mapping[str, object],
) -> tuple[list[dict[str, object]], str | None]:
    if not JOURNAL_PATH.exists():
        return [], None
    events: list[dict[str, object]] = []
    previous: str | None = None
    expected_candidate = contract.get("candidate_id")
    expected_contract = _read_contract_sha()
    boundary = str(
        (contract.get("evidence_boundary") or {}).get("first_eligible_session") or ""
    )
    order = {"DECISION": 0, "ENTRY": 1, "EXIT": 2}
    per_session: dict[str, int] = {}
    try:
        lines = JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], f"JOURNAL_READ_ERROR:{type(exc).__name__}"
    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return [], f"JOURNAL_CORRUPT_LINE_{line_number}"
        if not isinstance(event, dict):
            return [], f"JOURNAL_EVENT_INVALID_LINE_{line_number}"
        unsigned = dict(event)
        embedded = unsigned.pop("event_sha256", None)
        if embedded != _canonical_sha256(unsigned):
            return [], f"JOURNAL_HASH_MISMATCH_LINE_{line_number}"
        if event.get("sequence") != line_number:
            return [], f"JOURNAL_SEQUENCE_INVALID_LINE_{line_number}"
        if event.get("previous_event_sha256") != previous:
            return [], f"JOURNAL_CHAIN_INVALID_LINE_{line_number}"
        event_type = str(event.get("event_type") or "")
        session = str(event.get("session_date") or "")
        if event_type not in order:
            return [], f"JOURNAL_EVENT_TYPE_INVALID_LINE_{line_number}"
        if (
            event.get("candidate_id") != expected_candidate
            or event.get("contract_sha256") != expected_contract
            or event.get("paper_shadow_only") is not True
            or event.get("brokerage_orders") is not False
            or session < boundary
        ):
            return [], f"JOURNAL_IDENTITY_INVALID_LINE_{line_number}"
        expected_order = per_session.get(session, -1) + 1
        if order[event_type] != expected_order:
            return [], f"JOURNAL_LIFECYCLE_INVALID_LINE_{line_number}"
        per_session[session] = order[event_type]
        events.append(event)
        previous = str(embedded)
    return events, None


def _read_contract_sha() -> str | None:
    try:
        value = CONTRACT_SHA_PATH.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def _payload(event: Mapping[str, object] | None) -> dict[str, object]:
    value = (event or {}).get("payload")
    return dict(value) if isinstance(value, Mapping) else {}


def _compounded(values: list[float]) -> float:
    wealth = 1.0
    for value in values:
        wealth *= 1.0 + value
    return wealth - 1.0


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    wealth = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1.0)
    return abs(worst)


def _completed_sessions(
    decisions: list[dict[str, object]],
    exits: list[dict[str, object]],
) -> list[dict[str, object]]:
    exit_by_session = {str(row.get("session_date")): row for row in exits}
    rows = []
    for decision in sorted(decisions, key=lambda row: str(row.get("session_date") or "")):
        session = str(decision.get("session_date") or "")
        decision_payload = _payload(decision)
        trade = bool(decision_payload.get("trade"))
        exit_event = exit_by_session.get(session)
        if trade and exit_event is None:
            continue
        exit_payload = _payload(exit_event)
        rows.append(
            {
                "session_date": session,
                "trade": trade,
                "selected_symbols": list(
                    decision_payload.get("selected_symbols") or []
                ),
                "v15_return": (
                    _number(exit_payload.get("v15_net_return"))
                    if trade
                    else 0.0
                ),
                "v11_return": (
                    _number(exit_payload.get("matched_v11_net_return"))
                    if trade
                    else 0.0
                ),
                "v14_return": (
                    _number(exit_payload.get("matched_v14_context_net_return"))
                    if trade
                    else 0.0
                ),
                "spy_return": (
                    _number(exit_payload.get("matched_spy_return"))
                    if trade
                    else 0.0
                ),
                "stop_count": int(
                    _number(
                        exit_payload.get("v15_stop_triggered_positions"),
                        0,
                    )
                    or 0
                ),
            }
        )
    return rows


def _performance(completed: list[dict[str, object]]) -> dict[str, object]:
    wealth = {"v15": 1.0, "v11": 1.0, "v14": 1.0, "spy": 1.0}
    curve = []
    trade_returns: list[float] = []
    relative_spy: list[float] = []
    for row in completed:
        for key, source in (
            ("v15", "v15_return"),
            ("v11", "v11_return"),
            ("v14", "v14_return"),
            ("spy", "spy_return"),
        ):
            value = _number(row.get(source), 0.0) or 0.0
            wealth[key] *= 1.0 + value
        if row["trade"]:
            v15_return = _number(row.get("v15_return"), 0.0) or 0.0
            spy_return = _number(row.get("spy_return"), 0.0) or 0.0
            trade_returns.append(v15_return)
            relative_spy.append(v15_return - spy_return)
        curve.append(
            {
                "session_date": row["session_date"],
                "event": "TRADE_EXIT" if row["trade"] else "CASH_SESSION",
                "v15_normalized": STARTING_EQUITY * wealth["v15"],
                "v11_normalized": STARTING_EQUITY * wealth["v11"],
                "v14_normalized": STARTING_EQUITY * wealth["v14"],
                "spy_normalized": STARTING_EQUITY * wealth["spy"],
            }
        )
    current = {
        key: STARTING_EQUITY * value for key, value in wealth.items()
    }
    return {
        "starting_equity": STARTING_EQUITY,
        "current_equity": current["v15"],
        "current_v11_equity": current["v11"],
        "current_v14_equity": current["v14"],
        "current_spy_equity": current["spy"],
        "current_return": wealth["v15"] - 1.0,
        "current_v11_return": wealth["v11"] - 1.0,
        "current_v14_return": wealth["v14"] - 1.0,
        "current_spy_return": wealth["spy"] - 1.0,
        "current_excess_v11": wealth["v15"] - wealth["v11"],
        "current_excess_v14": wealth["v15"] - wealth["v14"],
        "current_excess_spy": wealth["v15"] - wealth["spy"],
        "curve": curve,
        "profitable_trade_rate": (
            sum(value > 0.0 for value in trade_returns) / len(trade_returns)
            if trade_returns
            else None
        ),
        "relative_spy_hit_rate": (
            sum(value > 0.0 for value in relative_spy) / len(relative_spy)
            if relative_spy
            else None
        ),
        "max_drawdown": _max_drawdown(trade_returns),
        "worst_trade_return": min(trade_returns, default=None),
        "completed_trade_returns": trade_returns,
    }


def _blocks(
    completed: list[dict[str, object]],
    block_sessions: int,
) -> list[dict[str, object]]:
    rows = []
    for start in range(0, len(completed), block_sessions):
        group = completed[start : start + block_sessions]
        if len(group) != block_sessions:
            break
        returns = {
            name: [
                _number(row.get(field), 0.0) or 0.0
                for row in group
            ]
            for name, field in (
                ("v15", "v15_return"),
                ("v11", "v11_return"),
                ("v14", "v14_return"),
                ("spy", "spy_return"),
            )
        }
        trades = sum(bool(row["trade"]) for row in group)
        values = {name: _compounded(series) for name, series in returns.items()}
        rows.append(
            {
                "block": len(rows) + 1,
                "start_session": group[0]["session_date"],
                "end_session": group[-1]["session_date"],
                "completed_sessions": block_sessions,
                "trades": trades,
                "active": trades > 0,
                "v15_return": values["v15"],
                "v11_return": values["v11"],
                "v14_return": values["v14"],
                "spy_return": values["spy"],
                "v15_minus_v11": values["v15"] - values["v11"],
                "v15_minus_v14": values["v15"] - values["v14"],
                "v15_minus_spy": values["v15"] - values["spy"],
            }
        )
    return rows


def _review(
    completed: list[dict[str, object]],
    performance: Mapping[str, object],
    contract: Mapping[str, object],
    operational_integrity: bool,
) -> dict[str, object]:
    review = contract.get("review") or {}
    gates = review.get("gates") or {}
    block_sessions = int(_number(review.get("block_sessions"), 20) or 20)
    blocks = _blocks(completed, block_sessions)
    active = [row for row in blocks if row["active"]]
    positive_active_share = (
        sum(row["v15_return"] > 0.0 for row in active) / len(active)
        if active
        else None
    )
    non_losing_share = (
        sum(row["v15_return"] >= 0.0 for row in blocks) / len(blocks)
        if blocks
        else None
    )
    completed_trades = sum(bool(row["trade"]) for row in completed)
    checks = {
        "positive_net_return": (
            performance["current_return"] > 0.0 if completed_trades else None
        ),
        "positive_relative_to_matched_v11": (
            performance["current_excess_v11"] > 0.0 if completed_trades else None
        ),
        "positive_relative_to_v14_context": (
            performance["current_excess_v14"] > 0.0 if completed_trades else None
        ),
        "positive_relative_to_matched_spy": (
            performance["current_excess_spy"] > 0.0 if completed_trades else None
        ),
        "maximum_drawdown": (
            performance["max_drawdown"]
            <= float(gates.get("maximum_drawdown_at_most", 0.10))
            if performance["max_drawdown"] is not None
            else None
        ),
        "worst_portfolio_trade": (
            performance["worst_trade_return"]
            >= float(gates.get("worst_portfolio_trade_at_least", -0.02))
            if performance["worst_trade_return"] is not None
            else None
        ),
        "profitable_trade_rate": (
            performance["profitable_trade_rate"]
            >= float(gates.get("profitable_trade_rate_at_least", 0.50))
            if performance["profitable_trade_rate"] is not None
            else None
        ),
        "positive_active_block_share": (
            positive_active_share
            >= float(gates.get("positive_active_block_share_at_least", 0.60))
            if positive_active_share is not None
            else None
        ),
        "non_losing_all_block_share": (
            non_losing_share
            >= float(gates.get("non_losing_all_block_share_at_least", 0.80))
            if non_losing_share is not None
            else None
        ),
        "operational_integrity": operational_integrity,
    }
    minimum_trades = int(_number(review.get("minimum_completed_trades"), 30) or 30)
    minimum_active_blocks = int(_number(review.get("minimum_active_blocks"), 6) or 6)
    sufficient = (
        completed_trades >= minimum_trades
        and len(active) >= minimum_active_blocks
    )
    return {
        "block_sessions": block_sessions,
        "complete_blocks": len(blocks),
        "active_blocks": len(active),
        "sessions_toward_next_block": len(completed) % block_sessions,
        "minimum_completed_trades": minimum_trades,
        "minimum_active_blocks": minimum_active_blocks,
        "positive_active_block_share": positive_active_share,
        "non_losing_all_block_share": non_losing_share,
        "gate_results": checks,
        "review_eligible": sufficient and all(value is True for value in checks.values()),
        "automatic_promotion": False,
        "human_review_required": True,
        "blocks": blocks,
    }


def _coefficients(model: Mapping[str, object]) -> list[dict[str, object]]:
    snapshot = model.get("model_snapshot")
    if not isinstance(snapshot, Mapping):
        return []
    features = list(snapshot.get("feature_names") or [])
    weights = list(snapshot.get("weights") or [])
    means = list(snapshot.get("feature_mean") or [])
    deviations = list(snapshot.get("feature_std") or [])
    rows = []
    for index, feature in enumerate(features):
        coefficient = _number(weights[index] if index < len(weights) else None)
        if coefficient is None:
            continue
        rows.append(
            {
                "feature": str(feature),
                "coefficient": coefficient,
                "absolute_coefficient": abs(coefficient),
                "direction": "POSITIVE" if coefficient >= 0.0 else "NEGATIVE",
                "training_mean": _number(means[index] if index < len(means) else None),
                "training_std": _number(
                    deviations[index] if index < len(deviations) else None
                ),
            }
        )
    return sorted(rows, key=lambda row: row["absolute_coefficient"], reverse=True)


def _latest_decision(
    decisions: list[dict[str, object]],
) -> dict[str, object] | None:
    if not decisions:
        return None
    event = max(decisions, key=lambda row: str(row.get("occurred_at_utc") or ""))
    payload = _payload(event)
    return {
        "session_date": event.get("session_date"),
        "occurred_at_utc": event.get("occurred_at_utc"),
        "trade": bool(payload.get("trade")),
        "cash_fallback": bool(payload.get("cash_fallback")),
        "selected_symbols": list(payload.get("selected_symbols") or []),
        "v11_control_symbols": list(payload.get("v11_control_symbols") or []),
        "v14_control_symbols": list(payload.get("v14_control_symbols") or []),
        "top_n": payload.get("top_n"),
        "predicted_topk_net_return": payload.get("predicted_topk_net_return"),
        "applied_threshold": payload.get("applied_threshold"),
        "participation_quantile": payload.get("participation_quantile"),
        "daily_context_session": payload.get("daily_context_session"),
        "training_cutoff_session": payload.get("training_cutoff_session"),
        "model_snapshot_sha256": payload.get("model_snapshot_sha256"),
        "prepared_artifact_sha256": payload.get("prepared_artifact_sha256"),
        "decision_source_sha256": payload.get("decision_source_sha256"),
        "source_snapshot_sha256": payload.get("source_snapshot_sha256"),
    }


def _open_positions(
    decisions: list[dict[str, object]],
    entries: list[dict[str, object]],
    exits: list[dict[str, object]],
) -> list[dict[str, object]]:
    decisions_by_session = {
        str(row.get("session_date")): row for row in decisions
    }
    exited = {str(row.get("session_date")) for row in exits}
    rows = []
    for entry in entries:
        session = str(entry.get("session_date") or "")
        if session in exited:
            continue
        entry_payload = _payload(entry)
        decision_payload = _payload(decisions_by_session.get(session))
        prices = entry_payload.get("entry_prices") or {}
        for symbol in decision_payload.get("selected_symbols") or []:
            rows.append(
                {
                    "session_date": session,
                    "symbol": symbol,
                    "entry_price": (
                        prices.get(symbol)
                        if isinstance(prices, Mapping)
                        else None
                    ),
                    "exposure": entry_payload.get("maximum_invested_fraction"),
                    "status": "WAITING_FOR_SCHEDULED_EXIT",
                }
            )
    return rows


def _event_history(events: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for event in events:
        payload = _payload(event)
        rows.append(
            {
                "sequence": event.get("sequence"),
                "event_type": event.get("event_type"),
                "session_date": event.get("session_date"),
                "occurred_at_utc": event.get("occurred_at_utc"),
                "trade": payload.get("trade"),
                "selected_symbols": list(payload.get("selected_symbols") or []),
                "predicted_topk_net_return": payload.get(
                    "predicted_topk_net_return"
                ),
                "applied_threshold": payload.get("applied_threshold"),
                "v15_net_return": payload.get("v15_net_return"),
                "matched_v11_net_return": payload.get("matched_v11_net_return"),
                "matched_v14_context_net_return": payload.get(
                    "matched_v14_context_net_return"
                ),
                "matched_spy_return": payload.get("matched_spy_return"),
                "stop_triggered_positions": payload.get(
                    "v15_stop_triggered_positions"
                ),
                "event_sha256": event.get("event_sha256"),
            }
        )
    return sorted(
        rows,
        key=lambda row: int(row.get("sequence") or 0),
        reverse=True,
    )[:100]


def get_v15_intraday_v7_dashboard() -> dict[str, object]:
    signature = tuple(
        _signature(path)
        for path in (
            STATUS_PATH,
            JOURNAL_PATH,
            MODEL_PATH,
            CONTRACT_PATH,
            CONTRACT_SHA_PATH,
        )
    )
    now = time.monotonic()
    if (
        _cache["payload"] is not None
        and _cache["signature"] == signature
        and now < float(_cache["expires_at"])
    ):
        return dict(_cache["payload"])

    contract = _read_json(CONTRACT_PATH)
    status = _read_json(STATUS_PATH)
    model = _read_json(MODEL_PATH)
    events, journal_error = _read_events(contract)
    decisions = [row for row in events if row.get("event_type") == "DECISION"]
    entries = [row for row in events if row.get("event_type") == "ENTRY"]
    exits = [row for row in events if row.get("event_type") == "EXIT"]
    completed = _completed_sessions(decisions, exits)
    performance = _performance(completed)
    operational_failures = list(status.get("operational_failures") or [])
    historical_operational_gaps = list(
        status.get("historical_operational_gaps") or []
    )
    operational_integrity = (
        journal_error is None
        and status.get("current_run_health", True) is True
        and not operational_failures
    )
    review = _review(completed, performance, contract, operational_integrity)
    mechanics = contract.get("frozen_mechanics") or {}
    evidence = contract.get("evidence_boundary") or {}
    training = contract.get("training_policy") or {}
    authority = contract.get("authority") or {}
    model_snapshot = model.get("model_snapshot") or {}
    latest = _latest_decision(decisions)

    state = (
        "JOURNAL_ERROR"
        if journal_error
        else str(status.get("status") or "WAITING_FOR_PROSPECTIVE_BOUNDARY")
    )
    next_event = str(
        status.get("lifecycle_stage")
        or status.get("schedule_state")
        or "WAITING_FOR_PROSPECTIVE_BOUNDARY"
    )
    payload: dict[str, object] = {
        "classification": "PREREGISTERED_PROSPECTIVE_INTRADAY_ML_PAPER_SHADOW",
        "contract_classification": contract.get("classification"),
        "state": state,
        "candidate_id": contract.get("candidate_id"),
        "contract_id": contract.get("contract_id"),
        "contract_sha256": _read_contract_sha(),
        "prepared_artifact_sha256": model.get("prepared_artifact_sha256"),
        "latest_model_sha256": model_snapshot.get("model_sha256"),
        "model_type": "RIDGE_RETURN_REGRESSION_V11_V14_HYBRID",
        "target": model_snapshot.get("target"),
        "features": list(model_snapshot.get("feature_names") or []),
        "coefficients": _coefficients(model),
        "first_eligible_session": evidence.get("first_eligible_session"),
        "next_lifecycle_event": next_event,
        "decision_time_eastern": mechanics.get("decision_time_eastern"),
        "holding_minutes": mechanics.get("holding_minutes"),
        "maximum_invested_fraction": mechanics.get("maximum_invested_fraction"),
        "required_cash_fraction": mechanics.get("required_cash_fraction"),
        "protective_stop_loss_fraction": mechanics.get(
            "protective_stop_loss_fraction"
        ),
        "modeled_total_cost_bps_round_trip": mechanics.get(
            "modeled_total_cost_bps_round_trip"
        ),
        "decision_checkpoint": list(
            (contract.get("lifecycle") or {}).get("decision_checkpoint") or []
        ),
        "entry_checkpoint": list(
            (contract.get("lifecycle") or {}).get("entry_checkpoint") or []
        ),
        "exit_checkpoint": list(
            (contract.get("lifecycle") or {}).get("exit_checkpoint") or []
        ),
        "training_start_session": model.get("eligible_history_start_session"),
        "training_end_session": model.get("eligible_history_end_session"),
        "training_sessions": model.get("eligible_history_sessions"),
        "training_cutoff_session": model_snapshot.get("training_cutoff_session"),
        "training_rows": model_snapshot.get("training_rows"),
        "prepared_model_verified": status.get(
            "model_prepared_and_verified",
            bool(model.get("prepared_artifact_sha256")),
        ),
        "checked_at_utc": status.get("checked_at_utc"),
        "current_run_health": status.get("current_run_health", operational_integrity),
        "operational_failures": operational_failures
        + ([journal_error] if journal_error else []),
        "historical_operational_gaps": historical_operational_gaps,
        "journal_integrity": journal_error is None,
        "journal_error": journal_error,
        "decisions": len(decisions),
        "trade_decisions": sum(
            bool(_payload(row).get("trade")) for row in decisions
        ),
        "cash_decisions": sum(
            not bool(_payload(row).get("trade")) for row in decisions
        ),
        "entries": len(entries),
        "completed_exits": len(exits),
        "completed_sessions": len(completed),
        "journal_events": len(events),
        "latest_decision": latest,
        "open_positions": _open_positions(decisions, entries, exits),
        "event_history": _event_history(events),
        "review": review,
        "review_eligible": review["review_eligible"],
        "historical_v5_result_sha256": (
            (contract.get("heritage") or {}).get("v5_observed_result_sha256")
        ),
        "historical_backward_result_sha256": (
            (contract.get("heritage") or {}).get(
                "backward_robustness_result_sha256"
            )
        ),
        "historical_results_are_v7_evidence": False,
        "historical_reconstruction_read": False,
        "v5_result_artifact_read": False,
        "paper_shadow_only": authority.get("paper_shadow_collection_allowed") is True,
        "model_frozen_for_production": False,
        "automatic_promotion": False,
        "human_review_required": True,
        "brokerage_orders": False,
        "runner_invoked": False,
        "dashboard_network_requests": 0,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v13_modified": False,
        "v14_modified": False,
        "method_note": (
            "V15 V7 is a preregistered intraday ML paper shadow. It combines "
            "V11 completed five-minute features with prior-close V14 context, "
            "uses an immutable ridge-return model prepared before September 21, "
            "2026, invests at most 60%, holds for 120 minutes with a gap-aware "
            "2% protective stop and 10-bps modeled round-trip cost, and compares "
            "the same exposure against matched V11, V14-context, and SPY controls. "
            "Only append-only post-boundary journal events count. Historical V5 "
            "and backward-robustness results are disclosed lineage, not V7 evidence."
        ),
        **performance,
    }
    _cache.update(
        {
            "signature": signature,
            "expires_at": now + _CACHE_TTL_SECONDS,
            "payload": dict(payload),
        }
    )
    return payload
