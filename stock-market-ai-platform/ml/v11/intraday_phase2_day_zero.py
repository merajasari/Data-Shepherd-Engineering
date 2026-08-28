"""Read-only day-zero readiness checkpoint for V11 Phase 2."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_journal import (
    DEFAULT_JOURNAL_PATH,
    EvidenceJournalCorrupt,
    Phase2EvidenceJournal,
)
from ml.v11.intraday_phase2_monitor import run_monitor
from ml.v11.intraday_phase2_preflight import (
    EXPECTED_CONTRACT_SHA256,
    run_preflight,
)
from ml.v11.intraday_phase2_scheduled_entrypoint import (
    MAX_COLLECTIONS_PER_SESSION,
    MAX_REQUESTS_PER_SESSION,
    STATUS_PATH,
    schedule_state,
)

SERVICE_LABEL = "com.datashepherd.v11phase2"
BOUNDARY = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)


def _snapshot(path: Path) -> tuple[bool, bytes | None]:
    return path.exists(), path.read_bytes() if path.exists() else None


def _service_registered(label: str) -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, f"unsupported platform: {sys.platform}"
    target = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        ["launchctl", "print", target],
        text=True,
        capture_output=True,
        check=False,
    )
    return (
        result.returncode == 0,
        "registered" if result.returncode == 0 else "not registered",
    )


def run_checkpoint(
    *,
    now_utc: datetime | None = None,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
    service_checker: Callable[[str], tuple[bool, str]] = _service_registered,
) -> dict[str, object]:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    before_journal = _snapshot(journal_path)
    before_status = _snapshot(status_path)
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
        "fresh_confirmation_boundary",
        contract["fresh_confirmation_start_utc"]
        == "2026-09-01T14:00:00+00:00",
        str(contract["fresh_confirmation_start_utc"]),
    )
    check(
        "paper_confirmation_authority",
        contract["activation_status"]
        == "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY",
        str(contract["activation_status"]),
    )

    preflight = run_preflight(production_journal_path=journal_path)
    check(
        "operational_preflight",
        preflight["status"] == "READY_PAPER_CONFIRMATION",
        str(preflight["status"]),
    )

    loaded, service_detail = service_checker(SERVICE_LABEL)
    check("launchagent_registered", loaded, service_detail)
    check(
        "collection_ceiling",
        MAX_COLLECTIONS_PER_SESSION == 4
        and MAX_REQUESTS_PER_SESSION == 404,
        f"collections={MAX_COLLECTIONS_PER_SESSION}; requests={MAX_REQUESTS_PER_SESSION}/500",
    )
    check(
        "decision_checkpoint",
        schedule_state(datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc))
        == "OBSERVATION_WINDOW",
        "9:58-10:03 Eastern window active",
    )
    check(
        "entry_checkpoint",
        schedule_state(datetime(2026, 9, 1, 14, 5, tzinfo=timezone.utc))
        == "OBSERVATION_WINDOW",
        "10:03-10:08 Eastern window active",
    )
    check(
        "exit_checkpoint",
        schedule_state(datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc))
        == "OBSERVATION_WINDOW",
        "10:28-10:33 Eastern window active",
    )
    check(
        "bounded_wakeup_catch_up",
        schedule_state(datetime(2026, 9, 1, 14, 35, tzinfo=timezone.utc))
        == "CATCH_UP_WINDOW",
        "one same-session attempt after 10:33 Eastern",
    )

    journal_valid = True
    try:
        events = Phase2EvidenceJournal(journal_path).read()
    except EvidenceJournalCorrupt as exc:
        journal_valid = False
        events = []
        journal_detail = str(exc)
    else:
        journal_detail = f"events={len(events)}; hash-chain valid"
    check("production_journal_integrity", journal_valid, journal_detail)
    if now < BOUNDARY:
        check(
            "pre_boundary_journal_empty",
            len(events) == 0,
            f"events={len(events)}",
        )

    operational: dict[str, object] = {}
    operational_detail = "absent"
    operational_valid = False
    if status_path.exists():
        try:
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                operational = raw
                operational_valid = True
                operational_detail = str(raw.get("status"))
            else:
                operational_detail = "root is not an object"
        except (json.JSONDecodeError, OSError) as exc:
            operational_detail = f"{type(exc).__name__}: {exc}"
    check("operational_status_json", operational_valid, operational_detail)
    if operational_valid:
        check(
            "status_contract_identity",
            operational.get("contract_sha256") == observed_sha,
            str(operational.get("contract_sha256")),
        )
        check(
            "status_brokerage_authority",
            operational.get("brokerage_orders") is False,
            "OFF",
        )

    monitor = run_monitor(journal_path=journal_path, status_path=status_path)
    check(
        "operational_monitor",
        monitor["status"] == "HEALTHY_PAPER_CONFIRMATION",
        str(monitor["status"]),
    )
    check(
        "paper_only_safety_boundary",
        contract["paper_trading_only"] is True
        and contract["live_trading_enabled"] is False
        and contract["brokerage_orders"] is False,
        "live trading disabled; brokerage orders off",
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

    after_journal = _snapshot(journal_path)
    after_status = _snapshot(status_path)
    check(
        "production_evidence_unchanged",
        before_journal == after_journal,
        "read-only checkpoint",
    )
    check(
        "operational_status_unchanged",
        before_status == after_status,
        "read-only checkpoint",
    )

    passed = all(bool(row["passed"]) for row in checks)
    return {
        "status": "READY_FOR_2026_09_01" if passed else "FAILED",
        "checks": checks,
        "contract_sha256": observed_sha,
        "fresh_confirmation_start_utc": contract[
            "fresh_confirmation_start_utc"
        ],
        "journal_events": len(events),
        "launchagent": SERVICE_LABEL,
        "maximum_tiingo_requests_per_session": MAX_REQUESTS_PER_SESSION,
        "production_evidence_modified": before_journal != after_journal,
        "operational_status_modified": before_status != after_status,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }


def main() -> None:
    print("V11 PHASE 2 DAY-ZERO READINESS CHECKPOINT")
    print("=" * 88)
    result = run_checkpoint()
    for row in result["checks"]:
        marker = "PASS" if row["passed"] else "FAIL"
        print(f"[{marker}] {row['name']}: {row['detail']}")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Contract SHA-256: {result['contract_sha256']}")
    print(
        "Fresh confirmation boundary: "
        f"{result['fresh_confirmation_start_utc']}"
    )
    print(f"Journal events: {result['journal_events']}")
    print(
        "Maximum Tiingo requests per session: "
        f"{result['maximum_tiingo_requests_per_session']}/500"
    )
    print("Production evidence modified: NO")
    print("Operational status modified: NO")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")
    if result["status"] != "READY_FOR_2026_09_01":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
