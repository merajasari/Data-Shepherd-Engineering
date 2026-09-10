"""Scheduler entry point for guarded V8 orchestration plus alert monitoring."""
from __future__ import annotations

import traceback

from ml.v8.eod_orchestrator import main as run_orchestrator
from ml.v8.operational_monitor import run_monitor


def main():
    orchestrator_error = None
    try:
        run_orchestrator()
    except Exception as exc:
        orchestrator_error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    result = run_monitor(orchestrator_error=orchestrator_error)
    print("V8 SCHEDULED ENTRYPOINT")
    print("=" * 88)
    print(f"Operational monitor: {result['status']}")
    print(f"Notification: {result['notification']}")
    print("Production evidence modified by monitor: NO")
    print("Brokerage orders: OFF")

    if orchestrator_error or result["status"] != "HEALTHY":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
