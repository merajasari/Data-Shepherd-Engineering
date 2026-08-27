"""Read-only production preflight for V11 Phase 2 evidence collection."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ml.v11.intraday_phase2_contract import (
    contract_sha256,
    load_contract,
)
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    EvidenceJournalCorrupt,
    Phase2EvidenceJournal,
    build_rehearsal_event,
)

EXPECTED_CONTRACT_SHA256 = (
    "f539fabe9532752adb2a3b6b98aa244671b5ec8d8ae86b5eaacf8076f812a6c8"
)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def run_preflight(
    *,
    production_journal_path: Path = DEFAULT_JOURNAL_PATH,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    contract = load_contract()
    observed_sha = contract_sha256(contract)
    check(
        "contract_identity",
        observed_sha == EXPECTED_CONTRACT_SHA256,
        observed_sha,
    )
    check(
        "paper_confirmation_activation",
        contract["activation_status"]
        == "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY",
        str(contract["activation_status"]),
    )
    check(
        "fresh_boundary",
        contract["fresh_confirmation_start_utc"]
        == "2026-09-01T14:00:00+00:00",
        str(contract["fresh_confirmation_start_utc"]),
    )
    check(
        "paper_only",
        contract["paper_trading_only"] is True,
        "paper only",
    )
    check(
        "brokerage_orders",
        contract["brokerage_orders"] is False,
        "OFF",
    )
    check(
        "v8_v10_isolation",
        all(
            contract[field] is False
            for field in (
                "v8_production_reads",
                "v8_production_writes",
                "v10_production_reads",
                "v10_production_writes",
            )
        ),
        "no production reads/writes",
    )

    before = _snapshot(production_journal_path)
    production_valid = True
    production_detail = "valid/absent"
    try:
        Phase2EvidenceJournal(production_journal_path).read()
    except EvidenceJournalCorrupt as exc:
        production_valid = False
        production_detail = str(exc)
    check("production_journal_valid", production_valid, production_detail)

    with tempfile.TemporaryDirectory(prefix="v11_phase2_preflight_") as directory:
        rehearsal_path = Path(directory) / "evidence.jsonl"
        journal = Phase2EvidenceJournal(rehearsal_path)
        event = build_rehearsal_event()
        first_append = journal.append(event)
        second_append = journal.append(event)
        restarted_rows = Phase2EvidenceJournal(rehearsal_path).read()
        check("rehearsal_append", first_append, "first append accepted")
        check(
            "duplicate_safe",
            second_append is False and len(restarted_rows) == 1,
            f"rows={len(restarted_rows)}",
        )
        check(
            "restart_recovery",
            restarted_rows[0]["event_type"] == "DECISION",
            "chain reconstructed",
        )

        corrupted = Path(directory) / "corrupted.jsonl"
        corrupted.write_bytes(rehearsal_path.read_bytes().replace(b'"rehearsal":true', b'"rehearsal":false'))
        corrupt_failed_closed = False
        try:
            Phase2EvidenceJournal(corrupted).read()
        except EvidenceJournalCorrupt:
            corrupt_failed_closed = True
        check(
            "tamper_detection",
            corrupt_failed_closed,
            "modified record rejected",
        )

        pre_boundary = build_rehearsal_event(
            session_date="2026-08-31",
            timestamp_utc="2026-08-31T14:05:00+00:00",
        )
        boundary_failed_closed = False
        try:
            Phase2EvidenceJournal(
                Path(directory) / "pre_boundary.jsonl"
            ).append(pre_boundary)
        except ValueError:
            boundary_failed_closed = True
        check(
            "pre_boundary_fail_closed",
            boundary_failed_closed,
            "Aug 31 evidence rejected",
        )

    after = _snapshot(production_journal_path)
    check(
        "production_journal_unchanged",
        before == after,
        "read-only preflight",
    )

    passed = all(bool(row["passed"]) for row in checks)
    return {
        "status": "READY_PAPER_CONFIRMATION" if passed else "FAILED",
        "checks": checks,
        "contract_sha256": observed_sha,
        "fresh_confirmation_start_utc": contract[
            "fresh_confirmation_start_utc"
        ],
        "activation": "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY",
        "production_journal_events": (
            len(Phase2EvidenceJournal(production_journal_path).read())
            if production_valid
            else None
        ),
        "production_evidence_modified": before != after,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }


def main() -> None:
    print("V11 INTRADAY PHASE 2 OPERATIONAL PREFLIGHT")
    print("=" * 80)
    result = run_preflight()
    for row in result["checks"]:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}: {row['detail']}")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"Contract SHA-256: {result['contract_sha256']}")
    print(
        "Fresh confirmation boundary: "
        f"{result['fresh_confirmation_start_utc']}"
    )
    print(f"Production journal events: {result['production_journal_events']}")
    print(
        "Production evidence modified: "
        f"{'YES' if result['production_evidence_modified'] else 'NO'}"
    )
    print("Activation: ENABLED FRESH CONFIRMATION PAPER ONLY")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")
    if result["status"] != "READY_PAPER_CONFIRMATION":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
