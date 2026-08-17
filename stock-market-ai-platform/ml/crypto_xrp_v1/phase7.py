"""Crypto XRP V1 Phase 7: untouched future paper evaluator.

Phase 7 evaluates the already-frozen XRP V1 Phase 6 Ridge +
``hyst_10_05_hold24`` candidate beginning at the untouched future boundary
2026-09-01 00:00 UTC.

It performs no fitting, model selection, threshold selection, or policy tuning.
The Phase 6 artifact SHA-256 and execution policy are verified before every
cycle.  Brokerage orders are permanently disabled.

Evaluation contract
-------------------
- Nothing is scored before 2026-09-01 00:00 UTC.
- The first future decision resets to the frozen initial state BTC, matching the
  Phase 5 fold-boundary reset convention.
- Decisions remain on the frozen 4-hour UTC cadence.
- No missed future decisions are backfilled. A missed 4-hour interval causes a
  neutral BTC reset at the next genuinely observed decision.
- Every future DECISION is appended once to an immutable JSONL event journal.
- A matching REALIZATION event is appended only after the exact +4h XRP and BTC
  endpoint candles exist and both four-hour windows are contiguous.
- State-change costs are reported in parallel at the Phase 5 pre-registered
  0/5/10/20 bps scenarios. No single cost scenario is newly selected here.
- Always-XRP, always-BTC, and always-CASH benchmarks are recorded on exactly the
  same valid future realization intervals.

The JSONL journal is append-only. Derived status and summary JSON files are
replaceable operational views and are never the source of truth for historical
future-evaluation events.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import time
from typing import Any

import numpy as np
import pandas as pd

from ml.crypto_xrp_v1.forward_service import (
    BTC,
    XRP,
    HOLDOUT,
    EXPECTED_STEP,
    MINIMUM_HOLD,
    INITIAL_STATE,
    POLICY_ID,
    PHASE6_ROOT,
    MODEL_PATH,
    MANIFEST_PATH,
    _build_feature_row,
    _latest_available_timestamp,
    _latest_decision_timestamp,
    _load_contract,
    _next_state,
    _predict,
    _read_recent,
    _sha256,
    _xrp_continuous_between,
)


PHASE = 7
OUTPUT_ROOT = Path("data/model/crypto_xrp_v1/phase7")
EVENT_JOURNAL_PATH = OUTPUT_ROOT / "forward_evaluation_events.jsonl"
EVALUATION_STATE_PATH = OUTPUT_ROOT / "evaluation_state.json"
EVALUATION_STATUS_PATH = OUTPUT_ROOT / "evaluation_status.json"
SUMMARY_PATH = OUTPUT_ROOT / "forward_summary.json"
EVALUATOR_MANIFEST_PATH = OUTPUT_ROOT / "evaluator_manifest.json"
LOCK_PATH = OUTPUT_ROOT / "phase7_evaluator.lock"

COST_BPS_SCENARIOS = (0, 5, 10, 20)
DEFAULT_POLL_SECONDS = 60
STATE_SPACE = {"XRP", "BTC", "CASH"}

_STOP = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _acquire_lock() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"XRP Phase 7 evaluator lock already exists: {LOCK_PATH}") from exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def _release_lock(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def _append_event(event: dict) -> None:
    """Append exactly one immutable JSON event and fsync it to disk."""
    decision_ts = pd.Timestamp(event["decision_timestamp_utc"])
    if decision_ts < HOLDOUT:
        raise RuntimeError("Phase 7 refused to append a pre-holdout event")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    fd = os.open(EVENT_JOURNAL_PATH, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _load_events() -> list[dict]:
    if not EVENT_JOURNAL_PATH.exists():
        return []
    events: list[dict] = []
    with EVENT_JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid Phase 7 journal JSON at line {lineno}"
                ) from exc
            if event.get("research_version") != "crypto_xrp_v1" or int(event.get("phase", -1)) != 7:
                raise RuntimeError(f"Unexpected Phase 7 journal contract at line {lineno}")
            ts = pd.Timestamp(event["decision_timestamp_utc"])
            if ts < HOLDOUT:
                raise RuntimeError("Existing Phase 7 journal contains pre-holdout event")
            events.append(event)
    ids = [event.get("event_id") for event in events]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate event_id found in append-only Phase 7 journal")
    return events


def _event_maps(events: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    decisions: dict[str, dict] = {}
    realizations: dict[str, dict] = {}
    for event in events:
        kind = event.get("event_type")
        key = event["decision_timestamp_utc"]
        if kind == "DECISION":
            decisions[key] = event
        elif kind == "REALIZATION":
            realizations[key] = event
        else:
            raise RuntimeError(f"Unknown Phase 7 event_type: {kind}")
    return decisions, realizations


def _verify_contract() -> tuple[dict, list[str], object, str]:
    manifest, features, model = _load_contract()
    if pd.Timestamp(manifest["future_holdout_start_utc"]) != HOLDOUT:
        raise RuntimeError("Phase 6 future boundary differs from Phase 7 contract")
    if manifest["execution_policy"]["policy_id"] != POLICY_ID:
        raise RuntimeError("Phase 6 policy differs from Phase 7 contract")
    if manifest.get("brokerage_orders") is not False:
        raise RuntimeError("Phase 6 unexpectedly permits brokerage orders")
    policy_hash = _canonical_sha256(manifest["execution_policy"])
    return manifest, features, model, policy_hash


def _write_evaluator_manifest(manifest: dict, policy_hash: str) -> dict:
    payload = {
        "research_version": "crypto_xrp_v1",
        "phase": PHASE,
        "stage": "untouched_future_paper_evaluation",
        "generated_at_utc": _utc_now().isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "source_phase6_manifest": str(MANIFEST_PATH),
        "source_phase6_manifest_sha256": _sha256(MANIFEST_PATH),
        "frozen_model_path": str(MODEL_PATH),
        "frozen_model_sha256": manifest["model"]["artifact_sha256"],
        "frozen_policy_id": POLICY_ID,
        "frozen_policy_sha256": policy_hash,
        "decision_cadence_hours": 4,
        "target_horizon_hours": 4,
        "initial_state": INITIAL_STATE,
        "minimum_hold_hours": 24,
        "cost_bps_scenarios_per_state_change": list(COST_BPS_SCENARIOS),
        "journal": str(EVENT_JOURNAL_PATH),
        "journal_contract": "append-only DECISION and REALIZATION JSONL events",
        "pre_holdout_journal_writes_allowed": False,
        "missed_decision_backfill": False,
        "brokerage_orders": False,
        "leverage": False,
        "shorting": False,
        "derivatives": False,
        "shared_crypto_v2_modified": False,
        "selection_or_tuning": False,
    }
    # Manifest is operational metadata and may exist before Sep 1. It contains
    # no future score or performance result.
    _atomic_json(EVALUATOR_MANIFEST_PATH, payload)
    return payload


def _default_eval_state(manifest: dict, policy_hash: str) -> dict:
    return {
        "research_version": "crypto_xrp_v1",
        "phase": PHASE,
        "model_sha256": manifest["model"]["artifact_sha256"],
        "policy_id": POLICY_ID,
        "policy_sha256": policy_hash,
        "current_state": INITIAL_STATE,
        "state_since_utc": None,
        "last_decision_timestamp_utc": None,
        "last_score": None,
        "last_updated_utc": None,
        "missed_decision_intervals_total": 0,
        "brokerage_orders": False,
    }


def _state_from_last_decision(
    default: dict,
    decisions: dict[str, dict],
) -> dict:
    if not decisions:
        return default
    last = max(decisions.values(), key=lambda x: pd.Timestamp(x["decision_timestamp_utc"]))
    rebuilt = dict(default)
    rebuilt.update(
        {
            "current_state": last["state_after"],
            "state_since_utc": last.get("state_since_utc"),
            "last_decision_timestamp_utc": last["decision_timestamp_utc"],
            "last_score": last["predicted_btc_relative_return_4h"],
            "last_updated_utc": last["recorded_at_utc"],
            "missed_decision_intervals_total": int(
                last.get("missed_decision_intervals_total", 0)
            ),
        }
    )
    return rebuilt


def _load_eval_state(
    manifest: dict,
    policy_hash: str,
    decisions: dict[str, dict],
) -> dict:
    default = _default_eval_state(manifest, policy_hash)
    source_truth = _state_from_last_decision(default, decisions)
    if not EVALUATION_STATE_PATH.exists():
        return source_truth
    try:
        state = json.loads(EVALUATION_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return source_truth
    expected = {
        "model_sha256": manifest["model"]["artifact_sha256"],
        "policy_id": POLICY_ID,
        "policy_sha256": policy_hash,
        "brokerage_orders": False,
    }
    if any(state.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Existing XRP Phase 7 state belongs to a different frozen contract")
    if state.get("current_state") not in STATE_SPACE:
        raise RuntimeError("Existing XRP Phase 7 state has invalid current_state")
    # The append-only decision journal is authoritative after crashes.
    if state.get("last_decision_timestamp_utc") != source_truth.get("last_decision_timestamp_utc"):
        return source_truth
    return state


def _advance_eval_state(
    state: dict,
    decision_ts: pd.Timestamp,
    score: float,
) -> tuple[dict, dict]:
    last_value = state.get("last_decision_timestamp_utc")
    last_ts = pd.Timestamp(last_value) if last_value else None
    state_before = state["current_state"]
    reset = False
    reset_reason = None
    missed = 0

    if last_ts is None:
        reset = True
        reset_reason = "future_holdout_boundary_initialization"
    elif decision_ts <= last_ts:
        raise RuntimeError("Phase 7 attempted to process a non-new decision")
    elif decision_ts - last_ts != EXPECTED_STEP:
        reset = True
        reset_reason = "missed_future_decision_interval"
        missed = max(0, int((decision_ts - last_ts) / EXPECTED_STEP) - 1)
    elif not _xrp_continuous_between(last_ts, decision_ts):
        reset = True
        reset_reason = "xrp_continuity_break"

    if reset:
        state_after = INITIAL_STATE
        proposed = INITIAL_STATE
        switched = False
        hold_blocked = False
        elapsed_hours = 0.0
        state["current_state"] = INITIAL_STATE
        state["state_since_utc"] = decision_ts.isoformat()
        state["missed_decision_intervals_total"] = int(
            state.get("missed_decision_intervals_total", 0)
        ) + missed
    else:
        state_since = pd.Timestamp(state["state_since_utc"])
        elapsed = decision_ts - state_since
        elapsed_hours = float(elapsed.total_seconds() / 3600.0)
        proposed = _next_state(state_before, score)
        hold_blocked = proposed != state_before and elapsed < MINIMUM_HOLD
        state_after = state_before if hold_blocked else proposed
        switched = state_after != state_before
        if switched:
            state["current_state"] = state_after
            state["state_since_utc"] = decision_ts.isoformat()

    state["last_decision_timestamp_utc"] = decision_ts.isoformat()
    state["last_score"] = score
    state["last_updated_utc"] = _utc_now().isoformat()

    return state, {
        "state_before": state_before,
        "state_after": state_after,
        "proposed_state": proposed,
        "state_switch": bool(switched),
        "state_reset": bool(reset),
        "reset_reason": reset_reason,
        "minimum_hold_blocked": bool(hold_blocked),
        "hours_since_state_change": elapsed_hours,
        "missed_intervals_this_decision": missed,
    }


def _continuous_product_window(product_id: str, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    frame = _read_recent(product_id, end)
    window = frame[
        (frame["timestamp_utc"] >= start)
        & (frame["timestamp_utc"] <= end)
    ].copy()
    expected = pd.date_range(start, end, freq="15min", tz="UTC")
    observed = set(window["timestamp_utc"])
    return len(window) == len(expected) and all(ts in observed for ts in expected)


def _close_at(product_id: str, timestamp: pd.Timestamp) -> float:
    frame = _read_recent(product_id, timestamp)
    row = frame[frame["timestamp_utc"] == timestamp]
    if len(row) != 1:
        raise RuntimeError(f"Expected exactly one {product_id} candle at {timestamp}")
    close = float(row.iloc[0]["close"])
    if not np.isfinite(close) or close <= 0:
        raise RuntimeError(f"Invalid {product_id} close at {timestamp}")
    return close


def _return_for_state(state: str, xrp_return: float, btc_return: float) -> float:
    if state == "XRP":
        return xrp_return
    if state == "BTC":
        return btc_return
    if state == "CASH":
        return 0.0
    raise RuntimeError(f"Unknown evaluation state: {state}")


def _last_valid_realization(realizations: dict[str, dict]) -> dict | None:
    valid = [r for r in realizations.values() if r.get("realization_status") == "VALID"]
    if not valid:
        return None
    return max(valid, key=lambda x: pd.Timestamp(x["decision_timestamp_utc"]))


def _realize_pending(
    events: list[dict],
    manifest: dict,
    policy_hash: str,
) -> list[dict]:
    decisions, realizations = _event_maps(events)
    pending = [
        d for key, d in decisions.items() if key not in realizations
    ]
    pending.sort(key=lambda x: pd.Timestamp(x["decision_timestamp_utc"]))
    appended: list[dict] = []

    btc_latest = _latest_available_timestamp(BTC)
    xrp_latest = _latest_available_timestamp(XRP)
    if btc_latest is None or xrp_latest is None:
        return appended
    common_latest = min(btc_latest, xrp_latest)

    for decision in pending:
        decision_ts = pd.Timestamp(decision["decision_timestamp_utc"])
        endpoint = decision_ts + EXPECTED_STEP
        if common_latest < endpoint:
            continue

        event: dict[str, Any] = {
            "event_id": f"realization:{decision_ts.isoformat()}",
            "event_type": "REALIZATION",
            "research_version": "crypto_xrp_v1",
            "phase": PHASE,
            "recorded_at_utc": _utc_now().isoformat(),
            "decision_timestamp_utc": decision_ts.isoformat(),
            "target_endpoint_utc": endpoint.isoformat(),
            "model_sha256": manifest["model"]["artifact_sha256"],
            "policy_id": POLICY_ID,
            "policy_sha256": policy_hash,
            "state": decision["state_after"],
            "state_switch": bool(decision["state_switch"]),
            "brokerage_orders": False,
        }

        xrp_ok = _continuous_product_window(XRP, decision_ts, endpoint)
        btc_ok = _continuous_product_window(BTC, decision_ts, endpoint)
        if not (xrp_ok and btc_ok):
            event.update(
                {
                    "realization_status": "INVALID_DATA_GAP",
                    "xrp_contiguous_4h": bool(xrp_ok),
                    "btc_contiguous_4h": bool(btc_ok),
                }
            )
            _append_event(event)
            realizations[decision_ts.isoformat()] = event
            appended.append(event)
            continue

        xrp_start = _close_at(XRP, decision_ts)
        xrp_end = _close_at(XRP, endpoint)
        btc_start = _close_at(BTC, decision_ts)
        btc_end = _close_at(BTC, endpoint)
        xrp_return = xrp_end / xrp_start - 1.0
        btc_return = btc_end / btc_start - 1.0
        relative_return = xrp_return - btc_return
        gross_return = _return_for_state(decision["state_after"], xrp_return, btc_return)

        previous = _last_valid_realization(realizations)
        previous_btc_equity = float(previous["always_btc_equity"]) if previous else 1.0
        previous_xrp_equity = float(previous["always_xrp_equity"]) if previous else 1.0

        event.update(
            {
                "realization_status": "VALID",
                "xrp_contiguous_4h": True,
                "btc_contiguous_4h": True,
                "xrp_forward_return_4h": xrp_return,
                "btc_forward_return_4h": btc_return,
                "btc_relative_forward_return_4h": relative_return,
                "gross_state_return_4h": gross_return,
                "always_xrp_equity": previous_xrp_equity * (1.0 + xrp_return),
                "always_btc_equity": previous_btc_equity * (1.0 + btc_return),
                "always_cash_equity": 1.0,
            }
        )

        for cost_bps in COST_BPS_SCENARIOS:
            key = f"equity_{cost_bps}bps"
            previous_equity = float(previous[key]) if previous else 1.0
            cost_rate = cost_bps / 10_000.0 if decision["state_switch"] else 0.0
            net_return = gross_return - cost_rate
            event[f"switch_cost_{cost_bps}bps"] = cost_rate
            event[f"net_return_{cost_bps}bps"] = net_return
            event[key] = previous_equity * (1.0 + net_return)

        _append_event(event)
        realizations[decision_ts.isoformat()] = event
        appended.append(event)

    return appended


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    arr = np.asarray(values, dtype=float)
    peak = np.maximum.accumulate(arr)
    drawdown = arr / peak - 1.0
    return float(np.min(drawdown))


def _build_summary(events: list[dict], manifest: dict, policy_hash: str) -> dict:
    decisions, realizations = _event_maps(events)
    valid = sorted(
        [r for r in realizations.values() if r.get("realization_status") == "VALID"],
        key=lambda x: pd.Timestamp(x["decision_timestamp_utc"]),
    )
    invalid = [r for r in realizations.values() if r.get("realization_status") != "VALID"]
    pending_count = len(decisions) - len(realizations)
    summary: dict[str, Any] = {
        "research_version": "crypto_xrp_v1",
        "phase": PHASE,
        "research_status": "UNTOUCHED FUTURE PAPER EVALUATION",
        "generated_at_utc": _utc_now().isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "model_sha256": manifest["model"]["artifact_sha256"],
        "policy_id": POLICY_ID,
        "policy_sha256": policy_hash,
        "decision_count": len(decisions),
        "valid_realization_count": len(valid),
        "invalid_realization_count": len(invalid),
        "pending_realization_count": pending_count,
        "state_switch_count": sum(bool(d.get("state_switch")) for d in decisions.values()),
        "last_decision_timestamp_utc": max(decisions.keys()) if decisions else None,
        "last_realized_decision_utc": valid[-1]["decision_timestamp_utc"] if valid else None,
        "brokerage_orders": False,
        "leverage": False,
        "shorting": False,
        "derivatives": False,
    }
    if valid:
        last = valid[-1]
        summary.update(
            {
                "always_xrp_equity": last["always_xrp_equity"],
                "always_btc_equity": last["always_btc_equity"],
                "always_cash_equity": 1.0,
                "always_xrp_max_drawdown": _max_drawdown([r["always_xrp_equity"] for r in valid]),
                "always_btc_max_drawdown": _max_drawdown([r["always_btc_equity"] for r in valid]),
            }
        )
        for cost_bps in COST_BPS_SCENARIOS:
            key = f"equity_{cost_bps}bps"
            summary[key] = last[key]
            summary[f"max_drawdown_{cost_bps}bps"] = _max_drawdown([r[key] for r in valid])
    else:
        summary.update(
            {
                "always_xrp_equity": 1.0,
                "always_btc_equity": 1.0,
                "always_cash_equity": 1.0,
                "always_xrp_max_drawdown": None,
                "always_btc_max_drawdown": None,
            }
        )
        for cost_bps in COST_BPS_SCENARIOS:
            summary[f"equity_{cost_bps}bps"] = 1.0
            summary[f"max_drawdown_{cost_bps}bps"] = None
    return summary


def run_once(now: datetime | None = None) -> dict:
    manifest, features, model, policy_hash = _verify_contract()
    _write_evaluator_manifest(manifest, policy_hash)
    current_time = pd.Timestamp(now or _utc_now())
    if current_time.tzinfo is None:
        current_time = current_time.tz_localize("UTC")
    else:
        current_time = current_time.tz_convert("UTC")

    if current_time < HOLDOUT:
        # Deliberately do not create/read the event journal before the untouched
        # future boundary. Only operational readiness metadata is written.
        status = {
            "status": "ok",
            "mode": "WAITING_PRE_HOLDOUT",
            "generated_at_utc": _utc_now().isoformat(),
            "future_holdout_start_utc": HOLDOUT.isoformat(),
            "journal_exists": EVENT_JOURNAL_PATH.exists(),
            "journal_event_count": None,
            "model_sha256_verified": True,
            "policy_verified": True,
            "brokerage_orders": False,
            "note": "No Phase 7 decision or performance event may be written before Sep 1, 2026 00:00 UTC.",
        }
        _atomic_json(EVALUATION_STATUS_PATH, status)
        return status

    events = _load_events()
    decisions, _ = _event_maps(events)
    state = _load_eval_state(manifest, policy_hash, decisions)
    latest_decision, archive_diag = _latest_decision_timestamp()

    action = "no_new_future_decision"
    decision_event = None
    if latest_decision >= HOLDOUT:
        key = latest_decision.isoformat()
        if key not in decisions:
            feature_frame, feature_diag = _build_feature_row(latest_decision, features)
            score = _predict(model, feature_frame)
            state, state_diag = _advance_eval_state(state, latest_decision, score)
            decision_event = {
                "event_id": f"decision:{key}",
                "event_type": "DECISION",
                "research_version": "crypto_xrp_v1",
                "phase": PHASE,
                "recorded_at_utc": _utc_now().isoformat(),
                "decision_timestamp_utc": key,
                "target_endpoint_utc": (latest_decision + EXPECTED_STEP).isoformat(),
                "model_id": "ridge",
                "model_sha256": manifest["model"]["artifact_sha256"],
                "feature_count": len(features),
                "predicted_btc_relative_return_4h": score,
                "policy_id": POLICY_ID,
                "policy_sha256": policy_hash,
                "state_since_utc": state.get("state_since_utc"),
                "missed_decision_intervals_total": int(state.get("missed_decision_intervals_total", 0)),
                "brokerage_orders": False,
                **archive_diag,
                **feature_diag,
                **state_diag,
            }
            _append_event(decision_event)
            _atomic_json(EVALUATION_STATE_PATH, state)
            action = "appended_future_decision"

    # Reload journal so the just-appended decision is source-of-truth before
    # adding any realization events.
    events = _load_events()
    realized_now = _realize_pending(events, manifest, policy_hash)
    if realized_now:
        action = f"{action}+appended_{len(realized_now)}_realization(s)"
    events = _load_events()
    summary = _build_summary(events, manifest, policy_hash)
    _atomic_json(SUMMARY_PATH, summary)

    status = {
        "status": "ok",
        "mode": "FUTURE_PAPER_EVALUATION",
        "generated_at_utc": _utc_now().isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "action": action,
        "latest_available_decision_utc": latest_decision.isoformat(),
        "decision_count": summary["decision_count"],
        "valid_realization_count": summary["valid_realization_count"],
        "invalid_realization_count": summary["invalid_realization_count"],
        "pending_realization_count": summary["pending_realization_count"],
        "model_sha256_verified": True,
        "policy_verified": True,
        "brokerage_orders": False,
    }
    _atomic_json(EVALUATION_STATUS_PATH, status)
    return status


def _write_error_status(exc: Exception) -> None:
    _atomic_json(
        EVALUATION_STATUS_PATH,
        {
            "status": "error",
            "generated_at_utc": _utc_now().isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "brokerage_orders": False,
        },
    )


def _handle_signal(_signum, _frame) -> None:
    global _STOP
    _STOP = True


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one evaluator cycle and exit.")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help="Polling interval for service mode.",
    )
    args = parser.parse_args(argv)
    if args.poll_seconds < 1:
        raise SystemExit("--poll-seconds must be >= 1")

    fd = None
    try:
        fd = _acquire_lock()
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        if args.once:
            try:
                status = run_once()
            except Exception as exc:
                _write_error_status(exc)
                raise
            print("CRYPTO XRP V1 PHASE 7")
            print("=" * 80)
            print(f"Mode:       {status['mode']}")
            print(f"Status:     {status['status']}")
            print(f"Boundary:   {status['future_holdout_start_utc']}")
            if status["mode"] == "WAITING_PRE_HOLDOUT":
                print("Journal:    disabled before future boundary")
            else:
                print(f"Decisions:  {status['decision_count']}")
                print(f"Realized:   {status['valid_realization_count']}")
                print(f"Pending:    {status['pending_realization_count']}")
            print("Real orders: NO")
            return

        while not _STOP:
            try:
                run_once()
            except Exception as exc:
                _write_error_status(exc)
            slept = 0
            while slept < args.poll_seconds and not _STOP:
                time.sleep(1)
                slept += 1
    finally:
        _release_lock(fd)


if __name__ == "__main__":
    main()
