"""Verify V8 operational runtime files against the reviewed SHA manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ml.v8.holdout_runner import EXPECTED_SHA

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "ml/v8/operational_lock_manifest.json"


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    failures = []

    if manifest.get("frozen_candidate_sha256") != EXPECTED_SHA:
        failures.append("manifest frozen SHA does not match holdout runner EXPECTED_SHA")
    if manifest.get("rules", {}).get("brokerage_orders") is not False:
        failures.append("manifest must lock brokerage_orders=false")

    checked = []
    for item in manifest.get("protected_files", []):
        relative = item.get("path")
        expected = item.get("sha256")
        path = PROJECT_ROOT / str(relative)
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


def main():
    manifest, checked, failures = verify()
    print("V8 OPERATIONAL CHANGE-CONTROL VERIFICATION")
    print("=" * 88)
    print(f"Contract: {manifest.get('contract')}")
    print(f"Frozen candidate SHA: {manifest.get('frozen_candidate_sha256')}")
    for item in checked:
        mark = "PASS" if item["actual"] == item["expected"] else "FAIL"
        print(f"[{mark}] {item['path']}: {item['actual']}")

    if failures:
        print("Status: BLOCKED")
        for failure in failures:
            print(f"  - {failure}")
        print("Do not operate or promote changed V8 runtime code.")
        raise SystemExit(2)

    print(f"Protected files verified: {len(checked)}")
    print("Status: LOCKED_AND_VERIFIED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
