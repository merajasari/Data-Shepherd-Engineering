"""Combined pre-boundary regression gate for frozen crypto forward evaluation.

Runs the Shared Crypto V2 forward-service invariant suite, the XRP V1 Phase 7
invariant suite, and the canonical crypto pre-holdout readiness audit. The
runner stops at the first failing stage and returns a non-zero exit code.

This module does not run either live forward service and does not place orders.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...]


STAGES = (
    Stage(
        "Shared Crypto V2 forward invariants",
        (sys.executable, "-m", "unittest", "tests.test_crypto_15m_v2_forward_service", "-v"),
    ),
    Stage(
        "XRP V1 Phase 7 invariants",
        (sys.executable, "-m", "unittest", "tests.test_crypto_xrp_v1_phase7", "-v"),
    ),
    Stage(
        "Canonical pre-holdout readiness audit",
        (sys.executable, "-m", "ml.crypto_pre_holdout_readiness"),
    ),
)


def _run_stage(index: int, stage: Stage) -> bool:
    print()
    print("=" * 100)
    print(f"[{index}/{len(STAGES)}] {stage.name}")
    print("=" * 100)
    sys.stdout.flush()
    result = subprocess.run(stage.command, check=False)
    if result.returncode != 0:
        print()
        print(f"FAILED: {stage.name} (exit code {result.returncode})")
        return False
    print()
    print(f"PASS: {stage.name}")
    return True


def main() -> int:
    print("CRYPTO PRE-BOUNDARY REGRESSION GATE")
    print("=" * 100)
    print("Runs both frozen forward invariant suites plus the canonical readiness audit.")
    print("Real brokerage orders: NO")

    for index, stage in enumerate(STAGES, start=1):
        if not _run_stage(index, stage):
            print()
            print("PRE_BOUNDARY_REGRESSION_FAILED")
            return 1

    print()
    print("=" * 100)
    print("PRE_BOUNDARY_REGRESSION_PASSED")
    print("Shared V2 invariants: PASS")
    print("XRP Phase 7 invariants: PASS")
    print("Canonical readiness audit: PASS")
    print("Real brokerage orders: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
