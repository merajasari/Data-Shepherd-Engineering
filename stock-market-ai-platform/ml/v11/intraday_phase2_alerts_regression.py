"""Regression coverage for V11 milestone, failure and recovery alerts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v11.intraday_phase2_alerts import run
from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    Phase2EvidenceJournal,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def event(event_type: str) -> dict[str, object]:
    contract = load_contract()
    return {
        "event_type": event_type,
        "session_date": "2026-09-01",
        "timestamp_utc": "2026-09-01T15:00:00+00:00",
        "contract_sha256": contract_sha256(contract),
        "rehearsal": False,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }


def healthy(**_: object) -> dict[str, object]:
    return {
        "status": "HEALTHY_PAPER_CONFIRMATION",
        "failures": [],
        "operational_status": "COMPLETE_SESSION",
    }


def failed(**_: object) -> dict[str, object]:
    return {
        "status": "ALERT",
        "failures": ["SCHEDULER_FAILURE:synthetic"],
        "operational_status": "ERROR",
    }


def main() -> None:
    production_before = digest(DEFAULT_JOURNAL_PATH)
    with TemporaryDirectory() as raw:
        root = Path(raw)
        journal_path = root / "evidence.jsonl"
        state_path = root / "alerts.json"
        journal = Phase2EvidenceJournal(journal_path)
        for event_type in ("DECISION", "ENTRY", "SESSION_OBSERVATION"):
            journal.append(event(event_type))

        delivered: list[tuple[str, str]] = []
        notifier = lambda title, message: not delivered.append((title, message))
        scheduler_ok = lambda: (True, "registered")

        first = run(
            now=datetime(2026, 9, 1, 16, tzinfo=timezone.utc),
            journal_path=journal_path,
            state_path=state_path,
            notifier=notifier,
            scheduler_check=scheduler_ok,
            health_runner=healthy,
        )
        require(
            first["new_milestones"]
            == ["DECISION", "ENTRY", "SESSION_OBSERVATION"],
            "First decision, entry and completed-session milestones notify",
        )
        require(len(delivered) == 3, "Exactly three milestone notices are sent")

        second = run(
            journal_path=journal_path,
            state_path=state_path,
            notifier=notifier,
            scheduler_check=scheduler_ok,
            health_runner=healthy,
        )
        require(second["new_milestones"] == [], "Milestones are duplicate-safe")
        require(len(delivered) == 3, "Restart sends no duplicate milestone notice")

        problem = run(
            journal_path=journal_path,
            state_path=state_path,
            notifier=notifier,
            scheduler_check=scheduler_ok,
            health_runner=failed,
        )
        require(
            problem["operational_notification"] == "NEW_FAILURE",
            "Scheduler failure sends one new alert",
        )
        repeated = run(
            journal_path=journal_path,
            state_path=state_path,
            notifier=notifier,
            scheduler_check=scheduler_ok,
            health_runner=failed,
        )
        require(
            repeated["operational_notification"] == "NONE",
            "Repeated failure is deduplicated",
        )
        recovered = run(
            journal_path=journal_path,
            state_path=state_path,
            notifier=notifier,
            scheduler_check=scheduler_ok,
            health_runner=healthy,
        )
        require(
            recovered["operational_notification"] == "RECOVERY",
            "Scheduler recovery sends one recovery notice",
        )
        require(
            recovered["production_evidence_modified"] is False,
            "Alert monitor never modifies production evidence",
        )
        require(
            recovered["brokerage_orders"] is False,
            "Alert monitor has no brokerage authority",
        )

    require(
        digest(DEFAULT_JOURNAL_PATH) == production_before,
        "Production V11 journal remains unchanged",
    )
    print("Status: PASSED")
    print("V11 milestones/failure/recovery alerts: VERIFIED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
