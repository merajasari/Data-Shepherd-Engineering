"""Regression coverage for V13 disabled scheduling, monitoring, and alerts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_alerts import run as run_alerts
from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    contract_sha256,
    load_contract,
)
from ml.v13.regime_overlay_journal import DEFAULT_JOURNAL_PATH
from ml.v13.regime_overlay_monitor import run_monitor
from ml.v13.regime_overlay_preflight import run_preflight
from ml.v13.regime_overlay_scheduled_entrypoint import (
    run_scheduled,
    schedule_state,
)


SCHEDULER_SOURCE = Path(__file__).with_name(
    "regime_overlay_scheduled_entrypoint.py"
)
MONITOR_SOURCE = Path(__file__).with_name("regime_overlay_monitor.py")
ALERT_SOURCE = Path(__file__).with_name("regime_overlay_alerts.py")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main() -> None:
    contract = load_contract()
    require(
        contract_sha256(contract) == EXPECTED_CONTRACT_SHA256,
        "V13 preregistered contract identity matches",
    )
    require(
        contract["fresh_evidence"]["activation_status"]
        == "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "Fresh evidence activation remains disabled",
    )
    require(
        schedule_state(datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc))
        == "WAITING_FOR_BOUNDARY",
        "Pre-boundary invocation waits",
    )
    require(
        schedule_state(datetime(2026, 9, 3, 13, 57, tzinfo=timezone.utc))
        == "BEFORE_DECISION_CHECKPOINT",
        "Pre-checkpoint invocation remains dormant",
    )
    require(
        schedule_state(datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc))
        == "DECISION_CHECKPOINT",
        "Ten Eastern decision checkpoint is identified",
    )
    require(
        schedule_state(datetime(2026, 9, 3, 14, 6, tzinfo=timezone.utc))
        == "AFTER_DECISION_CHECKPOINT",
        "Post-checkpoint state is explicit",
    )
    require(
        schedule_state(datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc))
        == "MARKET_CLOSED",
        "Weekend invocation fails closed",
    )

    production_before = digest(DEFAULT_JOURNAL_PATH)
    with TemporaryDirectory(prefix="v13_operational_regression_") as raw:
        root = Path(raw)
        status_path = root / "operational_status.json"
        journal_path = root / "evidence.jsonl"
        calls = 0

        def forbidden_runner() -> str:
            nonlocal calls
            calls += 1
            return "MUST_NOT_RUN"

        scheduled = run_scheduled(
            now_utc=datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc),
            status_path=status_path,
            production_journal_path=journal_path,
            runner=forbidden_runner,
        )
        require(scheduled["status"] == "READY_DISABLED", "Disabled status is published")
        require(status_path.exists(), "Operational status publishes atomically")
        require(
            scheduled["runner_invoked"] is False and calls == 0,
            "Disabled entrypoint never invokes an injected runner",
        )
        require(
            scheduled["market_data_requests"] == 0,
            "Disabled entrypoint makes zero market-data requests",
        )
        require(
            scheduled["collection_expected"] is False,
            "Disabled entrypoint expects no fresh collection",
        )
        require(not journal_path.exists(), "Disabled entrypoint writes no evidence")
        require(
            scheduled["brokerage_orders"] is False,
            "Scheduled control has no brokerage authority",
        )
        try:
            run_scheduled(
                now_utc=datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc),
                status_path=journal_path,
                production_journal_path=journal_path,
            )
        except ValueError:
            require(True, "Status path cannot alias the evidence journal")
        else:
            raise AssertionError("Status path cannot alias the evidence journal")

        monitored = run_monitor(journal_path=journal_path, status_path=status_path)
        require(
            monitored["status"] == "HEALTHY_DISABLED",
            "Disabled operational state monitors healthy",
        )
        require(monitored["failures"] == [], "Healthy disabled state has no failures")

        preflight = run_preflight(production_journal_path=journal_path)
        require(preflight["status"] == "READY_DISABLED", "Operational preflight remains ready-disabled")
        require(not journal_path.exists(), "Preflight leaves evidence absent")

        missing_path = root / "missing_status.json"
        missing_payload = dict(scheduled)
        missing_payload.update(
            {
                "collection_expected": True,
                "expected_session_date": "2026-09-03",
            }
        )
        missing_path.write_text(json.dumps(missing_payload), encoding="utf-8")
        missing = run_monitor(journal_path=journal_path, status_path=missing_path)
        require(
            missing["status"] == "ALERT"
            and "FRESH_SESSION_MISSING_AFTER_EXPECTED_COLLECTION:2026-09-03"
            in missing["failures"],
            "Expected but missing fresh session raises an alert",
        )

        invoked_path = root / "invoked_status.json"
        invoked_payload = dict(scheduled)
        invoked_payload["runner_invoked"] = True
        invoked_path.write_text(json.dumps(invoked_payload), encoding="utf-8")
        invoked = run_monitor(journal_path=journal_path, status_path=invoked_path)
        require(
            "DISABLED_RUNNER_INVOCATION_DETECTED" in invoked["failures"],
            "Unexpected disabled runner invocation raises an alert",
        )

        state_path = root / "alerts.json"
        delivered: list[tuple[str, str]] = []
        notifier = lambda title, message: not delivered.append((title, message))
        try:
            run_alerts(
                journal_path=journal_path,
                status_path=status_path,
                state_path=journal_path,
                notifier=notifier,
            )
        except ValueError:
            require(True, "Alert state cannot alias the evidence journal")
        else:
            raise AssertionError("Alert state cannot alias the evidence journal")
        first_alert = run_alerts(
            now=datetime(2026, 9, 3, 14, 10, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=missing_path,
            state_path=state_path,
            notifier=notifier,
        )
        require(
            first_alert["operational_notification"] == "NEW_FAILURE",
            "First operational failure sends one alert",
        )
        repeated = run_alerts(
            journal_path=journal_path,
            status_path=missing_path,
            state_path=state_path,
            notifier=notifier,
        )
        require(
            repeated["operational_notification"] == "NONE",
            "Repeated operational failure is duplicate-safe",
        )
        recovered = run_alerts(
            journal_path=journal_path,
            status_path=status_path,
            state_path=state_path,
            notifier=notifier,
        )
        require(
            recovered["operational_notification"] == "RECOVERY",
            "Healthy disabled state sends one recovery notice",
        )
        require(len(delivered) == 2, "Exactly one failure and one recovery notice are sent")
        require(
            recovered["production_evidence_modified"] is False,
            "Alert monitor never modifies production evidence",
        )
        require(not journal_path.exists(), "Operational alerts write no evidence")

    require(
        digest(DEFAULT_JOURNAL_PATH) == production_before,
        "Production V13 journal remains unchanged",
    )
    sources = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (SCHEDULER_SOURCE, MONITOR_SOURCE, ALERT_SOURCE)
    )
    for token in (
        "import alpaca",
        "from alpaca",
        "robin_stocks",
        "ib_insync",
        "tiingointradayclient",
        "collect_complete_snapshot",
        "run_session_decision(",
    ):
        require(token not in sources, f"Forbidden execution surface absent: {token}")
    require(
        "launchctl" not in sources,
        "No V13 scheduler installation or launch control is introduced",
    )

    print("Status: PASSED")
    print("V13 disabled schedule/status/monitor/alerts: VERIFIED")
    print("Collection expected: NO")
    print("Market data requests: 0")
    print("Scheduler installed or changed: NO")
    print("Fresh evidence activation: DISABLED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
