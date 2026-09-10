"""Regression checks for the V13 lease-gated collection commit layer."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from ml.v13.regime_overlay_collection_apply import (
    EXPECTED_CONTRACT_SHA256,
    commit_paired_observation,
    commit_session_decision,
)
from ml.v13.regime_overlay_journal import (
    RegimeOverlayEvidenceJournal,
    V13EvidenceActivationDisabled,
)
from ml.v13.regime_overlay_observation import canonical_sha256
from ml.v13.regime_overlay_observation_regression import fixtures


LEASE_SHA = "a" * 64


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def active(_: datetime) -> dict[str, object]:
    return {
        "valid": True,
        "active": True,
        "latest_lease_sha256": LEASE_SHA,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
    }


def inactive(_: datetime) -> dict[str, object]:
    return {**active(_), "active": False}


def main() -> None:
    ranking, intraday, regime, _, prices, _ = fixtures()
    with TemporaryDirectory(prefix="v13_collection_apply_") as raw:
        root = Path(raw)
        journal_path = root / "production.jsonl"
        blocked_path = root / "blocked.jsonl"
        try:
            commit_session_decision(
                session_date="2026-09-03",
                decision_timestamp_utc="2026-09-03T14:00:00+00:00",
                ranking_snapshot=ranking,
                intraday_snapshot=intraday,
                regime_snapshot=regime,
                journal_path=blocked_path,
                activation_validator=inactive,
            )
        except RuntimeError:
            require(not blocked_path.exists(), "Inactive lease blocks production evidence before file creation")
        else:
            raise AssertionError("Inactive lease blocks production evidence before file creation")

        decision = commit_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=intraday,
            regime_snapshot=regime,
            journal_path=journal_path,
            activation_validator=active,
        )
        require(decision.event_appended, "Active paper lease permits one fresh decision")
        rows = RegimeOverlayEvidenceJournal(journal_path).read()
        require(len(rows) == 1 and rows[0]["fresh_evidence"] is True and rows[0]["rehearsal"] is False, "Committed decision is fresh production evidence")
        require(rows[0]["activation_lease_sha256"] == LEASE_SHA and rows[0]["collection_contract_sha256"] == EXPECTED_CONTRACT_SHA256, "Fresh decision binds lease and collection contract identities")
        require(rows[0]["brokerage_orders"] is False and rows[0]["live_trading_enabled"] is False, "Fresh decision has no brokerage authority")

        duplicate = commit_session_decision(
            session_date="2026-09-03",
            decision_timestamp_utc="2026-09-03T14:00:00+00:00",
            ranking_snapshot=ranking,
            intraday_snapshot=intraday,
            regime_snapshot=regime,
            journal_path=journal_path,
            activation_validator=active,
        )
        require(not duplicate.event_appended and len(RegimeOverlayEvidenceJournal(journal_path).read()) == 1, "Fresh decision restart is duplicate-safe")

        exits = {symbol: price * 1.02 for symbol, price in prices.items()}
        observation = commit_paired_observation(
            session_date="2026-09-03",
            exit_session_date="2026-09-11",
            exit_timestamp_utc="2026-09-11T20:00:00+00:00",
            exit_prices=exits,
            exit_snapshot_sha256=canonical_sha256(exits),
            completed_holding_sessions=5,
            journal_path=journal_path,
            activation_validator=active,
        )
        require(observation.event_appended, "Active paper lease permits the paired five-session outcome")
        rows = RegimeOverlayEvidenceJournal(journal_path).read()
        require(len(rows) == 2 and rows[-1]["event_type"] == "PAIRED_SESSION_OBSERVATION", "Fresh decision and outcome form one production lifecycle")
        require(all(row["activation_lease_sha256"] == LEASE_SHA for row in rows), "Every fresh event is bound to its effective lease")

        try:
            bad_event = dict(rows[0])
            for field in ("event_id", "previous_record_sha256", "record_sha256"):
                bad_event.pop(field, None)
            bad_event["session_date"] = "2026-09-04"
            bad_event["activation_lease_sha256"] = "b" * 64
            RegimeOverlayEvidenceJournal(journal_path, activation_validator=active).append(bad_event)
        except V13EvidenceActivationDisabled:
            require(True, "Mismatched lease identity is rejected")
        else:
            raise AssertionError("Mismatched lease identity is rejected")

        require(len(RegimeOverlayEvidenceJournal(journal_path).read()) == 2, "Rejected append leaves the journal unchanged")

    print("Status: PASSED")
    print("V13 lease-gated fresh collection commit: VERIFIED")
    print("Scheduler installed or changed: NO")
    print("Market data requested: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
