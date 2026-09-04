"""Regression checks for immutable V13 paper-only lease renewal."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT, activate
from ml.v13.regime_overlay_lease_renewal_apply import (
    EXPECTED_APPLICATION_CONTRACT_SHA256,
    V13LeaseRenewalRejected,
    renew,
    validate_renewal_chain,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    preflight = {
        "status": "READY_DISABLED",
        "contract_sha256": "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702",
        "v12_disposition_sha256": "d099f7cd1b915f05ef3e57dd1f5f2e6eff21962f3202821cb3a115290915d6f2",
        "activation": "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "production_journal_events": 0,
        "production_evidence_modified": False,
        "paper_trading_only": True,
        "brokerage_orders": False,
    }
    with TemporaryDirectory(prefix="v13_renewal_apply_") as raw:
        root = Path(raw)
        approval_path = root / "manual_approval.json"
        lease_path = root / "lease.json"
        renewals_path = root / "renewals"
        journal_path = root / "evidence.jsonl"
        issued = datetime(2026, 9, 4, 14, tzinfo=timezone.utc)
        activate(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=issued,
            approval_path=approval_path,
            lease_path=lease_path,
            preflight_runner=lambda: preflight,
        )
        originals = (approval_path.read_bytes(), lease_path.read_bytes())

        try:
            renew(
                operator="Meraj Asari",
                acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
                now_utc=issued + timedelta(hours=23),
                approval_path=approval_path,
                lease_path=lease_path,
                renewals_path=renewals_path,
                journal_path=journal_path,
            )
        except V13LeaseRenewalRejected:
            require(not renewals_path.exists(), "Overlapping renewal is rejected before artifact creation")
        else:
            raise AssertionError("Overlapping renewal is rejected before artifact creation")

        first = renew(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=issued + timedelta(hours=24),
            approval_path=approval_path,
            lease_path=lease_path,
            renewals_path=renewals_path,
            journal_path=journal_path,
        )
        require(first["sequence"] == 1 and first["active"] is True, "First expired lease renews as sequence 000001")
        require(len(EXPECTED_APPLICATION_CONTRACT_SHA256) == 64, "Renewal application contract identity is locked")
        require((approval_path.read_bytes(), lease_path.read_bytes()) == originals, "Original approval and lease remain byte-for-byte unchanged")
        require(not journal_path.exists() and first["evidence_appended"] is False, "Renewal binds but does not append evidence")
        require(first["scheduler_changed"] is False and first["market_data_requested"] is False, "Renewal changes no scheduler and requests no data")
        require(first["paper_trading_only"] is True and first["live_trading_enabled"] is False and first["brokerage_orders"] is False, "Renewal retains paper-only authority")

        try:
            renew(
                operator="Meraj Asari",
                acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
                now_utc=issued + timedelta(hours=25),
                approval_path=approval_path,
                lease_path=lease_path,
                renewals_path=renewals_path,
                journal_path=journal_path,
            )
        except V13LeaseRenewalRejected:
            require(True, "Renewed lease cannot be overlapped")
        else:
            raise AssertionError("Renewed lease cannot be overlapped")

        second = renew(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=issued + timedelta(hours=48),
            approval_path=approval_path,
            lease_path=lease_path,
            renewals_path=renewals_path,
            journal_path=journal_path,
        )
        first_lease = json.loads((renewals_path / "000001/lease.json").read_text())
        second_lease = json.loads((renewals_path / "000002/lease.json").read_text())
        require(second["sequence"] == 2 and second_lease["previous_lease_sha256"] == first["lease_sha256"], "Second renewal is immutably hash-linked to the first")
        require(validate_renewal_chain(approval_path=approval_path, lease_path=lease_path, renewals_path=renewals_path, journal_path=journal_path, now_utc=issued + timedelta(hours=49))["valid"] is True, "Complete renewal chain validates")

        for bad_operator, bad_ack, label in (
            ("Different Operator", REQUIRED_ACKNOWLEDGEMENT, "Different operator is rejected"),
            ("Meraj Asari", "APPROVE", "Non-exact acknowledgement is rejected"),
        ):
            try:
                renew(operator=bad_operator, acknowledgement=bad_ack, now_utc=issued + timedelta(hours=72), approval_path=approval_path, lease_path=lease_path, renewals_path=renewals_path, journal_path=journal_path)
            except V13LeaseRenewalRejected:
                require(True, label)
            else:
                raise AssertionError(label)

        first_lease["brokerage_orders"] = True
        (renewals_path / "000001/lease.json").write_text(json.dumps(first_lease), encoding="utf-8")
        try:
            validate_renewal_chain(approval_path=approval_path, lease_path=lease_path, renewals_path=renewals_path, journal_path=journal_path, now_utc=issued + timedelta(hours=49))
        except V13LeaseRenewalRejected:
            require(True, "Tampered historical renewal blocks the entire chain")
        else:
            raise AssertionError("Tampered historical renewal blocks the entire chain")

    print("Status: PASSED")
    print("V13 immutable lease renewal: VERIFIED FAIL CLOSED")
    print("Original activation artifacts modified: NO")
    print("Evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
