"""Launch-control regression for disabled V11 Phase 2 scheduling."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract
from ml.v11.intraday_phase2_preflight import (
    EXPECTED_CONTRACT_SHA256,
    run_preflight,
)
from ml.v11.intraday_phase2_scheduled_entrypoint import (
    run_scheduled,
    schedule_state,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    contract = load_contract()
    require(
        contract_sha256(contract) == EXPECTED_CONTRACT_SHA256,
        "Frozen Phase 2 contract identity matches",
    )
    require(
        schedule_state(
            datetime(2026, 8, 31, 14, 5, tzinfo=timezone.utc)
        ) == "WAITING_FOR_BOUNDARY",
        "Pre-boundary schedule waits",
    )
    require(
        schedule_state(
            datetime(2026, 9, 1, 14, 5, tzinfo=timezone.utc)
        ) == "OBSERVATION_WINDOW",
        "Post-boundary 10:05 Eastern enters observation window",
    )
    require(
        schedule_state(
            datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
        ) == "OUTSIDE_OBSERVATION_WINDOW",
        "Midday invocation performs no collection",
    )
    require(
        schedule_state(
            datetime(2026, 9, 5, 14, 5, tzinfo=timezone.utc)
        ) == "MARKET_CLOSED",
        "Weekend invocation fails closed",
    )

    with tempfile.TemporaryDirectory(prefix="v11_phase2_launch_") as directory:
        root = Path(directory)
        status_path = root / "status.json"
        journal_path = root / "production_evidence.jsonl"
        runner_calls = 0

        def forbidden_runner():
            nonlocal runner_calls
            runner_calls += 1
            raise AssertionError("disabled scheduler invoked runner")

        result = run_scheduled(
            now_utc=datetime(
                2026, 9, 1, 14, 5, tzinfo=timezone.utc
            ),
            status_path=status_path,
            production_journal_path=journal_path,
            active_runner=forbidden_runner,
        )
        require(result["status"] == "READY_DISABLED", "Disabled entrypoint remains ready")
        require(result["runner_invoked"] is False, "Disabled entrypoint makes no market request")
        require(runner_calls == 0, "Disabled entrypoint cannot invoke observation runner")
        require(not journal_path.exists(), "Disabled entrypoint writes no evidence")
        require(status_path.exists(), "Operational status publishes atomically")
        require(result["brokerage_orders"] is False, "Scheduled entrypoint has no brokerage authority")

        preflight = run_preflight(
            production_journal_path=journal_path
        )
        require(preflight["status"] == "READY_DISABLED", "Operational preflight remains ready")
        require(not journal_path.exists(), "Launch rehearsal leaves production journal absent")

    require(contract["v8_production_writes"] is False, "V8 production remains isolated")
    require(contract["v10_production_writes"] is False, "V10 production remains isolated")
    print("Status: PASSED")
    print("Five-minute launch control: VERIFIED DISABLED")
    print("Market-window and boundary guards: VERIFIED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
