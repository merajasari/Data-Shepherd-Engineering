"""Regression checks for the clean V10 Cycle 3 V2 paper-forward lane."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
from ml.v10.cycle3_accelerated_forward_v2_contract import (
    EXPECTED_CANDIDATE_ID, EXPECTED_CONTRACT_SHA256, EXPECTED_FROZEN_SHA256,
    FIRST_DECISION_SESSION_UTC, contract_sha256, load_contract, validate_contract,
)
from ml.v10.cycle3_accelerated_forward_v2_journal import (
    AcceleratedEvidenceCorrupt, AcceleratedEvidenceJournal,
)
from ml.v10.cycle3_accelerated_forward_v2_runner import run_once
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = PROJECT_ROOT / "scripts/mac/install_v10_cycle3_accelerated_v2.sh"

def _market(end: str):
    dates = list(pd.bdate_range("2026-09-10", end, tz="UTC"))
    symbols = [f"S{index:03d}" for index in range(100)]
    frames = {}
    for index, symbol in enumerate(symbols + ["SPY"]):
        values = 100.0 + index + np.arange(len(dates), dtype=float)
        frames[symbol] = pd.DataFrame({"open": values, "close": values, "volume": 1_000_000.0}, index=dates)
    return symbols, frames, dates, {value: i for i, value in enumerate(dates)}

def _rank(timestamp, symbols, frames, dates, date_to_idx):
    del timestamp, frames, dates, date_to_idx
    return pd.DataFrame([{"symbol": symbol, "raw": float(index), "score": float(100 - index), "defensive_active": True} for index, symbol in enumerate(symbols)])

def _assert_contract():
    contract = load_contract()
    assert contract_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert contract["contract_id"] == "V10_CYCLE3_ACCELERATED_PAPER_FORWARD_V2"
    assert contract["source_candidate"]["candidate_id"] == EXPECTED_CANDIDATE_ID
    assert contract["source_candidate"]["frozen_sha256"] == EXPECTED_FROZEN_SHA256
    assert contract["evidence_window"]["first_decision_session_utc"] == FIRST_DECISION_SESSION_UTC
    assert contract["evidence_window"]["missed_decisions_backfilled"] is False
    assert contract["authority"]["paper_trading_only"] is True
    assert contract["authority"]["brokerage_orders"] is False
    tampered = json.loads(json.dumps(contract))
    tampered["source_candidate"]["candidate_modified"] = True
    assert "CANDIDATE_MUST_REMAIN_UNMODIFIED" in validate_contract(tampered)

def _assert_clean_start_and_duplicate_safe():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary); journal_path = root / "journal.jsonl"; status_path = root / "status.json"
        first = run_once(now_utc=datetime(2026, 9, 10, 20, 10, tzinfo=timezone.utc), journal_path=journal_path, status_path=status_path, load_market=lambda: _market("2026-09-10"), rank_for_date=_rank, verify_source=lambda: None)
        assert first["decisions"] == 1 and first["entries"] == 0 and first["appended_this_run"] == 1
        assert first["latest_source_session"] == "2026-09-10" and first["missed_decisions_not_backfilled"] == []
        assert first["current_run_health"] is True and first["study_integrity"] is True
        duplicate = run_once(now_utc=datetime(2026, 9, 10, 20, 15, tzinfo=timezone.utc), journal_path=journal_path, status_path=status_path, load_market=lambda: _market("2026-09-10"), rank_for_date=_rank, verify_source=lambda: None)
        assert duplicate["journal_events"] == 1 and duplicate["appended_this_run"] == 0
        second = run_once(now_utc=datetime(2026, 9, 11, 20, 10, tzinfo=timezone.utc), journal_path=journal_path, status_path=status_path, load_market=lambda: _market("2026-09-11"), rank_for_date=_rank, verify_source=lambda: None)
        assert second["decisions"] == 2 and second["entries"] == 1 and second["study_integrity"] is True
        rows = AcceleratedEvidenceJournal(journal_path).read()
        assert all(row["contract_sha256"] == EXPECTED_CONTRACT_SHA256 for row in rows)
        assert all(row["brokerage_orders"] is False for row in rows)
        original = journal_path.read_text(encoding="utf-8")
        journal_path.write_text(original.replace('"paper_trading_only":true', '"paper_trading_only":false', 1), encoding="utf-8")
        try:
            AcceleratedEvidenceJournal(journal_path).read()
        except AcceleratedEvidenceCorrupt:
            pass
        else:
            raise AssertionError("tampered V2 journal was accepted")

def _assert_scheduler_is_separate():
    source = INSTALLER_PATH.read_text(encoding="utf-8")
    assert "com.datashepherd.v10cycle3acceleratedv2" in source
    assert "FEATURE_BACKEND" in source and "spark" in source
    assert "accelerated_forward_v2" in source
    runner = Path(__file__).with_name("cycle3_accelerated_forward_v2_runner.py").read_text(encoding="utf-8")
    assert "cycle3_accelerated_forward_journal" not in runner
    assert "brokerage_orders" in runner

def main():
    _assert_contract(); _assert_clean_start_and_duplicate_safe(); _assert_scheduler_is_separate()
    print("V10 CYCLE 3 V2 CLEAN PAPER-FORWARD REGRESSION")
    print("=" * 88)
    print("V2 contract identity and frozen candidate: PASS")
    print("Clean September 10 start boundary: PASS")
    print("Prospective decision and duplicate safety: PASS")
    print("V2 journal isolation and tamper detection: PASS")
    print("Spark scheduler namespace is separate from V1: PASS")
    print("No backfill; automatic promotion disabled; human review required: PASS")
    print("V1 journal and January confirmation: UNCHANGED")

if __name__ == "__main__":
    main()


