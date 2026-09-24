"""StockEagle250 V5 Phase 1: preregistered causal self-drawdown throttle.

V5 is the final fixed risk-control hypothesis on the current development sample.
Phase 1 validates preserved pre-guard V4 rejection evidence and the exact saved
V1 Ridge portfolio source without calculating V5 performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v5 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION


PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
V1_PERIODS_PATH = Path("data/model/stock_eagle_250/phase3/portfolio_periods.parquet")
V4_PHASE2_ROOT = Path("data/model/stock_eagle_250_v4/phase2")
V4_MANIFEST_PATH = V4_PHASE2_ROOT / "manifest.json"
V4_QUALIFICATION_PATH = V4_PHASE2_ROOT / "qualification.json"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_v5/phase1")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

V1_RANKING_CANDIDATE = "ridge_fixed_v1"
V4_CANDIDATE = "ridge_v1_rank_cross_sectional_confidence_v4"
V5_CANDIDATE = "ridge_v1_rank_self_drawdown_throttle_v5"
V4_RESEARCH_VERSION = "stock_eagle_250_v4_confidence_conditioned_ridge"

GUARD_BAND_START_UTC = pd.Timestamp("2026-09-23", tz="UTC")
FUTURE_START_UTC = pd.Timestamp("2026-10-01", tz="UTC")
MAXIMUM_DEVELOPMENT_ENDPOINT_UTC = pd.Timestamp("2026-09-22", tz="UTC")
MAXIMUM_DEVELOPMENT_DECISION_UTC = pd.Timestamp("2026-09-15", tz="UTC")

STARTING_EQUITY = 100_000.0
SLEEVE_COUNT = 5
PRIMARY_COST_BPS_PER_SIDE = 10.0
STRESS_COST_BPS_PER_SIDE = 20.0
POSITIONS_PER_COHORT = 10
MINIMUM_GROSS_EXPOSURE = 0.5
MAXIMUM_GROSS_EXPOSURE = 1.0
DRAWDOWN_SLOPE = 2.5

EXPECTED_V4_FAILED_GATES = {
    "gate_median_fold_excess_vs_v1_ridge_gte_minus_2pct",
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
REQUIRED_PERIOD_COLUMNS = {
    "fold_id",
    "portfolio_id",
    "timestamp_utc",
    "entry_timestamp_utc_5d",
    "target_endpoint_utc_5d",
    "selected_symbols",
    "selected_count",
    "gross_return",
    "net_return",
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
        raise RuntimeError(f"StockEagle250 V5 identity mismatch: {mismatches}")
    if contract.get("created_before_v5_results") is not True:
        raise RuntimeError("V5 contract was not marked preregistered")

    motivation = contract["scientific_motivation"]
    if "do not create another tuned generation" not in motivation.get(
        "stopping_rule", ""
    ):
        raise RuntimeError("V5 stopping rule is missing")

    candidate = contract["fixed_candidate"]
    if candidate.get("candidate_id") != V5_CANDIDATE:
        raise RuntimeError("Unexpected V5 candidate identity")
    if candidate.get("ranking_source") != V1_RANKING_CANDIDATE:
        raise RuntimeError("V5 ranking source is not the fixed V1 Ridge ranker")
    if candidate.get("risk_signal_family") != (
        "causal_full_exposure_v1_shadow_account_drawdown"
    ):
        raise RuntimeError("V5 risk signal family differs from preregistration")

    shadow = candidate["shadow_account"]
    expected_shadow = {
        "starting_equity": 100000,
        "sleeve_count": SLEEVE_COUNT,
        "reference_cost_bps_per_side": 10,
        "fold_state_reset": True,
        "completion_rule":
            "target_endpoint_utc_5d_strictly_less_than_current_decision_timestamp",
        "same_session_completion_visible": False,
        "apply_each_cohort_once": True,
        "sleeve_assignment": "original_decision_order_index_modulo_5",
        "peak_reference":
            "maximum_completed_shadow_equity_observed_before_current_decision",
    }
    if any(shadow.get(key) != value for key, value in expected_shadow.items()):
        raise RuntimeError("V5 shadow-account contract differs from code")

    if candidate.get("gross_exposure_rule") != (
        "clip(1.0 - 2.5 * abs(shadow_drawdown), 0.5, 1.0)"
    ):
        raise RuntimeError("V5 exposure formula differs from preregistration")
    if float(candidate.get("minimum_gross_exposure")) != MINIMUM_GROSS_EXPOSURE:
        raise RuntimeError("V5 minimum exposure differs from code")
    if float(candidate.get("maximum_gross_exposure")) != MAXIMUM_GROSS_EXPOSURE:
        raise RuntimeError("V5 maximum exposure differs from code")
    if candidate.get("spy_trend_used") is not False:
        raise RuntimeError("V5 must not use SPY trend")
    if candidate.get("spy_volatility_used") is not False:
        raise RuntimeError("V5 must not use SPY volatility")
    if candidate.get("prediction_confidence_used") is not False:
        raise RuntimeError("V5 must not use prediction confidence")
    if any(candidate.get(key) is not False for key in (
        "threshold_search",
        "exposure_search",
        "model_search",
        "hyperparameter_search",
    )):
        raise RuntimeError("V5 contract permits a prohibited search")

    boundaries = contract["data_boundaries"]
    if _utc(boundaries["sealed_guard_band_start_utc"]) != GUARD_BAND_START_UTC:
        raise RuntimeError("V5 guard-band start differs from code")
    if _utc(boundaries["new_untouched_future_start_utc"]) != FUTURE_START_UTC:
        raise RuntimeError("V5 future boundary differs from code")
    if (
        _utc(boundaries["maximum_development_target_endpoint_utc"])
        != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC
    ):
        raise RuntimeError("V5 development endpoint differs from code")

    gates = contract["preregistered_development_gates"]
    if gates.get("policy") != "reuse_v2_v3_v4_gates_without_relaxation":
        raise RuntimeError("V5 gate policy was changed")
    if set(gates) - {"policy"} != EXPECTED_GATE_KEYS:
        raise RuntimeError("V5 preregistered gate set is incomplete or changed")

    authority = contract["authority"]
    if any(authority.get(key) is not False for key in (
        "model_freezing_enabled",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
    )):
        raise RuntimeError("V5 Phase 1 has trading or freezing authority")
    return contract


def validate_v4_evidence(
    manifest: dict,
    qualification: dict,
) -> dict:
    problems = []
    if manifest.get("research_version") != V4_RESEARCH_VERSION:
        problems.append("unexpected V4 research version")
    if manifest.get("phase") != 2:
        problems.append("V4 evidence is not Phase 2")
    if manifest.get("candidate_id") != V4_CANDIDATE:
        problems.append("unexpected V4 candidate")
    if manifest.get("guard_band_rows_read") != 0:
        problems.append("V4 reports guard-band rows")
    if manifest.get("future_rows_read") != 0:
        problems.append("V4 reports future rows")

    safety = manifest.get("safety", {})
    if any(safety.get(key) is not False for key in (
        "future_holdout_scored",
        "candidate_frozen",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
    )):
        problems.append("V4 evidence reports forbidden activity")

    if qualification.get("candidate_id") != V4_CANDIDATE:
        problems.append("V4 qualification candidate differs")
    if qualification.get("status") != "REJECT_CURRENT_STOCK_EAGLE_250_V4_CANDIDATE":
        problems.append("V4 is not preserved as rejected")
    if qualification.get("qualified_for_human_review") is not False:
        problems.append("V4 unexpectedly qualified for human review")
    if qualification.get("gates_passed") != 8 or qualification.get("gates_total") != 11:
        problems.append("V4 gate count differs from preserved result")
    failed = set(qualification.get("failed_gates", []))
    if failed != EXPECTED_V4_FAILED_GATES:
        problems.append("V4 failed-gate set differs from preserved result")

    if problems:
        raise RuntimeError(
            "StockEagle250 V5 rejected its V4 evidence:\n- "
            + "\n- ".join(problems)
        )

    summary = manifest.get("summary", {})
    return {
        "v4_status": qualification["status"],
        "v4_gates_passed": int(qualification["gates_passed"]),
        "v4_gates_total": int(qualification["gates_total"]),
        "v4_failed_gates": sorted(failed),
        "v4_median_fold_excess_vs_v1_ridge":
            float(summary["median_fold_excess_vs_v1_ridge"]),
        "v4_median_drawdown_improvement_vs_v1_ridge":
            float(summary["median_fold_drawdown_improvement_vs_v1_ridge"]),
        "v4_drawdown_improvement_fold_fraction":
            float(summary["drawdown_improvement_fold_fraction"]),
        "v4_median_fold_calmar": float(summary["median_fold_calmar"]),
        "v1_ridge_median_fold_calmar":
            float(summary["median_v1_ridge_calmar"]),
        "v4_median_gross_exposure":
            float(summary["median_gross_exposure"]),
    }


def validate_v1_period_source(periods: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    missing = sorted(REQUIRED_PERIOD_COLUMNS - set(periods.columns))
    if missing:
        raise RuntimeError(f"V1 period source is missing columns: {missing}")

    ridge = periods.loc[
        periods["portfolio_id"] == V1_RANKING_CANDIDATE
    ].copy()
    problems = []
    if ridge.empty:
        problems.append("saved V1 Ridge periods are empty")

    for column in (
        "timestamp_utc",
        "entry_timestamp_utc_5d",
        "target_endpoint_utc_5d",
    ):
        ridge[column] = pd.to_datetime(ridge[column], utc=True)
        if (ridge[column] >= GUARD_BAND_START_UTC).any():
            problems.append(f"{column} enters the sealed guard band")

    if ridge["fold_id"].nunique() != 14:
        problems.append("saved V1 Ridge periods do not contain 14 folds")
    if ridge.duplicated(["fold_id", "timestamp_utc"]).any():
        problems.append("duplicate V1 Ridge fold/timestamp periods")
    if (
        pd.to_numeric(ridge["selected_count"], errors="coerce")
        != POSITIONS_PER_COHORT
    ).any():
        problems.append("a V1 Ridge period does not contain exactly ten stocks")

    for column in ("gross_return", "net_return"):
        values = pd.to_numeric(ridge[column], errors="coerce")
        if not np.isfinite(values).all():
            problems.append(f"non-finite saved V1 Ridge {column}")

    expected_net = (
        (1.0 + pd.to_numeric(ridge["gross_return"], errors="coerce"))
        * (1.0 - PRIMARY_COST_BPS_PER_SIDE / 10_000.0) ** 2
        - 1.0
    )
    if not np.allclose(
        expected_net,
        pd.to_numeric(ridge["net_return"], errors="coerce"),
        rtol=0.0,
        atol=1e-12,
    ):
        problems.append("saved V1 Ridge costs differ from fixed 10-bps source")

    if not ridge.empty:
        if ridge["timestamp_utc"].max() != MAXIMUM_DEVELOPMENT_DECISION_UTC:
            problems.append("V1 Ridge source lacks the fixed final decision date")
        if ridge["target_endpoint_utc_5d"].max() != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC:
            problems.append("V1 Ridge source lacks the fixed final target endpoint")

    if problems:
        raise RuntimeError(
            "StockEagle250 V5 rejected its V1 period source:\n- "
            + "\n- ".join(problems)
        )

    summary = {
        "source_rows": int(len(ridge)),
        "fold_count": int(ridge["fold_id"].nunique()),
        "development_decision_start_utc": ridge["timestamp_utc"].min().isoformat(),
        "development_decision_end_utc": ridge["timestamp_utc"].max().isoformat(),
        "maximum_development_target_endpoint_utc":
            ridge["target_endpoint_utc_5d"].max().isoformat(),
        "minimum_selected_count": int(ridge["selected_count"].min()),
        "maximum_selected_count": int(ridge["selected_count"].max()),
    }
    return ridge, summary


def self_drawdown_exposure_frame(
    ridge_periods: pd.DataFrame,
) -> pd.DataFrame:
    """Build causal V5 exposure from only strictly prior completed V1 cohorts."""
    required = REQUIRED_PERIOD_COLUMNS
    missing = sorted(required - set(ridge_periods.columns))
    if missing:
        raise ValueError(f"V1 Ridge periods missing columns: {missing}")

    frame = ridge_periods.copy()
    for column in (
        "timestamp_utc",
        "entry_timestamp_utc_5d",
        "target_endpoint_utc_5d",
    ):
        frame[column] = pd.to_datetime(frame[column], utc=True)

    if (frame["timestamp_utc"] >= GUARD_BAND_START_UTC).any():
        raise RuntimeError("V5 input enters the sealed guard band")
    if (frame["target_endpoint_utc_5d"] >= GUARD_BAND_START_UTC).any():
        raise RuntimeError("V5 target endpoint enters the sealed guard band")

    side_cost = PRIMARY_COST_BPS_PER_SIDE / 10_000.0
    output = []

    for fold_id, fold in frame.groupby("fold_id", sort=True):
        fold = fold.sort_values(
            ["timestamp_utc", "target_endpoint_utc_5d"]
        ).reset_index(drop=True).copy()

        sleeves = np.full(SLEEVE_COUNT, STARTING_EQUITY / SLEEVE_COUNT)
        shadow_equity = float(STARTING_EQUITY)
        shadow_peak = float(STARTING_EQUITY)
        pending = []

        for decision_index, row in fold.iterrows():
            decision_timestamp = row["timestamp_utc"]

            completed_now = [
                item
                for item in pending
                if (
                    not item["applied"]
                    and item["target_endpoint_utc_5d"] < decision_timestamp
                )
            ]
            completed_now.sort(
                key=lambda item: (
                    item["target_endpoint_utc_5d"],
                    item["decision_index"],
                )
            )

            for item in completed_now:
                sleeves[item["sleeve_id"]] *= 1.0 + item["shadow_net_return"]
                item["applied"] = True
                shadow_equity = float(sleeves.sum())
                shadow_peak = max(shadow_peak, shadow_equity)

            shadow_equity = float(sleeves.sum())
            shadow_peak = max(shadow_peak, shadow_equity)
            shadow_drawdown = float(shadow_equity / shadow_peak - 1.0)
            exposure = float(np.clip(
                1.0 - DRAWDOWN_SLOPE * abs(shadow_drawdown),
                MINIMUM_GROSS_EXPOSURE,
                MAXIMUM_GROSS_EXPOSURE,
            ))

            output.append({
                "fold_id": fold_id,
                "timestamp_utc": decision_timestamp,
                "shadow_completed_cohort_count":
                    int(sum(bool(item["applied"]) for item in pending)),
                "shadow_equity": shadow_equity,
                "shadow_peak_equity": shadow_peak,
                "shadow_drawdown": shadow_drawdown,
                "gross_exposure": exposure,
                "cash_fraction": 1.0 - exposure,
            })

            gross_return = float(row["gross_return"])
            shadow_net_return = (
                (1.0 + gross_return)
                * (1.0 - side_cost) ** 2
                - 1.0
            )
            pending.append({
                "decision_index": int(decision_index),
                "target_endpoint_utc_5d": row["target_endpoint_utc_5d"],
                "sleeve_id": int(decision_index % SLEEVE_COUNT),
                "shadow_net_return": float(shadow_net_return),
                "applied": False,
            })

    result = pd.DataFrame(output).sort_values(
        ["fold_id", "timestamp_utc"]
    ).reset_index(drop=True)

    if not result["gross_exposure"].between(
        MINIMUM_GROSS_EXPOSURE,
        MAXIMUM_GROSS_EXPOSURE,
    ).all():
        raise RuntimeError("V5 exposure is outside [0.5, 1.0]")
    if (result["shadow_drawdown"] > 1e-12).any():
        raise RuntimeError("V5 shadow drawdown became positive")
    return result


def build_manifest(
    contract: dict,
    v4_evidence: dict,
    source_summary: dict,
) -> dict:
    return {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "preregistered_causal_self_drawdown_throttle_readiness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": V5_CANDIDATE,
        "candidate_count": 1,
        "ranking_source": V1_RANKING_CANDIDATE,
        "risk_signal_family":
            "causal_full_exposure_v1_shadow_account_drawdown",
        "contract_sha256": _sha256(CONTRACT_PATH),
        "v4_development_evidence": v4_evidence,
        "source": source_summary,
        "sealed_guard_band_start_utc": GUARD_BAND_START_UTC.isoformat(),
        "sealed_guard_band_end_exclusive_utc": FUTURE_START_UTC.isoformat(),
        "new_untouched_future_start_utc": FUTURE_START_UTC.isoformat(),
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v5_performance_calculated": False,
        "qualification_gates_fixed_before_v5_results": bool(
            contract["created_before_v5_results"]
        ),
        "gate_policy": contract["preregistered_development_gates"]["policy"],
        "stopping_rule": contract["scientific_motivation"]["stopping_rule"],
        "safety": {
            "v1_artifacts_modified": False,
            "v2_artifacts_modified": False,
            "v3_artifacts_modified": False,
            "v4_artifacts_modified": False,
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
            "this one fixed causal self-drawdown throttle on the same saved V1 "
            "out-of-sample development portfolio periods at 10-bps primary and "
            "20-bps stress costs. Do not read September 23 or later. If the "
            "candidate fails the unchanged gates, stop development iteration "
            "on this sample."
        ),
    }


def run(
    periods_path: Path = V1_PERIODS_PATH,
    v4_manifest_path: Path = V4_MANIFEST_PATH,
    v4_qualification_path: Path = V4_QUALIFICATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    v4_manifest = json.loads(
        Path(v4_manifest_path).read_text(encoding="utf-8")
    )
    v4_qualification = json.loads(
        Path(v4_qualification_path).read_text(encoding="utf-8")
    )
    v4_evidence = validate_v4_evidence(v4_manifest, v4_qualification)

    periods = pd.read_parquet(periods_path)
    _ridge, source_summary = validate_v1_period_source(periods)

    payload = build_manifest(contract, v4_evidence, source_summary)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=Path, default=V1_PERIODS_PATH)
    parser.add_argument("--v4-manifest", type=Path, default=V4_MANIFEST_PATH)
    parser.add_argument(
        "--v4-qualification",
        type=Path,
        default=V4_QUALIFICATION_PATH,
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        periods_path=args.periods,
        v4_manifest_path=args.v4_manifest,
        v4_qualification_path=args.v4_qualification,
        output_root=args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
