"""Regression checks for the isolated September 8 diagnostic reconstruction."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from ml.v10.cycle3_accelerated_diagnostic_backfill import (
    ACKNOWLEDGEMENT,
    DiagnosticReconstructionRejected,
    EXPECTED_CONTRACT_SHA256,
    load_contract,
    reconstruct,
)


def _market(include_target: bool = True):
    dates = list(pd.bdate_range("2026-08-03", "2026-09-09", tz="UTC"))
    dates = [
        value
        for value in dates
        if value.date().isoformat() != "2026-09-07"
        and (include_target or value.date().isoformat() != "2026-09-08")
    ]
    symbols = [f"S{index:03d}" for index in range(100)]
    frames = {}
    for index, symbol in enumerate(symbols + ["SPY"]):
        values = 100.0 + index / 10.0 + np.arange(len(dates)) * 0.1
        frames[symbol] = pd.DataFrame(
            {"open": values, "close": values, "volume": 1_000_000.0},
            index=dates,
        )
    return symbols, frames, dates, {value: i for i, value in enumerate(dates)}


def _rank(timestamp, symbols, frames, dates, date_to_idx):
    del timestamp, frames, dates, date_to_idx
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "raw": float(index),
                "score": float(100 - index),
                "defensive_active": True,
            }
            for index, symbol in enumerate(symbols)
        ]
    )


def main() -> None:
    assert load_contract()
    assert EXPECTED_CONTRACT_SHA256 == (
        "98096f2729e294d9747ffef42838d3af1599ee63c8ee50fe363b8096ceb0a709"
    )
    print("[PASS] Diagnostic reconstruction contract identity is locked")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        artifact = root / "diagnostic.json"
        journal = root / "journal.jsonl"
        journal.write_text('{"preserved":"v1"}\n', encoding="utf-8")
        before = journal.read_bytes()

        inert = reconstruct(
            operator="",
            acknowledgement="",
            artifact_path=artifact,
            journal_path=journal,
            load_market=_market,
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert inert["status"] == "IMPLEMENTED_NOT_INVOKED"
        assert not artifact.exists()
        print("[PASS] Default command is inert")

        try:
            reconstruct(
                operator="Meraj Asari",
                acknowledgement="wrong",
                apply=True,
                artifact_path=artifact,
                journal_path=journal,
                load_market=_market,
                rank_for_date=_rank,
                verify_source=lambda: None,
            )
        except DiagnosticReconstructionRejected:
            pass
        else:
            raise AssertionError("non-exact acknowledgement accepted")
        assert not artifact.exists()
        print("[PASS] Non-exact acknowledgement creates no diagnostic")

        result = reconstruct(
            operator="Meraj Asari",
            acknowledgement=ACKNOWLEDGEMENT,
            apply=True,
            now_utc=datetime(2026, 9, 9, 23, 50, tzinfo=timezone.utc),
            artifact_path=artifact,
            journal_path=journal,
            load_market=_market,
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert result["status"] == "DIAGNOSTIC_RECONSTRUCTED_OUTSIDE_V1_EVIDENCE"
        assert result["prospective_evidence"] is False
        assert result["promotion_eligible"] is False
        assert result["v1_journal_appended"] is False
        assert result["decision_locked_prospectively"] is False
        assert len(result["symbols"]) == 10
        assert len(result["v8_control_symbols"]) == 10
        assert journal.read_bytes() == before
        print("[PASS] September 8 decision is reconstructed diagnostically")
        print("[PASS] Diagnostic is excluded from prospective and promotion evidence")
        print("[PASS] V1 journal remains byte-for-byte unchanged")

        duplicate = reconstruct(
            operator="Meraj Asari",
            acknowledgement=ACKNOWLEDGEMENT,
            apply=True,
            artifact_path=artifact,
            journal_path=journal,
            load_market=lambda: (_ for _ in ()).throw(AssertionError()),
            rank_for_date=_rank,
            verify_source=lambda: None,
        )
        assert duplicate["status"] == "DIAGNOSTIC_ALREADY_RECONSTRUCTED"
        assert journal.read_bytes() == before
        print("[PASS] Diagnostic restart is immutable and duplicate-safe")

    with tempfile.TemporaryDirectory() as temporary:
        artifact = Path(temporary) / "diagnostic.json"
        try:
            reconstruct(
                operator="Meraj Asari",
                acknowledgement=ACKNOWLEDGEMENT,
                apply=True,
                artifact_path=artifact,
                journal_path=Path(temporary) / "absent.jsonl",
                load_market=lambda: _market(False),
                rank_for_date=_rank,
                verify_source=lambda: None,
            )
        except DiagnosticReconstructionRejected as exc:
            assert str(exc) == "SEPTEMBER_8_SOURCE_SESSION_UNAVAILABLE"
        else:
            raise AssertionError("missing target source accepted")
        assert not artifact.exists()
        print("[PASS] Missing September 8 source fails without an artifact")

    source = Path(__file__).with_name(
        "cycle3_accelerated_diagnostic_backfill.py"
    ).read_text(encoding="utf-8").lower()
    assert ".append(event)" not in source
    assert "import alpaca" not in source
    assert "robin_stocks" not in source
    assert "ib_insync" not in source
    print("[PASS] Diagnostic utility has no evidence-journal append surface")
    print("[PASS] Diagnostic utility has no brokerage authority")
    print("Status: PASSED")
    print("V1 prospective evidence modified: NO")
    print("Diagnostic promotion eligibility: NO")
    print("Current scheduled collection may continue: YES")


if __name__ == "__main__":
    main()

