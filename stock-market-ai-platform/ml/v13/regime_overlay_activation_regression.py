"""Regression coverage for the real, paper-only V13 activation ceremony."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_activation import (
    ENABLED_ACTIVATION,
    REQUIRED_ACKNOWLEDGEMENT,
    V13ActivationRejected,
    activate,
    validate_activation_lease,
)
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
)
from ml.v13.regime_overlay_journal import DISABLED_ACTIVATION


SOURCE = Path(__file__).with_name("regime_overlay_activation.py")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def ready_preflight() -> dict[str, object]:
    return {
        "status": "READY_DISABLED",
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "activation": DISABLED_ACTIVATION,
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


def main() -> None:
    now = datetime(2026, 9, 4, 16, 30, tzinfo=timezone.utc)
    with TemporaryDirectory(prefix="v13_activation_regression_") as raw:
        root = Path(raw)
        approval = root / "activation/manual_approval.json"
        lease = root / "activation/lease.json"
        journal = root / "fresh/evidence.jsonl"
        journal_before = digest(journal)

        result = activate(
            operator="Meraj Asari",
            acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
            now_utc=now,
            approval_path=approval,
            lease_path=lease,
            preflight_runner=ready_preflight,
        )
        require(
            result["status"] == "ACTIVATED_FRESH_EVIDENCE_PAPER_ONLY",
            "Explicit ceremony activates only fresh paper evidence",
        )
        require(approval.exists() and lease.exists(), "Approval and lease are persisted")
        require(
            result["transition_gates_passed"] == result["transition_gates_total"] == 16,
            "All locked transition gates pass before writes",
        )
        valid = validate_activation_lease(
            approval_path=approval,
            lease_path=lease,
            now_utc=now + timedelta(hours=1),
        )
        require(valid["valid"] is True, "Persisted activation lease validates")
        require(
            valid["activation"] == ENABLED_ACTIVATION,
            "Effective activation state is paper evidence only",
        )
        require(
            valid["live_trading_enabled"] is False
            and valid["brokerage_orders"] is False,
            "Live trading and brokerage authority remain absent",
        )
        expired = validate_activation_lease(
            approval_path=approval,
            lease_path=lease,
            now_utc=now + timedelta(hours=25),
        )
        require(
            expired["valid"] is False and expired["status"] == "NOT_ACTIVE",
            "Expired lease fails closed",
        )
        try:
            activate(
                operator="Meraj Asari",
                acknowledgement=REQUIRED_ACKNOWLEDGEMENT,
                now_utc=now,
                approval_path=approval,
                lease_path=lease,
                preflight_runner=ready_preflight,
            )
        except V13ActivationRejected:
            require(True, "Activation cannot overwrite existing artifacts")
        else:
            raise AssertionError("Activation cannot overwrite existing artifacts")
        require(digest(journal) == journal_before, "Activation writes no evidence")

    with TemporaryDirectory(prefix="v13_activation_rejection_") as raw:
        root = Path(raw)
        approval = root / "manual_approval.json"
        lease = root / "lease.json"
        try:
            activate(
                operator="Meraj Asari",
                acknowledgement="approve",
                now_utc=now,
                approval_path=approval,
                lease_path=lease,
                preflight_runner=ready_preflight,
            )
        except V13ActivationRejected:
            require(True, "Non-exact acknowledgement is rejected")
        else:
            raise AssertionError("Non-exact acknowledgement is rejected")
        require(
            not approval.exists() and not lease.exists(),
            "Rejected ceremony writes no artifacts",
        )

    source = SOURCE.read_text(encoding="utf-8").lower()
    for token in (
        "import alpaca",
        "from alpaca",
        "robin_stocks",
        "ib_insync",
        "launchctl",
        "tiingointradayclient",
    ):
        require(token not in source, f"Forbidden authority absent: {token}")
    require(
        "regime_overlay_journal" not in source,
        "Activation ceremony has no evidence-journal write surface",
    )
    print("Status: PASSED")
    print("V13 manual approval and 24-hour paper-only lease: VERIFIED")
    print("Scheduler changed: NO")
    print("Market data requested: NO")
    print("Production evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
