"""Regression suite for the V11 Phase 2 evidence journal and preflight."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import (
    EvidenceJournalCorrupt,
    Phase2EvidenceJournal,
    build_rehearsal_event,
)
from ml.v11.intraday_phase2_preflight import run_preflight


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    contract = load_contract()
    with tempfile.TemporaryDirectory(prefix="v11_phase2_regression_") as directory:
        root = Path(directory)
        path = root / "evidence.jsonl"
        journal = Phase2EvidenceJournal(path)
        event = build_rehearsal_event()

        require(journal.append(event), "First post-boundary event appends")
        require(not journal.append(event), "Duplicate event is idempotent")
        rows = Phase2EvidenceJournal(path).read()
        require(len(rows) == 1, "Restart reconstructs one event")
        require(rows[0]["previous_record_sha256"] == "0" * 64, "First record anchors to genesis")
        require(rows[0]["contract_sha256"] == contract_sha256(contract), "Contract identity is journaled")
        require(rows[0]["paper_trading_only"] is True, "Journal remains paper only")
        require(rows[0]["brokerage_orders"] is False, "Journal has no brokerage authority")

        second = {
            **build_rehearsal_event(
                session_date="2026-09-02",
                timestamp_utc="2026-09-02T14:05:00+00:00",
            ),
            "event_type": "SESSION_OBSERVATION",
            "strategy_net_return": 0.001,
            "spy_return": 0.0005,
            "net_excess_return": 0.0005,
        }
        require(journal.append(second), "Second session event appends")
        chained = journal.read()
        require(
            chained[1]["previous_record_sha256"]
            == chained[0]["record_sha256"],
            "Records form a SHA-256 chain",
        )

        tampered_lines = path.read_text(encoding="utf-8").splitlines()
        altered = json.loads(tampered_lines[0])
        altered["selected_symbols"][0] = "TAMPERED"
        tampered_lines[0] = json.dumps(altered, separators=(",", ":"), sort_keys=True)
        tampered = root / "tampered.jsonl"
        tampered.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")
        failed_closed = False
        try:
            Phase2EvidenceJournal(tampered).read()
        except EvidenceJournalCorrupt:
            failed_closed = True
        require(failed_closed, "Tampered journal fails closed")

        pre_boundary_failed = False
        try:
            Phase2EvidenceJournal(root / "early.jsonl").append(
                build_rehearsal_event(
                    session_date="2026-08-31",
                    timestamp_utc="2026-08-31T14:05:00+00:00",
                )
            )
        except ValueError:
            pre_boundary_failed = True
        require(pre_boundary_failed, "Pre-boundary evidence fails closed")

        wrong_sha = build_rehearsal_event(
            session_date="2026-09-03",
            timestamp_utc="2026-09-03T14:05:00+00:00",
        )
        wrong_sha["contract_sha256"] = "f" * 64
        wrong_contract_failed = False
        try:
            Phase2EvidenceJournal(root / "wrong.jsonl").append(wrong_sha)
        except ValueError:
            wrong_contract_failed = True
        require(wrong_contract_failed, "Wrong contract identity fails closed")

        production = root / "production.jsonl"
        preflight = run_preflight(production_journal_path=production)
        require(preflight["status"] == "READY_DISABLED", "Operational preflight passes")
        require(not production.exists(), "Preflight creates no production evidence")
        require(preflight["production_evidence_modified"] is False, "Production evidence remains unchanged")
        require(preflight["activation"] == "DISABLED", "Activation remains disabled")

    require(contract["v8_production_writes"] is False, "V8 production remains isolated")
    require(contract["v10_production_writes"] is False, "V10 production remains isolated")
    print("Status: PASSED")
    print("Append-only evidence journal: VERIFIED")
    print("Duplicate/restart/tamper/boundary safety: VERIFIED")
    print("Activation: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
