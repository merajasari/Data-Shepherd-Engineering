"""Regression checks for the locked V5 backward-robustness study."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from ml.v15.intraday_extended_history_backfill import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_HISTORY_CONTRACT_SHA256,
    canonical_sha256,
    load_contract as load_history_contract,
)
from ml.v15.intraday_v5_backward_robustness import (
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)
from ml.v15.intraday_risk_managed_v5 import load_contract as load_v5_contract
from ml.v15.intraday_risk_managed_v5_disposition import load_disposition


def main() -> None:
    study = load_contract()
    history = load_history_contract()
    v5 = load_v5_contract()
    disposition = load_disposition()

    assert canonical_sha256(study) == EXPECTED_CONTRACT_SHA256
    assert canonical_sha256(history) == EXPECTED_HISTORY_CONTRACT_SHA256
    assert study["evidence_boundary"]["history_contract_sha256"] == (
        EXPECTED_HISTORY_CONTRACT_SHA256
    )
    print("[PASS] Robustness study is bound to the isolated history contract")

    assert study["candidate"]["v5_contract_sha256"] == canonical_sha256(v5)
    assert study["candidate"]["v5_disposition_sha256"] == disposition[
        "disposition_sha256"
    ]
    assert study["candidate"]["v5_observed_result_sha256"] == disposition[
        "observed_result_sha256"
    ]
    assert study["candidate"]["mechanics_modified"] is False
    assert study["candidate"]["gates_modified"] is False
    print("[PASS] Study freezes the superior V5 candidate without retuning")

    boundary = study["evidence_boundary"]
    assert boundary["required_end_date"] < "2025-06-18"
    assert boundary["previous_v15_evaluation_overlap_prohibited"] is True
    assert study["evaluation"]["results_are_backward_robustness_only"] is True
    assert study["evaluation"]["fresh_paper_boundary_still_required"] is True
    print("[PASS] Earlier history cannot be mislabeled as fresh forward evidence")

    source = Path(__file__).with_name(
        "intraday_v5_backward_robustness.py"
    ).read_text(encoding="utf-8")
    assert "evaluate_walk_forward" in source
    assert "load_v5_contract" in source
    assert "intraday_stability_first_v6" not in source
    assert "import requests" not in source.lower()
    assert "import subprocess" not in source.lower()
    assert "launchctl" not in source.lower()
    print("[PASS] Evaluator reuses V5 only and cannot schedule or trade")

    authority = study["authority"]
    assert authority["paper_forward_allowed"] is False
    assert authority["brokerage_orders"] is False
    assert authority["automatic_promotion"] is False
    assert all(
        authority[f"modify_v{version}"] is False
        for version in (8, 10, 11, 13, 14)
    )
    print("[PASS] Study has no model, promotion, or brokerage authority")

    tampered = deepcopy(study)
    tampered["candidate"]["gates_modified"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_V5_ROBUSTNESS_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("Robustness contract accepted changed gates")
    print("[PASS] Contract validation fails closed on gate tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
