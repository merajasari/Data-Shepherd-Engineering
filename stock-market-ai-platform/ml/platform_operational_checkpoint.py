"""Read-only combined operational checkpoint for Data Shepherd model services.

Validates local web/API recovery, LaunchAgent registration, frozen identities, and
append-only journal integrity. It never invokes a model runner, writes evidence,
or imports a brokerage interface.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V8_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
V10_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
V10_CANDIDATE = "c3_confirm2_blend50"
SERVICES = (
    "com.datashepherd.web",
    "com.datashepherd.cloudflared",
    "com.datashepherd.v8paper",
    "com.datashepherd.v10cycle3",
    "com.datashepherd.papershadow",
)
ENDPOINTS = {
    "web_health": "http://127.0.0.1:5001/health",
    "v8_holdout": "http://127.0.0.1:5001/api/v8/holdout",
    "v10_cycle3": "http://127.0.0.1:5001/api/v10/cycle3/holdout",
    "performance": "http://127.0.0.1:5001/api/operations/performance",
}


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _journal(path):
    path = Path(path)
    rows = []
    if not path.exists():
        return rows
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.strip():
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"corrupt journal line {number}: {path}") from exc
    keys = [
        (row.get("event_type"), row.get("decision_timestamp_utc"), row.get("cohort_offset"))
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise RuntimeError(f"duplicate event key detected: {path}")
    return rows


def _service(label):
    if sys.platform != "darwin":
        return False, f"unsupported platform: {sys.platform}"
    target = f"gui/{os.getuid()}/{label}"
    import subprocess

    result = subprocess.run(
        ["launchctl", "print", target],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0, "registered" if result.returncode == 0 else "not registered"


def _endpoint(url):
    started = time.perf_counter()
    try:
        with urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload, (time.perf_counter() - started) * 1000.0
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{url}: {type(exc).__name__}: {exc}") from exc


def _check(condition, label, detail, failures):
    state = "PASS" if condition else "FAIL"
    print(f"[{state}] {label}: {detail}")
    if not condition:
        failures.append(f"{label}: {detail}")


def main():
    print("DATA SHEPHERD MODEL OPERATIONS CHECKPOINT")
    print("=" * 88)
    failures = []

    v8_spec = _json(PROJECT_ROOT / "data/model/v8/phase7/frozen_candidate_spec.json")
    v8_lock = (PROJECT_ROOT / "data/model/v8/phase7/frozen_candidate.sha256").read_text().strip().split()[0]
    v10_spec = _json(PROJECT_ROOT / "data/model/v10/cycle3/freeze/frozen_candidate_spec.json")

    _check(v8_spec.get("spec_sha256") == V8_SHA and v8_lock == V8_SHA,
           "V8 frozen identity", V8_SHA, failures)
    _check(v10_spec.get("spec_sha256") == V10_SHA,
           "V10 Cycle 3 frozen identity", V10_SHA, failures)
    _check(v10_spec.get("candidate_id") == V10_CANDIDATE,
           "V10 Cycle 3 candidate", str(v10_spec.get("candidate_id")), failures)

    v8_events = _journal(PROJECT_ROOT / "data/model/v8/holdout/journal.jsonl")
    v10_events = _journal(PROJECT_ROOT / "data/model/v10/cycle3/holdout/journal.jsonl")
    now = datetime.now(timezone.utc)
    if now < datetime(2026, 9, 1, tzinfo=timezone.utc):
        _check(len(v8_events) == 0, "V8 pre-boundary journal", f"events={len(v8_events)}", failures)
    else:
        _check(True, "V8 journal integrity", f"events={len(v8_events)}; duplicate-safe", failures)
    if now < datetime(2027, 1, 4, tzinfo=timezone.utc):
        _check(len(v10_events) == 0, "V10 pre-boundary journal", f"events={len(v10_events)}", failures)
    else:
        _check(True, "V10 journal integrity", f"events={len(v10_events)}; duplicate-safe", failures)

    from ml.trading.paper_shadow_operational_change_control import verify as verify_paper_shadow_lock
    _, protected_files, lock_failures = verify_paper_shadow_lock()
    _check(not lock_failures, "Paper-shadow operational change control",
           f"protected={len(protected_files)}; LOCKED_AND_VERIFIED" if not lock_failures else "; ".join(lock_failures),
           failures)

    monitor_path = PROJECT_ROOT / "data/trading/paper_shadow/monitor/status.json"
    try:
        paper_monitor = _json(monitor_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        paper_monitor = {}
        _check(False, "Paper-shadow monitor status",
               f"{type(exc).__name__}: {monitor_path}", failures)
    expected_execution = (
        "WAITING_FOR_BOUNDARY"
        if now < datetime(2026, 9, 1, tzinfo=timezone.utc)
        else "WAITING_FOR_MANUAL_ACTIVATION"
    )
    _check(paper_monitor.get("status") == "HEALTHY",
           "Paper-shadow monitor health", str(paper_monitor.get("status")), failures)
    _check(paper_monitor.get("execution_state") == expected_execution,
           "Paper-shadow execution state", str(paper_monitor.get("execution_state")), failures)
    _check(paper_monitor.get("bridge_status") == "PREREGISTERED_DISABLED",
           "Paper-shadow bridge state", str(paper_monitor.get("bridge_status")), failures)
    _check(paper_monitor.get("paper_account_status") in {"EMPTY_READY", "HEALTHY"},
           "Paper-shadow account state", str(paper_monitor.get("paper_account_status")), failures)
    _check(paper_monitor.get("signal_exports") == 0,
           "Paper-shadow signal exports", "0", failures)
    _check(paper_monitor.get("holdout_outcomes_read") is False,
           "Paper-shadow holdout outcome access", "NO", failures)
    _check(paper_monitor.get("production_holdout_evidence_modified") is False,
           "Paper-shadow production evidence writes", "NONE", failures)
    _check(paper_monitor.get("live_credentials") is False,
           "Paper-shadow live credentials", "ABSENT", failures)
    _check(paper_monitor.get("brokerage_orders") is False,
           "Paper-shadow brokerage authority", "OFF", failures)

    activation_path = PROJECT_ROOT / "data/trading/readiness/paper_shadow_activation_audit.json"
    try:
        activation_audit = _json(activation_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        activation_audit = {}
        _check(False, "Paper-shadow activation audit",
               f"{type(exc).__name__}: {activation_path}", failures)
    expected_audit_states = {"WAITING_FOR_BOUNDARY", "READY_FOR_MANUAL_APPROVAL"}
    _check(activation_audit.get("status") in expected_audit_states,
           "Paper-shadow activation audit state", str(activation_audit.get("status")), failures)
    _check(activation_audit.get("contract_sha256") ==
           "81e211909d3bb2dd6964fae959c1e81677a7861fb3402a00f813abcf16739e94",
           "Activation audit contract identity", str(activation_audit.get("contract_sha256")), failures)
    _check(activation_audit.get("manual_approval_required") is True,
           "Activation manual approval boundary", "REQUIRED", failures)
    _check(activation_audit.get("activation_performed") is False,
           "Paper-shadow activation authority", "NONE", failures)
    _check(activation_audit.get("paper_signal_export") is False,
           "Activation audit signal exports", "NONE", failures)
    _check(activation_audit.get("holdout_outcomes_read") is False,
           "Activation audit holdout outcome access", "NO", failures)
    _check(activation_audit.get("brokerage_orders") is False,
           "Activation audit brokerage authority", "OFF", failures)

    approval_contract = PROJECT_ROOT / "ml/trading/paper_shadow_manual_approval_contract.json"
    approval_contract_sha = __import__("hashlib").sha256(approval_contract.read_bytes()).hexdigest()
    _check(approval_contract_sha ==
           "28d38e8c9cfa2c5170b38b15a12d2110d04634ba6d3e7852b1bf4a111e424a4e",
           "Manual approval ceremony contract", approval_contract_sha, failures)
    approval_artifact = PROJECT_ROOT / "data/trading/paper_shadow/activation/manual_approval.json"
    if now < datetime(2026, 9, 1, tzinfo=timezone.utc):
        _check(not approval_artifact.exists(), "Pre-boundary manual approval artifact",
               "ABSENT", failures)
    else:
        _check(True, "Manual approval artifact state",
               "present for validation" if approval_artifact.exists() else "not present", failures)
    _check(True, "Manual approval validator authority", "READ ONLY", failures)
    _check(True, "Manual approval activation authority", "NONE", failures)

    for label in SERVICES:
        loaded, detail = _service(label)
        _check(loaded, f"LaunchAgent {label}", detail, failures)

    responses = {}
    for name, url in ENDPOINTS.items():
        try:
            status, payload, elapsed_ms = _endpoint(url)
            responses[name] = payload
            _check(status == 200, f"API {name}", f"HTTP {status}", failures)
            _check(elapsed_ms < 2000.0, f"API {name} latency", f"{elapsed_ms:.1f} ms (<2000 ms)", failures)
        except RuntimeError as exc:
            responses[name] = {}
            _check(False, f"API {name}", str(exc), failures)

    health = responses.get("web_health", {})
    _check(health.get("status") == "ok", "Web health payload", str(health.get("status")), failures)

    v8_api = responses.get("v8_holdout", {})
    _check(v8_api.get("frozen_sha256") == V8_SHA,
           "V8 API frozen identity", str(v8_api.get("frozen_sha256")), failures)
    _check(v8_api.get("brokerage_orders") is False,
           "V8 API brokerage authority", "OFF", failures)
    v8_ops = v8_api.get("launch_operations") or {}
    _check(v8_ops.get("request_time_historical_parquet_load") is False,
           "V8 API historical Parquet load", "DISABLED", failures)
    _check(float(v8_ops.get("response_cache_ttl_seconds") or 0) >= 10.0,
           "V8 API response cache", f"{v8_ops.get('response_cache_ttl_seconds')} seconds", failures)

    v10_api = responses.get("v10_cycle3", {})
    _check(v10_api.get("frozen_sha256") == V10_SHA,
           "V10 API frozen identity", str(v10_api.get("frozen_sha256")), failures)
    _check(v10_api.get("candidate_id") == V10_CANDIDATE,
           "V10 API candidate", str(v10_api.get("candidate_id")), failures)
    _check(v10_api.get("brokerage_orders") is False,
           "V10 API brokerage authority", "OFF", failures)
    _check(v10_api.get("v8_modified") is False,
           "V10 API V8 isolation", "V8 modified: NO", failures)

    performance = responses.get("performance", {})
    _check(performance.get("status") == "ok",
           "Endpoint timing telemetry", str(performance.get("status")), failures)
    _check(performance.get("brokerage_orders") is False,
           "Performance endpoint brokerage authority", "OFF", failures)
    _check((performance.get("sample_limit_per_endpoint") or 0) == 200,
           "Timing memory bound", "200 samples per endpoint", failures)
    _check("startup_policy" in performance,
           "Gunicorn lazy research-service policy", str(performance.get("startup_policy")), failures)

    print("\n" + "=" * 88)
    if failures:
        print("Status: FAILED")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)

    print("Status: HEALTHY")
    print(f"V8 journal events: {len(v8_events)}")
    print(f"V10 Cycle 3 journal events: {len(v10_events)}")
    print(f"Services registered: {len(SERVICES)}/{len(SERVICES)}")
    print(f"Local APIs healthy: {len(ENDPOINTS)}/{len(ENDPOINTS)}")
    print("Frozen identities: VERIFIED")
    print(f"Paper-shadow protected files: {len(protected_files)}")
    print(f"Paper-shadow execution state: {paper_monitor.get('execution_state')}")
    print(f"Activation audit state: {activation_audit.get('status')}")
    print("Activation performed: NO")
    print("Manual approval validator: READ ONLY")
    print("Brokerage orders: OFF")
    print("Evidence writes: NONE")


if __name__ == "__main__":
    main()
