"""Regression checks for preauthorized September 8 V13 automation."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_session_automation import (
    AUTOMATION_ACKNOWLEDGEMENT,
    _require_contract,
    authorize_session,
    get_session_status,
    run_collection,
    run_preflight,
)


SOURCE = Path(__file__).with_name("regime_overlay_session_automation.py")
ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts/mac/install_v13_session_automation.sh"
LEASE_SHA = "a" * 64


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def active(**_: object) -> dict[str, object]:
    return {
        "valid": True,
        "active": True,
        "operator": "Meraj Asari",
        "latest_lease_sha256": LEASE_SHA,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def inactive(**kwargs: object) -> dict[str, object]:
    return {**active(**kwargs), "active": False}


def write_context(root: Path) -> None:
    target = root / "2026-09-08"
    target.mkdir(parents=True)
    (target / "ranking_snapshot.json").write_text(
        json.dumps(
            {
                "session_date": "2026-09-08",
                "source_decision_session": "2026-09-04",
                "ranking_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    (target / "control_context.json").write_text(
        json.dumps(
            {
                "session_date": "2026-09-08",
                "source_decision_sessions": ["2026-09-03", "2026-09-04"],
                "control_context_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )


def main() -> None:
    require(len(_require_contract()) == 64, "Session automation contract identity is locked")
    with TemporaryDirectory(prefix="v13_session_automation_regression_") as raw:
        root = Path(raw)
        authorization = root / "authorization.json"
        attempt = root / "attempt.json"
        status = root / "status.json"
        inbox = root / "inbox"
        write_context(inbox)

        try:
            authorize_session(
                operator="Meraj Asari",
                acknowledgement="not exact",
                now_utc=datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc),
                authorization_path=authorization,
            )
        except RuntimeError:
            require(not authorization.exists(), "Non-exact automation acknowledgement is rejected")
        else:
            raise AssertionError("Non-exact automation acknowledgement is rejected")

        authorized = authorize_session(
            operator="Meraj Asari",
            acknowledgement=AUTOMATION_ACKNOWLEDGEMENT,
            now_utc=datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc),
            authorization_path=authorization,
        )
        require(
            authorized["status"] == "AUTHORIZED_ONE_SESSION_AUTOMATION",
            "Exact pre-window operator authorization is persisted",
        )

        ready = run_preflight(
            now_utc=datetime(2026, 9, 8, 13, 55, tzinfo=timezone.utc),
            authorization_path=authorization,
            inbox_root=inbox,
            status_path=status,
            lease_validator=active,
            require_api_key=False,
        )
        require(ready["status"] == "READY_FOR_AUTOMATIC_COLLECTION", "6:55 preflight passes")
        require(ready["market_data_requests"] == 0, "Preflight requests no market data")

        failed_attempt = root / "failed-attempt.json"
        failed_status = root / "failed-status.json"

        def failed_collector(**_: object) -> object:
            raise ValueError("V13_BID_INVALID:CRM")

        try:
            run_collection(
                now_utc=datetime(2026, 9, 8, 14, 0, 4, tzinfo=timezone.utc),
                authorization_path=authorization,
                attempt_path=failed_attempt,
                inbox_root=inbox,
                status_path=failed_status,
                lease_validator=active,
                collector=failed_collector,
                require_api_key=False,
            )
        except ValueError as exc:
            require(str(exc) == "V13_BID_INVALID:CRM", "Original provider failure is preserved")
        else:
            raise AssertionError("Original provider failure is preserved")
        failed = get_session_status(
            authorization_path=authorization,
            attempt_path=failed_attempt,
            status_path=failed_status,
        )
        require(
            failed["status"] == "COLLECTION_FAILED_NO_EVIDENCE"
            and failed["failure_reason"] == "V13_BID_INVALID:CRM",
            "Provider failure becomes a sanitized terminal status",
        )
        require(
            failed["attempt_consumed"] is True
            and failed["retry_permitted"] is False
            and failed["backfill_permitted"] is False
            and failed["evidence_appended"] is False,
            "Failed collection cannot be retried or counted as evidence",
        )

        stale_status = root / "stale-status.json"
        stale_status.write_text(json.dumps(ready), encoding="utf-8")
        inferred = get_session_status(
            authorization_path=authorization,
            attempt_path=failed_attempt,
            status_path=stale_status,
        )
        require(
            inferred["status"] == "COLLECTION_ATTEMPTED_OUTCOME_UNRECORDED"
            and inferred["attempt_consumed"] is True
            and inferred["retry_permitted"] is False,
            "Existing attempt outranks stale preflight and authorization",
        )

        blocked_attempt = root / "blocked-attempt.json"
        try:
            run_collection(
                now_utc=datetime(2026, 9, 8, 14, 0, 5, tzinfo=timezone.utc),
                authorization_path=authorization,
                attempt_path=blocked_attempt,
                inbox_root=inbox,
                status_path=status,
                lease_validator=inactive,
                collector=lambda **_: None,
                require_api_key=False,
            )
        except RuntimeError:
            require(not blocked_attempt.exists(), "Inactive lease blocks before attempt creation")
        else:
            raise AssertionError("Inactive lease blocks before attempt creation")

        calls = 0

        def collector(**kwargs: object) -> object:
            nonlocal calls
            calls += 1
            require(kwargs["apply"] is True, "Automation invokes explicit guarded apply")
            require(kwargs["market_session_open"] is True, "Authorized open-session assertion is preserved")
            return SimpleNamespace(
                status="FRESH_PAPER_DECISION_RECORDED",
                collector_invoked=True,
                market_data_requests=103,
                event_appended=True,
                activation_lease_sha256=LEASE_SHA,
            )

        collected = run_collection(
            now_utc=datetime(2026, 9, 8, 14, 0, 5, tzinfo=timezone.utc),
            authorization_path=authorization,
            attempt_path=attempt,
            inbox_root=inbox,
            status_path=status,
            lease_validator=active,
            collector=collector,
            require_api_key=False,
        )
        require(calls == 1 and attempt.exists(), "Exactly one automatic attempt is made")
        require(collected["evidence_appended"] is True, "Fresh paper decision is recorded")
        require(collected["market_data_requests"] == 103, "Locked Tiingo request count is preserved")
        require(collected["brokerage_orders"] is False, "Automation has no brokerage authority")

        try:
            run_collection(
                now_utc=datetime(2026, 9, 8, 14, 1, tzinfo=timezone.utc),
                authorization_path=authorization,
                attempt_path=attempt,
                inbox_root=inbox,
                status_path=status,
                lease_validator=active,
                collector=collector,
                require_api_key=False,
            )
        except FileExistsError:
            require(calls == 1, "A second scheduled invocation cannot retry collection")
        else:
            raise AssertionError("A second scheduled invocation cannot retry collection")

    source = SOURCE.read_text(encoding="utf-8").lower()
    for prohibited in ("import alpaca", "robin_stocks", "ib_insync", "launchctl", "crontab"):
        require(prohibited not in source, f"Automation runtime excludes {prohibited}")
    installer = INSTALLER.read_text(encoding="utf-8")
    require("<integer>6</integer><key>Minute</key><integer>55</integer>" in installer, "Preflight is scheduled at 6:55 local time")
    require("<integer>7</integer><key>Minute</key><integer>0</integer>" in installer, "Collection is scheduled at 7:00 local time")
    require("FEATURE_BACKEND=spark" in installer, "Scheduled collection uses the Spark backend")

    print("Status: PASSED")
    print("V13 September 8 automatic paper collection: VERIFIED FAIL CLOSED")
    print("Maximum collection attempts: 1")
    print("Backfill: PROHIBITED")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
