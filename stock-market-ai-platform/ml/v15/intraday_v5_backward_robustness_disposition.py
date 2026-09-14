"""Audit receipt for the failed locked V5 backward-robustness study."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ml.v15.intraday_logistic import canonical_sha256


DISPOSITION_PATH = Path(__file__).with_name(
    "intraday_v5_backward_robustness_disposition.json"
)
RESULT_PATH = Path(__file__).resolve().parents[2] / (
    "data/research/v15/v5_backward_robustness/latest_results.json"
)
EXPECTED_DISPOSITION_SHA256 = (
    "279211f35099b778ab1d3b927e8d27a3ce859bb94bb66aabbdc8a6a5f9f4cd33"
)


def load_disposition(path: Path = DISPOSITION_PATH) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V15_V5_ROBUSTNESS_DISPOSITION_MUST_BE_OBJECT")
    unsigned = dict(payload)
    embedded = unsigned.pop("disposition_sha256", None)
    actual = canonical_sha256(unsigned)
    if embedded != actual or actual != EXPECTED_DISPOSITION_SHA256:
        raise ValueError("V15_V5_ROBUSTNESS_DISPOSITION_SHA_MISMATCH")
    if payload.get("decision") != "BACKWARD_ROBUSTNESS_FAILED_DO_NOT_ADVANCE":
        raise ValueError("V15_V5_ROBUSTNESS_DISPOSITION_DECISION_INVALID")
    diagnosis = payload.get("diagnosis", {})
    if diagnosis.get("further_historical_tuning_on_observed_windows_prohibited") is not True:
        raise ValueError("V15_V5_ROBUSTNESS_RETUNING_PROHIBITION_MISSING")
    if diagnosis.get("genuinely_prospective_evidence_required") is not True:
        raise ValueError("V15_V5_ROBUSTNESS_PROSPECTIVE_BOUNDARY_MISSING")
    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        raise ValueError("V15_V5_ROBUSTNESS_AUTHORITY_INVALID")
    required_false = (
        "model_frozen",
        "paper_forward_allowed",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "scheduler_installation_allowed",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        raise ValueError("V15_V5_ROBUSTNESS_AUTHORITY_INVALID")
    return payload


def validate_result_artifact(
    result_path: Path = RESULT_PATH,
    disposition: Mapping[str, object] | None = None,
) -> dict[str, object]:
    receipt = load_disposition() if disposition is None else dict(disposition)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    unsigned = dict(result)
    embedded = unsigned.pop("result_sha256", None)
    if embedded != canonical_sha256(unsigned) or embedded != receipt["observed_result_sha256"]:
        raise ValueError("V15_V5_ROBUSTNESS_RESULT_SHA_MISMATCH")
    if result.get("study_contract_sha256") != receipt["study_contract_sha256"]:
        raise ValueError("V15_V5_ROBUSTNESS_STUDY_CONTRACT_MISMATCH")
    if result.get("model_contract_sha256") != receipt["model_contract_sha256"]:
        raise ValueError("V15_V5_ROBUSTNESS_MODEL_CONTRACT_MISMATCH")
    if result.get("source_manifest_sha256") != receipt["source_manifest_sha256"]:
        raise ValueError("V15_V5_ROBUSTNESS_SOURCE_MISMATCH")
    evidence = receipt["evidence"]
    for name in (
        "status",
        "eligible_sessions",
        "fold_count",
        "test_sessions",
        "completed_trades",
        "cash_sessions",
        "trade_rate",
        "profitable_trade_rate",
        "positive_fold_share",
        "v15_net_total_return",
        "matched_v11_net_total_return",
        "matched_v14_context_net_total_return",
        "matched_spy_total_return",
        "always_on_spy_total_return",
        "v15_relative_to_matched_v11",
        "v15_relative_to_matched_v14_context",
        "v15_relative_to_matched_spy",
        "v15_relative_to_always_on_spy",
        "v15_max_drawdown",
        "worst_trade_return",
    ):
        if result.get(name) != evidence[name]:
            raise ValueError(f"V15_V5_ROBUSTNESS_RESULT_METRIC_MISMATCH:{name}")
    if result.get("gate_results") != receipt["gate_results"]:
        raise ValueError("V15_V5_ROBUSTNESS_RESULT_GATES_MISMATCH")
    return result


def main() -> None:
    receipt = load_disposition()
    validate_result_artifact()
    evidence = receipt["evidence"]
    print("V15 V5 BACKWARD-ROBUSTNESS DISPOSITION")
    print("=" * 76)
    print(f"Decision: {receipt['decision']}")
    print(f"Observed result SHA-256: {receipt['observed_result_sha256']}")
    print(f"Primary diagnosis: {receipt['diagnosis']['primary']}")
    print(
        f"Return: {evidence['v15_net_total_return']:+.2%} | "
        f"trades: {evidence['completed_trades']} | "
        f"drawdown: {evidence['v15_max_drawdown']:.2%}"
    )
    print("Passed gates: 10 / 12")
    print("Failed gates: DRAWDOWN_CONTROL, FOLD_STABILITY")
    print("Historical signal persistence: OBSERVED")
    print("Robustness qualification: FAILED")
    print("Paper forward allowed: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
