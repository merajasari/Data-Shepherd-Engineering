"""Deterministic regression checks for V15 V6 stability-first research."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from ml.v15.intraday_risk_managed_v5_disposition import (
    EXPECTED_DISPOSITION_SHA256 as EXPECTED_V5_DISPOSITION_SHA256,
    load_disposition as load_v5_disposition,
    validate_result_artifact as validate_v5_result_artifact,
)
from ml.v15.intraday_hybrid_v2_regression import _daily_frames
from ml.v15.intraday_selective_v3_regression import _intraday_dataset
from ml.v15.intraday_stability_first_v6 import (
    EXPECTED_CONTRACT_SHA256,
    _gap_aware_stop_return,
    build_risk_managed_examples,
    canonical_sha256,
    evaluate_walk_forward,
    load_contract,
)


def _test_contract(contract: dict[str, object]) -> dict[str, object]:
    value = deepcopy(contract)
    value["data"]["minimum_eligible_intraday_sessions"] = 60
    value["model"]["minimum_outer_training_sessions"] = 40
    value["model"]["minimum_training_rows"] = 2000
    value["nested_selection"]["inner_validation_sessions"] = 10
    value["nested_selection"]["minimum_inner_training_sessions"] = 20
    value["nested_selection"]["minimum_inner_trades"] = 2
    value["evaluation"]["test_sessions_per_fold"] = 10
    value["evaluation"]["minimum_final_test_sessions"] = 10
    value["evaluation"]["gates"]["completed_trades_at_least"] = 2
    return value


def _bars() -> list[dict[str, float]]:
    return [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        }
        for _ in range(30)
    ]


def main() -> None:
    contract = load_contract()
    disposition = load_v5_disposition()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert disposition["disposition_sha256"] == EXPECTED_V5_DISPOSITION_SHA256
    assert disposition["observed_result_sha256"] == (
        "f758339035337ef05283199f0d5f9fd1c4abb896311a4e9e21a7dee95b7c55bb"
    )
    assert disposition["decision"] == "REJECTED_DO_NOT_ADVANCE_TO_PAPER_FORWARD"
    assert disposition["gate_results"]["drawdown_control"] is True
    assert disposition["gate_results"]["fold_stability"] is False
    assert contract["heritage"]["v5_disposition_sha256"] == (
        EXPECTED_V5_DISPOSITION_SHA256
    )
    assert contract["heritage"]["v5_results_reused_as_fresh_evidence"] is False
    print("[PASS] V5 rejection is immutable and separated from V6 development")

    with tempfile.TemporaryDirectory() as directory:
        fake = Path(directory) / "result.json"
        fake.write_text(
            json.dumps({"result_sha256": disposition["observed_result_sha256"]}),
            encoding="utf-8",
        )
        try:
            validate_v5_result_artifact(fake, disposition)
        except ValueError as exc:
            assert "V15_V5_RESULT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 V5 disposition accepted a fabricated result")
    print("[PASS] V5 result receipt detects artifact substitution")

    assert contract["risk_management"]["protective_stop_loss_fraction"] == 0.02
    assert contract["risk_management"]["stop_parameter_grid_search"] is False
    assert contract["nested_selection"]["validation_subwindow_count"] == 2
    assert contract["nested_selection"]["candidate_top_n"] == [1, 3, 5]
    assert contract["nested_selection"]["candidate_participation_quantiles"] == [
        0.5,
        0.65,
        0.8,
    ]
    assert contract["nested_selection"]["selection_objective"] == (
        "HIGHEST_WORST_VALIDATION_SUBWINDOW_RETURN"
    )
    assert contract["nested_selection"]["tie_break_order"][0] == (
        "HIGHEST_COMPOUNDED_ABSOLUTE_NET_RETURN"
    )
    print("[PASS] V6 freezes stability-first selection without changing the grid")

    normal = _bars()
    normal[7]["low"] = 97.5
    value, stopped, bar_index = _gap_aware_stop_return(
        normal,
        entry_bar_index=6,
        exit_bar_index=29,
        stop_fraction=0.02,
    )
    assert abs(value - (-0.02)) < 1e-15
    assert stopped is True and bar_index == 7

    gap = _bars()
    gap[8].update({"open": 96.5, "low": 96.0, "close": 97.0})
    value, stopped, bar_index = _gap_aware_stop_return(
        gap,
        entry_bar_index=6,
        exit_bar_index=29,
        stop_fraction=0.02,
    )
    assert abs(value - (-0.035)) < 1e-15
    assert stopped is True and bar_index == 8

    scheduled = _bars()
    scheduled[29]["close"] = 102.0
    value, stopped, bar_index = _gap_aware_stop_return(
        scheduled,
        entry_bar_index=6,
        exit_bar_index=29,
        stop_fraction=0.02,
    )
    assert abs(value - 0.02) < 1e-15
    assert stopped is False and bar_index is None
    print("[PASS] Protective stops use normal, gap-aware, and scheduled fills")

    intraday = _intraday_dataset()
    daily = _daily_frames(intraday)
    test_contract = _test_contract(contract)
    sessions, examples, audit = build_risk_managed_examples(
        intraday, daily, test_contract
    )
    assert len(sessions) == 69
    assert all(len(examples[session]) == 100 for session in sessions)
    assert all(
        "risk_managed_gross_return" in row["outcomes"]["24"]
        for row in examples[sessions[0]]
    )
    assert len(audit["daily_context_input_sha256"]) == 64
    print("[PASS] V6 preserves V5 stop paths and frozen hybrid features")

    result = evaluate_walk_forward(intraday, daily, test_contract)
    assert result["eligible_sessions"] == 69
    assert result["test_sessions"] == 29
    assert result["fold_count"] == 3
    assert result["folds"][-1]["test_sessions"] == 9
    assert result["completed_trades"] + result["cash_sessions"] == 29
    assert result["model_frozen"] is False
    assert result["paper_forward_allowed"] is False
    assert "worst_trade_control" in result["gate_results"]
    assert "protective_stop_triggered_positions" in result
    print("[PASS] V6 produces stability-first walk-forward evidence")

    for fold in result["folds"]:
        selected = fold["selected_configuration"]
        snapshot = dict(fold["model_snapshot"])
        assert snapshot["training_cutoff_session"] < selected[
            "inner_validation_start_session"
        ]
        assert selected["inner_validation_end_session"] < fold["test_start_session"]
        embedded = snapshot.pop("model_sha256")
        assert embedded == canonical_sha256(snapshot)
        for diagnostic in fold["inner_configuration_diagnostics"]:
            assert len(diagnostic["validation_subwindow_returns"]) == 2
            assert len(diagnostic["validation_subwindow_trades"]) == 2
    assert result["selection_on_outer_test_data"] is False
    print("[PASS] V6 stability selection is complete before each outer test")

    assert result["brokerage_orders"] is False
    assert all(result[f"v{version}_modified"] is False for version in (8, 10, 11, 13, 14))
    source = Path(__file__).with_name("intraday_stability_first_v6.py").read_text(
        encoding="utf-8"
    )
    assert (
        'key=lambda item: (\n'
        '                float(item["worst_validation_subwindow_return"]),\n'
        '                float(item["net_total_return"]),'
    ) in source
    assert "import requests" not in source.lower()
    assert "import subprocess" not in source.lower()
    assert "launchctl" not in source.lower()
    print("[PASS] V6 cannot schedule itself, alter existing models, or place orders")

    tampered = deepcopy(contract)
    tampered["authority"]["paper_forward_allowed"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_V6_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 V6 accepted expanded authority")
    print("[PASS] V6 contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
