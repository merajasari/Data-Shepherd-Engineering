"""Lightweight read-only dashboard service for StockEagle250 Autonomous ML prospective evidence."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time


ROOT = Path("data/model/stock_eagle_250_autonomous_ml_prospective_v1")
PHASE2_MANIFEST_PATH = ROOT / "phase2" / "manifest.json"
PHASE3_ROOT = ROOT / "phase3"
STATUS_PATH = PHASE3_ROOT / "status.json"
JOURNAL_PATH = PHASE3_ROOT / "journal.jsonl"
CONTRACT_PATH = Path(
    "ml/stock_eagle_250_autonomous_ml_prospective_v1/phase3_contract.json"
)

STARTING_EQUITY = 100000.0
SLEEVE_COUNT = 5
CANDIDATE_ORDER = (
    "autonomous_ml_v1",
    "autonomous_ml_v2",
    "autonomous_ml_v3",
)
CANDIDATE_LABELS = {
    "autonomous_ml_v1": "Autonomous ML V1",
    "autonomous_ml_v2": "Autonomous ML V2",
    "autonomous_ml_v3": "Autonomous ML V3",
}
_CACHE_TTL_SECONDS = 5.0
_cache = {"signature": None, "expires_at": 0.0, "payload": None}


def _signature(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_events(path: Path | None = None):
    path = JOURNAL_PATH if path is None else Path(path)
    if not path.exists():
        return [], None
    events = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], f"JOURNAL_READ_ERROR:{exc.__class__.__name__}"

    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return [], f"JOURNAL_CORRUPT_LINE_{line_number}"
        if not isinstance(value, dict):
            return [], f"JOURNAL_EVENT_INVALID_LINE_{line_number}"
        events.append(value)
    return events, None


def _number(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _candidate_curve(exits):
    sleeves = {
        candidate_id: [STARTING_EQUITY / SLEEVE_COUNT] * SLEEVE_COUNT
        for candidate_id in CANDIDATE_ORDER
    }
    spy_sleeves = [STARTING_EQUITY / SLEEVE_COUNT] * SLEEVE_COUNT
    curve = [{
        "timestamp_utc": None,
        "event": "PROSPECTIVE_BOUNDARY",
        "spy_normalized": STARTING_EQUITY,
        **{
            f"{candidate_id}_normalized": STARTING_EQUITY
            for candidate_id in CANDIDATE_ORDER
        },
    }]

    for event in sorted(
        exits,
        key=lambda row: (
            str(row.get("exit_timestamp_utc") or ""),
            str(row.get("decision_timestamp_utc") or ""),
        ),
    ):
        try:
            offset = int(event.get("cohort_offset", -1))
        except (TypeError, ValueError):
            continue
        if offset not in range(SLEEVE_COUNT):
            continue

        candidates = event.get("candidates") or {}
        spy_return = None
        valid = True
        for candidate_id in CANDIDATE_ORDER:
            candidate = candidates.get(candidate_id) or {}
            net = _number(candidate.get("primary_net_return"))
            candidate_spy = _number(candidate.get("spy_return"))
            if net is None or candidate_spy is None:
                valid = False
                break
            sleeves[candidate_id][offset] *= 1.0 + net
            if spy_return is None:
                spy_return = candidate_spy
        if not valid or spy_return is None:
            continue
        spy_sleeves[offset] *= 1.0 + spy_return

        curve.append({
            "timestamp_utc": event.get("exit_timestamp_utc"),
            "decision_timestamp_utc": event.get("decision_timestamp_utc"),
            "event": "EXIT_BATCH",
            "cohort_offset": offset,
            "spy_normalized": float(sum(spy_sleeves)),
            **{
                f"{candidate_id}_normalized":
                    float(sum(sleeves[candidate_id]))
                for candidate_id in CANDIDATE_ORDER
            },
        })
    return curve


def _latest_decision(events):
    decisions = [
        event
        for event in events
        if event.get("event_type") == "DECISION_BATCH"
    ]
    decisions.sort(
        key=lambda row: str(row.get("decision_timestamp_utc") or "")
    )
    return decisions[-1] if decisions else None


def _event_history(events):
    rows = []
    for event in events:
        event_type = str(event.get("event_type") or "UNKNOWN")
        timestamp = (
            event.get("exit_timestamp_utc")
            or event.get("entry_timestamp_utc")
            or event.get("decision_timestamp_utc")
        )
        row = {
            "event_type": event_type,
            "timestamp_utc": timestamp,
            "decision_timestamp_utc":
                event.get("decision_timestamp_utc"),
            "cohort_offset": event.get("cohort_offset"),
            "reason": event.get("reason"),
            "backfilled_decision": event.get("backfilled_decision"),
        }
        if event_type == "DECISION_BATCH":
            candidate_rows = event.get("candidates") or {}
            row["candidates"] = {
                candidate_id: {
                    "active_weight":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "active_weight"
                        ),
                    "spy_weight":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "spy_weight"
                        ),
                    "cash_fraction":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "cash_fraction"
                        ),
                    "selected_symbols":
                        list(
                            (candidate_rows.get(candidate_id) or {}).get(
                                "selected_symbols"
                            )
                            or []
                        ),
                }
                for candidate_id in CANDIDATE_ORDER
            }
        elif event_type == "EXIT_BATCH":
            candidate_rows = event.get("candidates") or {}
            row["candidates"] = {
                candidate_id: {
                    "primary_net_return":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "primary_net_return"
                        ),
                    "stress_20bps_net_return":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "stress_20bps_net_return"
                        ),
                    "spy_return":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "spy_return"
                        ),
                    "excess_vs_spy":
                        (candidate_rows.get(candidate_id) or {}).get(
                            "excess_vs_spy"
                        ),
                }
                for candidate_id in CANDIDATE_ORDER
            }
        rows.append(row)

    return sorted(
        rows,
        key=lambda row: str(row.get("timestamp_utc") or ""),
        reverse=True,
    )[:100]


def get_stock_eagle_autonomous_ml_prospective_dashboard():
    signature = tuple(
        _signature(path)
        for path in (
            STATUS_PATH,
            JOURNAL_PATH,
            CONTRACT_PATH,
            PHASE2_MANIFEST_PATH,
        )
    )
    now = time.monotonic()
    if (
        _cache["payload"] is not None
        and _cache["signature"] == signature
        and now < _cache["expires_at"]
    ):
        return _cache["payload"]

    status = _read_json(STATUS_PATH)
    contract = _read_json(CONTRACT_PATH)
    snapshots = _read_json(PHASE2_MANIFEST_PATH)
    events, journal_error = _read_events()

    decisions = [
        row for row in events
        if row.get("event_type") == "DECISION_BATCH"
    ]
    entries = [
        row for row in events
        if row.get("event_type") == "ENTRY_BATCH"
    ]
    exits = [
        row for row in events
        if row.get("event_type") == "EXIT_BATCH"
    ]
    missed = [
        row for row in events
        if row.get("event_type") == "MISSED_DECISION"
    ]

    fixed = {
        row.get("candidate_id"): row
        for row in contract.get("fixed_snapshots") or []
        if isinstance(row, dict)
    }
    snapshot_manifest = {
        row.get("candidate_id"): row
        for row in snapshots.get("snapshots") or []
        if isinstance(row, dict)
    }
    metrics = status.get("candidate_metrics") or {}
    latest = _latest_decision(events)

    candidates = []
    for candidate_id in CANDIDATE_ORDER:
        fixed_row = fixed.get(candidate_id) or {}
        manifest_row = snapshot_manifest.get(candidate_id) or {}
        metric = metrics.get(candidate_id) or {}
        latest_candidate = (
            (latest.get("candidates") or {}).get(candidate_id) or {}
            if latest else {}
        )
        candidates.append({
            "candidate_id": candidate_id,
            "label": CANDIDATE_LABELS[candidate_id],
            "snapshot_sha256":
                fixed_row.get("snapshot_sha256")
                or manifest_row.get("snapshot_sha256"),
            "learned_component_count":
                fixed_row.get("learned_component_count")
                or manifest_row.get("learned_component_count"),
            "meta_oos_training_sessions":
                fixed_row.get("meta_oos_training_sessions")
                or manifest_row.get("meta_oos_training_sessions"),
            "training_cutoff_utc":
                fixed_row.get("training_cutoff_utc")
                or manifest_row.get("training_cutoff_utc"),
            "allocation_policy": fixed_row.get("allocation_policy"),
            "normalized_equity":
                _number(metric.get("normalized_equity"), STARTING_EQUITY),
            "total_net_return":
                _number(metric.get("total_net_return"), 0.0),
            "matched_spy_return":
                _number(metric.get("matched_spy_return"), 0.0),
            "excess_vs_spy":
                _number(metric.get("excess_vs_spy"), 0.0),
            "maximum_drawdown":
                _number(metric.get("maximum_drawdown"), 0.0),
            "stress_20bps_total_net_return":
                _number(
                    metric.get("stress_20bps_total_net_return"),
                    0.0,
                ),
            "positive_excess_vs_spy_cohort_fraction":
                _number(
                    metric.get(
                        "positive_excess_vs_spy_cohort_fraction"
                    )
                ),
            "mean_active_weight":
                _number(metric.get("mean_active_weight")),
            "completed_cohorts":
                int(metric.get("completed_cohorts") or 0),
            "latest_active_weight":
                _number(latest_candidate.get("active_weight")),
            "latest_spy_weight":
                _number(latest_candidate.get("spy_weight")),
            "latest_cash_fraction":
                _number(latest_candidate.get("cash_fraction")),
            "latest_selected_symbols":
                list(latest_candidate.get("selected_symbols") or []),
        })

    state = (
        "JOURNAL_ERROR"
        if journal_error
        else status.get("status")
        or "WAITING_FOR_PROSPECTIVE_BOUNDARY"
    )
    review = contract.get("formal_review") or {}
    payload = {
        "classification":
            "FIXED_SNAPSHOT_AUTONOMOUS_ML_PROSPECTIVE_COMPARISON",
        "state": state,
        "decision_status": status.get("decision_status"),
        "checked_at_utc": status.get("checked_at_utc"),
        "prospective_start_utc":
            contract.get("prospective_start_utc")
            or status.get("prospective_start_utc"),
        "latest_completed_session_utc":
            status.get("latest_completed_session_utc"),
        "decision_batches":
            int(status.get("decision_batches") or len(decisions)),
        "entry_batches":
            int(status.get("entry_batches") or len(entries)),
        "exit_batches":
            int(status.get("exit_batches") or len(exits)),
        "completed_cohorts_per_candidate":
            int(
                status.get("completed_cohorts_per_candidate")
                or len(exits)
            ),
        "complete_five_sleeve_blocks":
            int(status.get("complete_five_sleeve_blocks") or 0),
        "formal_review_ready":
            bool(status.get("formal_review_ready")),
        "formal_review_status":
            status.get("formal_review_status")
            or "COLLECTING_UNSEEN_EVIDENCE",
        "formal_review_minimum_completed_cohorts":
            int(
                review.get("minimum_completed_cohorts_per_candidate")
                or 60
            ),
        "formal_review_minimum_complete_blocks":
            int(
                review.get("minimum_complete_five_sleeve_blocks")
                or 12
            ),
        "missed_decision_sessions":
            list(status.get("missed_decision_sessions") or []),
        "missed_decision_count": len(missed),
        "contract_sha256": status.get("contract_sha256"),
        "development_panel_sha256":
            (contract.get("fixed_source") or {}).get(
                "development_panel_sha256"
            ),
        "training_rows":
            (contract.get("fixed_source") or {}).get("training_rows"),
        "training_decision_end_utc":
            (contract.get("fixed_source") or {}).get(
                "training_decision_end_utc"
            ),
        "training_target_endpoint_max_utc":
            (contract.get("fixed_source") or {}).get(
                "training_target_endpoint_max_utc"
            ),
        "sealed_guard_band_start_utc":
            (contract.get("fixed_source") or {}).get(
                "sealed_guard_band_start_utc"
            ),
        "sealed_guard_band_end_exclusive_utc":
            (contract.get("fixed_source") or {}).get(
                "sealed_guard_band_end_exclusive_utc"
            ),
        "candidates": candidates,
        "curve": _candidate_curve(exits),
        "event_history": _event_history(events),
        "latest_decision_timestamp_utc":
            latest.get("decision_timestamp_utc") if latest else None,
        "same_decision_clock": True,
        "late_decision_backfill": False,
        "retraining_enabled": False,
        "automatic_winner_selection": False,
        "automatic_model_promotion": False,
        "new_architecture_before_formal_review": False,
        "paper_only": True,
        "brokerage_orders": False,
        "live_execution_enabled": False,
        "dashboard_invoked_runner": False,
        "journal_error": journal_error,
        "method_note": (
            "Read-only view of the exact frozen V1/V2/V3 snapshot comparison. "
            "Only post-Oct-1 append-only DECISION_BATCH / ENTRY_BATCH / "
            "EXIT_BATCH evidence is shown. Missed decision windows remain "
            "MISSED_DECISION evidence and are never backfilled. The dashboard "
            "does not run, retrain, promote, or place orders."
        ),
    }

    _cache.update({
        "signature": signature,
        "expires_at": now + _CACHE_TTL_SECONDS,
        "payload": payload,
    })
    return payload
