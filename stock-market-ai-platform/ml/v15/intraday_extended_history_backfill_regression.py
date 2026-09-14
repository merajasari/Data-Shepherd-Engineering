"""Regression checks for the isolated V15 extended-history boundary."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile

from ml.v15.intraday_extended_history_backfill import (
    EXPECTED_CONTRACT_SHA256,
    OUTPUT_ROOT,
    V11_LATEST_MANIFEST,
    canonical_sha256,
    load_contract,
)


def main() -> None:
    contract = load_contract()
    assert canonical_sha256(contract) == EXPECTED_CONTRACT_SHA256
    assert contract["boundary"]["end_date"] < (
        contract["boundary"]["previously_observed_v15_window_starts"]
    )
    assert contract["boundary"][
        "overlaps_v15_v1_through_v6_evaluation_window"
    ] is False
    print("[PASS] Extended history ends before every observed V15 evaluation session")

    assert str(OUTPUT_ROOT).endswith(
        "data/research/v15/extended_intraday_backfills"
    )
    assert str(V11_LATEST_MANIFEST).endswith(
        "data/research/v11/intraday/backfills/latest_complete_manifest.json"
    )
    assert contract["storage"][
        "v11_latest_manifest_must_remain_byte_identical"
    ] is True
    print("[PASS] V15 acquisition is isolated from the immutable V11 manifest")

    assert contract["purpose"]["use"] == "BACKWARD_ROBUSTNESS_ONLY"
    assert contract["purpose"]["fresh_forward_evidence"] is False
    assert contract["purpose"]["model_selection_allowed"] is False
    assert contract["purpose"]["gate_changes_allowed"] is False
    print("[PASS] New history cannot be labeled as fresh evidence or tune the model")

    source = Path(__file__).with_name(
        "intraday_extended_history_backfill.py"
    ).read_text(encoding="utf-8")
    assert "output_root=OUTPUT_ROOT" in source
    assert "before != after" in source
    assert "intraday_risk_managed_v5" not in source
    assert "evaluate_walk_forward" not in source
    assert "launchctl" not in source.lower()
    print("[PASS] Acquisition cannot execute V15 or install a scheduler")

    tampered = deepcopy(contract)
    tampered["authority"]["model_execution_allowed"] = True
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "contract.json"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            load_contract(path)
        except ValueError as exc:
            assert "V15_EXTENDED_HISTORY_CONTRACT_SHA_MISMATCH" in str(exc)
        else:
            raise AssertionError("Extended-history contract accepted model authority")
    print("[PASS] Contract validation fails closed on authority tampering")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
