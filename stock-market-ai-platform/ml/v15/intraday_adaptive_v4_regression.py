"""Deterministic regression checks for V15 V4 adaptive intraday research."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from ml.v15.intraday_hybrid_v2_regression import _daily_frames
from ml.v15.intraday_selective_v3_disposition import (
    EXPECTED_DISPOSITION_SHA256 as EXPECTED_V3_DISPOSITION_SHA256,
    load_disposition as load_v3_disposition,
    validate_result_artifact as validate_v3_result_artifact,
)
from ml.v15.intraday_selective_v3_regression import _intraday_dataset
from ml.v15.intraday_adaptive_v4 import (
    EXPECTED_CONTRACT_SHA256,
    _higher_quantile,
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


def main() -> None:
    contract = load_contract()
    disposition = load_v3_disposition()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert disposition["disposition_sha256"] == EXPECTED_V3_DISPOSITION_SHA256
    assert disposition["observed_result_sha256"] == (
        "54bf40e635f9a9285c035a43acbc3e0512e0fe4963dc9df0660809194b848341"
    )
    assert disposition["decision"] == "REJECTED_DO_NOT_ADVANCE_TO_PAPER_FORWARD"
    assert disposition["evidence"]["completed_trades"] == 1
    assert contract["heritage"]["v3_disposition_sha256"] == (
        EXPECTED_V3_DISPOSITION_SHA256
    )
    assert contract["heritage"]["v3_results_reused_as_fresh_evidence"] is False
    print("[PASS] V3 one-trade rejection is immutable and separated from V4")

    with tempfile.TemporaryDirectory() as directory:
        fake = Path(directory) / "result.json"
        fake.write_text(
            json.dumps(
                {
                    "result_sha256": disposition["observed_result_sha256"],
                    "status": disposition["evidence"]["status"],
                }
            ),
            encoding="utf-8",
        )
        try:
            validate_v3_result_artifact(fake, disposition)
        except ValueError as exc:
            assert "V15_V3_RESULT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 V3 disposition accepted a fabricated result")
    print("[PASS] V3 result receipt detects artifact substitution")

    assert contract["data"]["holding_bars"] == 24
    assert contract["nested_selection"]["candidate_top_n"] == [1, 3, 5]
    assert contract["nested_selection"]["candidate_participation_quantiles"] == [
        0.5,
        0.65,
        0.8,
    ]
    assert contract["nested_selection"]["absolute_predicted_net_return_floor"] == 0.0
    assert contract["portfolio"]["cost_applied_only_when_trade_occurs"] is True
    print("[PASS] V4 freezes 120 minutes, concentrated top-k, and adaptive quantiles")

    values = [-0.01, 0.001, 0.002, 0.004, 0.009]
    assert _higher_quantile(values, 0.5) == 0.002
    assert _higher_quantile(values, 0.65) == 0.004
    assert _higher_quantile(values, 0.8) == 0.009
    print("[PASS] Adaptive score thresholds are deterministic")

    intraday = _intraday_dataset()
    daily = _daily_frames(intraday)
    result = evaluate_walk_forward(intraday, daily, _test_contract(contract))
    assert result["eligible_sessions"] == 69
    assert result["test_sessions"] == 29
    assert result["fold_count"] == 3
    assert result["folds"][-1]["test_sessions"] == 9
    assert result["completed_trades"] + result["cash_sessions"] == 29
    assert result["model_frozen"] is False
    assert result["paper_forward_allowed"] is False
    assert "matched_spy_total_return" in result
    assert "always_on_spy_total_return" in result
    print("[PASS] V4 produces selective walk-forward evidence and dual SPY controls")

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
            assert diagnostic["top_n"] in {1, 3, 5}
            assert diagnostic["participation_quantile"] in {0.5, 0.65, 0.8}
    assert result["selection_on_outer_test_data"] is False
    print("[PASS] V4 calibration and configuration selection precede outer tests")

    assert result["brokerage_orders"] is False
    assert all(result[f"v{version}_modified"] is False for version in (8, 10, 11, 13, 14))
    source = Path(__file__).with_name("intraday_adaptive_v4.py").read_text(
        encoding="utf-8"
    )
    assert "import requests" not in source.lower()
    assert "import subprocess" not in source.lower()
    assert "launchctl" not in source.lower()
    print("[PASS] V4 cannot schedule itself, alter existing models, or place orders")

    tampered = deepcopy(contract)
    tampered["authority"]["paper_forward_allowed"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_V4_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("V15 V4 accepted expanded authority")
    print("[PASS] V4 contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
