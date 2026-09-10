"""Regression checks for the isolated V14 logistic candidate."""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path
import json
import tempfile

import numpy as np
import pandas as pd

from ml.v14.logistic_forward import (
    EXPECTED_CANDIDATE_ID,
    LogisticRegression,
    _training_rows,
    fit_as_of,
    run_once,
)


FEATURES = [
    "daily_return",
    "return_5d",
    "return_20d",
    "price_vs_sma_20",
    "volatility_ratio_5_20",
    "volume_ratio",
]


def _contract(start: pd.Timestamp) -> dict[str, object]:
    return {
        "contract_id": "V14_LOGISTIC_WALK_FORWARD_PAPER_FORWARD_V1",
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "model": {
            "type": "numpy_logistic_regression",
            "target": "target_up_5d",
            "features": FEATURES,
            "training_scope": "pooled_cross_sectional_expanding_window",
            "purge_gap_sessions": 5,
            "minimum_training_rows": 20,
            "learning_rate": 0.05,
            "epochs": 500,
            "l2": 0.001,
        },
        "portfolio": {
            "top_n": 10,
            "weighting": "equal_weight",
            "entry": "next_session_open",
            "holding_sessions": 5,
            "cost_bps_per_dollar_traded": 10,
            "cohort_offsets": [0, 1, 2, 3, 4],
        },
        "evaluation": {
            "paper_forward_start_utc": start.isoformat(),
            "outcomes_for_model_selection": False,
            "online_retraining": True,
            "training_cutoff_is_recorded": True,
            "model_snapshot_is_recorded": True,
        },
        "authority": {
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "human_review_required": True,
            "modify_v8": False,
            "modify_v10": False,
        },
    }


def _market():
    dates = [pd.Timestamp(value).tz_localize("UTC") for value in pd.bdate_range("2026-07-01", periods=36)]
    symbols = [f"S{index:03d}" for index in range(100)]
    frames: dict[str, pd.DataFrame] = {}
    for index, symbol in enumerate(symbols + ["SPY"]):
        signal = np.linspace(-1.0, 1.0, len(dates)) + index / 500.0
        values = 100.0 + index / 20.0 + np.arange(len(dates), dtype=float) * 0.2
        frame = pd.DataFrame(index=dates)
        frame["open"] = values
        frame["close"] = values
        frame["volume"] = 1_000_000.0 + index
        frame["daily_return"] = signal
        frame["return_5d"] = signal
        frame["return_20d"] = signal
        frame["price_vs_sma_20"] = signal
        frame["volatility_ratio_5_20"] = signal
        frame["volume_ratio"] = signal
        frame["target_up_5d"] = (signal > 0.0).astype(int)
        frames[symbol] = frame
    return symbols, frames, dates, {value: index for index, value in enumerate(dates)}


def main() -> None:
    # A learned coefficient must respond to a predictive feature.
    X = np.array([[-2.0], [-1.0], [1.0], [2.0]], dtype=float)
    y = np.array([0, 0, 1, 1], dtype=int)
    model = LogisticRegression(learning_rate=0.1, epochs=800, l2=0.0)
    model.fit(X, y)
    assert model.weights is not None and model.weights[0] > 0.0
    assert model.predict_probability(np.array([[-2.0], [2.0]])).tolist()[0] < 0.5
    assert model.predict_probability(np.array([[-2.0], [2.0]])).tolist()[1] > 0.5
    print("[PASS] Logistic regression learns coefficients from labels")

    symbols, frames, dates, date_to_idx = _market()
    decision_index = 25
    training, cutoff = _training_rows(symbols, frames, FEATURES, decision_index, 5)
    assert cutoff == dates[decision_index - 5]
    assert training["timestamp_utc"].max() <= cutoff
    print("[PASS] Training rows obey the five-session purge gap")

    contract = _contract(dates[decision_index])
    _, metadata, ranked = fit_as_of(dates[decision_index], symbols, frames, dates, contract)
    assert len(ranked) == 100
    assert len(ranked.head(10)) == 10
    assert metadata["training_cutoff_utc"] == cutoff.isoformat()
    assert len(metadata["model_snapshot"]["weights"]) == len(FEATURES)
    print("[PASS] Candidate records a model snapshot and training cutoff")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        journal = root / "journal.jsonl"
        status = root / "status.json"
        before = run_once(
            now_utc=dates[decision_index].to_pydatetime().replace(tzinfo=timezone.utc) - timedelta(hours=1),
            contract=contract,
            journal_path=journal,
            status_path=status,
            load_market_fn=lambda _: _market(),
        )
        assert before["status"] == "WAITING_FOR_PAPER_FORWARD_BOUNDARY"
        assert not journal.exists()
        after_decision = run_once(
            now_utc=dates[decision_index].to_pydatetime().replace(tzinfo=timezone.utc) + timedelta(hours=21),
            contract=contract,
            journal_path=journal,
            status_path=status,
            load_market_fn=lambda _: _market(),
        )
        events = [line for line in journal.read_text().splitlines() if line.strip()]
        assert after_decision["decisions"] >= 1
        assert any('"event_type": "DECISION"' in line for line in events)
        assert all('"candidate_id": "v14_logistic_walk_forward_top10"' in line for line in events)
        decision_event = next(
            json.loads(line)
            for line in events
            if json.loads(line).get("event_type") == "DECISION"
        )
        assert len(decision_event["ranked_predictions"]) == 100
        assert sum(
            item["selected_top10"]
            for item in decision_event["ranked_predictions"]
        ) == 10
        print("[PASS] Paper-forward runner creates isolated V14 decisions")

        after_entry = run_once(
            now_utc=dates[decision_index + 1].to_pydatetime().replace(tzinfo=timezone.utc) + timedelta(hours=21),
            contract=contract,
            journal_path=journal,
            status_path=status,
            load_market_fn=lambda _: _market(),
        )
        assert after_entry["entries"] >= 1
        assert not (root / "v8").exists()
        assert not (root / "v10").exists()
        print("[PASS] Entry remains paper-only and cannot write V8/V10 state")

        after_exit = run_once(
            now_utc=dates[decision_index + 6].to_pydatetime().replace(
                tzinfo=timezone.utc
            ) + timedelta(hours=21),
            contract=contract,
            journal_path=journal,
            status_path=status,
            load_market_fn=lambda _: _market(),
        )
        exit_events = [
            json.loads(line)
            for line in journal.read_text().splitlines()
            if json.loads(line).get("event_type") == "EXIT"
        ]
        assert after_exit["completed_exits"] >= 1
        assert exit_events
        assert exit_events[0]["spy_return"] is not None
        assert exit_events[0]["net_relative_return"] is not None
        assert len(exit_events[0]["symbol_returns"]) == 10
        print("[PASS] Exit records V14, SPY, relative, and symbol-level evidence")

    print("Status: PASSED")


if __name__ == "__main__":
    main()
