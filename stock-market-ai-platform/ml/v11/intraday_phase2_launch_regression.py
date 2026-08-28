"""Launch-control regression for activated V11 Phase 2 paper confirmation."""
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
    MAX_COLLECTIONS_PER_SESSION,
    MAX_REQUESTS_PER_SESSION,
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
        "Activated Phase 2 contract identity matches",
    )
    require(
        contract["activation_status"]
        == "ENABLED_FRESH_CONFIRMATION_PAPER_ONLY",
        "Authority is limited to fresh paper confirmation",
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
            datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
        ) == "OBSERVATION_WINDOW",
        "Decision checkpoint is active",
    )
    require(
        schedule_state(
            datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)
        ) == "OBSERVATION_WINDOW",
        "Exit checkpoint is active",
    )
    require(
        schedule_state(
            datetime(2026, 9, 1, 14, 35, tzinfo=timezone.utc)
        ) == "CATCH_UP_WINDOW",
        "Post-checkpoint invocation enters bounded catch-up",
    )
    require(
        schedule_state(
            datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
        ) == "CATCH_UP_WINDOW",
        "Midday wake remains eligible for bounded catch-up",
    )
    require(
        MAX_COLLECTIONS_PER_SESSION == 4,
        "Three checkpoints plus one catch-up are allowed",
    )
    require(
        MAX_REQUESTS_PER_SESSION == 404,
        "Maximum session requests remain below the 500 hourly budget",
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

        def paper_runner():
            nonlocal runner_calls
            runner_calls += 1
            return "SYNTHETIC_PAPER_RUNNER_COMPLETE"

        early = run_scheduled(
            now_utc=datetime(
                2026, 8, 31, 14, 5, tzinfo=timezone.utc
            ),
            status_path=status_path,
            production_journal_path=journal_path,
            active_runner=paper_runner,
        )
        require(
            early["status"] == "WAITING_FOR_BOUNDARY",
            "Activated entrypoint remains dormant before boundary",
        )
        require(
            early["runner_invoked"] is False and runner_calls == 0,
            "Pre-boundary entrypoint makes no market request",
        )
        require(
            not journal_path.exists(),
            "Pre-boundary entrypoint writes no evidence",
        )

        active = run_scheduled(
            now_utc=datetime(
                2026, 9, 1, 14, 5, tzinfo=timezone.utc
            ),
            status_path=status_path,
            production_journal_path=journal_path,
            active_runner=paper_runner,
        )
        require(
            active["runner_invoked"] is True and runner_calls == 1,
            "Observation-window entrypoint invokes paper runner once",
        )
        require(
            active["runner_status"]
            == "SYNTHETIC_PAPER_RUNNER_COMPLETE",
            "Paper runner result is published",
        )
        require(
            not journal_path.exists(),
            "Injected launch rehearsal writes no production evidence",
        )
        require(
            status_path.exists(),
            "Operational status publishes atomically",
        )

        catch_up = run_scheduled(
            now_utc=datetime(
                2026, 9, 1, 14, 35, tzinfo=timezone.utc
            ),
            status_path=status_path,
            production_journal_path=journal_path,
            active_runner=paper_runner,
        )
        require(
            catch_up["schedule_state"] == "CATCH_UP_WINDOW",
            "Wake-up invocation enters catch-up window",
        )
        require(
            catch_up["runner_invoked"] is True and runner_calls == 2,
            "First wake-up invokes one catch-up attempt",
        )
        repeated_catch_up = run_scheduled(
            now_utc=datetime(
                2026, 9, 1, 14, 40, tzinfo=timezone.utc
            ),
            status_path=status_path,
            production_journal_path=journal_path,
            active_runner=paper_runner,
        )
        require(
            repeated_catch_up["status"]
            == "CATCH_UP_ALREADY_ATTEMPTED",
            "Repeated same-session catch-up is suppressed",
        )
        require(
            repeated_catch_up["runner_invoked"] is False
            and runner_calls == 2,
            "Catch-up adds at most one collection",
        )
        require(
            active["brokerage_orders"] is False,
            "Scheduled entrypoint has no brokerage authority",
        )

        preflight = run_preflight(
            production_journal_path=journal_path
        )
        require(
            preflight["status"] == "READY_PAPER_CONFIRMATION",
            "Activated operational preflight passes",
        )
        require(
            not journal_path.exists(),
            "Launch rehearsal leaves production journal absent",
        )

    require(
        contract["live_trading_enabled"] is False,
        "Live trading remains disabled",
    )
    require(
        contract["brokerage_orders"] is False,
        "Brokerage orders remain off",
    )
    require(
        contract["v8_production_writes"] is False,
        "V8 production remains isolated",
    )
    require(
        contract["v10_production_writes"] is False,
        "V10 production remains isolated",
    )
    print("Status: PASSED")
    print("Five-minute launch control: VERIFIED PAPER CONFIRMATION")
    print("Market-window and boundary guards: VERIFIED")
    print("Production evidence modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
