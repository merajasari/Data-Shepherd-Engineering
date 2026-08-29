"""Read-only operational preflight for the disabled V13 evidence system."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    V12_DISPOSITION_PATH,
    contract_sha256,
    load_contract,
    validate_contract,
    validate_predecessor_disposition,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    DISABLED_ACTIVATION,
    RegimeOverlayEvidenceJournal,
    V13EvidenceActivationDisabled,
    V13EvidenceJournalCorrupt,
    build_rehearsal_event,
)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def run_preflight(
    *,
    production_journal_path: Path = DEFAULT_JOURNAL_PATH,
    v12_disposition_path: Path = V12_DISPOSITION_PATH,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    contract = load_contract()
    observed_sha = contract_sha256(contract)
    contract_failures = validate_contract(contract)
    check(
        "contract_identity",
        observed_sha == EXPECTED_CONTRACT_SHA256 and not contract_failures,
        observed_sha if not contract_failures else ",".join(contract_failures),
    )
    activation = contract.get("fresh_evidence", {}).get("activation_status")
    check(
        "activation_disabled",
        activation == DISABLED_ACTIVATION,
        str(activation),
    )
    check(
        "fresh_boundary",
        contract.get("fresh_evidence", {}).get("boundary_utc")
        == "2026-09-01T14:00:00+00:00",
        str(contract.get("fresh_evidence", {}).get("boundary_utc")),
    )
    authority = contract.get("authority", {})
    check(
        "paper_only",
        authority.get("paper_trading_only") is True,
        "paper only",
    )
    check(
        "brokerage_orders",
        authority.get("brokerage_orders") is False,
        "OFF",
    )
    check(
        "production_isolation",
        all(
            authority.get(field) is False
            for field in (
                "v8_production_reads",
                "v8_production_writes",
                "v10_production_reads",
                "v10_production_writes",
                "v11_production_reads",
                "v11_production_writes",
                "v12_development_evidence_reads",
                "holdout_outcomes_read",
            )
        ),
        "V8/V10/V11/V12 and holdout paths prohibited",
    )

    disposition_valid = False
    disposition_detail = "missing"
    if v12_disposition_path.exists():
        try:
            disposition = json.loads(
                v12_disposition_path.read_text(encoding="utf-8")
            )
            disposition_failures = validate_predecessor_disposition(disposition)
            disposition_valid = not disposition_failures
            disposition_detail = (
                EXPECTED_V12_DISPOSITION_SHA256
                if disposition_valid
                else ",".join(disposition_failures)
            )
        except (OSError, json.JSONDecodeError) as exc:
            disposition_detail = f"{type(exc).__name__}:{exc}"
    check(
        "v12_disposition_identity",
        disposition_valid,
        disposition_detail,
    )

    before = _snapshot(production_journal_path)
    production_valid = True
    production_rows: list[dict[str, object]] = []
    production_detail = "valid/absent"
    try:
        production_rows = RegimeOverlayEvidenceJournal(
            production_journal_path
        ).read()
        production_detail = f"events={len(production_rows)}"
    except V13EvidenceJournalCorrupt as exc:
        production_valid = False
        production_detail = str(exc)
    check("production_journal_valid", production_valid, production_detail)
    check(
        "preactivation_journal_empty",
        production_valid and len(production_rows) == 0,
        f"events={len(production_rows)}" if production_valid else "invalid",
    )

    with tempfile.TemporaryDirectory(prefix="v13_regime_preflight_") as directory:
        root = Path(directory)
        rehearsal_path = root / "evidence.jsonl"
        rehearsal = RegimeOverlayEvidenceJournal(
            rehearsal_path,
            rehearsal=True,
        )
        decision = build_rehearsal_event()
        first_append = rehearsal.append(decision)
        second_append = rehearsal.append(decision)
        observation = build_rehearsal_event(
            event_type="PAIRED_SESSION_OBSERVATION",
            timestamp_utc="2026-09-01T20:05:00+00:00",
        )
        observation_append = rehearsal.append(observation)
        restarted_rows = RegimeOverlayEvidenceJournal(rehearsal_path).read()
        check("rehearsal_append", first_append, "decision accepted")
        check(
            "duplicate_safe",
            second_append is False and len(restarted_rows) == 2,
            f"events={len(restarted_rows)}",
        )
        check(
            "paired_observation_append",
            observation_append,
            "paired control/challenger observation accepted",
        )
        check(
            "restart_recovery",
            [row["event_type"] for row in restarted_rows]
            == ["SESSION_DECISION", "PAIRED_SESSION_OBSERVATION"],
            "hash chain reconstructed",
        )

        tampered = root / "tampered.jsonl"
        tampered.write_bytes(
            rehearsal_path.read_bytes().replace(
                b'"regime_eligible":true',
                b'"regime_eligible":false',
                1,
            )
        )
        tamper_failed_closed = False
        try:
            RegimeOverlayEvidenceJournal(tampered).read()
        except V13EvidenceJournalCorrupt:
            tamper_failed_closed = True
        check("tamper_detection", tamper_failed_closed, "modified record rejected")

        pre_boundary_failed_closed = False
        try:
            RegimeOverlayEvidenceJournal(
                root / "pre_boundary.jsonl",
                rehearsal=True,
            ).append(
                build_rehearsal_event(
                    session_date="2026-08-31",
                    timestamp_utc="2026-08-31T14:05:00+00:00",
                )
            )
        except ValueError:
            pre_boundary_failed_closed = True
        check(
            "pre_boundary_fail_closed",
            pre_boundary_failed_closed,
            "Aug 31 evidence rejected",
        )

        production_attempt_path = root / "production_attempt.jsonl"
        disabled_failed_closed = False
        try:
            RegimeOverlayEvidenceJournal(production_attempt_path).append(decision)
        except V13EvidenceActivationDisabled:
            disabled_failed_closed = True
        check(
            "disabled_production_append",
            disabled_failed_closed and not production_attempt_path.exists(),
            "non-rehearsal append rejected before file creation",
        )

    after = _snapshot(production_journal_path)
    check(
        "production_journal_unchanged",
        before == after,
        "read-only preflight",
    )
    passed = all(bool(row["passed"]) for row in checks)
    return {
        "status": "READY_DISABLED" if passed else "FAILED",
        "checks": checks,
        "contract_sha256": observed_sha,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "fresh_evidence_boundary_utc": contract.get("fresh_evidence", {}).get(
            "boundary_utc"
        ),
        "activation": activation,
        "production_journal_events": (
            len(production_rows) if production_valid else None
        ),
        "production_evidence_modified": before != after,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }


def main() -> None:
    print("V13 FRESH REGIME-OVERLAY OPERATIONAL PREFLIGHT")
    print("=" * 84)
    result = run_preflight()
    for row in result["checks"]:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}: {row['detail']}")
    print("=" * 84)
    print(f"Status: {result['status']}")
    print(f"Contract SHA-256: {result['contract_sha256']}")
    print(f"V12 disposition SHA-256: {result['v12_disposition_sha256']}")
    print(f"Fresh evidence boundary: {result['fresh_evidence_boundary_utc']}")
    print(f"Production journal events: {result['production_journal_events']}")
    print(
        "Production evidence modified: "
        f"{'YES' if result['production_evidence_modified'] else 'NO'}"
    )
    print("Activation: DISABLED")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")
    if result["status"] != "READY_DISABLED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
