"""Deterministic regression checks for accelerated V10 paper-forward evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from ml.v10 import cycle3_holdout_runner as frozen
from ml.v10.cycle3_accelerated_forward_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_FROZEN_SHA256,
    INDEPENDENT_CONFIRMATION_START_UTC,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v10.cycle3_accelerated_forward_journal import (
    AcceleratedEvidenceCorrupt,
    AcceleratedEvidenceJournal,
)
from ml.v10.cycle3_accelerated_forward_runner import (
    promotion_summary,
    run_once,
)


def _sessions(end: str) -> pd.DatetimeIndex:
    values = pd.bdate_range("2026-08-03", end, tz="UTC")
    return values[~values.strftime("%Y-%m-%d").isin(["2026-09-07"])]


def _market(end: str):
    dates = list(_sessions(end))
    symbols = [f"S{index:03d}" for index in range(100)]
    frames: dict[str, pd.DataFrame] = {}
    for index, symbol in enumerate(symbols + ["SPY"]):
        base = 100.0 + index / 10.0
        values = base * (1.0 + np.arange(len(dates)) * 0.001)
        frames[symbol] = pd.DataFrame(
            {"open": values, "close": values, "volume": 1_000_000.0},
            index=dates,
        )
    return symbols, frames, dates, {value: i for i, value in enumerate(dates)}


def _rank(timestamp, symbols, frames, dates, date_to_idx):
    del timestamp, frames, dates, date_to_idx
    rows = []
    for index, symbol in enumerate(symbols):
        rows.append(
            {
                "symbol": symbol,
                "raw": float(index),
                "score": float(100 - index),
                "defensive_active": True,
            }
        )
    return pd.DataFrame(rows)


def _exit(offset: int, block: int) -> dict[str, object]:
    return {
        "event_type": "EXIT",
        "cohort_offset": offset,
        "exit_timestamp_utc": (
            datetime(2026, 9, 8, tzinfo=timezone.utc)
            + timedelta(days=int(block * 7 + offset))
        ).isoformat(),
        "net_portfolio_return": 0.02,
        "v8_control_net_portfolio_return": 0.015,
        "v10_minus_v8_net_return": 0.005,
        "net_relative_return": 0.004,
        "defensive_active": block == 0,
    }


def _assert_contract() -> None:
    contract = load_contract()
    assert contract_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert contract["source_candidate"]["frozen_sha256"] == EXPECTED_FROZEN_SHA256
    assert contract["evidence_window"]["first_decision_session_utc"] == (
        "2026-09-08T00:00:00+00:00"
    )
    assert contract["evidence_window"]["last_decision_session_utc"] == (
        "2026-12-18T00:00:00+00:00"
    )
    assert INDEPENDENT_CONFIRMATION_START_UTC == (
        "2027-01-04T00:00:00+00:00"
    )
    assert frozen.HOLDOUT_START.isoformat() == INDEPENDENT_CONFIRMATION_START_UTC
    assert frozen.EXPECTED_SHA == EXPECTED_FROZEN_SHA256
    assert contract["authority"]["brokerage_orders"] is False
    assert contract["authority"]["modify_v8"] is False
    assert contract["evidence_policy"]["automatic_promotion"] is False

    tampered = json.loads(json.dumps(contract))
    tampered["source_candidate"]["candidate_modified"] = True
    assert "CANDIDATE_MUST_REMAIN_UNMODIFIED" in validate_contract(tampered)


def _assert_prospective_and_duplicate_safe() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        journal_path = root / "journal.jsonl"
        status_path = root / "status.json"

        before_close = run_once(
            now_utc=datetime(2026, 9, 8, 19, 59, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            load_market=lambda: _market("2026-09-08"),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert before_close["decisions"] == 0

        first = run_once(
            now_utc=datetime(2026, 9, 8, 20, 10, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            load_market=lambda: _market("2026-09-08"),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert first["decisions"] == 1
        assert first["entries"] == 0
        assert first["appended_this_run"] == 1

        duplicate = run_once(
            now_utc=datetime(2026, 9, 8, 20, 15, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            load_market=lambda: _market("2026-09-08"),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert duplicate["journal_events"] == 1
        assert duplicate["appended_this_run"] == 0

        second = run_once(
            now_utc=datetime(2026, 9, 9, 20, 10, tzinfo=timezone.utc),
            journal_path=journal_path,
            status_path=status_path,
            load_market=lambda: _market("2026-09-09"),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert second["decisions"] == 2
        assert second["entries"] == 1
        assert second["appended_this_run"] == 2

        rows = AcceleratedEvidenceJournal(journal_path).read()
        first_decision = next(row for row in rows if row["event_type"] == "DECISION")
        assert first_decision["decision_locked_before_entry"] is True
        assert first_decision["created_at_utc"] < first_decision["next_session_open_utc"]
        assert all(row["brokerage_orders"] is False for row in rows)
        assert all(row["v8_modified"] is False for row in rows)
        assert all(row["january_confirmation_modified"] is False for row in rows)

        raw = journal_path.read_text(encoding="utf-8")
        journal_path.write_text(
            raw.replace('"paper_trading_only":true', '"paper_trading_only":false', 1),
            encoding="utf-8",
        )
        try:
            AcceleratedEvidenceJournal(journal_path).read()
        except AcceleratedEvidenceCorrupt:
            pass
        else:
            raise AssertionError("tampered accelerated journal was accepted")


def _assert_no_backfill() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = run_once(
            now_utc=datetime(2026, 9, 10, 20, 10, tzinfo=timezone.utc),
            journal_path=root / "journal.jsonl",
            status_path=root / "status.json",
            load_market=lambda: _market("2026-09-10"),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert result["decisions"] == 1
        assert result["missed_decisions_not_backfilled"] == [
            "2026-09-08",
            "2026-09-09",
        ]
        rows = AcceleratedEvidenceJournal(root / "journal.jsonl").read()
        assert rows[0]["decision_timestamp_utc"].startswith("2026-09-10")
        assert result["promotion"]["operational_integrity"] is False


def _assert_promotion_checkpoints() -> None:
    eight_blocks = [
        _exit(offset, block) for block in range(8) for offset in range(5)
    ]
    preliminary = promotion_summary(eight_blocks)
    assert preliminary["complete_five_sleeve_blocks"] == 8
    assert preliminary["provisional_review_eligible"] is True
    assert preliminary["stronger_review_eligible"] is False
    assert preliminary["review_status"] == (
        "PROVISIONAL_PAPER_CHAMPION_REVIEW_ELIGIBLE"
    )

    twelve_blocks = [
        _exit(offset, block) for block in range(12) for offset in range(5)
    ]
    stronger = promotion_summary(twelve_blocks)
    assert stronger["complete_five_sleeve_blocks"] == 12
    assert stronger["completed_defensive_exits"] == 5
    assert stronger["stronger_review_eligible"] is True
    assert stronger["review_status"] == (
        "STRONGER_LIMITED_LIVE_REVIEW_ELIGIBLE"
    )
    assert stronger["automatic_promotion"] is False
    assert stronger["human_review_required"] is True


def _assert_january_isolation() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = run_once(
            now_utc=datetime(2027, 1, 4, 22, 0, tzinfo=timezone.utc),
            journal_path=root / "journal.jsonl",
            status_path=root / "status.json",
            load_market=lambda: (_ for _ in ()).throw(
                AssertionError("accelerated lane loaded market after January boundary")
            ),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert result["status"] == (
            "ACCELERATED_WINDOW_CLOSED_JANUARY_CONFIRMATION_ACTIVE"
        )
        assert result["journal_events"] == 0
        assert result["january_confirmation_modified"] is False
        assert result["brokerage_orders"] is False


def main() -> None:
    _assert_contract()
    _assert_prospective_and_duplicate_safe()
    _assert_no_backfill()
    _assert_promotion_checkpoints()
    _assert_january_isolation()
    print("V10 CYCLE 3 ACCELERATED PAPER-FORWARD REGRESSION")
    print("=" * 88)
    print("Contract identity and frozen candidate: PASS")
    print("Prospective decision timing and duplicate safety: PASS")
    print("Missed-decision backfill prohibition: PASS")
    print("8-block and 12-block review checkpoints: PASS")
    print("January confirmation isolation: PASS")
    print("Automatic promotion: NO | human review required: YES")
    print("V8 modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
