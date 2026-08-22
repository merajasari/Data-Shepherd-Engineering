"""Efficient scheduled V10 prospective-confirmation cycle.

The main EOD scheduler invokes this frequently, but the expensive confirmation
reconstruction only runs when the common feature session advances. Artifacts are
published read-only for the dashboard after each successful run.

A same-session invocation may still rebuild once when a newly introduced
artifact is missing. This keeps dashboard publication complete across code
deployments without treating an unchanged feature session as new evidence.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ml.v10.confirmation import CONTRACT_PATH, HISTORY_PATH, STATUS_PATH, main as run_confirmation

READINESS_STATUS = Path("data/model/v8/readiness/status.json")
CYCLE_STATE = Path("data/model/v10/confirmation/cycle_state.json")
PUBLIC_DIR = Path("webapp/static/generated")
PUBLIC_STATUS = PUBLIC_DIR / "v10_confirmation_status.json"
PUBLIC_CONTRACT = PUBLIC_DIR / "v10_confirmation_contract.json"
PUBLIC_HISTORY = PUBLIC_DIR / "v10_confirmation_history.json"


def _read_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _feature_common_latest():
    data = _read_json(READINESS_STATUS)
    return data.get("checks", {}).get("feature_common_latest_utc")


def _publish():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    if STATUS_PATH.exists():
        shutil.copyfile(STATUS_PATH, PUBLIC_STATUS)
    if CONTRACT_PATH.exists():
        shutil.copyfile(CONTRACT_PATH, PUBLIC_CONTRACT)
    if HISTORY_PATH.exists():
        shutil.copyfile(HISTORY_PATH, PUBLIC_HISTORY)


def _all_local_artifacts_exist():
    """Return True only when every expected confirmation artifact exists.

    This prevents a same-session optimization skip from leaving a newly added
    dashboard artifact unpublished after a deployment. Rebuilding here remains
    deterministic because confirmation.py derives artifacts only from already
    completed prospective evidence and does not mutate the locked contract.
    """
    return all(path.exists() for path in (STATUS_PATH, CONTRACT_PATH, HISTORY_PATH))


def main():
    latest = _feature_common_latest()
    previous = _read_json(CYCLE_STATE).get("last_feature_common_latest_utc")

    # Always publish already-existing artifacts, even when no new EOD session is
    # available. This makes dashboard deployment independent of research reruns.
    _publish()

    artifacts_complete = _all_local_artifacts_exist()
    if latest and latest == previous and artifacts_complete:
        print(f"V10 CONFIRMATION CYCLE: SKIP | common feature session unchanged at {latest}")
        return

    if latest and latest == previous and not artifacts_complete:
        missing = [
            str(path)
            for path in (STATUS_PATH, CONTRACT_PATH, HISTORY_PATH)
            if not path.exists()
        ]
        print("V10 CONFIRMATION CYCLE: REBUILD MISSING ARTIFACTS")
        print("=" * 88)
        print(f"Common feature session unchanged at: {latest}")
        print("Missing: " + ", ".join(missing))
    else:
        print("V10 CONFIRMATION CYCLE")
        print("=" * 88)
        print(f"Feature common latest: {latest or 'unknown'}")
        print(f"Previously processed: {previous or 'none'}")

    run_confirmation()
    _publish()

    CYCLE_STATE.parent.mkdir(parents=True, exist_ok=True)
    CYCLE_STATE.write_text(json.dumps({
        "last_feature_common_latest_utc": latest,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status_path": str(STATUS_PATH),
        "public_status_path": str(PUBLIC_STATUS),
        "public_history_path": str(PUBLIC_HISTORY),
        "production_modified": False,
        "brokerage_orders": False,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
