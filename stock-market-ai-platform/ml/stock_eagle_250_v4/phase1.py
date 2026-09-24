"""StockEagle250 V4 Phase 1: preregistered confidence-conditioned exposure.

V4 is created after V3 improved return retention but failed three fixed
development gates. Phase 1 validates preserved pre-guard V3 evidence and the
saved V1 out-of-sample prediction source without calculating V4 performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v4 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION


PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
V1_PREDICTIONS_PATH = Path(
    "data/model/stock_eagle_250/phase3/walk_forward_predictions.parquet"
)
V3_PHASE2_ROOT = Path("data/model/stock_eagle_250_v3/phase2")
V3_MANIFEST_PATH = V3_PHASE2_ROOT / "manifest.json"
V3_QUALIFICATION_PATH = V3_PHASE2_ROOT / "qualification.json"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_v4/phase1")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

V1_RANKING_CANDIDATE = "ridge_fixed_v1"
V1_PREDICTION_COLUMN = "prediction_ridge_fixed_v1"
V3_CANDIDATE = "ridge_v1_rank_volatility_budget_v3"
V4_CANDIDATE = "ridge_v1_rank_cross_sectional_confidence_v4"
V3_RESEARCH_VERSION = "stock_eagle_250_v3_volatility_budgeted_ridge"

GUARD_BAND_START_UTC = pd.Timestamp("2026-09-23", tz="UTC")
FUTURE_START_UTC = pd.Timestamp("2026-10-01", tz="UTC")
MAXIMUM_DEVELOPMENT_ENDPOINT_UTC = pd.Timestamp("2026-09-22", tz="UTC")

TOP_GROUP_SIZE = 10
COMPARISON_GROUP_SIZE = 10
CONFIDENCE_LOOKBACK = 252
CONFIDENCE_MINIMUM_PRIOR = 60
MINIMUM_GROSS_EXPOSURE = 0.5
MAXIMUM_GROSS_EXPOSURE = 1.0

EXPECTED_V3_FAILED_GATES = {
    "gate_positive_excess_vs_spy_fold_fraction_gte_60pct",
    "gate_median_drawdown_improvement_vs_v1_gte_5pct",
    "gate_median_calmar_gte_v1_ridge",
}
EXPECTED_GATE_KEYS = {
    "median_fold_primary_net_return_gt",
    "positive_primary_fold_fraction_gte",
    "median_fold_excess_vs_spy_gt",
    "positive_excess_vs_spy_fold_fraction_gte",
    "median_fold_excess_vs_equal_weight_gt",
    "median_fold_excess_vs_v1_ridge_gte",
    "worst_fold_maximum_drawdown_gte",
    "median_fold_drawdown_improvement_vs_v1_ridge_gte",
    "drawdown_improvement_fold_fraction_gte",
    "median_fold_calmar_gte_v1_ridge",
    "median_fold_stress_20bps_net_return_gt",
}
REQUIRED_PREDICTION_COLUMNS = {
    "fold_id",
    "timestamp_utc",
    "entry_timestamp_utc_5d",
    "target_endpoint_utc_5d",
    "symbol",
    V1_PREDICTION_COLUMN,
}


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    mismatches = {
        key: {"expected": value, "actual": contract.get(key)}
        for key, value in expected.items()
        if contract.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"StockEagle250 V4 identity mismatch: {mismatches}")
    if contract.get("created_before_v4_results") is not True:
        raise RuntimeError("V4 contract was not marked preregistered")

    candidate = contract["fixed_candidate"]
    if candidate.get("candidate_id") != V4_CANDIDATE:
        raise RuntimeError("Unexpected V4 candidate identity")
    if candidate.get("ranking_source") != V1_RANKING_CANDIDATE:
        raise RuntimeError("V4 ranking source is not the fixed V1 Ridge ranker")
    if candidate.get("prediction_column") != V1_PREDICTION_COLUMN:
        raise RuntimeError("V4 prediction source differs from V1 Ridge")
    if candidate.get("spy_trend_used") is not False:
        raise RuntimeError("V4 must not use SPY trend")
    if candidate.get("spy_volatility_used") is not False:
        raise RuntimeError("V4 must not use SPY volatility")
    if any(candidate.get(key) is not False for key in (
        "threshold_search",
        "exposure_search",
        "model_search",
        "hyperparameter_search",
    )):
        raise RuntimeError("V4 contract permits a prohibited search")
    if float(candidate.get("minimum_gross_exposure")) != MINIMUM_GROSS_EXPOSURE:
        raise RuntimeError("V4 minimum exposure differs from code")
    if float(candidate.get("maximum_gross_exposure")) != MAXIMUM_GROSS_EXPOSURE:
        raise RuntimeError("V4 maximum exposure differs from code")

    signal = candidate["confidence_signal"]
    if signal.get("top_group_ranks") != [1, 10]:
        raise RuntimeError("V4 top confidence group differs from code")
    if signal.get("comparison_group_ranks") != [11, 20]:
        raise RuntimeError("V4 comparison confidence group differs from code")

    history = candidate["confidence_history"]
    if int(history.get("lookback_completed_decision_sessions")) != CONFIDENCE_LOOKBACK:
        raise RuntimeError("V4 confidence lookback differs from code")
    if int(history.get("minimum_prior_sessions")) != CONFIDENCE_MINIMUM_PRIOR:
        raise RuntimeError("V4 confidence minimum history differs from code")
    if history.get("current_session_excluded") is not True:
        raise RuntimeError("V4 confidence history must exclude the current session")

    expected_rule = (
        "if history_not_ready_or_confidence_invalid then 0.5 else "
        "0.5 + 0.5 * empirical_confidence_percentile"
    )
    if candidate.get("gross_exposure_rule") != expected_rule:
        raise RuntimeError("V4 exposure rule differs from preregistration")

    boundaries = contract["data_boundaries"]
    if _utc(boundaries["sealed_guard_band_start_utc"]) != GUARD_BAND_START_UTC:
        raise RuntimeError("V4 guard-band start differs from code")
    if _utc(boundaries["new_untouched_future_start_utc"]) != FUTURE_START_UTC:
        raise RuntimeError("V4 future boundary differs from code")
    if (
        _utc(boundaries["maximum_development_target_endpoint_utc"])
        != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC
    ):
        raise RuntimeError("V4 development endpoint differs from code")

    gates = contract["preregistered_development_gates"]
    if gates.get("policy") != "reuse_v2_v3_gates_without_relaxation":
        raise RuntimeError("V4 gate policy was changed")
    if set(gates) - {"policy"} != EXPECTED_GATE_KEYS:
        raise RuntimeError("V4 preregistered gate set is incomplete or changed")

    authority = contract["authority"]
    if any(authority.get(key) is not False for key in (
        "model_freezing_enabled",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
    )):
        raise RuntimeError("V4 Phase 1 has trading or freezing authority")
    return contract


def validate_v3_evidence(
    manifest: dict,
    qualification: dict,
) -> dict:
    problems = []
    if manifest.get("research_version") != V3_RESEARCH_VERSION:
        problems.append("unexpected V3 research version")
    if manifest.get("phase") != 2:
        problems.append("V3 evidence is not Phase 2")
    if manifest.get("candidate_id") != V3_CANDIDATE:
        problems.append("unexpected V3 candidate")
    if manifest.get("guard_band_rows_read") != 0:
        problems.append("V3 reports guard-band rows")
    if manifest.get("future_rows_read") != 0:
        problems.append("V3 reports future rows")

    safety = manifest.get("safety", {})
    if any(safety.get(key) is not False for key in (
        "future_holdout_scored",
        "candidate_frozen",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
    )):
        problems.append("V3 evidence reports forbidden activity")

    if qualification.get("candidate_id") != V3_CANDIDATE:
        problems.append("V3 qualification candidate differs")
    if qualification.get("status") != "REJECT_CURRENT_STOCK_EAGLE_250_V3_CANDIDATE":
        problems.append("V3 is not preserved as rejected")
    if qualification.get("qualified_for_human_review") is not False:
        problems.append("V3 unexpectedly qualified for human review")
    if qualification.get("gates_passed") != 8 or qualification.get("gates_total") != 11:
        problems.append("V3 gate count differs from preserved result")
    failed = set(qualification.get("failed_gates", []))
    if failed != EXPECTED_V3_FAILED_GATES:
        problems.append("V3 failed-gate set differs from preserved result")

    if problems:
        raise RuntimeError(
            "StockEagle250 V4 rejected its V3 evidence:\n- "
            + "\n- ".join(problems)
        )

    summary = manifest.get("summary", {})
    return {
        "v3_status": qualification["status"],
        "v3_gates_passed": int(qualification["gates_passed"]),
        "v3_gates_total": int(qualification["gates_total"]),
        "v3_failed_gates": sorted(failed),
        "v3_positive_excess_vs_spy_fold_fraction":
            float(summary["positive_excess_vs_spy_fold_fraction"]),
        "v3_median_drawdown_improvement_vs_v1_ridge":
            float(summary["median_fold_drawdown_improvement_vs_v1_ridge"]),
        "v3_median_fold_calmar": float(summary["median_fold_calmar"]),
        "v1_ridge_median_fold_calmar":
            float(summary["median_v1_ridge_calmar"]),
        "v3_median_gross_exposure":
            float(summary["median_gross_exposure"]),
    }


def validate_prediction_source(predictions: pd.DataFrame) -> dict:
    missing = sorted(REQUIRED_PREDICTION_COLUMNS - set(predictions.columns))
    if missing:
        raise RuntimeError(f"V1 prediction source is missing columns: {missing}")

    frame = predictions.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame["entry_timestamp_utc_5d"] = pd.to_datetime(
        frame["entry_timestamp_utc_5d"],
        utc=True,
    )
    frame["target_endpoint_utc_5d"] = pd.to_datetime(
        frame["target_endpoint_utc_5d"],
        utc=True,
    )

    problems = []
    if frame.empty:
        problems.append("prediction source is empty")
    for column in (
        "timestamp_utc",
        "entry_timestamp_utc_5d",
        "target_endpoint_utc_5d",
    ):
        if (frame[column] >= GUARD_BAND_START_UTC).any():
            problems.append(f"{column} enters the sealed guard band")
    if frame["target_endpoint_utc_5d"].max() != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC:
        problems.append("prediction source lacks the fixed final development endpoint")
    if frame.duplicated(["fold_id", "timestamp_utc", "symbol"]).any():
        problems.append("duplicate fold/timestamp/symbol prediction rows")

    scores = pd.to_numeric(frame[V1_PREDICTION_COLUMN], errors="coerce")
    if not np.isfinite(scores).all():
        problems.append("non-finite V1 Ridge predictions")
    if frame["fold_id"].nunique() != 14:
        problems.append("prediction source does not contain 14 folds")
    sessions_per_timestamp = frame.groupby("timestamp_utc")["symbol"].size()
    if (sessions_per_timestamp < TOP_GROUP_SIZE + COMPARISON_GROUP_SIZE).any():
        problems.append("a decision session has fewer than twenty eligible symbols")
    folds_per_timestamp = frame.groupby("timestamp_utc")["fold_id"].nunique()
    if (folds_per_timestamp != 1).any():
        problems.append("a decision timestamp appears in multiple folds")

    if problems:
        raise RuntimeError(
            "StockEagle250 V4 rejected its V1 prediction source:\n- "
            + "\n- ".join(problems)
        )
    return {
        "source_rows": int(len(frame)),
        "fold_count": int(frame["fold_id"].nunique()),
        "decision_sessions": int(frame["timestamp_utc"].nunique()),
        "development_decision_start_utc": frame["timestamp_utc"].min().isoformat(),
        "development_decision_end_utc": frame["timestamp_utc"].max().isoformat(),
        "maximum_development_target_endpoint_utc":
            frame["target_endpoint_utc_5d"].max().isoformat(),
        "minimum_symbols_per_decision":
            int(sessions_per_timestamp.min()),
    }


def confidence_exposure_frame(predictions: pd.DataFrame) -> pd.DataFrame:
    """Create the fixed V4 confidence/exposure series without realized returns."""
    validate_prediction_source(predictions)
    frame = predictions.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame[V1_PREDICTION_COLUMN] = pd.to_numeric(
        frame[V1_PREDICTION_COLUMN],
        errors="coerce",
    )

    rows = []
    for timestamp, group in frame.groupby("timestamp_utc", sort=True):
        ordered = group.sort_values(
            [V1_PREDICTION_COLUMN, "symbol"],
            ascending=[False, True],
        )
        top = ordered.head(TOP_GROUP_SIZE)[V1_PREDICTION_COLUMN]
        comparison = ordered.iloc[
            TOP_GROUP_SIZE:TOP_GROUP_SIZE + COMPARISON_GROUP_SIZE
        ][V1_PREDICTION_COLUMN]
        median = float(ordered[V1_PREDICTION_COLUMN].median())
        mad = float(
            (ordered[V1_PREDICTION_COLUMN] - median).abs().median()
        )
        margin = float(top.mean() - comparison.mean())
        standardized = (
            float(margin / mad)
            if np.isfinite(margin) and np.isfinite(mad) and mad > 0.0
            else np.nan
        )
        rows.append({
            "timestamp_utc": timestamp,
            "fold_id": str(ordered.iloc[0]["fold_id"]),
            "eligible_symbols": int(len(ordered)),
            "top10_mean_prediction": float(top.mean()),
            "ranks_11_20_mean_prediction": float(comparison.mean()),
            "selection_margin": margin,
            "cross_sectional_prediction_mad": mad,
            "standardized_confidence": standardized,
        })

    result = pd.DataFrame(rows).sort_values("timestamp_utc").reset_index(drop=True)
    percentiles = []
    exposures = []
    history_counts = []

    for index, row in result.iterrows():
        start = max(0, index - CONFIDENCE_LOOKBACK)
        history = pd.to_numeric(
            result.iloc[start:index]["standardized_confidence"],
            errors="coerce",
        )
        history = history[np.isfinite(history.to_numpy(dtype=float))]
        current = float(row["standardized_confidence"])

        if (
            len(history) < CONFIDENCE_MINIMUM_PRIOR
            or not np.isfinite(current)
        ):
            percentile = np.nan
            exposure = MINIMUM_GROSS_EXPOSURE
        else:
            percentile = float((history <= current).mean())
            exposure = (
                MINIMUM_GROSS_EXPOSURE
                + (MAXIMUM_GROSS_EXPOSURE - MINIMUM_GROSS_EXPOSURE)
                * percentile
            )

        history_counts.append(int(len(history)))
        percentiles.append(percentile)
        exposures.append(float(exposure))

    result["prior_confidence_count"] = history_counts
    result["confidence_percentile"] = percentiles
    result["gross_exposure"] = exposures
    result["cash_fraction"] = 1.0 - result["gross_exposure"]

    if not result["gross_exposure"].between(
        MINIMUM_GROSS_EXPOSURE,
        MAXIMUM_GROSS_EXPOSURE,
    ).all():
        raise RuntimeError("V4 confidence exposure is outside [0.5, 1.0]")
    return result


def build_manifest(
    contract: dict,
    v3_evidence: dict,
    source_summary: dict,
) -> dict:
    return {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "preregistered_cross_sectional_confidence_exposure_readiness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": V4_CANDIDATE,
        "candidate_count": 1,
        "ranking_source": V1_RANKING_CANDIDATE,
        "prediction_source": V1_PREDICTION_COLUMN,
        "spy_trend_used": False,
        "spy_volatility_used": False,
        "contract_sha256": _sha256(CONTRACT_PATH),
        "v3_development_evidence": v3_evidence,
        "source": source_summary,
        "sealed_guard_band_start_utc": GUARD_BAND_START_UTC.isoformat(),
        "sealed_guard_band_end_exclusive_utc": FUTURE_START_UTC.isoformat(),
        "new_untouched_future_start_utc": FUTURE_START_UTC.isoformat(),
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v4_performance_calculated": False,
        "qualification_gates_fixed_before_v4_results": bool(
            contract["created_before_v4_results"]
        ),
        "gate_policy": contract["preregistered_development_gates"]["policy"],
        "safety": {
            "v1_artifacts_modified": False,
            "v2_artifacts_modified": False,
            "v3_artifacts_modified": False,
            "model_refit": False,
            "hyperparameter_search_performed": False,
            "threshold_search_performed": False,
            "exposure_search_performed": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "paper_trading_enabled": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "existing_forward_journals_modified": False,
        },
        "next_step": (
            "Implement Phase 2 only after this preregistration exists. Evaluate "
            "this one fixed cross-sectional-confidence exposure rule on the same "
            "saved V1 out-of-sample development evidence at 10-bps primary and "
            "20-bps stress costs. Do not read September 23 or later."
        ),
    }


def run(
    predictions_path: Path = V1_PREDICTIONS_PATH,
    v3_manifest_path: Path = V3_MANIFEST_PATH,
    v3_qualification_path: Path = V3_QUALIFICATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    v3_manifest = json.loads(
        Path(v3_manifest_path).read_text(encoding="utf-8")
    )
    v3_qualification = json.loads(
        Path(v3_qualification_path).read_text(encoding="utf-8")
    )
    v3_evidence = validate_v3_evidence(v3_manifest, v3_qualification)

    predictions = pd.read_parquet(predictions_path)
    source_summary = validate_prediction_source(predictions)
    payload = build_manifest(contract, v3_evidence, source_summary)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=V1_PREDICTIONS_PATH)
    parser.add_argument("--v3-manifest", type=Path, default=V3_MANIFEST_PATH)
    parser.add_argument(
        "--v3-qualification",
        type=Path,
        default=V3_QUALIFICATION_PATH,
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        predictions_path=args.predictions,
        v3_manifest_path=args.v3_manifest,
        v3_qualification_path=args.v3_qualification,
        output_root=args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
