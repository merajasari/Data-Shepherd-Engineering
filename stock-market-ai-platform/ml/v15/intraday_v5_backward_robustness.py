"""Locked V5 evaluation on isolated pre-observation intraday history."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from ml.v14.logistic_forward import load_market as load_daily_market
from ml.v15.intraday_adaptive_v4 import _atomic_write
from ml.v15.intraday_extended_history_backfill import (
    EXPECTED_CONTRACT_SHA256 as EXPECTED_HISTORY_CONTRACT_SHA256,
    load_contract as load_history_contract,
)
from ml.v15.intraday_logistic import canonical_sha256, load_dataset
from ml.v15.intraday_risk_managed_v5 import (
    evaluate_walk_forward,
    load_contract as load_v5_contract,
)
from ml.v15.intraday_risk_managed_v5_disposition import (
    load_disposition as load_v5_disposition,
    validate_result_artifact as validate_v5_result_artifact,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name(
    "intraday_v5_backward_robustness_contract.json"
)
MANIFEST_PATH = (
    ROOT
    / "data/research/v15/extended_intraday_backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = (
    ROOT / "data/research/v15/v5_backward_robustness/latest_results.json"
)
EXPECTED_CONTRACT_SHA256 = (
    "034ca1dd6e7afe68dfd0ef1da5f16115c9b9604dd4ea7aaabd19ab1f4bc76787"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("V15_V5_ROBUSTNESS_CONTRACT_SHA_MISMATCH")
    candidate = contract.get("candidate", {})
    boundary = contract.get("evidence_boundary", {})
    evaluation = contract.get("evaluation", {})
    authority = contract.get("authority", {})
    if candidate.get("mechanics_modified") is not False:
        raise ValueError("V15_V5_ROBUSTNESS_MECHANICS_CHANGED")
    if candidate.get("gates_modified") is not False:
        raise ValueError("V15_V5_ROBUSTNESS_GATES_CHANGED")
    if boundary.get("required_start_date") != "2022-01-03":
        raise ValueError("V15_V5_ROBUSTNESS_START_INVALID")
    if boundary.get("required_end_date") != "2025-06-17":
        raise ValueError("V15_V5_ROBUSTNESS_END_INVALID")
    if boundary.get("previous_v15_evaluation_overlap_prohibited") is not True:
        raise ValueError("V15_V5_ROBUSTNESS_OVERLAP_BOUNDARY_MISSING")
    if evaluation.get("results_are_backward_robustness_only") is not True:
        raise ValueError("V15_V5_ROBUSTNESS_CLASSIFICATION_INVALID")
    if evaluation.get("fresh_paper_boundary_still_required") is not True:
        raise ValueError("V15_V5_ROBUSTNESS_FRESH_BOUNDARY_MISSING")
    if evaluation.get("success_requires_all_original_v5_gates") is not True:
        raise ValueError("V15_V5_ROBUSTNESS_GATE_WEAKENING_INVALID")
    required_false = (
        "model_frozen",
        "paper_forward_allowed",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "scheduler_installation_allowed",
        "dashboard_active_model_label_allowed",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        raise ValueError("V15_V5_ROBUSTNESS_AUTHORITY_INVALID")
    return contract


def run(
    *,
    manifest_path: Path = MANIFEST_PATH,
    output_path: Path = OUTPUT_PATH,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    study = load_contract()
    history_contract = load_history_contract()
    if canonical_sha256(history_contract) != study["evidence_boundary"][
        "history_contract_sha256"
    ]:
        raise ValueError("V15_V5_ROBUSTNESS_HISTORY_CONTRACT_MISMATCH")

    v5_contract = load_v5_contract()
    disposition = load_v5_disposition()
    validate_v5_result_artifact()
    if canonical_sha256(v5_contract) != study["candidate"]["v5_contract_sha256"]:
        raise ValueError("V15_V5_ROBUSTNESS_V5_CONTRACT_MISMATCH")
    if disposition["disposition_sha256"] != study["candidate"][
        "v5_disposition_sha256"
    ]:
        raise ValueError("V15_V5_ROBUSTNESS_V5_DISPOSITION_MISMATCH")
    if disposition["observed_result_sha256"] != study["candidate"][
        "v5_observed_result_sha256"
    ]:
        raise ValueError("V15_V5_ROBUSTNESS_V5_RESULT_MISMATCH")

    if progress:
        progress("Loading isolated pre-window intraday manifest...")
    manifest, intraday = load_dataset(manifest_path)
    boundary = study["evidence_boundary"]
    if manifest.get("start_date") != boundary["required_start_date"]:
        raise ValueError("V15_V5_ROBUSTNESS_MANIFEST_START_MISMATCH")
    if manifest.get("end_date") != boundary["required_end_date"]:
        raise ValueError("V15_V5_ROBUSTNESS_MANIFEST_END_MISMATCH")
    if int(manifest.get("common_session_count", 0)) < int(
        boundary["minimum_common_sessions"]
    ):
        raise ValueError("V15_V5_ROBUSTNESS_HISTORY_INSUFFICIENT")
    if str(manifest.get("last_common_session")) >= "2025-06-18":
        raise ValueError("V15_V5_ROBUSTNESS_PRIOR_WINDOW_OVERLAP")

    if progress:
        progress("Loading synchronized prior-close V14 daily context...")
    symbols, daily_frames, _, _ = load_daily_market()
    if sorted(symbols) != sorted(symbol for symbol in intraday if symbol != "SPY"):
        raise ValueError("V15_V5_ROBUSTNESS_V14_UNIVERSE_MISMATCH")

    if progress:
        progress("Evaluating unchanged V5 mechanics on the locked earlier window...")
    result = evaluate_walk_forward(
        intraday, daily_frames, v5_contract, progress=progress
    )
    passed = bool(result["development_gates_passed"])
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    unsigned.update(
        {
            "study_contract_id": study["contract_id"],
            "study_contract_sha256": canonical_sha256(study),
            "model_contract_sha256": canonical_sha256(v5_contract),
            "source_manifest_sha256": manifest["manifest_sha256"],
            "v5_disposition_sha256": disposition["disposition_sha256"],
            "classification": study["classification"],
            "status": (
                "V15_V5_BACKWARD_ROBUSTNESS_GATES_PASSED"
                if passed
                else "V15_V5_BACKWARD_ROBUSTNESS_GATES_FAILED"
            ),
            "fresh_forward_evidence": False,
            "paper_forward_allowed": False,
            "automatic_advancement": False,
        }
    )
    unsigned["result_sha256"] = canonical_sha256(unsigned)
    _atomic_write(output_path, unsigned)
    return unsigned


def main() -> None:
    print("V15 V5 LOCKED PRE-WINDOW BACKWARD ROBUSTNESS")
    print("=" * 80)
    try:
        result = run(progress=lambda message: print(message, flush=True))
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Fresh forward evidence: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result['status']}")
    print(f"Eligible sessions: {result['eligible_sessions']}")
    print(f"Walk-forward folds: {result['fold_count']}")
    print(f"Out-of-sample sessions: {result['test_sessions']}")
    print(f"Trades: {result['completed_trades']}")
    print(f"V15 V5 net return: {result['v15_net_total_return']:+.2%}")
    print(f"Positive fold share: {result['positive_fold_share']:.1%}")
    print(f"Maximum drawdown: {result['v15_max_drawdown']:.2%}")
    print(f"Worst portfolio trade: {result['worst_trade_return']:+.2%}")
    print(
        f"Original V5 gates: {'PASS' if result['development_gates_passed'] else 'FAIL'}"
    )
    print(f"Result SHA-256: {result['result_sha256']}")
    print("Classification: BACKWARD ROBUSTNESS ONLY")
    print("Fresh forward evidence: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
