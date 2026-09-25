"""Build fixed pre-boundary snapshots for the V1/V2/V3 prospective comparison.

This phase fits one final snapshot per already-defined Autonomous ML
architecture using only the authorized development panel. It does not read the
Sep 23-30 guard band or any Oct 1+ prospective observation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import pickle
from pathlib import Path

import pandas as pd

from ml.stock_eagle_250.phase2 import (
    ENDPOINT_COLUMN,
    PANEL_PATH,
)
from ml.stock_eagle_250.phase3 import build_model_frame
from ml.stock_eagle_250_autonomous_ml_prospective_v1 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)
from ml.stock_eagle_250_autonomous_ml_prospective_v1.phase1 import (
    CONTRACT_PATH,
    EXPECTED_CANDIDATE_ORDER,
    EXPECTED_DEVELOPMENT_END,
    EXPECTED_GUARD_START,
    EXPECTED_MAX_ENDPOINT,
    EXPECTED_PROSPECTIVE_START,
    OUTPUT_ROOT as PHASE1_OUTPUT_ROOT,
    git_blob_sha1,
    load_contract,
    sha256,
)

from ml.stock_eagle_250_autonomous_ml_v1 import phase1 as v1_phase1
from ml.stock_eagle_250_autonomous_ml_v1 import phase2 as v1_phase2
from ml.stock_eagle_250_autonomous_ml_v2 import phase1 as v2_phase1
from ml.stock_eagle_250_autonomous_ml_v2 import phase2 as v2_phase2
from ml.stock_eagle_250_autonomous_ml_v3 import phase1 as v3_phase1
from ml.stock_eagle_250_autonomous_ml_v3 import phase2 as v3_phase2


PHASE = 2
PHASE1_MANIFEST_PATH = PHASE1_OUTPUT_ROOT / "manifest.json"
OUTPUT_ROOT = Path(
    "data/model/stock_eagle_250_autonomous_ml_prospective_v1/phase2"
)
SNAPSHOT_ROOT = OUTPUT_ROOT / "snapshots"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

DEVELOPMENT_END = pd.Timestamp(EXPECTED_DEVELOPMENT_END)
MAX_ENDPOINT = pd.Timestamp(EXPECTED_MAX_ENDPOINT)
GUARD_START = pd.Timestamp(EXPECTED_GUARD_START)
PROSPECTIVE_START = pd.Timestamp(EXPECTED_PROSPECTIVE_START)


def _utc_series(values) -> pd.Series:
    return pd.to_datetime(values, utc=True)


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def validate_phase1_manifest(manifest: dict, contract: dict) -> None:
    problems = []
    if manifest.get("research_version") != RESEARCH_VERSION:
        problems.append("research_version")
    if manifest.get("phase") != 1:
        problems.append("phase")
    if manifest.get("contract_sha256") != sha256(CONTRACT_PATH):
        problems.append("contract_sha256")
    if manifest.get("prospective_rows_read") != 0:
        problems.append("prospective_rows_read")
    if manifest.get("prospective_performance_calculated") is not False:
        problems.append("prospective_performance_calculated")
    if manifest.get("snapshots_built") is not False:
        problems.append("snapshots_built")
    if manifest.get("automatic_winner_selection") is not False:
        problems.append("automatic_winner_selection")
    if manifest.get("automatic_model_promotion") is not False:
        problems.append("automatic_model_promotion")
    if manifest.get("brokerage_orders") is not False:
        problems.append("brokerage_orders")
    if manifest.get("live_execution_enabled") is not False:
        problems.append("live_execution_enabled")

    expected_ids = tuple(
        row["candidate_id"]
        for row in contract["candidate_snapshots"]
    )
    actual_ids = tuple(
        row["candidate_id"]
        for row in manifest.get("candidates", [])
    )
    if expected_ids != EXPECTED_CANDIDATE_ORDER:
        problems.append("contract_candidate_order")
    if actual_ids != EXPECTED_CANDIDATE_ORDER:
        problems.append("manifest_candidate_order")

    if problems:
        raise RuntimeError(
            "Prospective snapshot build rejected Phase 1: "
            + ", ".join(problems)
        )


def validate_bound_code(contract: dict) -> None:
    for candidate in contract["candidate_snapshots"]:
        contract_path = Path(candidate["phase1_contract_path"])
        code_path = Path(candidate["phase2_code_path"])
        if git_blob_sha1(contract_path) != candidate[
            "phase1_contract_git_blob_sha1"
        ]:
            raise RuntimeError(
                f"{candidate['candidate_id']} Phase-1 contract changed"
            )
        if git_blob_sha1(code_path) != candidate[
            "phase2_code_git_blob_sha1"
        ]:
            raise RuntimeError(
                f"{candidate['candidate_id']} Phase-2 code changed"
            )


def validate_training_frame(frame: pd.DataFrame) -> dict:
    timestamps = _utc_series(frame["timestamp_utc"])
    endpoints = _utc_series(frame[ENDPOINT_COLUMN])

    problems = []
    if frame.empty:
        problems.append("empty_training_frame")
    if (timestamps > DEVELOPMENT_END).any():
        problems.append("decision_after_development_end")
    if (endpoints > MAX_ENDPOINT).any():
        problems.append("target_after_maximum_training_endpoint")
    if (timestamps >= GUARD_START).any():
        problems.append("guard_band_decision_row")
    if (endpoints >= GUARD_START).any():
        problems.append("guard_band_target_row")
    if (timestamps >= PROSPECTIVE_START).any():
        problems.append("prospective_decision_row")
    if (endpoints >= PROSPECTIVE_START).any():
        problems.append("prospective_target_row")
    if frame.duplicated(["timestamp_utc", "symbol"]).any():
        problems.append("duplicate_timestamp_symbol")

    if problems:
        raise RuntimeError(
            "Prospective snapshot training frame rejected: "
            + ", ".join(problems)
        )

    return {
        "training_rows": int(len(frame)),
        "training_decision_start_utc":
            timestamps.min().isoformat(),
        "training_decision_end_utc":
            timestamps.max().isoformat(),
        "training_target_endpoint_max_utc":
            endpoints.max().isoformat(),
        "guard_band_rows_read": 0,
        "prospective_rows_read": 0,
    }


def _candidate_modules(candidate_id: str):
    if candidate_id == "autonomous_ml_v1":
        return v1_phase1, v1_phase2, 3
    if candidate_id == "autonomous_ml_v2":
        return v2_phase1, v2_phase2, 4
    if candidate_id == "autonomous_ml_v3":
        return v3_phase1, v3_phase2, 4
    raise RuntimeError(f"Unknown candidate: {candidate_id}")


def _snapshot_payload(
    candidate: dict,
    frame: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[dict, dict]:
    candidate_id = candidate["candidate_id"]
    phase1_module, phase2_module, component_count = _candidate_modules(
        candidate_id
    )

    candidate_contract = phase1_module.load_contract()
    templates = phase1_module.model_templates(candidate_contract)

    inner_meta = phase2_module.inner_meta_training_rows(
        frame,
        feature_columns,
        templates,
        candidate_contract,
    )
    meta_model = phase2_module.fit_meta_allocator(
        inner_meta,
        templates["meta_allocator"],
        candidate_contract,
    )

    fitted = phase2_module.fit_base_models(
        frame,
        feature_columns,
        templates,
    )
    if component_count == 3:
        alpha_model, downside_model = fitted
        model_objects = {
            "alpha_model": alpha_model,
            "downside_model": downside_model,
            "meta_allocator": meta_model,
        }
    else:
        alpha_model, downside_model, tail_model = fitted
        model_objects = {
            "alpha_model": alpha_model,
            "downside_model": downside_model,
            "tail_model": tail_model,
            "meta_allocator": meta_model,
        }

    if len(model_objects) != component_count:
        raise RuntimeError(
            f"{candidate_id} fitted component count changed"
        )

    training_cutoff = pd.Timestamp(
        frame[ENDPOINT_COLUMN].max()
    )
    meta_cutoff = pd.Timestamp(
        inner_meta["inner_test_timestamp_utc"].max()
    )

    model_hashes = {}
    for name, model in model_objects.items():
        columns = (
            list(phase2_module.META_FEATURES)
            if name == "meta_allocator"
            else feature_columns
        )
        cutoff = meta_cutoff if name == "meta_allocator" else training_cutoff
        model_hashes[name] = phase2_module._snapshot_sha(
            model,
            columns,
            cutoff,
        )

    snapshot = {
        "candidate_id": candidate_id,
        "research_version": candidate["research_version"],
        "phase1_contract_sha256":
            phase1_module.sha256(phase1_module.CONTRACT_PATH),
        "phase1_contract_git_blob_sha1":
            candidate["phase1_contract_git_blob_sha1"],
        "phase2_code_git_blob_sha1":
            candidate["phase2_code_git_blob_sha1"],
        "feature_columns": list(feature_columns),
        "meta_features": list(phase2_module.META_FEATURES),
        "training_cutoff_utc": training_cutoff.isoformat(),
        "meta_oos_cutoff_utc": meta_cutoff.isoformat(),
        "training_rows": int(len(frame)),
        "meta_oos_training_sessions": int(len(inner_meta)),
        "models": model_objects,
    }

    serialized = pickle.dumps(snapshot, protocol=5)
    snapshot_sha256 = hashlib.sha256(serialized).hexdigest()

    summary = {
        "candidate_id": candidate_id,
        "research_version": candidate["research_version"],
        "learned_component_count": component_count,
        "training_rows": int(len(frame)),
        "meta_oos_training_sessions": int(len(inner_meta)),
        "training_cutoff_utc": training_cutoff.isoformat(),
        "meta_oos_cutoff_utc": meta_cutoff.isoformat(),
        "feature_count": int(len(feature_columns)),
        "meta_feature_count": int(len(phase2_module.META_FEATURES)),
        "model_sha256": model_hashes,
        "snapshot_sha256": snapshot_sha256,
    }
    return {"bytes": serialized, "summary": summary}, snapshot


def write_snapshot(
    candidate_id: str,
    serialized: bytes,
    root: Path = SNAPSHOT_ROOT,
) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{candidate_id}.pkl"
    temporary = path.with_suffix(".pkl.tmp")
    temporary.write_bytes(serialized)
    temporary.replace(path)
    return path


def run(
    panel_path: Path = PANEL_PATH,
    phase1_manifest_path: Path = PHASE1_MANIFEST_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    phase1_manifest = json.loads(
        Path(phase1_manifest_path).read_text(encoding="utf-8")
    )
    validate_phase1_manifest(phase1_manifest, contract)
    validate_bound_code(contract)

    panel = pd.read_parquet(panel_path)
    frame, feature_columns = build_model_frame(panel)
    training = validate_training_frame(frame)

    panel_sha256 = file_sha256(Path(panel_path))
    snapshot_rows = []

    for candidate in contract["candidate_snapshots"]:
        candidate_id = candidate["candidate_id"]
        print(f"[SNAPSHOT] fitting {candidate_id} ...", flush=True)
        bundle, _snapshot = _snapshot_payload(
            candidate,
            frame,
            feature_columns,
        )
        path = write_snapshot(
            candidate_id,
            bundle["bytes"],
            root=Path(output_root) / "snapshots",
        )
        summary = dict(bundle["summary"])
        summary["path"] = str(path)
        snapshot_rows.append(summary)
        print(
            f"[SNAPSHOT] {candidate_id} "
            f"sha256={summary['snapshot_sha256']} "
            f"meta_oos={summary['meta_oos_training_sessions']:,}",
            flush=True,
        )

    payload = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "fixed_preboundary_candidate_snapshots_built",
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
        "contract_sha256": sha256(CONTRACT_PATH),
        "source_panel_path": str(panel_path),
        "source_panel_sha256": panel_sha256,
        "source": training,
        "candidate_count": len(snapshot_rows),
        "candidate_order": [
            row["candidate_id"] for row in snapshot_rows
        ],
        "snapshots": snapshot_rows,
        "snapshots_built": True,
        "snapshots_fixed_for_prospective_evaluation": True,
        "post_snapshot_retraining_during_evaluation": False,
        "sealed_guard_band_read": False,
        "prospective_rows_read": 0,
        "prospective_performance_calculated": False,
        "prospective_start_utc": EXPECTED_PROSPECTIVE_START,
        "formal_review_minimum_completed_cohorts": 60,
        "formal_review_minimum_complete_blocks": 12,
        "automatic_winner_selection": False,
        "automatic_model_promotion": False,
        "new_architecture_before_formal_review": False,
        "brokerage_orders": False,
        "live_execution_enabled": False,
        "next_step": (
            "Implement the fail-closed append-only prospective runner before "
            "Oct 1. It must use these exact snapshot SHA-256 values, refuse "
            "pre-boundary decisions, prohibit backfill, and score V1/V2/V3 "
            "on the same eligible decision clock."
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
