"""Identity and audit checks for the rejected V15 V6 development result."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from ml.v15.intraday_logistic import canonical_sha256


DISPOSITION_PATH = Path(__file__).with_name(
    "intraday_stability_first_v6_disposition.json"
)
RESULT_PATH = Path(__file__).resolve().parents[2] / (
    "data/research/v15/intraday_stability_first_v6/latest_results.json"
)
EXPECTED_DISPOSITION_SHA256 = (
    "5f5ed01dff080b13dc56feea8ec0bad531a5fa72d1d7c2bfbd52171fbb3b2091"
)


def load_disposition(path: Path = DISPOSITION_PATH) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V15_V6_DISPOSITION_MUST_BE_OBJECT")
    unsigned = dict(payload)
    embedded = unsigned.pop("disposition_sha256", None)
    actual = canonical_sha256(unsigned)
    if embedded != actual or actual != EXPECTED_DISPOSITION_SHA256:
        raise ValueError("V15_V6_DISPOSITION_SHA_MISMATCH")
    if payload.get("decision") != "REJECTED_DO_NOT_ADVANCE_TO_PAPER_FORWARD":
        raise ValueError("V15_V6_DISPOSITION_DECISION_INVALID")
    diagnosis = payload.get("diagnosis", {})
    if diagnosis.get("further_tuning_on_same_outer_test_window_prohibited") is not True:
        raise ValueError("V15_V6_SAME_WINDOW_TUNING_PROHIBITION_MISSING")
    if diagnosis.get("development_gate_weakening_prohibited") is not True:
        raise ValueError("V15_V6_GATE_WEAKENING_PROHIBITION_MISSING")
    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        raise ValueError("V15_V6_DISPOSITION_AUTHORITY_INVALID")
    required_false = (
        "model_frozen",
        "scheduler_installation_allowed",
        "paper_forward_allowed",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        raise ValueError("V15_V6_DISPOSITION_AUTHORITY_INVALID")
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
        raise ValueError("V15_V6_RESULT_SHA_MISMATCH")
    if result.get("contract_sha256") != receipt["contract_sha256"]:
        raise ValueError("V15_V6_RESULT_CONTRACT_MISMATCH")
    if result.get("source_manifest_sha256") != receipt["source_manifest_sha256"]:
        raise ValueError("V15_V6_RESULT_SOURCE_MISMATCH")
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
        "v15_max_drawdown",
        "worst_trade_return",
        "protective_stop_triggered_positions",
    ):
        if result.get(name) != evidence[name]:
            raise ValueError(f"V15_V6_RESULT_METRIC_MISMATCH:{name}")
    if result.get("gate_results") != receipt["gate_results"]:
        raise ValueError("V15_V6_RESULT_GATES_MISMATCH")
    return result


def main() -> None:
    receipt = load_disposition()
    validate_result_artifact()
    print("V15 V6 DEVELOPMENT DISPOSITION")
    print("=" * 72)
    print(f"Decision: {receipt['decision']}")
    print(f"Observed result SHA-256: {receipt['observed_result_sha256']}")
    print(f"Primary diagnosis: {receipt['diagnosis']['primary']}")
    print("Observed result: +11.14% net | 53 trades | 9.75% drawdown")
    print("Passed gates: 11 / 12 | failed gate: FOLD_STABILITY")
    print("Further same-window tuning: PROHIBITED")
    print("Paper forward allowed: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
