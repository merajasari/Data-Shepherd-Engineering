"""Production V8 EOD orchestration entry point.

This is the only scheduler-facing path that is allowed to invoke the frozen
V8 forward holdout runner.  It always evaluates the fail-closed EOD guard
first.  Only when the guard publishes ``decision_gate_open=true`` do we invoke
the append-only holdout runner.

The orchestration lock prevents the legacy V8 scheduler and the EOD refresh
scheduler from entering the runner concurrently.  The runner remains
idempotent, verifies the frozen contract/SHA on every invocation, places no
brokerage orders, and writes no holdout journal evidence before 2026-09-01.
"""
from __future__ import annotations

import fcntl
from pathlib import Path

from ml.v8.eod_guard import run_guard
from ml.v8.holdout_runner import main as run_holdout

LOCK_PATH = Path("data/model/v8/eod_guard/orchestrator.lock")


def main():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("V8 EOD ORCHESTRATOR")
            print("=" * 88)
            print("Status: SKIP_ALREADY_RUNNING")
            print("Another guarded V8 orchestration invocation is active.")
            return

        guard = run_guard()
        print("V8 EOD ORCHESTRATOR")
        print("=" * 88)
        print(f"Guard status: {guard.get('status')}")
        print(f"Decision gate open: {guard.get('decision_gate_open')}")
        print(f"Ranking timestamp: {guard.get('ranking_timestamp_utc')}")
        print(f"Eligible names: {guard.get('ranking_eligible_count')}/100")

        if not guard.get("decision_gate_open"):
            print("Holdout runner NOT invoked. Fail-closed policy enforced.")
            return

        print("Guard passed. Invoking frozen V8 holdout runner...")
        run_holdout()


if __name__ == "__main__":
    main()
