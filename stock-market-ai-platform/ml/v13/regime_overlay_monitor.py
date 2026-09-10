"""Read-only operational monitor for disabled V13 controls."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    DISABLED_ACTIVATION,
    RegimeOverlayEvidenceJournal,
    V13EvidenceJournalCorrupt,
)
from ml.v13.regime_overlay_scheduled_entrypoint import STATUS_PATH


def run_monitor(
    *,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
) -> dict[str, object]:
    failures: list[str] = []
    contract = load_contract()
    observed_sha = contract_sha256(contract)
    contract_failures = validate_contract(contract)
    if contract_failures or observed_sha != EXPECTED_CONTRACT_SHA256:
        failures.append("CONTRACT_IDENTITY_CHANGED")
    activation = str(contract.get("fresh_evidence", {}).get("activation_status"))
    if activation != DISABLED_ACTIVATION:
        failures.append("UNREVIEWED_ACTIVATION_STATE")

    try:
        events = RegimeOverlayEvidenceJournal(journal_path).read()
    except V13EvidenceJournalCorrupt as exc:
        failures.append(f"JOURNAL_INVALID:{exc}")
        events = []
    if activation == DISABLED_ACTIVATION and events:
        failures.append("PREACTIVATION_JOURNAL_NOT_EMPTY")

    operational: dict[str, object] | None = None
    if status_path.exists():
        try:
            candidate = json.loads(status_path.read_text(encoding="utf-8"))
            if not isinstance(candidate, dict):
                raise ValueError("status is not an object")
            operational = candidate
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            failures.append(f"OPERATIONAL_STATUS_INVALID:{type(exc).__name__}")
    if operational is not None:
        if operational.get("contract_sha256") != observed_sha:
            failures.append("STATUS_CONTRACT_SHA_MISMATCH")
        if operational.get("activation") != activation:
            failures.append("STATUS_ACTIVATION_MISMATCH")
        if operational.get("runner_invoked") is not False:
            failures.append("DISABLED_RUNNER_INVOCATION_DETECTED")
        if operational.get("market_data_requests") != 0:
            failures.append("DISABLED_MARKET_DATA_REQUEST_DETECTED")
        if operational.get("production_evidence_modified") is not False:
            failures.append("PRODUCTION_EVIDENCE_MUTATION_REPORTED")
        if operational.get("brokerage_orders") is not False:
            failures.append("BROKERAGE_AUTHORITY_VIOLATION")
        if any(
            operational.get(field) is not False
            for field in ("v8_modified", "v10_modified", "v11_modified", "v12_modified")
        ):
            failures.append("PRODUCTION_ISOLATION_VIOLATION")
        if operational.get("collection_expected") is True:
            expected_session = str(
                operational.get("expected_session_date")
                or operational.get("session_date_eastern")
                or "UNKNOWN"
            )
            has_decision = any(
                row.get("session_date") == expected_session
                and row.get("event_type") == "SESSION_DECISION"
                for row in events
            )
            if not has_decision:
                failures.append(
                    "FRESH_SESSION_MISSING_AFTER_EXPECTED_COLLECTION:"
                    + expected_session
                )

    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "HEALTHY_DISABLED" if not failures else "ALERT",
        "failures": failures,
        "contract_sha256": observed_sha,
        "activation": activation,
        "journal_events": len(events),
        "operational_status": (
            operational.get("status")
            if operational is not None
            else "NOT_YET_PUBLISHED"
        ),
        "collection_expected": (
            operational.get("collection_expected") is True
            if operational is not None
            else False
        ),
        "scheduler_installation_expected": False,
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
    print("V13 OPERATIONAL MONITOR")
    print("=" * 80)
    result = run_monitor()
    print(f"Status: {result['status']}")
    print(f"Activation: {result['activation']}")
    print(f"Journal events: {result['journal_events']}")
    print(f"Operational status: {result['operational_status']}")
    print("Collection expected: NO")
    if result["failures"]:
        print("Failures:")
        for failure in result["failures"]:
            print(f" - {failure}")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if result["status"] == "ALERT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
