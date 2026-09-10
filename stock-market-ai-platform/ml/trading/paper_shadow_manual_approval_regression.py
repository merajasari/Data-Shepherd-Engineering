"""Regression suite for the manual paper-shadow approval ceremony."""
from __future__ import annotations
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from ml.trading.paper_shadow_manual_approval import verify_approval


def require(value, label):
    if not value:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main():
    now = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    audit = {
        "status": "READY_FOR_MANUAL_APPROVAL",
        "frozen_v8_sha256": "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41",
        "activation_performed": False,
        "paper_signal_export": False,
        "brokerage_orders": False,
    }
    audit_sha = hashlib.sha256(json.dumps(
        audit, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    approval = {
        "operator": "Meraj Asari",
        "approved_at_utc": now.isoformat(),
        "activation_audit_sha256": audit_sha,
        "frozen_v8_sha256": audit["frozen_v8_sha256"],
        "bridge_contract_sha256": "e2bf696e11341b6517afa1e9363516879d59de2efa8d5da83975520b94a69b80",
        "acknowledgement": "I APPROVE PAPER SHADOW ONLY; NO LIVE BROKERAGE AUTHORITY",
    }
    valid = verify_approval(approval, audit, now=now)
    require(valid["valid"], "Exact fresh post-boundary approval validates")
    require(valid["activation_performed"] is False, "Validation cannot activate")
    require(valid["paper_signal_export"] is False, "Validation cannot export signals")
    require(valid["brokerage_orders"] is False, "Validation has no brokerage authority")

    before = verify_approval(approval, audit, now=datetime(2026, 8, 31, tzinfo=timezone.utc))
    require(not before["valid"], "Pre-boundary validation fails closed")
    stale = copy.deepcopy(approval)
    stale["approved_at_utc"] = (now - timedelta(hours=25)).isoformat()
    require(not verify_approval(stale, audit, now=now)["valid"], "Stale approval fails closed")
    wrong_audit = copy.deepcopy(approval)
    wrong_audit["activation_audit_sha256"] = "0" * 64
    require(not verify_approval(wrong_audit, audit, now=now)["valid"],
            "Approval bound to wrong audit fails closed")
    wrong_phrase = copy.deepcopy(approval)
    wrong_phrase["acknowledgement"] = "approve"
    require(not verify_approval(wrong_phrase, audit, now=now)["valid"],
            "Inexact acknowledgement fails closed")
    require(audit["activation_performed"] is False, "Audit remains non-activating")
    print("\nStatus: PASSED")
    print("Manual approval validator: VERIFIED READ-ONLY")
    print("Activation authority: NONE")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
