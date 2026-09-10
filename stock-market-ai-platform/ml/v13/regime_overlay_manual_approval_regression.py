"""Regression suite for the read-only V13 manual approval ceremony."""
from __future__ import annotations

import copy
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ml.v13.regime_overlay_manual_approval as approval_module
from ml.v13.regime_overlay_manual_approval import (
    APPROVAL_PATH,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    EXPECTED_V13_CONTRACT_SHA256,
    canonical_sha256,
    verify_approval,
)


def require(value: object, label: str) -> None:
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def fixture_preflight() -> dict[str, object]:
    return {
        "status": "READY_DISABLED",
        "contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "fresh_evidence_boundary_utc": "2026-09-01T14:00:00+00:00",
        "activation": "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "production_journal_events": 0,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def fixture_approval(
    preflight: dict[str, object], now: datetime
) -> dict[str, object]:
    return {
        "approval_type": "V13_FRESH_EVIDENCE_PAPER_ONLY",
        "operator": "Meraj Asari",
        "approved_at_utc": now.isoformat(),
        "preflight_sha256": canonical_sha256(preflight),
        "v13_contract_sha256": EXPECTED_V13_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "acknowledgement": (
            "I APPROVE V13 FRESH PAPER EVIDENCE ONLY; "
            "NO LIVE BROKERAGE AUTHORITY"
        ),
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def main() -> None:
    journal = (
        approval_module.ROOT
        / "data/research/v13/fresh_regime_overlay/evidence.jsonl"
    )
    before_approval = snapshot(APPROVAL_PATH)
    before_journal = snapshot(journal)
    now = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    preflight = fixture_preflight()
    approval = fixture_approval(preflight, now)

    valid = verify_approval(approval, preflight, now=now)
    require(valid["valid"], "Exact fresh post-boundary approval validates")
    require(
        valid["status"] == "VALID_FOR_SEPARATE_ACTIVATION_STEP",
        "Valid approval is limited to a separate future step",
    )
    require(
        valid["control_contract_sha256"] == EXPECTED_CONTRACT_SHA256,
        "Manual-approval ceremony identity is locked",
    )
    require(valid["approval_artifact_created"] is False, "Validator creates no approval")
    require(valid["activation_performed"] is False, "Validator cannot activate V13")
    require(valid["activation_lease_written"] is False, "Validator writes no lease")
    require(valid["evidence_appended"] is False, "Validator appends no evidence")
    require(valid["scheduler_changed"] is False, "Validator changes no scheduler")
    require(valid["brokerage_orders"] is False, "Validator has no brokerage authority")

    pre_boundary = verify_approval(
        approval,
        preflight,
        now=datetime(2026, 8, 31, 23, tzinfo=timezone.utc),
    )
    require(not pre_boundary["valid"], "Pre-boundary validation fails closed")

    stale_now = now + timedelta(hours=26)
    require(
        not verify_approval(approval, preflight, now=stale_now)["valid"],
        "Expired approval fails closed",
    )
    wrong_preflight = copy.deepcopy(approval)
    wrong_preflight["preflight_sha256"] = "0" * 64
    require(
        not verify_approval(wrong_preflight, preflight, now=now)["valid"],
        "Approval bound to another preflight fails closed",
    )
    wrong_v13 = copy.deepcopy(approval)
    wrong_v13["v13_contract_sha256"] = "0" * 64
    require(
        not verify_approval(wrong_v13, preflight, now=now)["valid"],
        "Wrong V13 identity fails closed",
    )
    wrong_phrase = copy.deepcopy(approval)
    wrong_phrase["acknowledgement"] = "approve"
    require(
        not verify_approval(wrong_phrase, preflight, now=now)["valid"],
        "Inexact acknowledgement fails closed",
    )
    brokerage = copy.deepcopy(approval)
    brokerage["brokerage_orders"] = True
    require(
        not verify_approval(brokerage, preflight, now=now)["valid"],
        "Brokerage authority fails closed",
    )
    mutated_preflight = copy.deepcopy(preflight)
    mutated_preflight["production_journal_events"] = 1
    rebound = fixture_approval(mutated_preflight, now)
    require(
        not verify_approval(rebound, mutated_preflight, now=now)["valid"],
        "Preactivation evidence fails readiness",
    )

    require(
        not hasattr(approval_module, "create_approval"),
        "Approval creation capability is absent",
    )
    require(
        not hasattr(approval_module, "activate"),
        "Activation capability is absent",
    )
    source = inspect.getsource(approval_module).lower()
    for forbidden in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(forbidden not in source, f"Brokerage SDK absent: {forbidden}")
    require(snapshot(APPROVAL_PATH) == before_approval, "Approval artifact remains unchanged")
    require(snapshot(journal) == before_journal, "Production journal remains unchanged")

    print("\nStatus: PASSED")
    print("V13 manual approval validator: VERIFIED READ ONLY")
    print("Approval artifact creation authority: NONE")
    print("Fresh evidence activation authority: NONE")
    print("Production evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production evidence modified: NO")


if __name__ == "__main__":
    main()
