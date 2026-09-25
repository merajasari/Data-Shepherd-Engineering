"""Phase 1 for the preregistered Autonomous ML V1/V2/V3 prospective comparison.

This phase validates the already-observed development evidence and seals the
October 1+ comparison protocol. It reads no prospective observations and
calculates no prospective performance.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

from ml.stock_eagle_250.phase2 import (
    CONTRACT_PATH as SOURCE_CONTRACT_PATH,
    MANIFEST_PATH as SOURCE_MANIFEST_PATH,
    PANEL_PATH as SOURCE_PANEL_PATH,
    RANK_FEATURE_COLUMNS,
    TARGET_COLUMN,
)
from ml.stock_eagle_250_autonomous_ml_prospective_v1 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)


PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
OUTPUT_ROOT = Path(
    "data/model/stock_eagle_250_autonomous_ml_prospective_v1/phase1"
)
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

CANDIDATE_ROOTS = {
    "autonomous_ml_v1": Path(
        "data/model/stock_eagle_250_autonomous_ml_v1/phase2"
    ),
    "autonomous_ml_v2": Path(
        "data/model/stock_eagle_250_autonomous_ml_v2/phase2"
    ),
    "autonomous_ml_v3": Path(
        "data/model/stock_eagle_250_autonomous_ml_v3/phase2"
    ),
}

EXPECTED_CANDIDATE_ORDER = (
    "autonomous_ml_v1",
    "autonomous_ml_v2",
    "autonomous_ml_v3",
)
EXPECTED_PROSPECTIVE_START = "2026-10-01T00:00:00+00:00"
EXPECTED_GUARD_START = "2026-09-23T00:00:00+00:00"
EXPECTED_DEVELOPMENT_END = "2026-09-15T00:00:00+00:00"
EXPECTED_MAX_ENDPOINT = "2026-09-22T00:00:00+00:00"

REQUIRED_SOURCE_COLUMNS = {
    "timestamp_utc",
    "symbol",
    "sector",
    "model_eligible",
    "forward_stock_return",
    "forward_spy_return",
    "target_endpoint_utc_5d",
    TARGET_COLUMN,
    *RANK_FEATURE_COLUMNS,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = Path(path).read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def _isclose(left, right, atol=1e-12) -> bool:
    try:
        return math.isclose(
            float(left),
            float(right),
            rel_tol=0.0,
            abs_tol=atol,
        )
    except (TypeError, ValueError):
        return False


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise RuntimeError(
                f"Prospective comparison identity mismatch: {key}"
            )

    if contract.get("created_before_prospective_results") is not True:
        raise RuntimeError(
            "Prospective comparison was not preregistered before results"
        )

    candidates = contract.get("candidate_snapshots") or []
    ids = tuple(row.get("candidate_id") for row in candidates)
    if ids != EXPECTED_CANDIDATE_ORDER:
        raise RuntimeError("Prospective candidate order changed")

    snapshot = contract["snapshot_build"]
    if snapshot.get("prospective_start_utc") != EXPECTED_PROSPECTIVE_START:
        raise RuntimeError("Prospective start boundary changed")
    if snapshot.get("sealed_guard_band_start_utc") != EXPECTED_GUARD_START:
        raise RuntimeError("Guard-band start changed")
    if snapshot.get("development_decision_end_utc") != EXPECTED_DEVELOPMENT_END:
        raise RuntimeError("Development decision end changed")
    if snapshot.get("maximum_training_target_endpoint_utc") != EXPECTED_MAX_ENDPOINT:
        raise RuntimeError("Maximum training target endpoint changed")

    for key in (
        "candidate_search",
        "hyperparameter_search",
        "feature_search",
        "threshold_search",
        "quantile_search",
        "post_snapshot_retraining_during_evaluation",
    ):
        if snapshot.get(key) is not False:
            raise RuntimeError(
                f"Prospective snapshot search/retraining enabled: {key}"
            )

    protocol = contract["prospective_protocol"]
    if protocol.get(
        "first_eligible_decision_session_utc"
    ) != EXPECTED_PROSPECTIVE_START:
        raise RuntimeError("Prospective decision boundary changed")
    if int(
        protocol.get(
            "minimum_completed_cohorts_for_formal_review_per_candidate",
            -1,
        )
    ) != 60:
        raise RuntimeError("Formal review cohort threshold changed")
    if int(
        protocol.get(
            "minimum_complete_five_sleeve_blocks_for_formal_review",
            -1,
        )
    ) != 12:
        raise RuntimeError("Formal review block threshold changed")

    for key in (
        "automatic_winner_selection",
        "automatic_model_promotion",
        "new_architecture_from_results_before_formal_review",
        "brokerage_orders",
        "live_execution_enabled",
    ):
        if protocol.get(key) is not False:
            raise RuntimeError(
                f"Prospective authority changed: {key}"
            )

    guardrails = contract["guardrails"]
    for key in (
        "september_23_through_30_training_use",
        "september_23_through_30_evaluation_use",
        "october_1_plus_read_before_prospective_runner",
        "modify_v1",
        "modify_v2",
        "modify_v3",
        "modify_existing_forward_journals",
        "automatic_promotion",
        "real_orders",
    ):
        if guardrails.get(key) is not False:
            raise RuntimeError(f"Guardrail changed: {key}")

    return contract


def validate_bound_code(contract: dict) -> dict:
    rows = []
    for candidate in contract["candidate_snapshots"]:
        contract_path = Path(candidate["phase1_contract_path"])
        code_path = Path(candidate["phase2_code_path"])

        if not contract_path.exists():
            raise RuntimeError(
                f"Missing candidate contract: {contract_path}"
            )
        if not code_path.exists():
            raise RuntimeError(
                f"Missing candidate Phase 2 code: {code_path}"
            )

        contract_blob = git_blob_sha1(contract_path)
        code_blob = git_blob_sha1(code_path)

        if contract_blob != candidate[
            "phase1_contract_git_blob_sha1"
        ]:
            raise RuntimeError(
                f"{candidate['candidate_id']} Phase-1 contract changed"
            )
        if code_blob != candidate[
            "phase2_code_git_blob_sha1"
        ]:
            raise RuntimeError(
                f"{candidate['candidate_id']} Phase-2 code changed"
            )

        rows.append({
            "candidate_id": candidate["candidate_id"],
            "phase1_contract_git_blob_sha1": contract_blob,
            "phase2_code_git_blob_sha1": code_blob,
        })
    return {"candidate_code_bindings": rows}


def _validate_candidate_result(
    candidate: dict,
    manifest: dict,
    qualification: dict,
) -> dict:
    problems = []
    candidate_id = candidate["candidate_id"]

    if manifest.get("research_version") != candidate["research_version"]:
        problems.append("research_version")
    if manifest.get("phase") != 2:
        problems.append("phase")
    if manifest.get("fold_count") != 14:
        problems.append("fold_count")
    if manifest.get("guard_band_rows_read") != 0:
        problems.append("guard_band_rows_read")
    if manifest.get("future_rows_read") != 0:
        problems.append("future_rows_read")

    if qualification.get("status") != candidate[
        "development_status_required"
    ]:
        problems.append("development_status")
    if int(qualification.get("gates_passed", -1)) != int(
        candidate["development_gates_passed_required"]
    ):
        problems.append("gates_passed")
    if int(qualification.get("gates_total", -1)) != int(
        candidate["development_gates_total_required"]
    ):
        problems.append("gates_total")

    actual_failed = sorted(
        qualification.get("failed_gates") or []
    )
    required_failed = sorted(
        candidate["development_failed_gates_required"]
    )
    if actual_failed != required_failed:
        problems.append("failed_gates")

    if qualification.get(
        "autonomous_paper_runtime_enabled"
    ) is not False:
        problems.append("autonomous_paper_runtime_enabled")
    if qualification.get("model_frozen") is not False:
        problems.append("model_frozen")

    safety = manifest.get("safety") or {}
    if safety.get("live_execution_enabled") is not False:
        problems.append("live_execution_enabled")

    summary = manifest.get("summary") or {}
    if candidate_id == "autonomous_ml_v1":
        if not _isclose(
            summary.get("worst_fold_maximum_drawdown"),
            -0.43458294422261523,
        ):
            problems.append("observed_v1_drawdown")
    elif candidate_id == "autonomous_ml_v2":
        if not _isclose(
            summary.get("positive_excess_vs_spy_fold_fraction"),
            0.5714285714285714,
        ):
            problems.append("observed_v2_spy_fraction")
        if not _isclose(
            summary.get("worst_fold_maximum_drawdown"),
            -0.27953452703039583,
        ):
            problems.append("observed_v2_drawdown")
    elif candidate_id == "autonomous_ml_v3":
        if not _isclose(
            summary.get("positive_excess_vs_spy_fold_fraction"),
            0.5,
        ):
            problems.append("observed_v3_spy_fraction")
        if not _isclose(
            summary.get("median_fold_excess_vs_spy"),
            -0.006803736486117984,
        ):
            problems.append("observed_v3_median_spy_excess")
        if not _isclose(
            summary.get("worst_fold_maximum_drawdown"),
            -0.38308663952794586,
        ):
            problems.append("observed_v3_drawdown")

    if problems:
        raise RuntimeError(
            f"{candidate_id} evidence changed: "
            + ", ".join(problems)
        )

    return {
        "candidate_id": candidate_id,
        "research_version": manifest["research_version"],
        "development_status": qualification["status"],
        "gates_passed": int(qualification["gates_passed"]),
        "gates_total": int(qualification["gates_total"]),
        "failed_gates": actual_failed,
        "median_fold_net_return":
            summary.get("median_fold_net_return"),
        "median_fold_excess_vs_spy":
            summary.get("median_fold_excess_vs_spy"),
        "positive_excess_vs_spy_fold_fraction":
            summary.get("positive_excess_vs_spy_fold_fraction"),
        "worst_fold_maximum_drawdown":
            summary.get("worst_fold_maximum_drawdown"),
    }


def validate_candidate_evidence(contract: dict) -> list[dict]:
    evidence = []
    for candidate in contract["candidate_snapshots"]:
        root = CANDIDATE_ROOTS[candidate["candidate_id"]]
        manifest_path = root / "manifest.json"
        qualification_path = root / "qualification.json"

        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        qualification = json.loads(
            qualification_path.read_text(encoding="utf-8")
        )
        evidence.append(
            _validate_candidate_result(
                candidate,
                manifest,
                qualification,
            )
        )
    return evidence


def validate_source() -> dict:
    source_manifest = json.loads(
        SOURCE_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    columns = set(pq.read_schema(SOURCE_PANEL_PATH).names)

    problems = []
    if int(source_manifest.get("candidate_count", -1)) != 250:
        problems.append("candidate_count")
    if int(source_manifest.get("fold_count", -1)) != 14:
        problems.append("fold_count")
    if int(source_manifest.get("future_holdout_rows_read", -1)) != 0:
        problems.append("future_holdout_rows_read")
    if source_manifest.get("development_end_utc") != EXPECTED_DEVELOPMENT_END:
        problems.append("development_end_utc")
    if source_manifest.get(
        "maximum_development_target_endpoint_utc"
    ) != EXPECTED_MAX_ENDPOINT:
        problems.append("maximum_development_target_endpoint_utc")
    if source_manifest.get("future_holdout_start_utc") != EXPECTED_GUARD_START:
        problems.append("future_holdout_start_utc")
    if source_manifest.get("contract_sha256") != sha256(
        SOURCE_CONTRACT_PATH
    ):
        problems.append("source_contract_sha256")

    missing = sorted(REQUIRED_SOURCE_COLUMNS - columns)
    if missing:
        problems.append("missing_columns:" + ",".join(missing))

    if problems:
        raise RuntimeError(
            "Prospective comparison source validation failed: "
            + "; ".join(problems)
        )

    return {
        "candidate_count": 250,
        "fold_count": 14,
        "source_rows": int(source_manifest["source_rows"]),
        "model_eligible_rows": int(
            source_manifest["model_eligible_rows"]
        ),
        "development_start_utc":
            source_manifest["development_start_utc"],
        "development_end_utc":
            source_manifest["development_end_utc"],
        "maximum_development_target_endpoint_utc":
            source_manifest[
                "maximum_development_target_endpoint_utc"
            ],
        "sealed_guard_band_start_utc":
            source_manifest["future_holdout_start_utc"],
        "prospective_start_utc": EXPECTED_PROSPECTIVE_START,
    }


def run(output_root: Path = OUTPUT_ROOT) -> dict:
    contract = load_contract()
    code_bindings = validate_bound_code(contract)
    development_evidence = validate_candidate_evidence(contract)
    source = validate_source()

    payload = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage":
            "preregistered_v1_v2_v3_prospective_comparison",
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
        "contract_sha256": sha256(CONTRACT_PATH),
        "candidate_count": len(development_evidence),
        "candidates": development_evidence,
        **code_bindings,
        "source": source,
        "sealed_guard_band_read": False,
        "prospective_rows_read": 0,
        "prospective_performance_calculated": False,
        "snapshots_built": False,
        "formal_review_minimum_completed_cohorts": 60,
        "formal_review_minimum_complete_blocks": 12,
        "automatic_winner_selection": False,
        "automatic_model_promotion": False,
        "new_architecture_before_formal_review": False,
        "brokerage_orders": False,
        "live_execution_enabled": False,
        "next_step": (
            "Build and hash one fixed pre-boundary snapshot for each "
            "already-defined V1/V2/V3 architecture using only authorized "
            "development rows. Do not read the Sep 23-30 guard band or any "
            "Oct 1+ prospective observation."
        ),
    }

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
