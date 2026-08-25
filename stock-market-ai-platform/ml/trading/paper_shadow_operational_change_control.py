"""Verify paper-shadow operational files against the reviewed SHA manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ml.trading.paper_shadow_signal_bridge import contract_sha256, load_contract

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "ml/trading/paper_shadow_operational_lock_manifest.json"
EXPECTED_V8_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify() -> tuple[dict[str, Any], list[dict[str, str]], list[str]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    rules = manifest.get("rules") or {}
    contract = load_contract()

    if manifest.get("contract") != "DATA_SHEPHERD_PAPER_SHADOW_OPERATIONAL_CHANGE_CONTROL":
        failures.append("operational manifest identity mismatch")
    if manifest.get("frozen_candidate_sha256") != EXPECTED_V8_SHA:
        failures.append("operational manifest V8 frozen SHA mismatch")
    if contract.get("source_frozen_sha256") != EXPECTED_V8_SHA:
        failures.append("bridge contract V8 frozen SHA mismatch")
    if manifest.get("bridge_contract_sha256") != contract_sha256():
        failures.append("bridge contract hash does not match operational manifest")
    if contract.get("status") != "PREREGISTERED_DISABLED":
        failures.append("bridge must remain PREREGISTERED_DISABLED")
    if rules.get("bridge_status") != "PREREGISTERED_DISABLED":
        failures.append("manifest must lock the bridge disabled")
    if rules.get("manual_activation_required") is not True:
        failures.append("manifest must require manual activation")
    if rules.get("scheduler_mode") != "MONITOR_ONLY":
        failures.append("manifest must lock scheduler to monitor-only")
    if rules.get("signal_exports_before_activation") != 0:
        failures.append("manifest must lock pre-activation signal exports to zero")
    for field in (
        "holdout_outcomes_read",
        "production_holdout_journal_write",
        "live_credentials",
        "brokerage_orders",
    ):
        if rules.get(field) is not False:
            failures.append(f"manifest must lock {field}=false")

    checked: list[dict[str, str]] = []
    for item in manifest.get("protected_files") or []:
        relative = str(item.get("path"))
        expected = str(item.get("sha256"))
        path = PROJECT_ROOT / relative
        if not path.is_file():
            failures.append(f"missing protected file: {relative}")
            continue
        actual = _sha256(path)
        checked.append({"path": relative, "expected": expected, "actual": actual})
        if actual != expected:
            failures.append(
                f"protected file changed: {relative} expected={expected} actual={actual}"
            )
    if not checked:
        failures.append("manifest contains no protected files")
    return manifest, checked, failures


def main() -> None:
    manifest, checked, failures = verify()
    print("PAPER-SHADOW OPERATIONAL CHANGE-CONTROL VERIFICATION")
    print("=" * 88)
    print(f"Contract: {manifest.get('contract')}")
    print(f"Frozen V8 SHA: {manifest.get('frozen_candidate_sha256')}")
    print(f"Bridge contract SHA: {manifest.get('bridge_contract_sha256')}")
    for item in checked:
        mark = "PASS" if item["actual"] == item["expected"] else "FAIL"
        print(f"[{mark}] {item['path']}: {item['actual']}")
    if failures:
        print("Status: BLOCKED")
        for failure in failures:
            print(f"  - {failure}")
        print("Do not operate changed paper-shadow runtime code.")
        raise SystemExit(2)
    print(f"Protected files verified: {len(checked)}")
    print("Status: LOCKED_AND_VERIFIED")
    print("Bridge activation: DISABLED")
    print("Scheduler mode: MONITOR_ONLY")
    print("Signal exports: 0")
    print("Holdout outcomes read: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
