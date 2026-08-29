"""Fail-closed regression for the V13 journal and disabled preflight."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    EXPECTED_V12_EVALUATION_SHA256,
)
from ml.v13.regime_overlay_journal import (
    GENESIS_HASH,
    RegimeOverlayEvidenceJournal,
    V13EvidenceActivationDisabled,
    V13EvidenceJournalCorrupt,
    V13EvidenceJournalLockTimeout,
    build_rehearsal_event,
)
from ml.v13.regime_overlay_preflight import run_preflight


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def predecessor_payload() -> dict[str, object]:
    return {
        "status": "V12_DEVELOPMENT_CLOSED_RETAIN_V10",
        "decision": "RETAIN_FROZEN_V10_CONTROL",
        "selected_candidate": "V10_CONTROL_5K",
        "evaluation_sha256": EXPECTED_V12_EVALUATION_SHA256,
        "disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "post_result_v12_tuning_allowed": False,
        "candidate_frozen": False,
        "fresh_paper_confirmation_activated": False,
        "brokerage_orders": False,
        "production_modified": False,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="v13_journal_regression_") as directory:
        root = Path(directory)
        path = root / "evidence.jsonl"
        journal = RegimeOverlayEvidenceJournal(path, rehearsal=True)
        decision = build_rehearsal_event()

        require(journal.append(decision), "First rehearsal decision appends")
        require(not journal.append(decision), "Duplicate decision is idempotent")
        rows = RegimeOverlayEvidenceJournal(path).read()
        require(len(rows) == 1, "Restart reconstructs one event")
        require(
            rows[0]["previous_record_sha256"] == GENESIS_HASH,
            "First record anchors to genesis",
        )
        require(
            rows[0]["contract_sha256"] == EXPECTED_CONTRACT_SHA256,
            "V13 contract identity is journaled",
        )
        require(
            rows[0]["v12_disposition_sha256"]
            == EXPECTED_V12_DISPOSITION_SHA256,
            "V12 disposition identity is journaled",
        )
        require(rows[0]["rehearsal"] is True, "Rehearsal evidence is explicit")
        require(rows[0]["fresh_evidence"] is False, "Rehearsal is not fresh evidence")
        require(rows[0]["paper_trading_only"] is True, "Journal remains paper only")
        require(rows[0]["live_trading_enabled"] is False, "Live trading remains disabled")
        require(rows[0]["brokerage_orders"] is False, "Journal has no brokerage authority")

        observation = build_rehearsal_event(
            event_type="PAIRED_SESSION_OBSERVATION",
            timestamp_utc="2026-09-01T20:05:00+00:00",
        )
        require(journal.append(observation), "Paired session observation appends")
        chained = journal.read()
        require(len(chained) == 2, "Exactly two lifecycle events persist")
        require(
            chained[1]["previous_record_sha256"]
            == chained[0]["record_sha256"],
            "Records form a SHA-256 chain",
        )
        require(
            chained[1]["control_net_return"] == 0.001
            and chained[1]["challenger_net_return"] == 0.0015,
            "Paired control and challenger outcomes are preserved",
        )

        observation_first_failed = False
        try:
            RegimeOverlayEvidenceJournal(
                root / "observation_first.jsonl",
                rehearsal=True,
            ).append(
                build_rehearsal_event(
                    event_type="PAIRED_SESSION_OBSERVATION",
                    session_date="2026-09-02",
                    timestamp_utc="2026-09-02T20:05:00+00:00",
                )
            )
        except ValueError:
            observation_first_failed = True
        require(
            observation_first_failed,
            "Observation before decision fails closed",
        )

        production_path = root / "production_attempt.jsonl"
        production_disabled = False
        try:
            RegimeOverlayEvidenceJournal(production_path).append(decision)
        except V13EvidenceActivationDisabled:
            production_disabled = True
        require(production_disabled, "Non-rehearsal append is disabled")
        require(not production_path.exists(), "Disabled append creates no evidence file")

        unlabeled_path = root / "unlabeled.jsonl"
        unlabeled_failed = False
        unlabeled = dict(decision)
        unlabeled["rehearsal"] = False
        try:
            RegimeOverlayEvidenceJournal(
                unlabeled_path,
                rehearsal=True,
            ).append(unlabeled)
        except V13EvidenceActivationDisabled:
            unlabeled_failed = True
        require(unlabeled_failed, "Unlabeled rehearsal append is rejected")
        require(not unlabeled_path.exists(), "Rejected rehearsal creates no file")

        pre_boundary_failed = False
        try:
            RegimeOverlayEvidenceJournal(
                root / "early.jsonl",
                rehearsal=True,
            ).append(
                build_rehearsal_event(
                    session_date="2026-08-31",
                    timestamp_utc="2026-08-31T14:05:00+00:00",
                )
            )
        except ValueError:
            pre_boundary_failed = True
        require(pre_boundary_failed, "Pre-boundary evidence fails closed")

        wrong_contract = dict(decision)
        wrong_contract["contract_sha256"] = "f" * 64
        wrong_contract_failed = False
        try:
            RegimeOverlayEvidenceJournal(
                root / "wrong_contract.jsonl",
                rehearsal=True,
            ).append(wrong_contract)
        except ValueError:
            wrong_contract_failed = True
        require(wrong_contract_failed, "Wrong V13 contract identity fails closed")

        wrong_predecessor = dict(decision)
        wrong_predecessor["v12_disposition_sha256"] = "f" * 64
        wrong_predecessor_failed = False
        try:
            RegimeOverlayEvidenceJournal(
                root / "wrong_predecessor.jsonl",
                rehearsal=True,
            ).append(wrong_predecessor)
        except ValueError:
            wrong_predecessor_failed = True
        require(
            wrong_predecessor_failed,
            "Wrong V12 disposition identity fails closed",
        )

        unsafe = dict(decision)
        unsafe["brokerage_orders"] = True
        unsafe_failed = False
        try:
            RegimeOverlayEvidenceJournal(
                root / "unsafe.jsonl",
                rehearsal=True,
            ).append(unsafe)
        except ValueError:
            unsafe_failed = True
        require(unsafe_failed, "Brokerage authority fails closed")

        tampered_lines = path.read_text(encoding="utf-8").splitlines()
        altered = json.loads(tampered_lines[0])
        altered["regime_eligible"] = False
        tampered_lines[0] = json.dumps(
            altered,
            separators=(",", ":"),
            sort_keys=True,
        )
        tampered_path = root / "tampered.jsonl"
        tampered_path.write_text(
            "\n".join(tampered_lines) + "\n",
            encoding="utf-8",
        )
        tamper_failed = False
        try:
            RegimeOverlayEvidenceJournal(tampered_path).read()
        except V13EvidenceJournalCorrupt:
            tamper_failed = True
        require(tamper_failed, "Tampered journal fails closed")

        malformed_path = root / "malformed.jsonl"
        malformed_path.write_text("{not-json}\n", encoding="utf-8")
        malformed_failed = False
        try:
            RegimeOverlayEvidenceJournal(malformed_path).read()
        except V13EvidenceJournalCorrupt:
            malformed_failed = True
        require(malformed_failed, "Malformed journal fails closed")

        lock_path = root / "locked.jsonl"
        locked = RegimeOverlayEvidenceJournal(
            lock_path,
            rehearsal=True,
            lock_timeout_seconds=0.02,
        )
        locked.lock_path.mkdir()
        lock_failed = False
        try:
            locked.append(
                build_rehearsal_event(
                    session_date="2026-09-03",
                    timestamp_utc="2026-09-03T14:05:00+00:00",
                )
            )
        except V13EvidenceJournalLockTimeout:
            lock_failed = True
        finally:
            locked.lock_path.rmdir()
        require(lock_failed, "Lock contention times out safely")
        require(not lock_path.exists(), "Lock timeout creates no evidence")

        disposition_path = root / "v12_status.json"
        disposition_path.write_text(
            json.dumps(predecessor_payload()),
            encoding="utf-8",
        )
        preflight_production = root / "preflight_production.jsonl"
        preflight = run_preflight(
            production_journal_path=preflight_production,
            v12_disposition_path=disposition_path,
        )
        require(preflight["status"] == "READY_DISABLED", "Operational preflight passes")
        require(
            preflight["activation"]
            == "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
            "Preflight preserves disabled activation",
        )
        require(
            not preflight_production.exists(),
            "Preflight creates no production evidence",
        )
        require(
            preflight["production_evidence_modified"] is False,
            "Production evidence remains unchanged",
        )

        nonempty_production = root / "nonempty_production.jsonl"
        RegimeOverlayEvidenceJournal(
            nonempty_production,
            rehearsal=True,
        ).append(decision)
        blocked = run_preflight(
            production_journal_path=nonempty_production,
            v12_disposition_path=disposition_path,
        )
        require(
            blocked["status"] == "FAILED",
            "Preactivation production evidence fails readiness",
        )

    for source_name in (
        "regime_overlay_journal.py",
        "regime_overlay_preflight.py",
    ):
        source = Path(__file__).with_name(source_name).read_text(encoding="utf-8")
        for forbidden_import in (
            "import alpaca",
            "from alpaca",
            "import robin_stocks",
            "from robin_stocks",
            "import ib_insync",
        ):
            require(
                forbidden_import not in source,
                f"Brokerage SDK absent from {source_name}: {forbidden_import}",
            )

    print("Status: PASSED")
    print("V13 append-only evidence journal: VERIFIED REHEARSAL ONLY")
    print("Duplicate/restart/tamper/boundary/lock safety: VERIFIED")
    print("Production evidence activation: DISABLED")
    print("Production evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production evidence modified: NO")


if __name__ == "__main__":
    main()
