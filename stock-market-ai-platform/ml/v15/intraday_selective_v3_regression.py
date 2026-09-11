"""Deterministic regression checks for V15 V3 selective intraday research."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.v15.intraday_hybrid_v2_disposition import (
    EXPECTED_DISPOSITION_SHA256 as EXPECTED_V2_DISPOSITION_SHA256,
    load_disposition as load_v2_disposition,
)
from ml.v15.intraday_hybrid_v2_regression import _daily_frames
from ml.v15.intraday_selective_v3 import (
    EXPECTED_CONTRACT_SHA256,
    RidgeReturnRegression,
    _evaluate_configuration,
    build_multihorizon_examples,
    canonical_sha256,
    evaluate_walk_forward,
    load_contract,
)


NEW_YORK = ZoneInfo("America/New_York")


def _intraday_dataset(session_count: int = 70):
    sessions = [
        value.date() for value in pd.bdate_range("2026-01-05", periods=session_count)
    ]
    symbols = [f"S{index:03d}" for index in range(100)] + ["SPY"]
    dataset: dict[str, list[dict[str, object]]] = {symbol: [] for symbol in symbols}
    for session_index, session in enumerate(sessions):
        start = datetime.combine(session, time(9, 30), tzinfo=NEW_YORK)
        regime = 1.0 if session_index % 4 != 0 else -0.35
        for symbol_index, symbol in enumerate(symbols):
            base_signal = (
                0.0 if symbol == "SPY" else ((symbol_index % 20) - 9.5) / 10.0
            )
            signal = base_signal * regime
            base = 80.0 + symbol_index * 0.08 + session_index * 0.025
            previous = base
            entry = base
            for bar_index in range(36):
                if bar_index <= 5:
                    open_price = previous
                    close = previous * (
                        1.0 + signal * 0.0006 + (bar_index - 2) * 0.00001
                    )
                elif bar_index == 6:
                    open_price = previous
                    entry = open_price
                    close = entry * (1.0 + signal * 0.00025)
                else:
                    open_price = previous
                    progress = (bar_index - 5) / 24.0
                    close = entry * (1.0 + signal * 0.009 * progress)
                dataset[symbol].append(
                    {
                        "symbol": symbol,
                        "timestamp_utc": (start + timedelta(minutes=5 * bar_index))
                        .astimezone(ZoneInfo("UTC"))
                        .isoformat(),
                        "open": open_price,
                        "high": max(open_price, close) * 1.0003,
                        "low": min(open_price, close) * 0.9997,
                        "close": close,
                        "volume": 900_000.0
                        * (1.0 + max(signal, -0.9) * 0.04 + bar_index * 0.01),
                    }
                )
                previous = close
    return dataset


def _test_contract(contract: dict[str, object]) -> dict[str, object]:
    value = deepcopy(contract)
    value["data"]["minimum_eligible_intraday_sessions"] = 60
    value["model"]["minimum_outer_training_sessions"] = 40
    value["model"]["minimum_training_rows"] = 4000
    value["nested_selection"]["inner_validation_sessions"] = 10
    value["nested_selection"]["minimum_inner_training_sessions"] = 20
    value["nested_selection"]["minimum_inner_trades"] = 2
    value["evaluation"]["test_sessions_per_fold"] = 10
    value["evaluation"]["minimum_final_test_sessions"] = 10
    value["evaluation"]["gates"]["completed_trades_at_least"] = 2
    return value


def main() -> None:
    contract = load_contract()
    disposition = load_v2_disposition()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert disposition["disposition_sha256"] == EXPECTED_V2_DISPOSITION_SHA256
    assert disposition["observed_result_sha256"] == (
        "a48f04a29b9f7f0799a136686a37432d39a4ed9de1a33657a9ee29694466dde8"
    )
    assert disposition["decision"] == "REJECTED_DO_NOT_ADVANCE_TO_PAPER_FORWARD"
    assert contract["heritage"]["v2_disposition_sha256"] == (
        EXPECTED_V2_DISPOSITION_SHA256
    )
    assert contract["heritage"]["v2_results_reused_as_fresh_evidence"] is False
    print("[PASS] V2 rejection is immutable and separated from V3 development")

    assert contract["objective"]["cash_is_valid_position"] is True
    assert contract["nested_selection"]["candidate_holding_bars"] == [6, 12, 24]
    assert contract["nested_selection"]["candidate_safety_buffers"] == [
        0.0005,
        0.001,
        0.0015,
    ]
    assert contract["portfolio"]["cost_applied_only_when_trade_occurs"] is True
    print("[PASS] V3 freezes cash, three horizons, and cost-aware thresholds")

    learner = RidgeReturnRegression(alpha=0.01).fit(
        np.asarray([[-2.0], [-1.0], [1.0], [2.0]]),
        np.asarray([-0.02, -0.01, 0.01, 0.02]),
    )
    prediction = learner.predict(np.asarray([[-2.0], [2.0]]))
    assert learner.weights is not None and learner.weights[0] > 0.0
    assert prediction[0] < 0.0 < prediction[1]
    print("[PASS] Ridge learner predicts continuous return magnitude")

    intraday = _intraday_dataset()
    daily = _daily_frames(intraday)
    test_contract = _test_contract(contract)
    sessions, examples, audit = build_multihorizon_examples(
        intraday, daily, test_contract
    )
    assert len(sessions) == 69
    assert all(len(examples[session]) == 100 for session in sessions)
    assert all(
        set(row["outcomes"]) == {"6", "12", "24"}
        for row in examples[sessions[0]]
    )
    assert all(
        row["daily_context_session"] < row["session"]
        for session in sessions
        for row in examples[session]
    )
    assert len(audit["daily_context_input_sha256"]) == 64
    print("[PASS] One leakage-safe feature row carries three isolated outcomes")

    cash_model = RidgeReturnRegression(
        alpha=0.01,
        weights=np.zeros(len(examples[sessions[0]][0]["features"])),
        bias=0.0,
    )
    cash_score = _evaluate_configuration(
        sessions[-5:],
        examples,
        cash_model,
        np.zeros(len(cash_model.weights)),
        np.ones(len(cash_model.weights)),
        horizon=6,
        buffer=0.0005,
        top_n=10,
        cost=0.001,
    )
    assert cash_score["trades"] == 0
    assert cash_score["net_total_return"] == 0.0
    assert cash_score["max_drawdown"] == 0.0
    print("[PASS] No-trade sessions stay in cash and incur no modeled cost")

    result = evaluate_walk_forward(intraday, daily, test_contract)
    assert result["eligible_sessions"] == 69
    assert result["test_sessions"] == 29
    assert result["fold_count"] == 3
    assert result["folds"][-1]["test_sessions"] == 9
    assert result["completed_trades"] + result["cash_sessions"] == 29
    assert result["model_frozen"] is False
    assert result["paper_forward_allowed"] is False
    for fold in result["folds"]:
        selected = fold["selected_configuration"]
        assert selected["inner_training_cutoff_session"] < (
            selected["inner_validation_start_session"]
        )
        assert selected["inner_validation_end_session"] < fold["test_start_session"]
        if fold["model_snapshot"] is not None:
            snapshot = dict(fold["model_snapshot"])
            embedded = snapshot.pop("model_sha256")
            assert embedded == canonical_sha256(snapshot)
    print("[PASS] Nested selection never reads outer test outcomes")

    assert result["brokerage_orders"] is False
    assert all(result[f"v{version}_modified"] is False for version in (8, 10, 11, 13, 14))
    source = Path(__file__).with_name("intraday_selective_v3.py").read_text(
        encoding="utf-8"
    )
    assert "import requests" not in source.lower()
    assert "import subprocess" not in source.lower()
    assert "launchctl" not in source.lower()
    print("[PASS] V3 cannot schedule itself, alter existing models, or place orders")

    tampered = deepcopy(contract)
    tampered["authority"]["paper_forward_allowed"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_V3_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 V3 accepted expanded authority")
    print("[PASS] V3 contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
