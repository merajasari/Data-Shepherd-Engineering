"""Fail-closed scheduler entrypoint for paper-shadow operations.

While the bridge is preregistered-disabled this entrypoint performs monitoring
only. It intentionally imports no signal-export runner or brokerage adapter.
"""
from __future__ import annotations

from ml.trading.paper_shadow_operational_monitor import run_monitor


def main() -> None:
    result = run_monitor()
    print("PAPER-SHADOW SCHEDULED ENTRYPOINT")
    print("=" * 88)
    print(f"Operational monitor: {result['status']}")
    print(f"Execution state: {result['execution_state']}")
    print("Bridge invocation: BLOCKED")
    print("Signal exports: 0")
    print("Holdout outcomes read: NO")
    print("Production evidence modified: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    if result["status"] != "HEALTHY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
