"""Phase 1 preregistration for StockEagle250 Autonomous ML V1.

Validates the frozen StockEagle250 development source and the three fixed
learned estimators before any model result is calculated.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from ml.stock_eagle_250.phase2 import (
    CONTRACT_PATH as SOURCE_CONTRACT_PATH,
    FOLDS_PATH as SOURCE_FOLDS_PATH,
    MANIFEST_PATH as SOURCE_MANIFEST_PATH,
    PANEL_PATH as SOURCE_PANEL_PATH,
    RANK_FEATURE_COLUMNS,
    TARGET_COLUMN,
)
from ml.stock_eagle_250_autonomous_ml_v1 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION

PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
OUTPUT_ROOT = Path("data/model/stock_eagle_250_autonomous_ml_v1/phase1")
EXPECTED_COMPONENTS = ("alpha_model", "downside_model", "meta_allocator")
REQUIRED_COLUMNS = {
    "timestamp_utc", "symbol", "sector", "model_eligible",
    "forward_stock_return", TARGET_COLUMN, "target_endpoint_utc_5d",
    *RANK_FEATURE_COLUMNS,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise RuntimeError(f"Autonomous ML identity mismatch: {key}")
    if contract.get("created_before_model_results") is not True:
        raise RuntimeError("Contract was not preregistered")
    if tuple(contract["architecture"]) != EXPECTED_COMPONENTS:
        raise RuntimeError("Learned component set changed")
    if contract["architecture"]["alpha_model"]["target"] != TARGET_COLUMN:
        raise RuntimeError("Alpha target changed")
    if contract["architecture"]["downside_model"]["target"] != "forward_stock_return_lt_0":
        raise RuntimeError("Downside target changed")
    if contract["architecture"]["meta_allocator"].get(
        "training_features_must_be_inner_walk_forward_oos"
    ) is not True:
        raise RuntimeError("Allocator must use OOS base-model predictions")
    nested = contract["nested_walk_forward"]
    for key in ("hyperparameter_search", "model_family_search", "feature_search", "allocator_threshold_search"):
        if nested.get(key) is not False:
            raise RuntimeError(f"Search enabled: {key}")
    if contract["isolation"].get("consume_stock_eagle_250_v5_phase2") is not False:
        raise RuntimeError("This lane cannot consume V5 Phase 2")
    return contract


def model_templates(contract: dict | None = None) -> dict:
    contract = load_contract() if contract is None else contract
    arch = contract["architecture"]
    return {
        "alpha_model": HistGradientBoostingRegressor(**arch["alpha_model"]["parameters"]),
        "downside_model": HistGradientBoostingClassifier(**arch["downside_model"]["parameters"]),
        "meta_allocator": HistGradientBoostingClassifier(**arch["meta_allocator"]["parameters"]),
    }


def validate_source(manifest: dict, folds: list[dict], columns: set[str]) -> dict:
    problems = []
    if manifest.get("candidate_count") != 250:
        problems.append("candidate_count")
    if manifest.get("fold_count") != 14:
        problems.append("fold_count")
    if manifest.get("future_holdout_rows_read") != 0:
        problems.append("future_holdout_rows_read")
    if manifest.get("future_holdout_start_utc") != "2026-09-23T00:00:00+00:00":
        problems.append("future_holdout_start_utc")
    if manifest.get("maximum_development_target_endpoint_utc") != "2026-09-22T00:00:00+00:00":
        problems.append("maximum_development_target_endpoint_utc")
    if manifest.get("development_end_utc") != "2026-09-15T00:00:00+00:00":
        problems.append("development_end_utc")
    if manifest.get("contract_sha256") != sha256(SOURCE_CONTRACT_PATH):
        problems.append("source_contract_sha256")
    if len(folds) != 14 or [row["fold_id"] for row in folds] != manifest.get("fold_ids"):
        problems.append("fold_file")
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        problems.append("missing_columns:" + ",".join(missing))
    if problems:
        raise RuntimeError("Autonomous ML source validation failed: " + "; ".join(problems))
    return {
        "candidate_count": int(manifest["candidate_count"]),
        "fold_count": int(manifest["fold_count"]),
        "source_rows": int(manifest["source_rows"]),
        "model_eligible_rows": int(manifest["model_eligible_rows"]),
        "development_start_utc": manifest["development_start_utc"],
        "development_end_utc": manifest["development_end_utc"],
        "maximum_development_target_endpoint_utc": manifest["maximum_development_target_endpoint_utc"],
        "future_holdout_start_utc": manifest["future_holdout_start_utc"],
        "future_holdout_rows_read": int(manifest["future_holdout_rows_read"]),
    }


def run(
    source_manifest_path: Path = SOURCE_MANIFEST_PATH,
    folds_path: Path = SOURCE_FOLDS_PATH,
    panel_path: Path = SOURCE_PANEL_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    manifest = json.loads(Path(source_manifest_path).read_text(encoding="utf-8"))
    folds = json.loads(Path(folds_path).read_text(encoding="utf-8"))
    columns = set(pq.read_schema(panel_path).names)
    source = validate_source(manifest, folds, columns)
    templates = model_templates(contract)
    if tuple(templates) != EXPECTED_COMPONENTS:
        raise RuntimeError("Estimator template set changed")
    payload = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "preregistered_three_model_ml_architecture",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": sha256(CONTRACT_PATH),
        "source_contract_sha256": sha256(SOURCE_CONTRACT_PATH),
        "learned_component_count": 3,
        "learned_components": list(EXPECTED_COMPONENTS),
        "source": source,
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "performance_calculated": False,
        "next_step": "Run the fixed nested walk-forward evaluation without reading September 23 or later."
    }
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
