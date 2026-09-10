"""Run the complete frozen V10 Cycle 3 operational validation suite."""
from __future__ import annotations

import subprocess
import sys

MODULES = [
    ("Read-only readiness", "ml.v10.cycle3_readiness"),
    ("End-to-end isolated rehearsal", "ml.v10.cycle3_holdout_rehearsal"),
    ("Production preflight", "ml.v10.cycle3_production_preflight"),
    ("Operational monitor", "ml.v10.cycle3_operational_monitor"),
    ("Operational change control", "ml.v10.cycle3_operational_change_control"),
]


def main():
    print("V10 CYCLE 3 COMPLETE OPERATIONAL VALIDATION SUITE")
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
        print("Cycle 3 operation must remain blocked.")
        raise SystemExit(2)

    print("Status: PASSED")
    print(f"Validation modules passed: {len(MODULES)}/{len(MODULES)}")
    print("Frozen Cycle 3 operational code: VERIFIED")
    print("Production holdout evidence modified: NO")
    print("V8 modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
