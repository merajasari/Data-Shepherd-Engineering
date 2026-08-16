"""Shadow-only forward inference for the frozen XRP V1 exploratory candidate.

This service uses authoritative reconciled Coinbase 15-minute bars, reconstructs
the exact frozen 44-feature XRP row, verifies the Phase 6 Ridge artifact hash,
and applies the frozen ``hyst_10_05_hold24`` state machine.

The service is deliberately shadow-only. It never appends a performance journal,
never places brokerage orders, and never modifies the shared Crypto 15m V2
candidate. Before and after the 2026-09-01 future boundary it records only the
latest shadow state and service health. A separate future-evaluation phase is
required before any forward results are scored or promoted.

State-machine fidelity
----------------------
Phase 5 reset semantics are preserved:

- initial/reset state is BTC
- a reset occurs at service initialization or after a missing 4-hour decision
  interval / XRP continuity break
- the 24-hour minimum hold starts at that reset timestamp
- enter XRP when score >= +0.0010
- enter CASH when score <= -0.0010
- leave XRP when score <= +0.0005
- leave CASH when score >= -0.0005
- otherwise use BTC

No historical decisions are replayed or backfilled. Only the latest genuinely
available 4-hour decision may advance state.
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

import joblib
import numpy as np
import pandas as pd

from ml.crypto_15m_v1.phase1 import _build_base_features, _btc_context


RAW_ROOT = Path("data/research/crypto_intraday/raw_15m")
PHASE6_ROOT = Path("data/model/crypto_xrp_v1/phase6")
MODEL_PATH = PHASE6_ROOT / "frozen_ridge.joblib"
MANIFEST_PATH = PHASE6_ROOT / "freeze_manifest.json"
STATE_PATH = PHASE6_ROOT / "forward_state.json"
SHADOW_PATH = PHASE6_ROOT / "shadow_latest.json"
SERVICE_STATUS_PATH = PHASE6_ROOT / "forward_service_status.json"
LOCK_PATH = PHASE6_ROOT / "forward_service.lock"

BTC = "BTC-USD"
XRP = "XRP-USD"
POLICY_ID = "hyst_10_05_hold24"
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
EXPECTED_STEP = pd.Timedelta(hours=4)
MINIMUM_HOLD = pd.Timedelta(hours=24)
ENTRY_THRESHOLD = 0.0010
EXIT_THRESHOLD = 0.0005
INITIAL_STATE = "BTC"
DECISION_HOURS_UTC = {0, 4, 8, 12, 16, 20}
LOOKBACK_DAYS = 10
DEFAULT_POLL_SECONDS = 60

_STOP = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _acquire_lock() -> int:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"XRP forward service lock already exists: {LOCK_PATH}") from exc
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


def _load_contract() -> tuple[dict, list[str], object]:
    for path in (MODEL_PATH, MANIFEST_PATH):
        if not path.exists():
            raise FileNotFoundError(path)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    if manifest.get("research_version") != "crypto_xrp_v1":
        raise RuntimeError("Unexpected XRP research version in freeze manifest")
    if int(manifest.get("phase", -1)) != 6:
        raise RuntimeError("XRP forward service requires Phase 6 freeze manifest")
    if manifest.get("research_status") != "EXPLORATORY FORWARD CANDIDATE":
        raise RuntimeError("XRP Phase 6 research status differs from frozen contract")
    if manifest.get("promotion_status") != "NOT PROMOTED FOR REAL TRADING":
        raise RuntimeError("XRP candidate promotion status differs from frozen contract")
    if manifest.get("brokerage_orders") is not False:
        raise RuntimeError("Frozen XRP manifest unexpectedly permits brokerage orders")
    if manifest.get("shared_crypto_v2_modified") is not False:
        raise RuntimeError("Frozen XRP manifest indicates shared V2 modification")

    policy = manifest["execution_policy"]
    if policy.get("policy_id") != POLICY_ID:
        raise RuntimeError("Frozen XRP execution policy does not match service contract")
    if int(policy.get("decision_cadence_hours")) != 4:
        raise RuntimeError("Frozen XRP decision cadence does not equal 4 hours")
    if float(policy.get("entry_threshold_positive")) != ENTRY_THRESHOLD:
        raise RuntimeError("Frozen positive entry threshold differs from service contract")
    if float(policy.get("entry_threshold_negative")) != -ENTRY_THRESHOLD:
        raise RuntimeError("Frozen negative entry threshold differs from service contract")
    if float(policy.get("exit_threshold_from_xrp")) != EXIT_THRESHOLD:
        raise RuntimeError("Frozen XRP exit threshold differs from service contract")
    if float(policy.get("exit_threshold_from_cash")) != -EXIT_THRESHOLD:
        raise RuntimeError("Frozen CASH exit threshold differs from service contract")
    if int(policy.get("minimum_hold_hours")) != 24:
        raise RuntimeError("Frozen minimum hold differs from service contract")
    if policy.get("initial_state") != INITIAL_STATE:
        raise RuntimeError("Frozen initial state differs from service contract")

    expected_hash = manifest["model"]["artifact_sha256"]
    actual_hash = _sha256(MODEL_PATH)
    if actual_hash != expected_hash:
        raise RuntimeError(
            f"Frozen XRP model SHA256 mismatch: expected {expected_hash}, got {actual_hash}"
        )

    features = list(manifest["feature_columns"])
    if len(features) != 44:
        raise RuntimeError(f"Expected 44 frozen XRP features, found {len(features)}")

    model = joblib.load(MODEL_PATH)
    return manifest, features, model


def _latest_available_timestamp(product_id: str) -> pd.Timestamp | None:
    paths = sorted((RAW_ROOT / product_id).glob("*.parquet"), reverse=True)
    for path in paths:
        try:
            df = pd.read_parquet(path, columns=["timestamp_utc"])
        except Exception:
            continue
        ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dropna()
        if len(ts):
            return ts.max()
    return None


def _latest_decision_timestamp() -> tuple[pd.Timestamp, dict]:
    btc_latest = _latest_available_timestamp(BTC)
    xrp_latest = _latest_available_timestamp(XRP)
    if btc_latest is None:
        raise RuntimeError("No authoritative archive for BTC-USD")
    if xrp_latest is None:
        raise RuntimeError("No authoritative archive for XRP-USD")

    common_latest = min(btc_latest, xrp_latest)
    decision_ts = common_latest.floor("4h")

    if decision_ts.hour not in DECISION_HOURS_UTC or decision_ts.minute != 0:
        raise RuntimeError(f"Unexpected XRP 4-hour decision boundary: {decision_ts}")

    diagnostics = {
        "btc_latest_bar_utc": btc_latest.isoformat(),
        "xrp_latest_bar_utc": xrp_latest.isoformat(),
        "common_latest_bar_utc": common_latest.isoformat(),
    }
    return decision_ts, diagnostics


def _read_recent(product_id: str, end: pd.Timestamp) -> pd.DataFrame:
    start = end - pd.Timedelta(days=LOOKBACK_DAYS)
    start_period = start.tz_localize(None).to_period("M")
    end_period = end.tz_localize(None).to_period("M")
    months = pd.period_range(start_period, end_period, freq="M")

    frames = []
    for period in months:
        path = RAW_ROOT / product_id / f"{period}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        df = df[
            (df["timestamp_utc"] >= start)
            & (df["timestamp_utc"] <= end)
        ].copy()
        if len(df):
            frames.append(df)

    if not frames:
        raise RuntimeError(f"No recent authoritative bars for {product_id}")

    out = pd.concat(frames, ignore_index=True)
    out = (
        out.sort_values("timestamp_utc")
        .drop_duplicates(["timestamp_utc", "product_id"], keep="last")
        .reset_index(drop=True)
    )
    return out


def _build_feature_row(
    decision_ts: pd.Timestamp,
    frozen_features: list[str],
) -> tuple[pd.DataFrame, dict]:
    btc_raw = _read_recent(BTC, decision_ts)
    xrp_raw = _read_recent(XRP, decision_ts)

    if decision_ts not in set(btc_raw["timestamp_utc"]):
        raise RuntimeError(f"Decision candle {decision_ts} missing for BTC-USD")
    if decision_ts not in set(xrp_raw["timestamp_utc"]):
        raise RuntimeError(f"Decision candle {decision_ts} missing for XRP-USD")

    btc_base = _build_base_features(btc_raw)
    xrp_base = _build_base_features(xrp_raw)
    btc_context = _btc_context(btc_base)

    row = xrp_base[xrp_base["timestamp_utc"] == decision_ts].copy()
    if row.empty:
        raise RuntimeError(f"No XRP feature row at {decision_ts}")

    row = row.merge(
        btc_context,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )

    for bars in (1, 4, 16, 96):
        row[f"btc_relative_return_{bars}bar"] = (
            row[f"return_{bars}bar"] - row[f"btc_return_{bars}bar"]
        )

    missing = [column for column in frozen_features if column not in row.columns]
    if missing:
        raise RuntimeError("Live XRP row missing frozen features: " + ", ".join(missing))

    feature_frame = row[frozen_features].replace([np.inf, -np.inf], np.nan)
    bad = [column for column in frozen_features if pd.isna(feature_frame.iloc[0][column])]
    if bad:
        raise RuntimeError(
            "Live XRP row has incomplete trailing features at "
            f"{decision_ts}: " + ", ".join(bad)
        )

    current_segment = int(row.iloc[0]["segment_id"])
    segment_rows = xrp_base[xrp_base["segment_id"] == current_segment]
    segment_start = pd.Timestamp(segment_rows["timestamp_utc"].min())

    diagnostics = {
        "xrp_feature_segment_start_utc": segment_start.isoformat(),
        "xrp_feature_segment_rows_available": int(len(segment_rows)),
    }
    return feature_frame, diagnostics


def _predict(model, features: pd.DataFrame) -> float:
    prediction = model.predict(features)
    if len(prediction) != 1:
        raise RuntimeError("Frozen XRP Ridge returned unexpected prediction shape")
    score = float(prediction[0])
    if not np.isfinite(score):
        raise RuntimeError("Frozen XRP Ridge returned non-finite prediction")
    return score


def _next_state(current_state: str, score: float) -> str:
    if current_state == "XRP":
        if score <= -ENTRY_THRESHOLD:
            return "CASH"
        if score > EXIT_THRESHOLD:
            return "XRP"
        return "BTC"

    if current_state == "CASH":
        if score >= ENTRY_THRESHOLD:
            return "XRP"
        if score < -EXIT_THRESHOLD:
            return "CASH"
        return "BTC"

    if current_state != "BTC":
        raise RuntimeError(f"Unexpected XRP shadow state: {current_state}")

    if score >= ENTRY_THRESHOLD:
        return "XRP"
    if score <= -ENTRY_THRESHOLD:
        return "CASH"
    return "BTC"


def _default_state(manifest: dict) -> dict:
    return {
        "research_version": "crypto_xrp_v1",
        "phase": 6,
        "model_sha256": manifest["model"]["artifact_sha256"],
        "policy_id": POLICY_ID,
        "current_state": INITIAL_STATE,
        "state_since_utc": None,
        "last_decision_timestamp_utc": None,
        "last_score": None,
        "last_updated_utc": None,
        "brokerage_orders": False,
    }


def _load_state(manifest: dict) -> dict:
    if not STATE_PATH.exists():
        return _default_state(manifest)

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state.get("model_sha256") != manifest["model"]["artifact_sha256"]:
        raise RuntimeError("Existing XRP forward state belongs to a different model hash")
    if state.get("policy_id") != POLICY_ID:
        raise RuntimeError("Existing XRP forward state belongs to a different policy")
    if state.get("brokerage_orders") is not False:
        raise RuntimeError("Existing XRP forward state unexpectedly permits brokerage orders")
    if state.get("current_state") not in {"XRP", "BTC", "CASH"}:
        raise RuntimeError("Existing XRP forward state has invalid current_state")
    return state


def _xrp_continuous_between(previous: pd.Timestamp, current: pd.Timestamp) -> bool:
    if current - previous != EXPECTED_STEP:
        return False

    frame = _read_recent(XRP, current)
    window = frame[
        (frame["timestamp_utc"] > previous)
        & (frame["timestamp_utc"] <= current)
    ].copy()

    expected = pd.date_range(
        previous + pd.Timedelta(minutes=15),
        current,
        freq="15min",
        tz="UTC",
    )
    observed = set(window["timestamp_utc"])
    return len(window) == len(expected) and all(ts in observed for ts in expected)


def _advance_state(
    state: dict,
    decision_ts: pd.Timestamp,
    score: float,
) -> tuple[dict, dict]:
    last_value = state.get("last_decision_timestamp_utc")
    last_ts = pd.Timestamp(last_value) if last_value else None

    # Same/older decision: do not mutate policy state or replay history.
    if last_ts is not None and decision_ts <= last_ts:
        return state, {
            "action": "already_processed",
            "state_before": state["current_state"],
            "state_after": state["current_state"],
            "proposed_state": state["current_state"],
            "state_switch": False,
            "state_reset": False,
            "reset_reason": None,
            "minimum_hold_blocked": False,
            "hours_since_state_change": None,
        }

    state_before = state["current_state"]
    reset = False
    reset_reason = None

    if last_ts is None:
        reset = True
        reset_reason = "initialization"
    elif decision_ts - last_ts != EXPECTED_STEP:
        reset = True
        reset_reason = "missed_4h_decision_interval"
    elif not _xrp_continuous_between(last_ts, decision_ts):
        reset = True
        reset_reason = "xrp_continuity_break"

    if reset:
        state_after = INITIAL_STATE
        state["current_state"] = INITIAL_STATE
        state["state_since_utc"] = decision_ts.isoformat()
        proposed = INITIAL_STATE
        switched = False
        hold_blocked = False
        elapsed_hours = 0.0
    else:
        state_since_value = state.get("state_since_utc")
        if not state_since_value:
            raise RuntimeError("XRP state is missing state_since_utc without a reset")
        state_since = pd.Timestamp(state_since_value)
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

    diagnostics = {
        "action": "processed_new_decision",
        "state_before": state_before,
        "state_after": state_after,
        "proposed_state": proposed,
        "state_switch": bool(switched),
        "state_reset": bool(reset),
        "reset_reason": reset_reason,
        "minimum_hold_blocked": bool(hold_blocked),
        "hours_since_state_change": elapsed_hours,
    }
    return state, diagnostics


def _mode(decision_ts: pd.Timestamp) -> str:
    if decision_ts < HOLDOUT:
        return "SHADOW_PRE_HOLDOUT"
    return "SHADOW_FORWARD"


def run_once() -> dict:
    manifest, frozen_features, model = _load_contract()
    decision_ts, archive_diag = _latest_decision_timestamp()
    feature_frame, feature_diag = _build_feature_row(decision_ts, frozen_features)
    score = _predict(model, feature_frame)
    state = _load_state(manifest)
    state, state_diag = _advance_state(state, decision_ts, score)

    if state_diag["action"] == "processed_new_decision":
        _atomic_json(STATE_PATH, state)

    snapshot = {
        "research_version": "crypto_xrp_v1",
        "phase": 6,
        "research_status": "EXPLORATORY FORWARD CANDIDATE",
        "mode": _mode(decision_ts),
        "generated_at_utc": _utc_now().isoformat(),
        "decision_timestamp_utc": decision_ts.isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "model_id": "ridge",
        "model_sha256": manifest["model"]["artifact_sha256"],
        "feature_count": len(frozen_features),
        "predicted_btc_relative_return_4h": score,
        "policy_id": POLICY_ID,
        "entry_threshold_positive": ENTRY_THRESHOLD,
        "entry_threshold_negative": -ENTRY_THRESHOLD,
        "exit_threshold_from_xrp": EXIT_THRESHOLD,
        "exit_threshold_from_cash": -EXIT_THRESHOLD,
        "minimum_hold_hours": 24,
        "current_shadow_state": state["current_state"],
        "state_since_utc": state.get("state_since_utc"),
        "last_processed_decision_utc": state.get("last_decision_timestamp_utc"),
        "shadow_only": True,
        "forward_evaluation_journal": False,
        "brokerage_orders": False,
        "leverage": False,
        "shorting": False,
        "derivatives": False,
        "shared_crypto_v2_modified": False,
        **archive_diag,
        **feature_diag,
        **state_diag,
        "note": (
            "Shadow-only XRP inference. No historical replay, no performance "
            "journal, no model/policy tuning, and no real orders."
        ),
    }

    _atomic_json(SHADOW_PATH, snapshot)

    status = {
        "status": "ok",
        "generated_at_utc": _utc_now().isoformat(),
        "mode": snapshot["mode"],
        "decision_timestamp_utc": snapshot["decision_timestamp_utc"],
        "current_shadow_state": snapshot["current_shadow_state"],
        "predicted_btc_relative_return_4h": score,
        "action": state_diag["action"],
        "model_sha256_verified": True,
        "policy_verified": True,
        "shadow_only": True,
        "brokerage_orders": False,
    }
    _atomic_json(SERVICE_STATUS_PATH, status)
    return snapshot


def _write_error_status(exc: Exception) -> None:
    _atomic_json(
        SERVICE_STATUS_PATH,
        {
            "status": "error",
            "generated_at_utc": _utc_now().isoformat(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "shadow_only": True,
            "brokerage_orders": False,
        },
    )


def _handle_signal(signum, _frame) -> None:
    global _STOP
    _STOP = True


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one shadow inference cycle and exit.",
    )
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
                snapshot = run_once()
            except Exception as exc:
                _write_error_status(exc)
                raise
            print("CRYPTO XRP V1 SHADOW FORWARD")
            print("=" * 80)
            print(f"Mode:      {snapshot['mode']}")
            print(f"Decision:  {snapshot['decision_timestamp_utc']}")
            print(
                "Score:     "
                f"{snapshot['predicted_btc_relative_return_4h']:+.8f}"
            )
            print(f"State:     {snapshot['current_shadow_state']}")
            print(f"Action:    {snapshot['action']}")
            print(f"Reset:     {snapshot['state_reset']}")
            print(f"Switch:    {snapshot['state_switch']}")
            print("Shadow only. No real orders.")
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
