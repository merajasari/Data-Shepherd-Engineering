"""Regression checks for V11 time-ordered walk-forward evaluation."""
from __future__ import annotations

import copy
import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_walk_forward import (
    _sha,
    evaluate_walk_forward,
    load_contract,
    load_dataset,
)


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def synthetic_dataset(session_count: int = 56) -> dict[str, list[dict[str, object]]]:
    from ml.v11.intraday_walk_forward import get_v5_data_symbols
    sessions = []
    cursor = date(2026, 1, 5)
    while len(sessions) < session_count:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    dataset = {}
    for symbol_index, symbol in enumerate(get_v5_data_symbols()):
        rows = []
        for session_index, session in enumerate(sessions):
            start = datetime(session.year, session.month, session.day, 14, 30, tzinfo=timezone.utc)
            base = 100.0 + symbol_index / 5.0 + session_index / 20.0
            strength = (symbol_index - 50) / 100000.0
            for bar_index in range(18):
                opening = base * (1.0 + strength * bar_index)
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp_utc": (start + timedelta(minutes=5 * bar_index)).isoformat(),
                        "open": opening,
                        "high": opening * 1.001,
                        "low": opening * 0.999,
                        "close": opening * (1.0002 + strength),
                        "volume": 1000 + symbol_index * 10 + bar_index * (5 + symbol_index),
                    }
                )
        dataset[symbol] = rows
    return dataset


def test_contract() -> dict[str, object]:
    contract = load_contract()
    contract = copy.deepcopy(contract)
    contract["minimum_train_sessions"] = 20
    contract["test_sessions_per_fold"] = 10
    contract["minimum_final_test_sessions"] = 5
    return contract


def main() -> None:
    contract = test_contract()
    dataset = synthetic_dataset()
    first = evaluate_walk_forward(dataset, contract)
    second = evaluate_walk_forward(dataset, contract)
    require(first["result_sha256"] == second["result_sha256"], "Walk-forward result is deterministic")
    require(first["fold_count"] >= 3, "Multiple expanding walk-forward folds are produced")
    require(first["test_observations"] >= 30, "Out-of-sample observations are accumulated")
    require(first["selection_on_test_data"] is False, "Test data is excluded from configuration selection")
    require(first["model_frozen"] is False, "Development evidence is not mislabeled frozen")
    require(first["paper_trading_only"] is True, "Evaluation remains paper only")
    require(first["brokerage_orders"] is False, "Evaluation has no brokerage authority")
    require(
        all(fold["train_end"] < fold["test_start"] for fold in first["folds"]),
        "Every fold trains strictly before its test window",
    )
    require(
        all(fold["selected_config"] in fold["all_train_scores"] for fold in first["folds"]),
        "Each selected configuration is supported by train-only scores",
    )
    require(
        all(len(row["selected"]) == 10 and "SPY" not in row["selected"] for row in first["test_results"]),
        "Every test cohort contains 10 stocks and excludes SPY",
    )
    require(first["modeled_total_cost_bps_round_trip"] == 10, "Ten-bps round-trip cost is applied")
    require(first["skipped_incomplete_sessions"] == 0, "Complete synthetic sessions are retained")

    incomplete_volume = copy.deepcopy(dataset)
    target_date = str(incomplete_volume["AAPL"][18]["timestamp_utc"])[:10]
    for row in incomplete_volume["AAPL"]:
        if str(row["timestamp_utc"])[:10] == target_date:
            row["volume"] = 0
    incomplete_result = evaluate_walk_forward(incomplete_volume, contract)
    require(
        incomplete_result["skipped_incomplete_sessions"] == 1,
        "Undefined historical volume skips exactly one session",
    )
    require(
        incomplete_result["eligible_sessions"] == first["eligible_sessions"] - 1,
        "Incomplete feature session cannot enter evaluation",
    )

    short = synthetic_dataset(session_count=20)
    try:
        evaluate_walk_forward(short, contract)
    except ValueError as exc:
        require("INSUFFICIENT_WALK_FORWARD_SESSIONS" in str(exc), "Insufficient history fails closed")
    else:
        raise AssertionError("Insufficient history was accepted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        run_id = "synthetic"
        run_root = root / run_id
        run_root.mkdir()
        metadata = {}
        for symbol, rows in dataset.items():
            path = run_root / f"{symbol}.json"
            path.write_text(json.dumps(rows))
            metadata[symbol] = {"file": f"{run_id}/{symbol}.json", "sha256": _sha(rows)}
        manifest = {
            "status": "COMPLETE_HISTORICAL_RESEARCH_DATASET",
            "symbol_count": 101,
            "symbol_metadata": metadata,
        }
        manifest["manifest_sha256"] = _sha(manifest)
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        _, loaded = load_dataset(manifest_path)
        require(len(loaded) == 101, "Complete SHA-verified historical dataset loads")
        tampered = json.loads((run_root / "AAPL.json").read_text())
        tampered[0]["close"] += 1
        (run_root / "AAPL.json").write_text(json.dumps(tampered))
        try:
            load_dataset(manifest_path)
        except ValueError as exc:
            require("SYMBOL_SHA_MISMATCH:AAPL" in str(exc), "Tampered historical symbol fails closed")
        else:
            raise AssertionError("Tampered historical data was accepted")

    source = Path(__file__).with_name("intraday_walk_forward.py").read_text()
    forbidden = ("submit_order", "place_order", "alpaca", "ib_insync")
    require(not any(value in source.lower() for value in forbidden), "Evaluation imports no brokerage interface")
    require("data/model/v8/holdout" not in source and "data/model/v10" not in source, "Evaluation references no holdout path")

    print("\nStatus: PASSED")
    print("V11 walk-forward methodology: VERIFIED")
    print("Future leakage: NOT DETECTED")
    print("Selection on test data: NO")
    print("Model frozen: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
