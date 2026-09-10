"""Publish read-only operational health for the stock scheduler/dashboard.

This module never mutates research, holdout, portfolio, or brokerage state. It
summarizes scheduler outcome, rolling Tiingo quota, EOD data convergence, V8
gate state, V10 confirmation state, feature freshness, and recent error-log
metadata.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ml.feature_source import (
    feature_dataset_exists,
    get_feature_backend,
    get_feature_dataset_path,
    get_feature_root,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "webapp/static/generated/stock_operations_health.json"
LEDGER = PROJECT_ROOT / "data/live/v5_tiingo_request_ledger.json"
V8_GUARD = PROJECT_ROOT / "data/model/v8/eod_guard/status.json"
V10_MONITOR = PROJECT_ROOT / "data/model/v10/cycle3/monitor/alert_state.json"
V10_SPEC = PROJECT_ROOT / "data/model/v10/cycle3/freeze/frozen_candidate_spec.json"
V10_EXPECTED_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
CONVERGENCE_STATUS = PROJECT_ROOT / "webapp/static/generated/stock_data_convergence.json"
ERR_LOG_CANDIDATES = (
    PROJECT_ROOT / "logs/v8_refresh.err.log",
    PROJECT_ROOT / "logs/v5_refresh.err.log",
)
EXPECTED_SYMBOLS = 101
DEFAULT_HOURLY_LIMIT = 45
MAX_SUPPORTED_HOURLY_LIMIT = 10_000


def _now():
    return datetime.now(timezone.utc)


def _configured_hourly_limit():
    raw = os.environ.get("TIINGO_HOURLY_REQUEST_LIMIT")
    if raw is None or not raw.strip():
        return DEFAULT_HOURLY_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HOURLY_LIMIT
    return value if 1 <= value <= MAX_SUPPORTED_HOURLY_LIMIT else DEFAULT_HOURLY_LIMIT


def _configured_tiingo_plan():
    value = os.environ.get("TIINGO_PLAN", "starter").strip().lower()
    return value if value in {"starter", "power"} else "unknown"


def _json(path: Path):
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}


def _iso_mtime(path: Path):
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _active_quota(now: datetime):
    payload = _json(LEDGER)
    cutoff = now - timedelta(hours=1)
    active = []
    for raw in payload.get("request_timestamps_utc", []):
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        if cutoff < ts <= now:
            active.append(ts)
    return len(active)


def _feature_common_latest():
    backend = get_feature_backend()
    root = get_feature_root(project_root=PROJECT_ROOT, backend=backend)
    latest = []
    found = 0
    if not root.exists():
        return None, found, backend
    for symbol_dir in root.iterdir():
        if not symbol_dir.is_dir():
            continue
        symbol = symbol_dir.name
        path = get_feature_dataset_path(
            symbol, project_root=PROJECT_ROOT, backend=backend
        )
        if not feature_dataset_exists(path):
            continue
        found += 1
        try:
            df = pd.read_parquet(path, columns=["timestamp_utc"])
            values = pd.to_datetime(
                df["timestamp_utc"], utc=True, errors="coerce"
            ).dropna()
            if not values.empty:
                latest.append(values.max())
        except Exception:
            continue
    if not latest:
        return None, found, backend
    return min(latest).isoformat(), found, backend


def _active_error_log():
    existing = [path for path in ERR_LOG_CANDIDATES if path.exists()]
    return max(existing, key=lambda path: path.stat().st_mtime) if existing else ERR_LOG_CANDIDATES[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline-exit-code", type=int, default=None)
    args = parser.parse_args()

    now = _now()
    used = _active_quota(now)
    hourly_limit = _configured_hourly_limit()
    tiingo_plan = _configured_tiingo_plan()
    v8 = _json(V8_GUARD)
    v10_monitor = _json(V10_MONITOR)
    v10_spec = _json(V10_SPEC)
    v10_identity_ok = v10_spec.get("spec_sha256") == V10_EXPECTED_SHA
    convergence = _json(CONVERGENCE_STATUS)
    common_latest, feature_files, feature_backend = _feature_common_latest()
    err_log = _active_error_log()
    err_size = err_log.stat().st_size if err_log.exists() else 0

    if args.pipeline_exit_code is None:
        scheduler_status = "UNKNOWN"
    elif args.pipeline_exit_code == 0:
        scheduler_status = "HEALTHY"
    else:
        scheduler_status = "ERROR"

    payload = {
        "generated_at_utc": now.isoformat(),
        "scheduler": {
            "status": scheduler_status,
            "last_exit_code": args.pipeline_exit_code,
            "schedule": "every_5_minutes",
            "real_orders": False,
        },
        "tiingo": {
            "rolling_requests_used": used,
            "plan": tiingo_plan,
            "rolling_request_limit": hourly_limit,
            "rolling_requests_available": max(0, hourly_limit - used),
            "quota_saturated": used >= hourly_limit,
        },
        "features": {
            "files_found": feature_files,
            "expected_files": EXPECTED_SYMBOLS,
            "common_latest_utc": common_latest,
            "backend": feature_backend,
        },
        "convergence": {
            "status": convergence.get("status", "UNKNOWN"),
            "target_session_utc": convergence.get("target_session_utc"),
            "data_converged": convergence.get("data_converged"),
            "verification": convergence.get("verification", "UNKNOWN"),
            "safety_violation": bool(convergence.get("safety_violation")),
            "layers": convergence.get("layers") or {},
        },
        "v8": {
            "guard_status": v8.get("status", "UNKNOWN"),
            "decision_gate_open": v8.get("decision_gate_open"),
            "ranking_timestamp_utc": v8.get("ranking_timestamp_utc"),
        },
        "v10": {
            "status": v10_monitor.get("status", "UNKNOWN"),
            "decision": "FROZEN_FRESH_HOLDOUT_AUTHORIZED" if v10_identity_ok else "FROZEN_IDENTITY_MISMATCH",
            "candidate_id": v10_spec.get("candidate_id"),
            "frozen_sha256": v10_spec.get("spec_sha256"),
            "formal_holdout_start_utc": (v10_spec.get("holdout_contract") or {}).get("fresh_holdout_start_utc"),
            "journal_events": v10_monitor.get("journal_events", 0),
            "brokerage_orders": False,
            "v8_modified": False,
        },
        "error_log": {
            "path": str(err_log.relative_to(PROJECT_ROOT)),
            "bytes": err_size,
            "modified_at_utc": _iso_mtime(err_log),
        },
        "safety": {
            "brokerage_orders": False,
            "production_mutation_from_health_publisher": False,
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n")
    temp.replace(OUTPUT)

    print("STOCK OPERATIONS HEALTH")
    print("=" * 80)
    print(f"Scheduler: {scheduler_status} | exit={args.pipeline_exit_code}")
    print(f"Tiingo ({tiingo_plan}): {used}/{hourly_limit} rolling requests")
    print(f"Features ({feature_backend}): {feature_files}/{EXPECTED_SYMBOLS} | common latest={common_latest}")
    print(f"Convergence: {payload['convergence']['status']} | verification={payload['convergence']['verification']}")
    print(f"V8 guard: {payload['v8']['guard_status']} | gate={payload['v8']['decision_gate_open']}")
    print(f"V10 Cycle 3: {payload['v10']['status']} | decision={payload['v10']['decision']}")
    print(f"Output: {OUTPUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
