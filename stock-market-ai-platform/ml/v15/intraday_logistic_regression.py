"""Deterministic regression checks for the V15 intraday ML foundation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
import math
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.v15.intraday_logistic import (
    EXPECTED_CONTRACT_SHA256,
    FEATURE_NAMES,
    LogisticRegression,
    build_examples,
    canonical_sha256,
    evaluate_walk_forward,
    load_contract,
)


NEW_YORK = ZoneInfo("America/New_York")


def _synthetic_dataset(session_count: int = 46):
    sessions = [value.date() for value in pd.bdate_range("2026-01-05", periods=session_count)]
    symbols = [f"S{index:03d}" for index in range(100)] + ["SPY"]
    dataset: dict[str, list[dict[str, object]]] = {symbol: [] for symbol in symbols}
    for session_index, session in enumerate(sessions):
        start = datetime.combine(session, time(9, 30), tzinfo=NEW_YORK)
        session_wave = ((session_index % 7) - 3) * 0.04
        for symbol_index, symbol in enumerate(symbols):
            signal = 0.0 if symbol == "SPY" else ((symbol_index % 20) - 9.5) / 10.0
            signal += session_wave if symbol != "SPY" else session_wave * 0.15
            base = 90.0 + symbol_index * 0.07 + session_index * 0.03
            previous = base
            entry = 0.0
            for bar_index in range(12):
                if bar_index <= 5:
                    close = previous * (1.0 + signal * 0.00055 + (bar_index - 2) * 0.00001)
                    open_price = previous
                elif bar_index == 6:
                    open_price = previous
                    entry = open_price
                    close = entry * (1.0 + signal * 0.0003)
                else:
                    open_price = previous
                    progress = (bar_index - 5) / 6.0
                    close = entry * (1.0 + signal * 0.0045 * progress)
                high = max(open_price, close) * 1.0004
                low = min(open_price, close) * 0.9996
                dataset[symbol].append(
                    {
                        "symbol": symbol,
                        "timestamp_utc": (start + timedelta(minutes=5 * bar_index))
                        .astimezone(ZoneInfo("UTC"))
                        .isoformat(),
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": 1_000_000.0
                        * (1.0 + max(signal, -0.9) * 0.04 + bar_index * 0.015),
                    }
                )
                previous = close
    return dataset


def main() -> None:
    contract = load_contract()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert contract["classification"] == (
        "PREREGISTERED_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
    )
    assert contract["data"]["decision_time_eastern"] == "10:00"
    assert contract["data"]["completed_bars_only"] is True
    assert contract["model"]["purge_gap_sessions"] == 1
    assert contract["authority"]["scheduler_installation_allowed"] is False
    assert contract["authority"]["brokerage_orders"] is False
    print("[PASS] V15 contract preserves the development and authority boundary")

    X = np.asarray([[-2.0], [-1.0], [1.0], [2.0]])
    y = np.asarray([0, 0, 1, 1])
    learner = LogisticRegression(learning_rate=0.1, epochs=700, l2=0.0).fit(X, y)
    probabilities = learner.predict_probability(np.asarray([[-2.0], [2.0]]))
    assert learner.weights is not None and learner.weights[0] > 0.0
    assert probabilities[0] < 0.5 < probabilities[1]
    print("[PASS] V15 logistic learner responds to labeled intraday outcomes")

    dataset = _synthetic_dataset()
    sessions, examples = build_examples(dataset, contract)
    assert len(sessions) == 45
    assert all(len(examples[session]) == 100 for session in sessions)
    assert all(len(row["features"]) == len(FEATURE_NAMES) for row in examples[sessions[0]])
    assert {row["label"] for session in sessions for row in examples[session]} == {0, 1}
    print("[PASS] V11 completed bars become 100-stock V15 training rows")

    result = evaluate_walk_forward(dataset, contract)
    assert result["status"] == "V15_WALK_FORWARD_DEVELOPMENT_EVIDENCE"
    assert result["test_sessions"] == 5
    assert result["fold_count"] == 1
    assert result["model_frozen"] is False
    assert result["selection_on_test_data"] is False
    for observation in result["test_observations"]:
        assert observation["training_cutoff_session"] < observation["session"]
        assert len(observation["selected_symbols"]) == 10
        assert len(observation["selected_probabilities"]) == 10
        assert len(observation["model_sha256"]) == 64
    print("[PASS] Walk-forward predictions use only earlier completed sessions")

    assert result["v15_relative_to_spy"] > 0.0
    expected_relative = (
        (1.0 + result["v15_net_total_return"])
        / (1.0 + result["v11_control_net_total_return"])
        - 1.0
    )
    assert math.isclose(result["v15_relative_to_v11"], expected_relative)
    print("[PASS] V15 comparisons with fixed V11 and SPY are internally consistent")

    assert result["paper_trading_only"] is True
    assert result["brokerage_orders"] is False
    assert all(result[f"v{version}_modified"] is False for version in (8, 10, 11, 13, 14))
    print("[PASS] V15 cannot modify existing models or place orders")

    tampered = deepcopy(contract)
    tampered["authority"]["brokerage_orders"] = True
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory) / "contract.json"
        temporary.write_text(__import__("json").dumps(tampered), encoding="utf-8")
        try:
            load_contract(temporary)
        except ValueError as exc:
            assert "V15_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 accepted brokerage authority")
    print("[PASS] Contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
