"""Deterministic regression checks for the V15 V2 hybrid foundation."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from ml.v15.intraday_hybrid_v2 import (
    EXPECTED_CONTRACT_SHA256,
    HYBRID_FEATURE_NAMES,
    build_hybrid_examples,
    canonical_sha256,
    evaluate_walk_forward,
    load_contract,
)
from ml.v15.intraday_logistic_regression import _synthetic_dataset
from ml.v15.intraday_logistic_v1_disposition import (
    EXPECTED_DISPOSITION_SHA256,
    load_disposition,
    validate_result_artifact,
)


def _daily_frames(intraday: dict[str, list[dict[str, object]]]):
    final = max(pd.Timestamp(row["timestamp_utc"]) for row in intraday["SPY"])
    sessions = pd.bdate_range(end=final.normalize(), periods=190, tz="UTC")
    frames: dict[str, pd.DataFrame] = {}
    for symbol_index, symbol in enumerate(sorted(intraday)):
        signal = 0.0 if symbol == "SPY" else ((symbol_index % 20) - 9.5) / 10.0
        records = []
        for session_index, session in enumerate(sessions):
            wave = ((session_index % 9) - 4) / 100.0
            records.append(
                {
                    "timestamp_utc": session,
                    "daily_return": signal * 0.003 + wave * 0.01,
                    "return_5d": signal * 0.012 + wave * 0.02,
                    "return_20d": signal * 0.035 + wave * 0.03,
                    "price_vs_sma_20": signal * 0.025 + wave * 0.01,
                    "volatility_ratio_5_20": 1.0 + abs(signal) * 0.1 + wave,
                    "volume_ratio": 1.0 + signal * 0.05 + wave,
                    "target_up_5d": int(signal + wave > 0.0),
                }
            )
        frames[symbol] = pd.DataFrame(records).set_index("timestamp_utc")
    return frames


def _development_sized_contract(contract: dict[str, object]) -> dict[str, object]:
    value = deepcopy(contract)
    value["data"]["minimum_eligible_intraday_sessions"] = 60
    value["slow_context_model"]["minimum_training_rows"] = 5000
    value["slow_context_model"]["epochs"] = 180
    value["hybrid_model"]["minimum_training_sessions"] = 40
    value["hybrid_model"]["minimum_training_rows"] = 4000
    value["hybrid_model"]["epochs"] = 240
    value["evaluation"]["test_sessions_per_fold"] = 10
    value["evaluation"]["minimum_final_test_sessions"] = 10
    return value


def main() -> None:
    contract = load_contract()
    disposition = load_disposition()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert disposition["disposition_sha256"] == EXPECTED_DISPOSITION_SHA256
    assert disposition["decision"] == "REJECTED_DO_NOT_ADVANCE_TO_PAPER_FORWARD"
    assert contract["heritage"]["v1_disposition_sha256"] == EXPECTED_DISPOSITION_SHA256
    assert contract["heritage"]["v1_results_reused_as_fresh_evidence"] is False
    print("[PASS] V1 failure is immutable and cannot become fresh V2 evidence")

    with tempfile.TemporaryDirectory() as directory:
        result_path = Path(directory) / "result.json"
        result_fixture = {
            "contract_sha256": "contract",
            "source_manifest_sha256": "source",
            "metric": -1.0,
        }
        result_fixture["result_sha256"] = canonical_sha256(result_fixture)
        result_path.write_text(json.dumps(result_fixture), encoding="utf-8")
        receipt_fixture = {
            "contract_sha256": "contract",
            "observed_result_sha256": result_fixture["result_sha256"],
            "evidence": {"metric": -1.0},
        }
        validate_result_artifact(result_path, receipt_fixture)
        result_fixture["metric"] = 1.0
        result_path.write_text(json.dumps(result_fixture), encoding="utf-8")
        try:
            validate_result_artifact(result_path, receipt_fixture)
        except ValueError as exc:
            assert str(exc) == "V15_V1_RESULT_SHA_MISMATCH"
        else:
            raise AssertionError("V15 V1 disposition accepted a changed result")
    print("[PASS] V1 result receipt detects artifact tampering")

    assert contract["objective"]["primary"] == (
        "MAXIMIZE_COMPOUNDED_NET_RETURN_AFTER_MODELED_COST"
    )
    assert contract["data"]["minimum_eligible_intraday_sessions"] == 252
    assert contract["data"]["current_session_daily_close_prohibited"] is True
    assert contract["evaluation"]["fresh_paper_boundary_required_after_development"] is True
    print("[PASS] V2 freezes the profit objective, history minimum, and fresh boundary")

    intraday = _synthetic_dataset(session_count=66)
    try:
        evaluate_walk_forward(intraday, {}, contract)
    except ValueError as exc:
        assert str(exc) == "V15_V2_INSUFFICIENT_ELIGIBLE_SESSIONS:65<252"
    else:
        raise AssertionError("V15 V2 accepted insufficient intraday history")
    print("[PASS] Insufficient intraday history fails before daily-model fitting")

    daily = _daily_frames(intraday)
    test_contract = _development_sized_contract(contract)
    sessions, examples, audit = build_hybrid_examples(
        intraday, daily, test_contract
    )
    assert len(sessions) == 65
    assert all(len(examples[session]) == 100 for session in sessions)
    assert all(
        len(row["features"]) == len(HYBRID_FEATURE_NAMES)
        for row in examples[sessions[0]]
    )
    assert all(
        row["daily_context_session"] < row["session"]
        for session in sessions
        for row in examples[session]
    )
    assert len(audit["slow_context_model_sha256"]) == 64
    assert len(audit["daily_context_input_sha256"]) == 64
    print("[PASS] Prior-close V14 context joins V11 completed bars without leakage")

    protected_session = sessions[-3]
    protected_symbol = "S000"
    before = next(
        row["features"]
        for row in examples[protected_session]
        if row["symbol"] == protected_symbol
    )
    changed = {symbol: frame.copy(deep=True) for symbol, frame in daily.items()}
    current_index = next(
        index
        for index in changed[protected_symbol].index
        if pd.Timestamp(index).date().isoformat() == protected_session
    )
    changed[protected_symbol].loc[current_index, "return_20d"] = 9999.0
    _, changed_examples, _ = build_hybrid_examples(
        intraday, changed, test_contract
    )
    after = next(
        row["features"]
        for row in changed_examples[protected_session]
        if row["symbol"] == protected_symbol
    )
    assert np.allclose(before, after)
    print("[PASS] Current-session daily data cannot influence the 10:00 decision")

    result = evaluate_walk_forward(intraday, daily, test_contract)
    assert result["test_sessions"] == 25
    assert result["fold_count"] == 3
    assert result["folds"][-1]["test_sessions"] == 5
    assert result["model_frozen"] is False
    assert result["paper_forward_allowed"] is False
    assert result["fresh_paper_boundary_required"] is True
    assert set(result["gate_results"]) == {
        "positive_net_return",
        "positive_relative_to_v11",
        "positive_relative_to_v14_context",
        "positive_relative_to_spy",
        "v11_win_rate",
        "spy_win_rate",
        "fold_stability",
        "drawdown_control",
    }
    for fold in result["folds"]:
        assert fold["training_cutoff_session"] < fold["test_start_session"]
        assert fold["model_sha256"] == canonical_sha256(fold["model_snapshot"])
    print("[PASS] Hybrid walk-forward snapshots and three controls are consistent")

    assert result["brokerage_orders"] is False
    assert all(result[f"v{version}_modified"] is False for version in (8, 10, 11, 13, 14))
    source = Path(__file__).with_name("intraday_hybrid_v2.py").read_text(encoding="utf-8")
    assert "alpaca" not in source.lower()
    assert "launchctl" not in source.lower()
    assert "import subprocess" not in source.lower()
    assert "import requests" not in source.lower()
    print("[PASS] V2 cannot install a scheduler, alter existing models, or place orders")

    tampered = deepcopy(contract)
    tampered["authority"]["paper_forward_allowed"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_V2_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 V2 accepted expanded authority")
    print("[PASS] V2 contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
