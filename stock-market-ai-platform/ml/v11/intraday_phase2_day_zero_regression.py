"""Regression coverage for the V11 Phase 2 day-zero checkpoint."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ml.v11.intraday_phase2_day_zero import run_checkpoint
from ml.v11.intraday_phase2_preflight import EXPECTED_CONTRACT_SHA256


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def _status(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "WAITING_FOR_BOUNDARY",
                "activation": "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY",
                "contract_sha256": EXPECTED_CONTRACT_SHA256,
                "brokerage_orders": False,
                "v8_modified": False,
                "v10_modified": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="v11_phase2_day_zero_") as directory:
        root = Path(directory)
        journal_path = root / "evidence.jsonl"
        status_path = root / "status.json"
        _status(status_path)
        status_before = status_path.read_bytes()

        ready = run_checkpoint(
            now_utc=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            service_checker=lambda _label: (True, "registered"),
        )
        require(
            ready["status"] == "READY_FOR_2026_09_01",
            "Complete day-zero checkpoint is ready",
        )
        require(
            all(row["passed"] for row in ready["checks"]),
            "Every readiness check passes",
        )
        require(
            ready["journal_events"] == 0,
            "Pre-boundary production journal is empty",
        )
        require(
            ready["maximum_tiingo_requests_per_session"] == 404,
            "Tiingo request ceiling is locked at 404/500",
        )
        require(
            not journal_path.exists(),
            "Checkpoint creates no production evidence",
        )
        require(
            status_path.read_bytes() == status_before,
            "Checkpoint leaves operational status unchanged",
        )
        require(
            ready["paper_trading_only"] is True
            and ready["live_trading_enabled"] is False
            and ready["brokerage_orders"] is False,
            "Paper-only authority remains enforced",
        )
        require(
            ready["v8_modified"] is False
            and ready["v10_modified"] is False,
            "V8 and V10 remain isolated",
        )

        service_failure = run_checkpoint(
            now_utc=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            service_checker=lambda _label: (False, "not registered"),
        )
        require(
            service_failure["status"] == "FAILED",
            "Missing LaunchAgent fails readiness",
        )
        require(
            not journal_path.exists(),
            "Failed readiness creates no production evidence",
        )

        status_path.write_text("{invalid", encoding="utf-8")
        malformed = run_checkpoint(
            now_utc=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            service_checker=lambda _label: (True, "registered"),
        )
        require(
            malformed["status"] == "FAILED",
            "Malformed operational status fails readiness",
        )
        require(
            malformed["brokerage_orders"] is False,
            "Failure cannot grant brokerage authority",
        )

    print("Status: PASSED")
    print("V11 Phase 2 day-zero readiness: VERIFIED")
    print("Production evidence modified: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
