"""Scheduler entrypoint for the isolated frozen V10 Cycle 3 holdout."""
from __future__ import annotations

import traceback

from ml.v10.cycle3_holdout_runner import main as run_holdout
from ml.v10.cycle3_operational_monitor import run_monitor


def main():
    runner_error = None
    try:
        run_holdout()
    except Exception as exc:
        runner_error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    result = run_monitor(runner_error=runner_error)
    print("V10 CYCLE 3 SCHEDULED ENTRYPOINT")
    print("=" * 88)
    print(f"Operational monitor: {result['status']}")
    print(f"Notification: {result['notification']}")
    print("V8 modified: NO | brokerage orders: OFF")

    if runner_error or result["status"] != "HEALTHY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
