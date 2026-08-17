"""Pre-holdout readiness audit for frozen crypto forward evaluation.

This audit is intentionally read-mostly. It verifies the frozen Shared Crypto
15m V2 and XRP V1 Phase 6/7 contracts, runtime freshness, process state,
pre-holdout journal locks, writable output directories, and the permanent
absence of brokerage-order capability before the untouched future evaluation
boundary at 2026-09-01 00:00 UTC.

Exit codes
----------
0: READY_FOR_FORWARD_EVALUATION
1: NOT_READY_FOR_FORWARD_EVALUATION

The audit never fits a model, changes a threshold, advances policy state, writes
an evaluation decision, or places a brokerage order. Temporary write probes are
created and immediately removed only to verify filesystem writability.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any

import pandas as pd


HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")

RECONCILE_STATUS = Path("data/live/crypto_rt/reconcile_status.json")

V2_ROOT = Path("data/model/crypto_15m_v2/phase5")
V2_MODEL = V2_ROOT / "frozen_hgb.joblib"
V2_MANIFEST = V2_ROOT / "freeze_manifest.json"
V2_STATE = V2_ROOT / "forward_state.json"
V2_JOURNAL = V2_ROOT / "forward_journal.csv"
V2_STATUS = V2_ROOT / "forward_service_status.json"

XRP6_ROOT = Path("data/model/crypto_xrp_v1/phase6")
XRP6_MODEL = XRP6_ROOT / "frozen_ridge.joblib"
XRP6_MANIFEST = XRP6_ROOT / "freeze_manifest.json"
XRP6_STATE = XRP6_ROOT / "forward_state.json"
XRP6_STATUS = XRP6_ROOT / "forward_service_status.json"

XRP7_ROOT = Path("data/model/crypto_xrp_v1/phase7")
XRP7_STATUS = XRP7_ROOT / "evaluation_status.json"
XRP7_MANIFEST = XRP7_ROOT / "evaluator_manifest.json"
XRP7_STATE = XRP7_ROOT / "evaluation_state.json"
XRP7_JOURNAL = XRP7_ROOT / "forward_evaluation_events.jsonl"

FRESHNESS_MINUTES = {
    "15m Reconciler": 45,
    "Shared V2 Forward": 90,
    "XRP V1 Forward": 90,
    "XRP Phase 7 Evaluator": 90,
}

LAUNCH_AGENTS = {
    "15m Reconciler": "com.datashepherd.cryptoreconcile",
    "Shared V2 Forward": "com.datashepherd.cryptov2forward",
    "XRP V1 Forward": "com.datashepherd.xrpforward",
    "XRP Phase 7 Evaluator": "com.datashepherd.xrpphase7",
}


class Audit:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.rows.append({"name": name, "passed": bool(passed), "detail": detail})

    @property
    def passed(self) -> bool:
        return all(row["passed"] for row in self.rows)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return ts.to_pydatetime()
    except Exception:
        return None


def _heartbeat(path: Path, payload: dict) -> datetime | None:
    for key in ("generated_at_utc", "last_updated_utc", "updated_at_utc"):
        parsed = _parse_utc(payload.get(key))
        if parsed is not None:
            return parsed
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _status_fresh(audit: Audit, name: str, path: Path, payload: dict) -> None:
    raw_status = str(payload.get("status", "ok")).strip().lower()
    healthy_status = raw_status in {"ok", "success", "running", "healthy"}
    audit.check(
        f"{name} runtime status",
        healthy_status,
        f"status={raw_status!r}",
    )
    hb = _heartbeat(path, payload)
    limit = FRESHNESS_MINUTES[name]
    if hb is None:
        audit.check(f"{name} heartbeat freshness", False, "No usable heartbeat timestamp")
        return
    age = max(0.0, (_utc_now() - hb).total_seconds() / 60.0)
    audit.check(
        f"{name} heartbeat freshness",
        age <= limit,
        f"age={age:.1f} min, stale_after={limit} min, heartbeat={hb.isoformat()}",
    )


def _write_probe(audit: Audit, name: str, directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix=".readiness_probe_", dir=directory)
        os.write(fd, b"readiness\n")
        os.fsync(fd)
        os.close(fd)
        Path(path).unlink()
    except Exception as exc:
        audit.check(name, False, f"write probe failed: {type(exc).__name__}: {exc}")
        return
    audit.check(name, True, f"temporary write/delete probe succeeded in {directory}")


def _launchagent_check(audit: Audit, name: str, label: str) -> None:
    if platform.system() != "Darwin":
        audit.check(f"{name} LaunchAgent", True, "Skipped: launchctl check applies to macOS")
        return
    try:
        uid = os.getuid()
        result = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{label}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        audit.check(f"{name} LaunchAgent", False, f"launchctl failed: {exc}")
        return
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    running = result.returncode == 0 and "state = running" in text
    detail = "loaded and running" if running else f"launchctl returncode={result.returncode}"
    audit.check(f"{name} LaunchAgent", running, detail)


def _csv_data_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    return max(0, len(rows) - 1)


def _audit_shared_v2(audit: Audit, pre_holdout: bool) -> None:
    required = [V2_MODEL, V2_MANIFEST, V2_STATE, V2_JOURNAL, V2_STATUS]
    for path in required:
        audit.check(f"Shared V2 file exists: {path.name}", path.exists(), str(path))
    if not all(path.exists() for path in required):
        return

    try:
        manifest = _read_json(V2_MANIFEST)
        state = _read_json(V2_STATE)
        status = _read_json(V2_STATUS)
    except Exception as exc:
        audit.check("Shared V2 JSON readable", False, str(exc))
        return
    audit.check("Shared V2 JSON readable", True, "freeze manifest, state, and status parsed")

    actual_hash = _sha256(V2_MODEL)
    expected_hash = manifest.get("model", {}).get("artifact_sha256")
    audit.check(
        "Shared V2 frozen model SHA-256",
        bool(expected_hash) and actual_hash == expected_hash,
        f"expected={expected_hash}, actual={actual_hash}",
    )

    policy = manifest.get("execution_policy", {})
    audit.check(
        "Shared V2 frozen policy",
        policy.get("policy_id") == "confirm_2"
        and int(policy.get("confirmation_hours", -1)) == 2
        and str(policy.get("decision_frequency")) == "1 hour",
        f"policy={policy.get('policy_id')}, confirmation_hours={policy.get('confirmation_hours')}, decision_frequency={policy.get('decision_frequency')}",
    )
    boundary = pd.Timestamp(manifest.get("future_evaluation_start_utc"))
    audit.check("Shared V2 holdout boundary", boundary == HOLDOUT, f"boundary={boundary.isoformat()}")

    prohibited = set(manifest.get("prohibited", []))
    audit.check(
        "Shared V2 brokerage-order prohibition",
        "brokerage order placement" in prohibited and status.get("brokerage_orders") is False,
        f"manifest_prohibited={sorted(prohibited)}, runtime_brokerage_orders={status.get('brokerage_orders')}",
    )

    audit.check(
        "Shared V2 runtime model verification",
        status.get("model_sha256_verified") is not False,
        f"model_sha256_verified={status.get('model_sha256_verified')}",
    )
    _status_fresh(audit, "Shared V2 Forward", V2_STATUS, status)

    journal_rows = _csv_data_rows(V2_JOURNAL)
    if pre_holdout:
        audit.check(
            "Shared V2 pre-holdout journal lock",
            journal_rows == 0,
            f"forward journal data rows={journal_rows}",
        )
        audit.check(
            "Shared V2 pre-holdout runtime mode",
            str(status.get("mode")) == "SHADOW",
            f"mode={status.get('mode')}",
        )
    else:
        audit.check("Shared V2 journal readable", True, f"forward journal data rows={journal_rows}")

    state_boundary = pd.Timestamp(state.get("forward_evaluation_start_utc"))
    audit.check(
        "Shared V2 state boundary",
        state_boundary == HOLDOUT,
        f"state boundary={state_boundary.isoformat()}",
    )
    _write_probe(audit, "Shared V2 output path writable", V2_ROOT)


def _audit_xrp(audit: Audit, pre_holdout: bool) -> None:
    required = [
        XRP6_MODEL,
        XRP6_MANIFEST,
        XRP6_STATE,
        XRP6_STATUS,
        XRP7_STATUS,
        XRP7_MANIFEST,
    ]
    for path in required:
        audit.check(f"XRP file exists: {path.name}", path.exists(), str(path))
    if not all(path.exists() for path in required):
        return

    try:
        phase6 = _read_json(XRP6_MANIFEST)
        phase6_status = _read_json(XRP6_STATUS)
        phase7 = _read_json(XRP7_MANIFEST)
        phase7_status = _read_json(XRP7_STATUS)
    except Exception as exc:
        audit.check("XRP contract JSON readable", False, str(exc))
        return
    audit.check("XRP contract JSON readable", True, "Phase 6/7 manifests and statuses parsed")

    actual_model_hash = _sha256(XRP6_MODEL)
    frozen_model_hash = phase6.get("model", {}).get("artifact_sha256")
    audit.check(
        "XRP frozen Ridge SHA-256",
        bool(frozen_model_hash) and actual_model_hash == frozen_model_hash,
        f"expected={frozen_model_hash}, actual={actual_model_hash}",
    )

    policy = phase6.get("execution_policy", {})
    correct_policy = (
        policy.get("policy_id") == "hyst_10_05_hold24"
        and int(policy.get("decision_cadence_hours", -1)) == 4
        and float(policy.get("entry_threshold_positive", 99)) == 0.001
        and float(policy.get("entry_threshold_negative", 99)) == -0.001
        and float(policy.get("exit_threshold_from_xrp", 99)) == 0.0005
        and float(policy.get("exit_threshold_from_cash", 99)) == -0.0005
        and int(policy.get("minimum_hold_hours", -1)) == 24
    )
    audit.check("XRP frozen Phase 6 policy", correct_policy, f"policy_id={policy.get('policy_id')}")

    phase6_boundary = pd.Timestamp(phase6.get("future_holdout_start_utc"))
    phase7_boundary = pd.Timestamp(phase7.get("future_holdout_start_utc"))
    status_boundary = pd.Timestamp(phase7_status.get("future_holdout_start_utc"))
    audit.check(
        "XRP Phase 6/7 holdout boundary",
        phase6_boundary == HOLDOUT and phase7_boundary == HOLDOUT and status_boundary == HOLDOUT,
        f"phase6={phase6_boundary.isoformat()}, phase7={phase7_boundary.isoformat()}, status={status_boundary.isoformat()}",
    )

    actual_phase6_manifest_hash = _sha256(XRP6_MANIFEST)
    expected_source_hash = phase7.get("source_phase6_manifest_sha256")
    audit.check(
        "XRP Phase 7 source-manifest pin",
        expected_source_hash == actual_phase6_manifest_hash,
        f"expected={expected_source_hash}, actual={actual_phase6_manifest_hash}",
    )
    audit.check(
        "XRP Phase 7 model pin",
        phase7.get("frozen_model_sha256") == actual_model_hash,
        f"phase7={phase7.get('frozen_model_sha256')}, actual={actual_model_hash}",
    )
    actual_policy_hash = _canonical_sha256(policy)
    audit.check(
        "XRP Phase 7 policy pin",
        phase7.get("frozen_policy_sha256") == actual_policy_hash,
        f"phase7={phase7.get('frozen_policy_sha256')}, actual={actual_policy_hash}",
    )

    no_orders = (
        phase6.get("brokerage_orders") is False
        and phase7.get("brokerage_orders") is False
        and phase6_status.get("brokerage_orders") is False
        and phase7_status.get("brokerage_orders") is False
    )
    audit.check("XRP brokerage orders permanently disabled", no_orders, "Phase 6/7 manifest and runtime flags all false")
    audit.check(
        "XRP Phase 7 no selection or tuning",
        phase7.get("selection_or_tuning") is False,
        f"selection_or_tuning={phase7.get('selection_or_tuning')}",
    )
    audit.check(
        "XRP Phase 7 no missed-decision backfill",
        phase7.get("missed_decision_backfill") is False,
        f"missed_decision_backfill={phase7.get('missed_decision_backfill')}",
    )
    audit.check(
        "XRP Phase 7 pre-holdout writes prohibited",
        phase7.get("pre_holdout_journal_writes_allowed") is False,
        f"pre_holdout_journal_writes_allowed={phase7.get('pre_holdout_journal_writes_allowed')}",
    )
    audit.check(
        "XRP runtime model verification",
        phase6_status.get("model_sha256_verified") is True and phase7_status.get("model_sha256_verified") is True,
        f"phase6={phase6_status.get('model_sha256_verified')}, phase7={phase7_status.get('model_sha256_verified')}",
    )
    audit.check(
        "XRP runtime policy verification",
        phase6_status.get("policy_verified") is True and phase7_status.get("policy_verified") is True,
        f"phase6={phase6_status.get('policy_verified')}, phase7={phase7_status.get('policy_verified')}",
    )
    _status_fresh(audit, "XRP V1 Forward", XRP6_STATUS, phase6_status)
    _status_fresh(audit, "XRP Phase 7 Evaluator", XRP7_STATUS, phase7_status)

    if pre_holdout:
        audit.check(
            "XRP Phase 7 pre-holdout journal lock",
            not XRP7_JOURNAL.exists(),
            "journal absent" if not XRP7_JOURNAL.exists() else f"unexpected journal exists: {XRP7_JOURNAL}",
        )
        audit.check(
            "XRP Phase 7 readiness mode",
            phase7_status.get("mode") == "WAITING_PRE_HOLDOUT",
            f"mode={phase7_status.get('mode')}",
        )
        audit.check(
            "XRP Phase 6 shadow mode",
            phase6_status.get("mode") == "SHADOW_PRE_HOLDOUT",
            f"mode={phase6_status.get('mode')}",
        )
    else:
        audit.check("XRP Phase 7 journal path", True, f"journal_exists={XRP7_JOURNAL.exists()}")

    _write_probe(audit, "XRP Phase 7 output path writable", XRP7_ROOT)


def _audit_reconciler(audit: Audit) -> None:
    audit.check("Reconciler status file exists", RECONCILE_STATUS.exists(), str(RECONCILE_STATUS))
    if not RECONCILE_STATUS.exists():
        return
    try:
        status = _read_json(RECONCILE_STATUS)
    except Exception as exc:
        audit.check("Reconciler status readable", False, str(exc))
        return
    audit.check("Reconciler status readable", True, "JSON parsed")
    _status_fresh(audit, "15m Reconciler", RECONCILE_STATUS, status)
    product_count = int(status.get("product_count", 0) or 0)
    audit.check("Reconciler universe available", product_count >= 25, f"product_count={product_count}")


def run_audit() -> Audit:
    audit = Audit()
    now = pd.Timestamp(_utc_now())
    pre_holdout = now < HOLDOUT
    audit.check(
        "Audit boundary context",
        True,
        f"now={now.isoformat()}, holdout={HOLDOUT.isoformat()}, pre_holdout={pre_holdout}",
    )

    _audit_reconciler(audit)
    _audit_shared_v2(audit, pre_holdout)
    _audit_xrp(audit, pre_holdout)

    for name, label in LAUNCH_AGENTS.items():
        _launchagent_check(audit, name, label)

    return audit


def _print(audit: Audit) -> None:
    print("CRYPTO PRE-HOLDOUT READINESS AUDIT")
    print("=" * 100)
    for row in audit.rows:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}")
        print(f"       {row['detail']}")
    print()
    print("=" * 100)
    if audit.passed:
        print("READY_FOR_FORWARD_EVALUATION")
    else:
        failures = sum(not row["passed"] for row in audit.rows)
        print(f"NOT_READY_FOR_FORWARD_EVALUATION ({failures} failed checks)")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    audit = run_audit()
    _print(audit)
    raise SystemExit(0 if audit.passed else 1)


if __name__ == "__main__":
    main()
