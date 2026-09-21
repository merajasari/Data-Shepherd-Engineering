"""Autonomous clean forward paper service for frozen Crypto V5.

The service begins observing at 2026-09-22 07:00 UTC (midnight Pacific).
Because V5 uses completed UTC daily candles, the first admissible decision is
2026-09-23 00:00 UTC.  No earlier decision is imported or reconstructed.

Every decision and realization is appended to an immutable hash-chained JSONL
journal.  The service has no brokerage client, never places orders, never
promotes the model, and fails closed if its first or any later required decision
boundary is missed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import time

import joblib
import pandas as pd

from ml.crypto_v5.phase5 import (
    ARTIFACT_PATHS,
    CONTRACT_PATH,
    SELECTED_COST_BPS,
    SELECTED_HORIZON_DAYS,
    SELECTED_MODEL_ID,
    SELECTED_TOP_N,
    STARTING_PAPER_EQUITY,
    _atomic_json,
    _canonical_hash,
    _sha256,
    build_snapshot,
    load_completed_bronze,
    score_snapshot,
    verify_contract,
)


ROOT = CONTRACT_PATH.parent.parent / "phase5" / "clean_forward_v1"
STATE_PATH = ROOT / "paper_state.json"
STATUS_PATH = ROOT / "forward_service_status.json"
JOURNAL_PATH = ROOT / "paper_events.jsonl"
MANIFEST_PATH = ROOT / "clean_lane_manifest.json"
LOCK_PATH = ROOT / "forward_service.lock"

LANE_ID = "crypto_v5_clean_forward_v1"
LANE_NAME = "Crypto V5 Clean Paper V1"
OBSERVATION_START_UTC = pd.Timestamp("2026-09-22T07:00:00Z")
FIRST_ELIGIBLE_DECISION_UTC = pd.Timestamp("2026-09-23T00:00:00Z")
DEFAULT_POLL_SECONDS = 300


def _utc(value) -> pd.Timestamp:
    result = pd.Timestamp(value)
    return result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return payload


def _append_event(event: dict, state: dict) -> dict:
    payload = {
        **event,
        "previous_event_hash": state.get("last_event_hash"),
        "paper_only": True,
        "brokerage_orders": False,
        "automatic_promotion": False,
        "human_review_required": True,
    }
    payload["event_hash"] = _canonical_hash(payload)
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    state["last_event_hash"] = payload["event_hash"]
    return payload


def _initial_state(contract_hash: str) -> dict:
    return {
        "lane_id": LANE_ID,
        "initialized_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_contract_sha256": contract_hash,
        "paper_equity": STARTING_PAPER_EQUITY,
        "starting_paper_equity": STARTING_PAPER_EQUITY,
        "weights": {"CASH": 1.0},
        "selected_regime": "CASH",
        "last_decision_utc": None,
        "last_regime_switch_utc": None,
        "last_event_hash": None,
        "decision_count": 0,
        "realization_count": 0,
        "pending_decisions": [],
        "paper_only": True,
        "brokerage_orders": False,
        "automatic_promotion": False,
        "human_review_required": True,
    }


def _ensure_lane(now: pd.Timestamp, contract_hash: str) -> tuple[dict, dict]:
    if MANIFEST_PATH.exists():
        manifest = _read_json(MANIFEST_PATH)
        checks = {
            "lane id": manifest.get("lane_id") == LANE_ID,
            "observation boundary": _utc(manifest.get("preregistered_observation_start_utc")) == OBSERVATION_START_UTC,
            "first decision boundary": _utc(manifest.get("first_eligible_decision_utc")) == FIRST_ELIGIBLE_DECISION_UTC,
            "contract hash": manifest.get("selected_contract_sha256") == contract_hash,
            "starting paper equity": float(manifest.get("starting_paper_equity", 0)) == STARTING_PAPER_EQUITY,
            "brokerage prohibition": manifest.get("brokerage_orders") is False,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError("Crypto V5 clean-lane contract failed: " + ", ".join(failed))
        if not STATE_PATH.exists() or not JOURNAL_PATH.exists():
            raise RuntimeError("Crypto V5 clean-lane manifest exists without state or journal")
        return manifest, _read_json(STATE_PATH)

    if STATE_PATH.exists() or JOURNAL_PATH.exists():
        raise RuntimeError("Unregistered Crypto V5 clean-lane files exist")
    if now >= OBSERVATION_START_UTC:
        raise RuntimeError("Crypto V5 observation boundary was missed; refusing late initialization")

    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "lane_id": LANE_ID,
        "display_name": LANE_NAME,
        "created_at_utc": now.isoformat(),
        "preregistered_observation_start_utc": OBSERVATION_START_UTC.isoformat(),
        "first_eligible_decision_utc": FIRST_ELIGIBLE_DECISION_UTC.isoformat(),
        "selected_contract_sha256": contract_hash,
        "model_id": SELECTED_MODEL_ID,
        "horizon_days": SELECTED_HORIZON_DAYS,
        "top_n": SELECTED_TOP_N,
        "cost_bps_round_trip": SELECTED_COST_BPS,
        "starting_paper_equity": STARTING_PAPER_EQUITY,
        "late_start_policy": "FAIL_CLOSED_NO_START",
        "missed_decision_policy": "FAIL_CLOSED_NO_BACKFILL",
        "paper_only": True,
        "brokerage_orders": False,
        "automatic_promotion": False,
        "human_review_required": True,
    }
    state = _initial_state(contract_hash)
    _atomic_json(MANIFEST_PATH, manifest)
    _atomic_json(STATE_PATH, state)
    JOURNAL_PATH.touch(exist_ok=False)
    return manifest, state


def _price(history: pd.DataFrame, product_id: str, timestamp: pd.Timestamp) -> float:
    match = history[
        history["product_id"].eq(product_id)
        & history["timestamp_utc"].eq(timestamp)
    ]
    if len(match) != 1:
        raise RuntimeError(f"Missing exact V5 realization candle: {product_id} at {timestamp.isoformat()}")
    return float(match.iloc[0]["close"])


def _finalize_pending(history: pd.DataFrame, latest_timestamp: pd.Timestamp, state: dict) -> int:
    completed = 0
    remaining = []
    for pending in sorted(state.get("pending_decisions", []), key=lambda row: row["decision_timestamp_utc"]):
        decision_timestamp = _utc(pending["decision_timestamp_utc"])
        realized_through = decision_timestamp + pd.Timedelta(SELECTED_HORIZON_DAYS, unit="D")
        if latest_timestamp < realized_through:
            remaining.append(pending)
            continue
        weights = {name: float(weight) for name, weight in pending["target_weights"].items()}
        asset_returns = {}
        gross_return = 0.0
        for product_id, weight in weights.items():
            if product_id == "CASH" or abs(weight) < 1e-15:
                asset_returns[product_id] = 0.0
                continue
            start = _price(history, product_id, decision_timestamp)
            end = _price(history, product_id, realized_through)
            asset_return = end / start - 1.0
            asset_returns[product_id] = asset_return
            gross_return += weight * asset_return
        equity_before = float(state["paper_equity"])
        transaction_cost = float(pending["estimated_transaction_cost"])
        equity_after_cost = max(0.0, equity_before - transaction_cost)
        equity_after = max(0.0, equity_after_cost * (1.0 + gross_return))
        net_return = equity_after / equity_before - 1.0 if equity_before else -1.0
        event = _append_event({
            "event_type": "REALIZATION",
            "decision_id": pending["decision_id"],
            "decision_timestamp_utc": decision_timestamp.isoformat(),
            "realized_through_utc": realized_through.isoformat(),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "selected_regime": pending["selected_regime"],
            "target_weights": weights,
            "asset_returns": asset_returns,
            "gross_return": gross_return,
            "transaction_cost": transaction_cost,
            "net_return": net_return,
            "paper_equity_before": equity_before,
            "paper_equity_after": equity_after,
            "status": "REALIZED",
        }, state)
        state["paper_equity"] = equity_after
        state["last_realized_through_utc"] = realized_through.isoformat()
        state["last_realization_event_hash"] = event["event_hash"]
        state["realization_count"] = int(state.get("realization_count", 0)) + 1
        completed += 1
    state["pending_decisions"] = remaining
    return completed


def _next_required_decision(state: dict) -> pd.Timestamp:
    previous = state.get("last_decision_utc")
    if not previous:
        return FIRST_ELIGIBLE_DECISION_UTC
    return _utc(previous) + pd.Timedelta(SELECTED_HORIZON_DAYS, unit="D")


def _status(now: pd.Timestamp, mode: str, action: str, state: dict, **extra) -> dict:
    payload = {
        "generated_at_utc": now.isoformat(),
        "status": "ok",
        "mode": mode,
        "action": action,
        "lane_id": LANE_ID,
        "lane_name": LANE_NAME,
        "observation_start_utc": OBSERVATION_START_UTC.isoformat(),
        "first_eligible_decision_utc": FIRST_ELIGIBLE_DECISION_UTC.isoformat(),
        "starting_paper_equity": STARTING_PAPER_EQUITY,
        "current_paper_equity": float(state.get("paper_equity", STARTING_PAPER_EQUITY)),
        "decision_count": int(state.get("decision_count", 0)),
        "realization_count": int(state.get("realization_count", 0)),
        "pending_count": len(state.get("pending_decisions", [])),
        "selected_regime": state.get("selected_regime", "CASH"),
        "contract_verified": True,
        "service_pid": os.getpid(),
        "paper_only": True,
        "brokerage_orders": False,
        "automatic_promotion": False,
        "human_review_required": True,
        **extra,
    }
    _atomic_json(STATUS_PATH, payload)
    return payload


def run_once(as_of_utc=None) -> dict:
    now = _utc(as_of_utc or datetime.now(timezone.utc))
    verify_contract()
    contract_hash = _sha256(CONTRACT_PATH)
    _, state = _ensure_lane(now, contract_hash)
    if now < OBSERVATION_START_UTC:
        return _status(now, "WAITING_CLEAN_BOUNDARY", "waiting_observation_start", state)

    history, completed_before = load_completed_bronze(as_of_utc=now)
    allocation, ranking, decision_timestamp = build_snapshot(history, completed_before)
    if decision_timestamp < FIRST_ELIGIBLE_DECISION_UTC:
        return _status(
            now, "OBSERVING_CLEAN_WINDOW", "waiting_first_complete_daily_decision", state,
            latest_completed_decision_utc=decision_timestamp.isoformat(),
        )

    expected = _next_required_decision(state)
    finalized = _finalize_pending(history, decision_timestamp, state)
    if decision_timestamp > expected:
        _atomic_json(STATE_PATH, state)
        return _status(
            now, "FAIL_CLOSED_MISSED_DECISION", "missed_decision_no_backfill", state,
            expected_decision_utc=expected.isoformat(),
            latest_completed_decision_utc=decision_timestamp.isoformat(),
            pending_rows_finalized=finalized,
        )

    if decision_timestamp < expected:
        _atomic_json(STATE_PATH, state)
        return _status(
            now, "CLEAN_FORWARD", "minimum_decision_cadence_active", state,
            pending_rows_finalized=finalized,
            latest_completed_decision_utc=decision_timestamp.isoformat(),
            next_decision_utc=expected.isoformat(),
        )

    models = {name: joblib.load(path) for name, path in ARTIFACT_PATHS.items()}
    decision = score_snapshot(allocation, ranking, models, state, decision_timestamp)
    decision_id = f"crypto_v5_clean:{decision_timestamp.isoformat()}"
    event = _append_event({
        "event_type": "DECISION",
        "decision_id": decision_id,
        "decision_timestamp_utc": decision_timestamp.isoformat(),
        "recorded_at_utc": now.isoformat(),
        "model_id": SELECTED_MODEL_ID,
        "horizon_days": SELECTED_HORIZON_DAYS,
        "top_n": SELECTED_TOP_N,
        "cost_bps_round_trip": SELECTED_COST_BPS,
        "selected_contract_sha256": contract_hash,
        "paper_equity_before": float(state["paper_equity"]),
        **decision,
        "status": "PENDING_REALIZATION",
    }, state)
    pending = {
        "decision_id": decision_id,
        "decision_timestamp_utc": decision_timestamp.isoformat(),
        "selected_regime": decision["selected_regime"],
        "target_weights": decision["target_weights"],
        "estimated_transaction_cost": decision["estimated_transaction_cost"],
        "decision_event_hash": event["event_hash"],
    }
    state["pending_decisions"] = [*state.get("pending_decisions", []), pending]
    state["weights"] = decision["target_weights"]
    previous_regime = state.get("selected_regime", "CASH")
    state["selected_regime"] = decision["selected_regime"]
    state["last_decision_utc"] = decision_timestamp.isoformat()
    if decision["selected_regime"] != previous_regime:
        state["last_regime_switch_utc"] = decision_timestamp.isoformat()
    state["decision_count"] = int(state.get("decision_count", 0)) + 1
    _atomic_json(STATE_PATH, state)
    return _status(
        now, "CLEAN_FORWARD", "paper_decision_recorded", state,
        pending_rows_finalized=finalized,
        decision_timestamp_utc=decision_timestamp.isoformat(),
        selected_regime=decision["selected_regime"],
        top_ranked_assets=decision["top_ranked_assets"],
        target_weights=decision["target_weights"],
        allocation_scores=decision["allocation_scores"],
        turnover=decision["turnover"],
        event_hash=event["event_hash"],
    )


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_lock() -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            owner = int(LOCK_PATH.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            owner = -1
        if _pid_is_running(owner):
            raise RuntimeError(f"Crypto V5 forward service already running with PID {owner}")
        LOCK_PATH.unlink(missing_ok=True)
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Crypto V5 forward service lock is already held") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))


def _release_lock() -> None:
    try:
        if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_PATH.unlink()
    except OSError:
        pass


def serve(poll_seconds=DEFAULT_POLL_SECONDS) -> None:
    _acquire_lock()
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            try:
                result = run_once()
                print(
                    f"[CRYPTO V5] {result['generated_at_utc']} mode={result['mode']} "
                    f"action={result['action']} equity={result['current_paper_equity']:.2f}",
                    flush=True,
                )
            except Exception as exc:
                now = datetime.now(timezone.utc).isoformat()
                payload = {
                    "generated_at_utc": now,
                    "status": "error",
                    "mode": "FAIL_CLOSED_RUNTIME_ERROR",
                    "action": "runtime_error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "contract_verified": False,
                    "service_pid": os.getpid(),
                    "paper_only": True,
                    "brokerage_orders": False,
                    "automatic_promotion": False,
                    "human_review_required": True,
                }
                _atomic_json(STATUS_PATH, payload)
                print(f"[CRYPTO V5 ERROR] {type(exc).__name__}: {exc}", flush=True)
            for _ in range(max(1, int(poll_seconds))):
                if stopping:
                    break
                time.sleep(1)
    finally:
        _release_lock()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--as-of-utc", default=None)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args(argv)
    if args.once or args.as_of_utc:
        print(json.dumps(run_once(args.as_of_utc), indent=2))
    else:
        serve(args.poll_seconds)


if __name__ == "__main__":
    main()
