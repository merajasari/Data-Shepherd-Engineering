"""StockEagle250 Autonomous ML V3 Phase 1: benchmark-relative preregistration.

Validates the rejected Autonomous ML V2 evidence, preserves the original
StockEagle250 development boundary, and seals a benchmark-relative four-model
learned architecture before any V3 performance is calculated.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from ml.stock_eagle_250.phase2 import (
    CONTRACT_PATH as SOURCE_CONTRACT_PATH,
    FOLDS_PATH as SOURCE_FOLDS_PATH,
    MANIFEST_PATH as SOURCE_MANIFEST_PATH,
    PANEL_PATH as SOURCE_PANEL_PATH,
    RANK_FEATURE_COLUMNS,
    TARGET_COLUMN,
)
from ml.stock_eagle_250_autonomous_ml_v3 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)


PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
OUTPUT_ROOT = Path("data/model/stock_eagle_250_autonomous_ml_v3/phase1")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

V2_CONTRACT_PATH = Path(
    "ml/stock_eagle_250_autonomous_ml_v2/phase1_contract.json"
)
V2_PHASE2_ROOT = Path(
    "data/model/stock_eagle_250_autonomous_ml_v2/phase2"
)
V2_MANIFEST_PATH = V2_PHASE2_ROOT / "manifest.json"
V2_QUALIFICATION_PATH = V2_PHASE2_ROOT / "qualification.json"

EXPECTED_COMPONENTS = (
    "alpha_model",
    "downside_model",
    "tail_model",
    "meta_allocator",
)
EXPECTED_V2_FAILED_GATES = {
    "positive_excess_vs_spy_fold_fraction_gte"
}
REQUIRED_COLUMNS = {
    "timestamp_utc",
    "symbol",
    "sector",
    "model_eligible",
    "forward_stock_return",
    "forward_spy_return",
    TARGET_COLUMN,
    "target_endpoint_utc_5d",
    *RANK_FEATURE_COLUMNS,
}
SEALED_GUARD_START_UTC = "2026-09-23T00:00:00+00:00"
UNTOUCHED_FUTURE_START_UTC = "2026-10-01T00:00:00+00:00"


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
            raise RuntimeError(f"Autonomous ML V3 identity mismatch: {key}")

    if contract.get("created_before_model_results") is not True:
        raise RuntimeError("Autonomous ML V3 contract was not preregistered")

    if tuple(contract["architecture"]) != EXPECTED_COMPONENTS:
        raise RuntimeError("Autonomous ML V3 learned component set changed")

    arch = contract["architecture"]
    if arch["alpha_model"]["target"] != TARGET_COLUMN:
        raise RuntimeError("V3 alpha target changed")
    if arch["downside_model"]["target"] != "forward_stock_return_lt_0":
        raise RuntimeError("V3 downside target changed")
    if arch["tail_model"]["target"] != "forward_stock_return":
        raise RuntimeError("V3 tail target changed")
    if arch["tail_model"]["parameters"].get("loss") != "quantile":
        raise RuntimeError("V3 tail model is not quantile regression")
    if float(arch["tail_model"]["parameters"].get("quantile")) != 0.10:
        raise RuntimeError("V3 tail quantile changed")

    meta = arch["meta_allocator"]
    if meta.get("target") != (
        "tail_aware_top10_net_return_10bps_each_side_gt_forward_spy_return"
    ):
        raise RuntimeError("V3 benchmark-relative meta target changed")
    if meta.get("training_features_must_be_inner_walk_forward_oos") is not True:
        raise RuntimeError("V3 allocator must use OOS base-model predictions")
    if meta.get("future_spy_return_is_label_only_not_feature") is not True:
        raise RuntimeError("V3 future SPY return must be label-only")

    nested = contract["nested_walk_forward"]
    for key in (
        "hyperparameter_search",
        "model_family_search",
        "feature_search",
        "allocator_threshold_search",
        "quantile_search",
        "benchmark_mix_search",
    ):
        if nested.get(key) is not False:
            raise RuntimeError(f"Prohibited V3 search enabled: {key}")

    portfolio = contract["portfolio_policy"]
    if portfolio.get("active_weight") != (
        "clip(meta_allocator_probability_top10_beats_spy, 0.0, 1.0)"
    ):
        raise RuntimeError("V3 active-weight mapping changed")
    if portfolio.get("spy_weight") != "1_minus_active_weight":
        raise RuntimeError("V3 SPY residual mapping changed")
    if float(portfolio.get("cash_fraction")) != 0.0:
        raise RuntimeError("V3 must not add a cash sleeve")
    if float(portfolio.get("total_gross_exposure")) != 1.0:
        raise RuntimeError("V3 total gross exposure must remain 1.0")
    if portfolio.get("leverage") is not False:
        raise RuntimeError("V3 leverage must remain disabled")
    if portfolio.get("short_sales") is not False:
        raise RuntimeError("V3 shorting must remain disabled")
    if portfolio.get("cost_application") != (
        "apply_cost_to_total_cohort_capital_on_entry_and_exit"
    ):
        raise RuntimeError("V3 cost application changed")

    boundary = contract["data_boundaries"]
    if boundary.get("sealed_guard_band_start_utc") != SEALED_GUARD_START_UTC:
        raise RuntimeError("V3 guard boundary changed")
    if boundary.get("untouched_future_start_utc") != UNTOUCHED_FUTURE_START_UTC:
        raise RuntimeError("V3 future boundary changed")
    if boundary.get("development_may_read_guard_band") is not False:
        raise RuntimeError("V3 development may not read guard band")
    if boundary.get("development_may_read_future") is not False:
        raise RuntimeError("V3 development may not read future sample")

    v2_contract = json.loads(
        V2_CONTRACT_PATH.read_text(encoding="utf-8")
    )
    v3_gates = {
        key: value
        for key, value in contract["development_gates"].items()
        if key != "policy"
    }
    v2_gates = {
        key: value
        for key, value in v2_contract["development_gates"].items()
        if key != "policy"
    }
    if v3_gates != v2_gates:
        raise RuntimeError("V3 development gates differ from V2")
    if contract["development_gates"].get("policy") != (
        "reuse_autonomous_ml_v1_v2_gates_without_relaxation"
    ):
        raise RuntimeError("V3 gate-reuse policy changed")

    authority = contract["authority"]
    if authority.get("autonomous_paper_runtime_enabled") is not False:
        raise RuntimeError("Phase 1 may not enable autonomous paper runtime")
    if authority.get("model_freezing_enabled") is not False:
        raise RuntimeError("Phase 1 may not freeze V3")
    if authority.get("live_execution_enabled") is not False:
        raise RuntimeError("Phase 1 may not enable live execution")

    return contract


def model_templates(contract: dict | None = None) -> dict:
    """Instantiate all four fixed learned estimators without fitting them."""
    contract = load_contract() if contract is None else contract
    arch = contract["architecture"]

    return {
        "alpha_model": HistGradientBoostingRegressor(
            **arch["alpha_model"]["parameters"]
        ),
        "downside_model": HistGradientBoostingClassifier(
            **arch["downside_model"]["parameters"]
        ),
        "tail_model": HistGradientBoostingRegressor(
            **arch["tail_model"]["parameters"]
        ),
        "meta_allocator": HistGradientBoostingClassifier(
            **arch["meta_allocator"]["parameters"]
        ),
    }


def validate_v2_evidence(
    manifest: dict,
    qualification: dict,
) -> dict:
    problems = []

    if manifest.get("research_version") != (
        "stock_eagle_250_autonomous_ml_v2_tail_aware"
    ):
        problems.append("unexpected V2 research version")
    if manifest.get("phase") != 2:
        problems.append("V2 evidence is not Phase 2")
    if manifest.get("fold_count") != 14:
        problems.append("V2 fold count differs")
    if manifest.get("learned_components") != 4:
        problems.append("V2 learned component count differs")
    if float(manifest.get("tail_quantile", float("nan"))) != 0.10:
        problems.append("V2 tail quantile differs")
    if manifest.get("meta_allocator_training_source") != (
        "inner_walk_forward_oos_only"
    ):
        problems.append("V2 allocator evidence was not OOS-only")
    if manifest.get("guard_band_rows_read") != 0:
        problems.append("V2 reports guard-band rows")
    if manifest.get("future_rows_read") != 0:
        problems.append("V2 reports future rows")

    if qualification.get("status") != "REJECT_DEVELOPMENT_CANDIDATE":
        problems.append("V2 is not preserved as rejected")
    if qualification.get("gates_passed") != 8:
        problems.append("V2 passed-gate count differs")
    if qualification.get("gates_total") != 9:
        problems.append("V2 total-gate count differs")

    failed = set(qualification.get("failed_gates", []))
    if failed != EXPECTED_V2_FAILED_GATES:
        problems.append("V2 failed-gate set differs")

    if qualification.get("autonomous_paper_runtime_enabled") is not False:
        problems.append("V2 autonomous paper runtime unexpectedly enabled")
    if qualification.get("model_frozen") is not False:
        problems.append("V2 unexpectedly frozen")

    safety = manifest.get("safety", {})
    if safety.get("autonomous_paper_runtime_enabled") is not False:
        problems.append("V2 manifest reports runtime enabled")
    if safety.get("model_frozen") is not False:
        problems.append("V2 manifest reports model frozen")
    if safety.get("live_execution_enabled") is not False:
        problems.append("V2 manifest reports live execution")

    summary = manifest.get("summary", {})
    positive_excess_fraction = float(
        summary.get(
            "positive_excess_vs_spy_fold_fraction",
            float("nan"),
        )
    )
    worst_drawdown = float(
        summary.get(
            "worst_fold_maximum_drawdown",
            float("nan"),
        )
    )

    if not np_isclose(
        positive_excess_fraction,
        0.5714285714285714,
    ):
        problems.append(
            "V2 positive-excess-vs-SPY fold fraction differs"
        )
    if not np_isclose(
        worst_drawdown,
        -0.27953452703039583,
    ):
        problems.append("V2 worst drawdown differs")

    if problems:
        raise RuntimeError(
            "Autonomous ML V3 rejected its V2 evidence:\n- "
            + "\n- ".join(problems)
        )

    return {
        "v2_status": qualification["status"],
        "v2_gates_passed": int(qualification["gates_passed"]),
        "v2_gates_total": int(qualification["gates_total"]),
        "v2_failed_gates": sorted(failed),
        "v2_median_fold_net_return":
            float(summary["median_fold_net_return"]),
        "v2_median_fold_excess_vs_spy":
            float(summary["median_fold_excess_vs_spy"]),
        "v2_positive_excess_vs_spy_fold_fraction":
            positive_excess_fraction,
        "v2_worst_fold_maximum_drawdown":
            worst_drawdown,
        "v2_median_fold_stress_20bps_net_return":
            float(summary["median_fold_stress_20bps_net_return"]),
        "v2_median_mean_gross_exposure":
            float(summary["median_mean_gross_exposure"]),
    }


def np_isclose(left: float, right: float, atol: float = 1e-12) -> bool:
    return abs(float(left) - float(right)) <= atol


def validate_source(
    manifest: dict,
    folds: list[dict],
    columns: set[str],
) -> dict:
    problems = []

    if manifest.get("candidate_count") != 250:
        problems.append("candidate_count")
    if manifest.get("fold_count") != 14:
        problems.append("fold_count")
    if manifest.get("future_holdout_rows_read") != 0:
        problems.append("future_holdout_rows_read")
    if manifest.get("future_holdout_start_utc") != SEALED_GUARD_START_UTC:
        problems.append("future_holdout_start_utc")
    if manifest.get("maximum_development_target_endpoint_utc") != (
        "2026-09-22T00:00:00+00:00"
    ):
        problems.append("maximum_development_target_endpoint_utc")
    if manifest.get("development_end_utc") != (
        "2026-09-15T00:00:00+00:00"
    ):
        problems.append("development_end_utc")
    if manifest.get("contract_sha256") != sha256(SOURCE_CONTRACT_PATH):
        problems.append("source_contract_sha256")

    if len(folds) != 14:
        problems.append("fold_count_file")
    elif [row["fold_id"] for row in folds] != manifest.get("fold_ids"):
        problems.append("fold_ids")

    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        problems.append("missing_columns:" + ",".join(missing))

    if problems:
        raise RuntimeError(
            "Autonomous ML V3 source validation failed: "
            + "; ".join(problems)
        )

    return {
        "candidate_count": int(manifest["candidate_count"]),
        "fold_count": int(manifest["fold_count"]),
        "source_rows": int(manifest["source_rows"]),
        "model_eligible_rows": int(manifest["model_eligible_rows"]),
        "development_start_utc": manifest["development_start_utc"],
        "development_end_utc": manifest["development_end_utc"],
        "maximum_development_target_endpoint_utc":
            manifest["maximum_development_target_endpoint_utc"],
        "future_holdout_start_utc":
            manifest["future_holdout_start_utc"],
        "future_holdout_rows_read":
            int(manifest["future_holdout_rows_read"]),
    }


def run(
    source_manifest_path: Path = SOURCE_MANIFEST_PATH,
    folds_path: Path = SOURCE_FOLDS_PATH,
    panel_path: Path = SOURCE_PANEL_PATH,
    v2_manifest_path: Path = V2_MANIFEST_PATH,
    v2_qualification_path: Path = V2_QUALIFICATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()

    v2_manifest = json.loads(
        Path(v2_manifest_path).read_text(encoding="utf-8")
    )
    v2_qualification = json.loads(
        Path(v2_qualification_path).read_text(encoding="utf-8")
    )
    v2_evidence = validate_v2_evidence(
        v2_manifest,
        v2_qualification,
    )

    source_manifest = json.loads(
        Path(source_manifest_path).read_text(encoding="utf-8")
    )
    folds = json.loads(
        Path(folds_path).read_text(encoding="utf-8")
    )
    columns = set(pq.read_schema(panel_path).names)
    source = validate_source(
        source_manifest,
        folds,
        columns,
    )

    templates = model_templates(contract)
    if tuple(templates) != EXPECTED_COMPONENTS:
        raise RuntimeError(
            "Autonomous ML V3 estimator template set changed"
        )

    payload = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage":
            "preregistered_benchmark_relative_four_model_ml_architecture",
        "generated_at_utc":
            datetime.now(timezone.utc).isoformat(),
        "contract_sha256": sha256(CONTRACT_PATH),
        "source_contract_sha256":
            sha256(SOURCE_CONTRACT_PATH),
        "learned_component_count": 4,
        "learned_components": list(EXPECTED_COMPONENTS),
        "tail_quantile": 0.10,
        "meta_target":
            "tail_aware_top10_net_return_10bps_each_side_gt_forward_spy_return",
        "residual_allocation": "SPY",
        "v2_development_evidence": v2_evidence,
        "source": source,
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "performance_calculated": False,
        "model_frozen": False,
        "autonomous_paper_runtime_enabled": False,
        "live_execution_enabled": False,
        "gate_policy":
            contract["development_gates"]["policy"],
        "next_step": (
            "Implement the fixed benchmark-relative nested walk-forward "
            "Phase 2. Generate alpha, downside, and tail predictions strictly "
            "out of sample for allocator training; train the meta target on "
            "whether the matured tail-aware Top-10 net return beat SPY; "
            "allocate residual cohort capital to SPY; reuse the same nine "
            "gates without relaxation; and do not read September 23 or later."
        ),
    }

    output_root = Path(output_root)
    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    (output_root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
