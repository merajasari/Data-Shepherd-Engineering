"""Regression checks for the guarded V15 V7 runner and scheduler."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from ml.v15.intraday_logistic import canonical_sha256
from ml.v15.intraday_prospective_v7_contract import load_contract
from ml.v15.intraday_prospective_v7_journal import V7EvidenceJournal
from ml.v15.intraday_prospective_v7_runner import run_snapshot
from ml.v15.intraday_prospective_v7_scheduled_entrypoint import run_scheduled


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = Path(__file__).with_name("intraday_prospective_v7_runner.py")
SCHEDULER_PATH = Path(__file__).with_name(
    "intraday_prospective_v7_scheduled_entrypoint.py"
)
INSTALLER_PATH = ROOT / "scripts/mac/install_v15_intraday_prospective_v7.sh"


def _rows(symbol: str, count: int) -> list[dict[str, object]]:
    base = 100.0 + int(symbol[1:]) / 100.0 if symbol != "SPY" else 500.0
    start = datetime(2026, 9, 21, 13, 30, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for index in range(count):
        close = base
        if index == 29:
            close = base * (1.01 if symbol in {"S000", "S001"} else 1.002)
        rows.append(
            {
                "symbol": symbol,
                "timestamp_utc": (start + timedelta(minutes=5 * index)).isoformat(),
                "open": base,
                "high": max(base, close) * 1.001,
                "low": min(base, close) * 0.995,
                "close": close,
                "volume": 100000 + index,
            }
        )
    return rows


def _snapshot(count: int) -> dict[str, object]:
    symbols = [f"S{index:03d}" for index in range(100)] + ["SPY"]
    series = {symbol: _rows(symbol, count) for symbol in symbols}
    return {
        "status": "COMPLETE_RESEARCH_SNAPSHOT",
        "session_date": "2026-09-21",
        "completed_bar_utc": series["SPY"][-1]["timestamp_utc"],
        "symbol_count": 101,
        "symbols": symbols,
        "series": series,
        "series_sha256": canonical_sha256(series),
        "paper_trading_only": True,
        "brokerage_orders": False,
    }


def _trade_decision(_: object) -> dict[str, object]:
    return {
        "trade": True,
        "cash_fallback": False,
        "selected_symbols": ["S000", "S001"],
        "v11_control_symbols": ["S002", "S003"],
        "v14_control_symbols": ["S004", "S005"],
        "top_n": 2,
        "predicted_topk_net_return": 0.004,
        "participation_quantile": 0.65,
        "applied_threshold": 0.002,
        "daily_context_session": "2026-09-18",
        "model_snapshot_sha256": "a" * 64,
        "prepared_artifact_sha256": "b" * 64,
        "training_cutoff_session": "2026-08-11",
    }


def _cash_decision(_: object) -> dict[str, object]:
    return {
        "trade": False,
        "cash_fallback": False,
        "selected_symbols": [],
        "v11_control_symbols": [],
        "v14_control_symbols": [],
        "top_n": 3,
        "predicted_topk_net_return": 0.001,
        "participation_quantile": 0.8,
        "applied_threshold": 0.002,
        "daily_context_session": "2026-09-18",
        "model_snapshot_sha256": "a" * 64,
        "prepared_artifact_sha256": "b" * 64,
        "training_cutoff_session": "2026-08-11",
    }


def _assert_runner_lifecycle() -> None:
    with TemporaryDirectory() as directory:
        journal_path = Path(directory) / "journal.jsonl"
        decision = run_snapshot(
            snapshot=_snapshot(6),
            journal_path=journal_path,
            decision_builder=_trade_decision,
            collected_at_utc=datetime(2026, 9, 21, 14, 2, tzinfo=timezone.utc),
        )
        assert decision["status"] == "WAITING_FOR_ENTRY"
        assert decision["appended_this_run"] == 1

        entry = run_snapshot(
            snapshot=_snapshot(7),
            journal_path=journal_path,
            decision_builder=lambda _: (_ for _ in ()).throw(
                AssertionError("existing decision must be reused")
            ),
            collected_at_utc=datetime(2026, 9, 21, 14, 6, tzinfo=timezone.utc),
        )
        assert entry["status"] == "WAITING_FOR_EXIT"
        assert entry["appended_this_run"] == 1

        completed = run_snapshot(
            snapshot=_snapshot(30),
            journal_path=journal_path,
            decision_builder=lambda _: (_ for _ in ()).throw(
                AssertionError("existing decision must be reused")
            ),
            collected_at_utc=datetime(2026, 9, 21, 16, 2, tzinfo=timezone.utc),
        )
        assert completed["status"] == "SESSION_EXIT_COMPLETE"
        assert completed["appended_this_run"] == 1
        rows = V7EvidenceJournal(journal_path).read()
        assert [row["event_type"] for row in rows] == [
            "DECISION",
            "ENTRY",
            "EXIT",
        ]
        exit_payload = rows[-1]["payload"]
        assert math.isclose(
            exit_payload["v15_net_return"],
            0.6 * (0.01 - 0.001),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        assert exit_payload["maximum_invested_fraction"] == 0.6
        assert exit_payload["required_cash_fraction"] == 0.4
        assert exit_payload["modeled_total_cost_bps_round_trip"] == 10

        duplicate = run_snapshot(
            snapshot=_snapshot(30),
            journal_path=journal_path,
            decision_builder=_trade_decision,
        )
        assert duplicate["appended_this_run"] == 0
        assert len(V7EvidenceJournal(journal_path).read()) == 3


def _assert_cash_is_complete() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "cash.jsonl"
        result = run_snapshot(
            snapshot=_snapshot(30),
            journal_path=path,
            decision_builder=_cash_decision,
        )
        assert result["status"] == "CASH_SESSION_COMPLETE"
        assert result["appended_this_run"] == 1
        rows = V7EvidenceJournal(path).read()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "DECISION"
        assert rows[0]["payload"]["trade"] is False


def _assert_scheduler_boundaries() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        calls: list[tuple[str, int]] = []

        def collector(now, session, minimum_bars, output_path):
            calls.append((session, minimum_bars))
            output_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(
                status="PUBLISHED_COMPLETE_RESEARCH_SNAPSHOT",
                published=True,
                symbol_count=101,
                completed_bar_utc=now.isoformat(),
                trimmed_incomplete_bars=0,
                reasons=(),
            )

        def runner(snapshot_path, journal_path):
            assert snapshot_path.exists()
            return {"status": "WAITING_FOR_EXIT"}

        ready = lambda _: {}
        # At 10:04 Eastern the seventh 10:00 bar is still forming.  The
        # scheduler must collect with the immutable six-bar decision floor so
        # the five-minute cadence cannot skip directly to a missed decision.
        active = run_scheduled(
            now_utc=datetime(2026, 9, 21, 14, 4, tzinfo=timezone.utc),
            status_path=root / "active_status.json",
            journal_path=root / "active_journal.jsonl",
            snapshot_path=root / "snapshot.json",
            model_path=root / "model.json",
            model_ready_fn=ready,
            collector_fn=collector,
            runner_fn=runner,
        )
        assert active["collector_invoked"] is True
        assert active["runner_invoked"] is True
        assert calls == [("2026-09-21", 6)]
        assert active["maximum_tiingo_requests_per_session"] == 303

        calls.clear()
        before = run_scheduled(
            now_utc=datetime(2026, 9, 18, 14, 5, tzinfo=timezone.utc),
            status_path=root / "before_status.json",
            journal_path=root / "before_journal.jsonl",
            snapshot_path=root / "before_snapshot.json",
            model_path=root / "model.json",
            model_ready_fn=ready,
            collector_fn=collector,
            runner_fn=runner,
        )
        assert before["status"] == "WAITING_FOR_PROSPECTIVE_BOUNDARY"
        assert before["lifecycle_stage"] == "WAITING_FOR_PROSPECTIVE_BOUNDARY"
        assert before["collector_invoked"] is False
        assert calls == []

        missed = run_scheduled(
            now_utc=datetime(2026, 9, 21, 14, 9, tzinfo=timezone.utc),
            status_path=root / "missed_status.json",
            journal_path=root / "missed_journal.jsonl",
            snapshot_path=root / "missed_snapshot.json",
            model_path=root / "model.json",
            model_ready_fn=ready,
            collector_fn=collector,
            runner_fn=runner,
        )
        assert missed["status"] == "MISSED_DECISION_NO_BACKFILL"
        assert missed["collector_invoked"] is False
        assert missed["missed_decision_sessions"] == ["2026-09-21"]
        assert missed["current_run_health"] is False
        assert missed["operational_failures"] == [
            "current_session_missed_decision_no_backfill"
        ]
        assert missed["historical_operational_gaps"] == [
            "missed_decision_sessions:2026-09-21"
        ]

        recovered = run_scheduled(
            now_utc=datetime(2026, 9, 22, 13, 30, tzinfo=timezone.utc),
            status_path=root / "missed_status.json",
            journal_path=root / "missed_journal.jsonl",
            snapshot_path=root / "missed_snapshot.json",
            model_path=root / "model.json",
            model_ready_fn=ready,
            collector_fn=collector,
            runner_fn=runner,
        )
        assert recovered["status"] == "WAITING_FOR_DECISION_CHECKPOINT"
        assert recovered["current_run_health"] is True
        assert recovered["operational_failures"] == []
        assert recovered["missed_decision_sessions"] == ["2026-09-21"]
        assert recovered["historical_operational_gaps"] == [
            "missed_decision_sessions:2026-09-21"
        ]


def _assert_source_isolation() -> None:
    contract = load_contract()
    assert contract["training_policy"]["fixed_history_last_session"] == "2026-09-10"
    assert contract["training_policy"]["historical_training_expansion_during_v7"] is False
    assert contract["frozen_mechanics"]["matched_controls_share_exposure"] is True
    assert contract["lifecycle"]["decision_features_fixed_to_first_six_completed_bars"] is True

    runner = RUNNER_PATH.read_text(encoding="utf-8").lower()
    scheduler = SCHEDULER_PATH.read_text(encoding="utf-8").lower()
    installer = INSTALLER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "alpaca",
        "robinhood",
        "interactive_brokers",
        "ibkr",
        "place_order",
        "submit_order",
        "requests.post",
    )
    assert not any(value in runner for value in forbidden)
    assert not any(value in scheduler for value in forbidden)
    assert "data/research/v15/prospective_v7/latest_complete_snapshot.json" in (
        RUNNER_PATH.read_text(encoding="utf-8")
    )
    assert "StartInterval</key><integer>$INTERVAL_SECONDS</integer>" in installer
    assert "INTERVAL_SECONDS=300" in installer
    assert "intraday_prospective_v7_regression" in installer
    assert "intraday_prospective_v7_runner --prepare" in installer
    assert "brokerage orders are off" in installer.lower()


def main() -> None:
    _assert_runner_lifecycle()
    print("[PASS] V7 records decision, entry, and risk-scaled exit exactly once")
    _assert_cash_is_complete()
    print("[PASS] No-trade decisions remain cash without synthetic entry or cost")
    _assert_scheduler_boundaries()
    print("[PASS] Scheduler honors the boundary, aligned windows, and no-backfill rule")
    _assert_source_isolation()
    print("[PASS] V7 uses fixed history, V15-owned snapshots, and no brokerage interface")
    print("[PASS] V7 keeps 60% exposure and identical stock-control risk treatment")
    print("Status: PASSED")
    print("Paper shadow only: YES")
    print("Automatic promotion: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
