"""Run the complete frozen V8 operational validation suite."""
from __future__ import annotations

import subprocess
import sys

MODULES = [
    ("Dedicated invariants", "ml.v8.holdout_invariant_tests"),
    ("End-to-end rehearsal", "ml.v8.holdout_rehearsal"),
    ("Forward dashboard regression", "ml.v8.holdout_dashboard_regression"),
    ("Production preflight", "ml.v8.production_preflight"),
    ("Operational change control", "ml.v8.operational_change_control"),
]


def main():
    print("V8 COMPLETE OPERATIONAL VALIDATION SUITE")
    print("=" * 88)
    failures = []

    for label, module in MODULES:
        print(f"\n--- {label}: python -m {module} ---")
        result = subprocess.run([sys.executable, "-m", module], check=False)
        if result.returncode:
            failures.append((label, module, result.returncode))

    print("\n" + "=" * 88)
    if failures:
        print("Status: FAILED")
        for label, module, returncode in failures:
            print(f"  - {label}: {module} exited {returncode}")
        print("Production promotion/operation must remain blocked.")
        raise SystemExit(2)

    print("Status: PASSED")
    print(f"Validation modules passed: {len(MODULES)}/{len(MODULES)}")
    print("Frozen V8 operational code: VERIFIED")
    print("Production holdout evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
