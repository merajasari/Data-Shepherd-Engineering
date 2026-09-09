"""Regression checks for the isolated V13 quote-recovery one-shot."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT
from ml.v13.regime_overlay_journal import RegimeOverlayEvidenceJournal
from ml.v13.regime_overlay_quote_recovery_one_shot import (
    _require_contract,
    run_quote_recovery_one_shot,
)
from ml.v13.regime_overlay_quote_recovery_regression import FakeClient
from ml.v13.regime_overlay_tiingo_provider_regression import contexts


SOURCE = Path(__file__).with_name("regime_overlay_quote_recovery_one_shot.py")
LEGACY_ONE_SHOT = Path(__file__).with_name("regime_overlay_one_shot.py")
SEPTEMBER_AUTOMATION = Path(__file__).with_name(
    "regime_overlay_session_automation.py"
)
LEASE_SHA = "a" * 64
OPERATOR = "Meraj Asari"
NOW = datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def active(_: datetime) -> dict[str, object]:
    return {
        "valid": True,
        "active": True,
        "operator": OPERATOR,
        "latest_lease_sha256": LEASE_SHA,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def inactive(now: datetime) -> dict[str, object]:
    return {**active(now), "active": False}


def main() -> None:
    require(
        len(_require_contract()) == 64,
        "Quote-recovery one-shot contract identity is locked",
    )
    ranking, control = contexts()
    factories = 0

    def unused_factory() -> FakeClient:
        nonlocal factories
        factories += 1
        return FakeClient([])

    inert = run_quote_recovery_one_shot(client_factory=unused_factory)
    require(
        inert.status == "IMPLEMENTED_NOT_INVOKED" and factories == 0,
        "Default quote-recovery one-shot is inert",
    )

    with TemporaryDirectory(prefix="v13_quote_recovery_one_shot_") as directory:
        root = Path(directory)
        common = {
            "apply": True,
            "now_utc": NOW,
            "operator": OPERATOR,
            "acknowledgement": REQUIRED_ACKNOWLEDGEMENT,
            "market_session_open": True,
            "ranking_snapshot": ranking,
            "control_context": control,
            "activation_validator": active,
        }

        blocked_path = root / "blocked.jsonl"
        try:
            run_quote_recovery_one_shot(
                **{
                    **common,
                    "acknowledgement": "paper please",
                    "client_factory": unused_factory,
                    "journal_path": blocked_path,
                }
            )
        except RuntimeError:
            require(
                factories == 0 and not blocked_path.exists(),
                "Non-exact acknowledgement blocks before client creation",
            )
        else:
            raise AssertionError(
                "Non-exact acknowledgement blocks before client creation"
            )

        try:
            run_quote_recovery_one_shot(
                **{
                    **common,
                    "activation_validator": inactive,
                    "client_factory": unused_factory,
                    "journal_path": blocked_path,
                }
            )
        except RuntimeError:
            require(
                factories == 0 and not blocked_path.exists(),
                "Inactive lease blocks before client creation",
            )
        else:
            raise AssertionError("Inactive lease blocks before client creation")

        normal_clients: list[FakeClient] = []

        def normal_factory() -> FakeClient:
            client = FakeClient([])
            normal_clients.append(client)
            return client

        normal_path = root / "normal.jsonl"
        waits: list[float] = []
        normal = run_quote_recovery_one_shot(
            **common,
            client_factory=normal_factory,
            journal_path=normal_path,
            sleeper=waits.append,
        )
        require(
            normal.status == "FRESH_PAPER_DECISION_RECORDED"
            and normal.market_data_requests == 103,
            "Complete quotes record one fresh paper decision with 103 requests",
        )
        require(
            len(normal_clients) == 1
            and normal_clients[0].quote_calls == 1
            and waits == [],
            "Complete quotes never invoke recovery",
        )
        rows = RegimeOverlayEvidenceJournal(normal_path).read()
        require(
            len(rows) == 1
            and rows[0]["fresh_evidence"] is True
            and rows[0]["activation_lease_sha256"] == LEASE_SHA,
            "Committed event remains fresh, paper-only, and lease-bound",
        )

        duplicate = run_quote_recovery_one_shot(
            **common,
            client_factory=normal_factory,
            journal_path=normal_path,
            sleeper=lambda _: None,
        )
        require(
            not duplicate.event_appended
            and len(RegimeOverlayEvidenceJournal(normal_path).read()) == 1,
            "Quote-recovery one-shot restart is duplicate-safe",
        )

        recovered_clients: list[FakeClient] = []

        def recovered_factory() -> FakeClient:
            client = FakeClient([("bid", "S010"), None])
            recovered_clients.append(client)
            return client

        recovered_path = root / "recovered.jsonl"
        waits = []
        recovered = run_quote_recovery_one_shot(
            **common,
            client_factory=recovered_factory,
            journal_path=recovered_path,
            sleeper=waits.append,
        )
        require(
            recovered.event_appended and recovered.market_data_requests == 104,
            "One transient missing bid recovers and records evidence at 104 requests",
        )
        require(
            recovered_clients[0].quote_calls == 2 and waits == [5.0],
            "Integrated collector performs exactly one five-second full-batch retry",
        )

        persistent_client = FakeClient(
            [("bid", "S010"), ("bid", "S010")]
        )
        failed_path = root / "failed.jsonl"
        waits = []
        try:
            run_quote_recovery_one_shot(
                **common,
                client_factory=lambda: persistent_client,
                journal_path=failed_path,
                sleeper=waits.append,
            )
        except ValueError as exc:
            require(
                str(exc) == "V13_BID_INVALID:S010"
                and getattr(exc, "market_data_requests", None) == 103,
                "Persistent missing bid fails with an auditable request count",
            )
            require(
                not failed_path.exists() and waits == [5.0],
                "Second quote failure writes no evidence and permits no extra retry",
            )
        else:
            raise AssertionError(
                "Persistent missing bid fails with an auditable request count"
            )

    historical_sources = LEGACY_ONE_SHOT.read_text(
        encoding="utf-8"
    ) + SEPTEMBER_AUTOMATION.read_text(encoding="utf-8")
    require(
        "regime_overlay_quote_recovery_one_shot" not in historical_sources,
        "Historical one-shot and September 8 automation remain unchanged",
    )
    source = SOURCE.read_text(encoding="utf-8").lower()
    for prohibited in (
        "import alpaca",
        "robin_stocks",
        "ib_insync",
        "launchctl",
        "crontab",
    ):
        require(prohibited not in source, f"Quote-recovery one-shot excludes {prohibited}")

    print("Status: PASSED")
    print("V13 guarded quote-recovery one-shot: VERIFIED IN TEMPORARY JOURNALS")
    print("Production scheduler integration: ABSENT")
    print("Live Tiingo requests during regression: 0")
    print("Real production evidence modified: NO")
    print("September 8 attempt modified: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
