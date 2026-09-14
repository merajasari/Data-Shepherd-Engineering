"""Regression checks for the frozen V15 V7 prospective boundary and journal."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from ml.v15.intraday_logistic import canonical_sha256
from ml.v15.intraday_prospective_v7_contract import (
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)
from ml.v15.intraday_prospective_v7_journal import (
    V7EvidenceJournal,
    build_event,
)
from ml.v15.intraday_risk_managed_v5_disposition import (
    load_disposition as load_v5_disposition,
)
from ml.v15.intraday_v5_backward_robustness_disposition import (
    load_disposition as load_robustness_disposition,
)


def main() -> None:
    contract = load_contract()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert contract["classification"] == (
        "PREREGISTERED_PROSPECTIVE_PAPER_SHADOW_NOT_PRODUCTION"
    )
    assert contract["evidence_boundary"]["first_eligible_session"] == "2026-09-15"
    assert contract["evidence_boundary"][
        "historical_rows_count_as_v7_evidence"
    ] is False
    assert contract["evidence_boundary"]["missed_decisions_may_be_backfilled"] is False
    print("[PASS] V7 begins at a clean prospective evidence boundary")

    v5 = load_v5_disposition()
    robustness = load_robustness_disposition()
    assert contract["heritage"]["v5_disposition_sha256"] == v5[
        "disposition_sha256"
    ]
    assert contract["heritage"]["backward_robustness_disposition_sha256"] == (
        robustness["disposition_sha256"]
    )
    assert contract["heritage"]["historical_results_are_design_context_not_v7_evidence"]
    assert contract["heritage"]["v6_logic_used"] is False
    print("[PASS] Historical V5 evidence is disclosed but excluded from V7 evidence")

    mechanics = contract["frozen_mechanics"]
    assert mechanics["maximum_invested_fraction"] == 0.6
    assert mechanics["required_cash_fraction"] == 0.4
    assert mechanics["protective_stop_loss_fraction"] == 0.02
    assert mechanics["modeled_total_cost_bps_round_trip"] == 10
    assert mechanics["holding_minutes"] == 120
    assert mechanics["short_sales"] is False
    assert mechanics["leverage"] is False
    print("[PASS] V7 freezes 60% exposure, cash reserve, stop, cost, and horizon")

    gates = contract["review"]["gates"]
    assert contract["review"]["minimum_completed_trades"] == 30
    assert contract["review"]["minimum_active_blocks"] == 6
    assert gates["positive_active_block_share_at_least"] == 0.6
    assert gates["non_losing_all_block_share_at_least"] == 0.8
    assert gates["maximum_drawdown_at_most"] == 0.1
    assert contract["review"]["automatic_promotion"] is False
    assert contract["review"]["human_review_required"] is True
    print("[PASS] Prospective review gates are fixed and require human approval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "journal.jsonl"
        journal = V7EvidenceJournal(path)
        decision = build_event(
            event_type="DECISION",
            session_date="2026-09-15",
            occurred_at_utc=datetime(2026, 9, 15, 14, 1, tzinfo=timezone.utc),
            payload={"selected_symbols": ["AAPL"], "expected_net_return": 0.001},
        )
        entry = build_event(
            event_type="ENTRY",
            session_date="2026-09-15",
            occurred_at_utc=datetime(2026, 9, 15, 14, 4, tzinfo=timezone.utc),
            payload={"entry_prices": {"AAPL": 100.0}, "invested_fraction": 0.6},
        )
        exit_event = build_event(
            event_type="EXIT",
            session_date="2026-09-15",
            occurred_at_utc=datetime(2026, 9, 15, 16, 2, tzinfo=timezone.utc),
            payload={"net_return": 0.006},
        )
        assert journal.append(decision) is True
        assert journal.append(decision) is False
        assert journal.append(entry) is True
        assert journal.append(exit_event) is True
        rows = journal.read()
        assert [row["event_type"] for row in rows] == [
            "DECISION",
            "ENTRY",
            "EXIT",
        ]
        assert rows[0]["previous_event_sha256"] is None
        assert rows[1]["previous_event_sha256"] == rows[0]["event_sha256"]
        assert rows[2]["previous_event_sha256"] == rows[1]["event_sha256"]
    print("[PASS] Journal is append-only, chained, lifecycle ordered, and duplicate safe")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "journal.jsonl"
        journal = V7EvidenceJournal(path)
        try:
            journal.append(
                build_event(
                    event_type="ENTRY",
                    session_date="2026-09-16",
                    occurred_at_utc=datetime(
                        2026, 9, 16, 14, 4, tzinfo=timezone.utc
                    ),
                    payload={"entry_prices": {"AAPL": 100.0}},
                )
            )
        except ValueError as exc:
            assert "V15_V7_LIFECYCLE_ORDER_INVALID" in str(exc)
        else:
            raise AssertionError("V7 accepted an entry without a decision")
    print("[PASS] Entry and exit events cannot precede their decision lifecycle")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "journal.jsonl"
        journal = V7EvidenceJournal(path)
        journal.append(
            build_event(
                event_type="DECISION",
                session_date="2026-09-17",
                occurred_at_utc=datetime(
                    2026, 9, 17, 14, 1, tzinfo=timezone.utc
                ),
                payload={"selected_symbols": ["AAPL"]},
            )
        )
        content = path.read_text(encoding="utf-8")
        path.write_text(content.replace("AAPL", "MSFT"), encoding="utf-8")
        try:
            journal.read()
        except ValueError as exc:
            assert "V15_V7_JOURNAL_HASH_MISMATCH" in str(exc)
        else:
            raise AssertionError("V7 journal accepted payload tampering")
    print("[PASS] Journal detects historical event tampering")

    authority = contract["authority"]
    assert authority["paper_shadow_collection_allowed"] is True
    assert authority["model_frozen_for_production"] is False
    assert authority["live_trading_enabled"] is False
    assert authority["brokerage_orders"] is False
    assert authority["automatic_promotion"] is False
    assert authority["dashboard_may_invoke_runner"] is False
    source = Path(__file__).with_name(
        "intraday_prospective_v7_journal.py"
    ).read_text(encoding="utf-8")
    assert "import requests" not in source.lower()
    assert "import subprocess" not in source.lower()
    assert "alpaca" not in source.lower()
    assert "robinhood" not in source.lower()
    print("[PASS] V7 boundary cannot trade, promote, or invoke brokerage SDKs")

    tampered = deepcopy(contract)
    tampered["authority"]["brokerage_orders"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_V7_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V7 accepted expanded brokerage authority")
    print("[PASS] Contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
