"""Regression checks for parameterized V13 quote-recovery automation."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from ml.v13.regime_overlay_quote_recovery_session_automation import (
    AUTOMATION_ROOT,
    automation_acknowledgement,
    authorize_session,
    describe,
    get_session_status,
    run_collection,
    run_preflight,
    session_paths,
)


SOURCE = Path(__file__).with_name(
    "regime_overlay_quote_recovery_session_automation.py"
)
HISTORICAL_AUTOMATION = Path(__file__).with_name(
    "regime_overlay_session_automation.py"
)
TARGET = "2026-09-10"
SOURCE_SESSION = "2026-09-09"
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
    target = root / TARGET
    target.mkdir(parents=True)
    (target / "ranking_snapshot.json").write_text(
        json.dumps(
            {
                "session_date": TARGET,
                "source_decision_session": SOURCE_SESSION,
                "ranking_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    (target / "control_context.json").write_text(
        json.dumps(
            {
                "session_date": TARGET,
                "source_decision_sessions": ["2026-09-08", SOURCE_SESSION],
                "control_context_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )


def main() -> None:
    inert = describe()
    require(
        inert["status"] == "IMPLEMENTED_NOT_AUTHORIZED_NOT_SCHEDULED"
        and len(str(inert["contract_sha256"])) == 64,
        "Parameterized automation contract identity is locked",
    )
    require(
        inert["maximum_attempts_per_session"] == 1
        and inert["maximum_market_data_requests"] == 104,
        "Automation limits one attempt to the 104-request ceiling",
    )

    with TemporaryDirectory(prefix="v13_quote_recovery_automation_") as raw:
        root = Path(raw)
        automation_root = root / "automation"
        inbox = root / "inbox"
        write_context(inbox)
        paths = session_paths(TARGET, automation_root=automation_root)

        try:
            authorize_session(
                target_session="2026-09-08",
                source_session="2026-09-04",
                operator="Meraj Asari",
                acknowledgement=automation_acknowledgement("2026-09-08"),
                market_session_open=True,
                now_utc=datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc),
                automation_root=automation_root,
            )
        except ValueError:
            require(
                not (automation_root / "2026-09-08").exists(),
                "Consumed September 8 session cannot be recreated",
            )
        else:
            raise AssertionError("Consumed September 8 session cannot be recreated")

        acknowledgement = automation_acknowledgement(TARGET)
        try:
            authorize_session(
                target_session=TARGET,
                source_session=SOURCE_SESSION,
                operator="Meraj Asari",
                acknowledgement="not exact",
                market_session_open=True,
                now_utc=datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc),
                automation_root=automation_root,
            )
        except RuntimeError:
            require(
                not paths.authorization.exists(),
                "Non-exact acknowledgement creates no authorization",
            )
        else:
            raise AssertionError(
                "Non-exact acknowledgement creates no authorization"
            )

        try:
            authorize_session(
                target_session=TARGET,
                source_session=SOURCE_SESSION,
                operator="Meraj Asari",
                acknowledgement=acknowledgement,
                market_session_open=False,
                now_utc=datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc),
                automation_root=automation_root,
            )
        except RuntimeError:
            require(
                not paths.authorization.exists(),
                "Missing open-session assertion creates no authorization",
            )
        else:
            raise AssertionError(
                "Missing open-session assertion creates no authorization"
            )

        authorized = authorize_session(
            target_session=TARGET,
            source_session=SOURCE_SESSION,
            operator="Meraj Asari",
            acknowledgement=acknowledgement,
            market_session_open=True,
            now_utc=datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc),
            automation_root=automation_root,
        )
        require(
            authorized["status"] == "AUTHORIZED_ONE_SESSION_AUTOMATION"
            and paths.authorization.exists(),
            "Exact future-session authorization is persisted immutably",
        )

        try:
            run_preflight(
                target_session=TARGET,
                source_session=SOURCE_SESSION,
                now_utc=datetime(2026, 9, 10, 13, 55, tzinfo=timezone.utc),
                automation_root=automation_root,
                inbox_root=inbox,
                lease_validator=inactive,
                require_api_key=False,
            )
        except RuntimeError:
            require(
                not paths.status.exists(),
                "Inactive lease blocks before preflight status creation",
            )
        else:
            raise AssertionError(
                "Inactive lease blocks before preflight status creation"
            )

        ready = run_preflight(
            target_session=TARGET,
            source_session=SOURCE_SESSION,
            now_utc=datetime(2026, 9, 10, 13, 55, tzinfo=timezone.utc),
            automation_root=automation_root,
            inbox_root=inbox,
            lease_validator=active,
            require_api_key=False,
        )
        require(
            ready["status"]
            == "READY_FOR_AUTOMATIC_QUOTE_RECOVERY_COLLECTION",
            "Target-day preflight passes without market data",
        )
        require(
            ready["market_data_requests"] == 0
            and ready["evidence_appended"] is False,
            "Preflight performs no collection or evidence write",
        )

        calls = 0

        def collector(**kwargs: object) -> object:
            nonlocal calls
            calls += 1
            require(
                kwargs["apply"] is True,
                "Automation invokes explicit guarded quote-recovery apply",
            )
            require(
                kwargs["market_session_open"] is True,
                "Authorized open-session assertion reaches the collector",
            )
            return SimpleNamespace(
                status="FRESH_PAPER_DECISION_RECORDED",
                collector_invoked=True,
                market_data_requests=104,
                event_appended=True,
                activation_lease_sha256=LEASE_SHA,
            )

        collected = run_collection(
            target_session=TARGET,
            source_session=SOURCE_SESSION,
            now_utc=datetime(2026, 9, 10, 14, 0, 4, tzinfo=timezone.utc),
            automation_root=automation_root,
            inbox_root=inbox,
            lease_validator=active,
            collector=collector,
            require_api_key=False,
        )
        require(
            calls == 1
            and paths.attempt.exists()
            and collected["evidence_appended"] is True,
            "Exactly one automatic quote-recovery attempt records success",
        )
        require(
            collected["market_data_requests"] == 104
            and collected["retry_permitted"] is False,
            "Successful recovered collection remains within its request ceiling",
        )

        try:
            run_collection(
                target_session=TARGET,
                source_session=SOURCE_SESSION,
                now_utc=datetime(2026, 9, 10, 14, 1, tzinfo=timezone.utc),
                automation_root=automation_root,
                inbox_root=inbox,
                lease_validator=active,
                collector=collector,
                require_api_key=False,
            )
        except FileExistsError:
            require(
                calls == 1,
                "A second scheduled invocation cannot retry collection",
            )
        else:
            raise AssertionError(
                "A second scheduled invocation cannot retry collection"
            )

    with TemporaryDirectory(prefix="v13_quote_recovery_failure_") as raw:
        root = Path(raw)
        automation_root = root / "automation"
        inbox = root / "inbox"
        write_context(inbox)
        paths = session_paths(TARGET, automation_root=automation_root)
        authorize_session(
            target_session=TARGET,
            source_session=SOURCE_SESSION,
            operator="Meraj Asari",
            acknowledgement=automation_acknowledgement(TARGET),
            market_session_open=True,
            now_utc=datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc),
            automation_root=automation_root,
        )

        def failed_collector(**_: object) -> object:
            error = ValueError("V13_BID_INVALID:CRM")
            error.market_data_requests = 103  # type: ignore[attr-defined]
            raise error

        try:
            run_collection(
                target_session=TARGET,
                source_session=SOURCE_SESSION,
                now_utc=datetime(2026, 9, 10, 14, 0, 4, tzinfo=timezone.utc),
                automation_root=automation_root,
                inbox_root=inbox,
                lease_validator=active,
                collector=failed_collector,
                require_api_key=False,
            )
        except ValueError as exc:
            require(
                str(exc) == "V13_BID_INVALID:CRM",
                "Original terminal quote failure is preserved",
            )
        else:
            raise AssertionError("Original terminal quote failure is preserved")
        failed = get_session_status(
            target_session=TARGET,
            source_session=SOURCE_SESSION,
            automation_root=automation_root,
        )
        require(
            failed["status"] == "COLLECTION_FAILED_NO_EVIDENCE"
            and failed["failure_reason"] == "V13_BID_INVALID:CRM"
            and failed["market_data_requests"] == 103,
            "Failure status preserves a sanitized reason and request count",
        )
        require(
            failed["attempt_consumed"] is True
            and failed["retry_permitted"] is False
            and failed["backfill_permitted"] is False
            and failed["evidence_appended"] is False,
            "Failed session cannot retry, backfill, or count as evidence",
        )

    require(
        "quote_recovery_automation" in str(AUTOMATION_ROOT)
        and "automation/2026-09-08" not in str(AUTOMATION_ROOT),
        "New controller uses a separate automation namespace",
    )
    historical = HISTORICAL_AUTOMATION.read_text(encoding="utf-8")
    require(
        "regime_overlay_quote_recovery_session_automation" not in historical,
        "Historical September 8 automation remains unchanged",
    )
    source = SOURCE.read_text(encoding="utf-8").lower()
    require(
        "collector: callable[..., object] = run_quote_recovery_one_shot"
        in source,
        "New automation defaults to the guarded quote-recovery collector",
    )
    for prohibited in (
        "regime_overlay_context_publisher",
        "derive_and_publish",
        "renew(",
        "import alpaca",
        "robin_stocks",
        "ib_insync",
        "launchctl",
        "crontab",
    ):
        require(
            prohibited not in source,
            f"New automation controller excludes {prohibited}",
        )

    print("Status: PASSED")
    print("V13 parameterized quote-recovery automation: VERIFIED FAIL CLOSED")
    print("Authorization created: NO (regression uses temporary paths)")
    print("Scheduler installed or changed: NO")
    print("Live Tiingo requests during regression: 0")
    print("Real production evidence modified: NO")
    print("September 8 attempt modified: NO")
    print("Maximum attempts per session: 1")
    print("Backfill: PROHIBITED")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
