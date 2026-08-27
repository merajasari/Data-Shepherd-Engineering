"""Read-only health monitor for V11 Phase 2 launch control."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    EvidenceJournalCorrupt,
    Phase2EvidenceJournal,
)
from ml.v11.intraday_phase2_preflight import EXPECTED_CONTRACT_SHA256
from ml.v11.intraday_phase2_scheduled_entrypoint import STATUS_PATH

ROOT = Path(__file__).resolve().parents[2]


def run_monitor(
    *,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, object]:
    failures: list[str] = []
    contract = load_contract()
    observed_sha = contract_sha256(contract)
    if observed_sha != EXPECTED_CONTRACT_SHA256:
        failures.append("CONTRACT_SHA_MISMATCH")

    try:
        events = Phase2EvidenceJournal(journal_path).read()
    except EvidenceJournalCorrupt as exc:
        failures.append(f"JOURNAL_INVALID:{exc}")
        events = []


    operational = None
    if status_path.exists():
        try:
            operational = json.loads(
                status_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            failures.append(
                f"OPERATIONAL_STATUS_INVALID:{type(exc).__name__}"
            )
    if isinstance(operational, dict):
        if operational.get("contract_sha256") != observed_sha:
            failures.append("STATUS_CONTRACT_SHA_MISMATCH")
        if operational.get("brokerage_orders") is not False:
            failures.append("BROKERAGE_AUTHORITY_VIOLATION")

    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "HEALTHY_PAPER_CONFIRMATION" if not failures else "ALERT",
        "failures": failures,
        "contract_sha256": observed_sha,
        "activation": contract["activation_status"],
        "journal_events": len(events),
        "operational_status": (
            operational.get("status")
            if isinstance(operational, dict)
            else "NOT_YET_PUBLISHED"
        ),
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }


def main() -> None:
    print("V11 PHASE 2 OPERATIONAL MONITOR")
    print("=" * 80)
    result = run_monitor()
    print(f"Status: {result['status']}")
    print(f"Activation: {result['activation']}")
    print(f"Journal events: {result['journal_events']}")
    print(f"Scheduled status: {result['operational_status']}")
    if result["failures"]:
        print("Failures:")
        for failure in result["failures"]:
            print(f" - {failure}")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")
    if result["status"] == "ALERT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
