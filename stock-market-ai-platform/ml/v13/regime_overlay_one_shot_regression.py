"""Regression checks for the V13 guarded one-shot collector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_activation import REQUIRED_ACKNOWLEDGEMENT
from ml.v13.regime_overlay_journal import RegimeOverlayEvidenceJournal
from ml.v13.regime_overlay_one_shot import _require_contract, run_one_shot
from ml.v13.regime_overlay_tiingo_provider_regression import FakeClient, contexts


SOURCE = Path(__file__).with_name("regime_overlay_one_shot.py")
LEASE_SHA = "a" * 64
OPERATOR = "Meraj Asari"


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


def late_lease(now: datetime) -> dict[str, object]:
    return {**active(now), "active": now.second != 0}


def main() -> None:
    require(len(_require_contract()) == 64, "One-shot collection contract identity is locked")
    ranking, control = contexts()
    factories = 0

    def factory() -> FakeClient:
        nonlocal factories
        factories += 1
        return FakeClient()

    inert = run_one_shot(client_factory=factory)
    require(inert.status == "IMPLEMENTED_NOT_INVOKED" and factories == 0, "Default command is inert")

    with TemporaryDirectory(prefix="v13_one_shot_regression_") as directory:
        journal_path = Path(directory) / "production.jsonl"
        common = {
            "apply": True,
            "now_utc": datetime(2026, 9, 3, 14, 0, 5, tzinfo=timezone.utc),
            "operator": OPERATOR,
            "acknowledgement": REQUIRED_ACKNOWLEDGEMENT,
            "market_session_open": True,
            "ranking_snapshot": ranking,
            "control_context": control,
            "client_factory": factory,
            "journal_path": journal_path,
        }
        try:
            run_one_shot(**{**common, "acknowledgement": "paper please", "activation_validator": active})
        except RuntimeError:
            require(factories == 0 and not journal_path.exists(), "Non-exact acknowledgement blocks before client creation")
        else:
            raise AssertionError("Non-exact acknowledgement blocks before client creation")

        try:
            run_one_shot(**{**common, "activation_validator": inactive})
        except RuntimeError:
            require(factories == 0 and not journal_path.exists(), "Inactive lease blocks before client creation")
        else:
            raise AssertionError("Inactive lease blocks before client creation")

        try:
            run_one_shot(**{**common, "activation_validator": late_lease})
        except RuntimeError:
            require(factories == 0 and not journal_path.exists(), "Lease issued after 10:00 decision blocks before client creation")
        else:
            raise AssertionError("Lease issued after 10:00 decision blocks before client creation")

        try:
            run_one_shot(**{**common, "market_session_open": False, "activation_validator": active})
        except RuntimeError:
            require(factories == 0 and not journal_path.exists(), "Closed session assertion blocks before client creation")
        else:
            raise AssertionError("Closed session assertion blocks before client creation")

        result = run_one_shot(**{**common, "activation_validator": active})
        require(result.status == "FRESH_PAPER_DECISION_RECORDED", "Explicit valid one-shot records one fresh paper decision")
        require(result.market_data_requests == 103 and factories == 1, "One-shot uses one provider and the locked request budget")
        require(result.event_appended and result.production_evidence_modified, "Fresh decision is appended only after complete input validation")
        rows = RegimeOverlayEvidenceJournal(journal_path).read()
        require(len(rows) == 1 and rows[0]["fresh_evidence"] is True, "Temporary production-mode journal contains one fresh event")
        require(rows[0]["activation_lease_sha256"] == LEASE_SHA, "Fresh event binds the effective paper lease")
        require(rows[0]["brokerage_orders"] is False, "Fresh event has no brokerage authority")

        duplicate = run_one_shot(**{**common, "activation_validator": active})
        require(not duplicate.event_appended and len(RegimeOverlayEvidenceJournal(journal_path).read()) == 1, "One-shot restart is duplicate-safe")

    source = SOURCE.read_text(encoding="utf-8").lower()
    for prohibited in ("import alpaca", "robin_stocks", "ib_insync", "launchctl", "crontab"):
        require(prohibited not in source, f"One-shot collector excludes {prohibited}")

    print("Status: PASSED")
    print("V13 explicit one-shot fresh paper collection: VERIFIED IN TEMPORARY JOURNAL")
    print("Live Tiingo requests during regression: 0")
    print("Scheduler installed or changed: NO")
    print("Real production evidence modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
