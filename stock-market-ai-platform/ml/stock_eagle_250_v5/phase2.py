"""StockEagle250 V5 Phase 2: fixed causal self-drawdown evaluation.

Consumes the exact saved StockEagle250 V1 Ridge out-of-sample portfolio periods
and applies the single Phase-1-preregistered self-drawdown throttle. The risk
state uses only strictly prior completed V1-equivalent cohorts. There is no
model refit, threshold search, exposure search, SPY input, confidence input, or
use of rows from the September 23 guard band or October 1 future sample.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v5 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250_v5.phase1 import (
    CONTRACT_PATH,
    FUTURE_START_UTC,
    GUARD_BAND_START_UTC,
    MANIFEST_PATH as PHASE1_MANIFEST_PATH,
    MAXIMUM_GROSS_EXPOSURE,
    MINIMUM_GROSS_EXPOSURE,
    PRIMARY_COST_BPS_PER_SIDE,
    SLEEVE_COUNT,
    STARTING_EQUITY,
    STRESS_COST_BPS_PER_SIDE,
    V1_PERIODS_PATH,
    V1_RANKING_CANDIDATE,
    V5_CANDIDATE,
    _sha256,
    load_contract,
    self_drawdown_exposure_frame,
    validate_v1_period_source,
)


PHASE = 2
V1_PHASE3_ROOT = Path("data/model/stock_eagle_250/phase3")
V1_FOLD_METRICS_PATH = V1_PHASE3_ROOT / "fold_metrics.csv"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_v5/phase2")
PERIOD_RESULTS_PATH = OUTPUT_ROOT / "period_results.parquet"
RISK_STATE_PATH = OUTPUT_ROOT / "risk_state.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
DRAWDOWN_SUMMARY_PATH = OUTPUT_ROOT / "drawdown_summary.csv"
YEAR_SUMMARY_PATH = OUTPUT_ROOT / "year_summary.csv"
GATE_RESULTS_PATH = OUTPUT_ROOT / "gate_results.csv"
QUALIFICATION_PATH = OUTPUT_ROOT / "qualification.json"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

EXPECTED_FOLD_COUNT = 14
REQUIRED_V1_METRIC_COLUMNS = {
    "fold_id",
    "candidate_id",
    "net_return",
    "maximum_drawdown",
    "spy_net_return",
    "equal_weight_net_return",
}


def validate_sources(
    periods: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    phase1_manifest: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    problems = []
    if phase1_manifest.get("research_version") != RESEARCH_VERSION:
        problems.append("unexpected Phase 1 research version")
    if phase1_manifest.get("candidate_id") != V5_CANDIDATE:
        problems.append("unexpected Phase 1 candidate")
    if phase1_manifest.get("guard_band_rows_read") != 0:
        problems.append("Phase 1 reports guard-band rows")
    if phase1_manifest.get("future_rows_read") != 0:
        problems.append("Phase 1 reports future rows")
    if phase1_manifest.get("v5_performance_calculated") is not False:
        problems.append("Phase 1 already reports V5 performance")
    if phase1_manifest.get("contract_sha256") != _sha256(CONTRACT_PATH):
        problems.append("Phase 1 contract hash differs from the current contract")
    if phase1_manifest.get("gate_policy") != (
        "reuse_v2_v3_v4_gates_without_relaxation"
    ):
        problems.append("Phase 1 gate policy differs from preregistration")

    missing_metrics = sorted(
        REQUIRED_V1_METRIC_COLUMNS - set(fold_metrics.columns)
    )
    if missing_metrics:
        problems.append(f"V1 fold metrics missing columns: {missing_metrics}")

    if problems:
        raise RuntimeError(
            "StockEagle250 V5 source validation failed:\n- "
            + "\n- ".join(problems)
        )

    ridge, _source_summary = validate_v1_period_source(periods)
    metrics = fold_metrics.loc[
        fold_metrics["candidate_id"] == V1_RANKING_CANDIDATE
    ].copy()

    if metrics["fold_id"].nunique() != EXPECTED_FOLD_COUNT:
        problems.append("saved V1 Ridge metrics do not contain 14 folds")
    if set(ridge["fold_id"]) != set(metrics["fold_id"]):
        problems.append("V1 period folds and metric folds differ")

    if problems:
        raise RuntimeError(
            "StockEagle250 V5 source validation failed:\n- "
            + "\n- ".join(problems)
        )

    risk_state = self_drawdown_exposure_frame(ridge)
    return ridge, metrics, risk_state


def attach_risk_state(
    ridge_periods: pd.DataFrame,
    risk_state: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "fold_id",
        "timestamp_utc",
        "shadow_completed_cohort_count",
        "shadow_equity",
        "shadow_peak_equity",
        "shadow_drawdown",
        "gross_exposure",
        "cash_fraction",
    ]
    state = risk_state[columns].copy()
    state["timestamp_utc"] = pd.to_datetime(state["timestamp_utc"], utc=True)
    state = state.rename(columns={"fold_id": "risk_fold_id"})

    periods = ridge_periods.copy()
    periods["timestamp_utc"] = pd.to_datetime(periods["timestamp_utc"], utc=True)

    merged = periods.merge(
        state,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )
    if merged["gross_exposure"].isna().any():
        first = merged.loc[
            merged["gross_exposure"].isna(),
            "timestamp_utc",
        ].min()
        raise RuntimeError(f"Missing V5 risk state for V1 decision {first}")
    if (
        merged["risk_fold_id"].astype(str)
        != merged["fold_id"].astype(str)
    ).any():
        raise RuntimeError("V5 risk-state fold differs from V1 portfolio fold")
    if not merged["gross_exposure"].between(
        MINIMUM_GROSS_EXPOSURE,
        MAXIMUM_GROSS_EXPOSURE,
    ).all():
        raise RuntimeError("V5 exposure is outside [0.5, 1.0]")
    if (pd.to_numeric(merged["shadow_drawdown"], errors="coerce") > 1e-12).any():
        raise RuntimeError("V5 shadow drawdown became positive")
    return merged


def simulate_exposure(
    periods: pd.DataFrame,
    cost_bps_per_side: float,
    exposure_column: str = "gross_exposure",
    starting_equity: float = STARTING_EQUITY,
    sleeve_count: int = SLEEVE_COUNT,
) -> tuple[pd.DataFrame, dict]:
    if cost_bps_per_side < 0:
        raise ValueError("cost_bps_per_side cannot be negative")
    if starting_equity <= 0 or sleeve_count < 1:
        raise ValueError("invalid account configuration")

    result = periods.sort_values(
        ["timestamp_utc", "target_endpoint_utc_5d"]
    ).reset_index(drop=True).copy()
    exposure = pd.to_numeric(result[exposure_column], errors="coerce")
    gross = pd.to_numeric(result["gross_return"], errors="coerce")
    if not np.isfinite(exposure).all() or not exposure.between(0.0, 1.0).all():
        raise RuntimeError("simulation exposure is invalid")
    if not np.isfinite(gross).all():
        raise RuntimeError("simulation gross return is invalid")

    side_cost = float(cost_bps_per_side) / 10_000.0
    result["invested_gross_return"] = exposure * gross
    result["modeled_cost_rate_per_side"] = exposure * side_cost
    result["net_return"] = (
        (1.0 + result["invested_gross_return"])
        * (1.0 - result["modeled_cost_rate_per_side"]) ** 2
        - 1.0
    )

    sleeves = np.full(sleeve_count, float(starting_equity) / sleeve_count)
    account_values = [float(starting_equity)]
    sleeve_ids = []
    account_equity = []

    for index, net_return in enumerate(result["net_return"].to_numpy(float)):
        sleeve_id = index % sleeve_count
        sleeves[sleeve_id] *= 1.0 + net_return
        total = float(sleeves.sum())
        sleeve_ids.append(sleeve_id)
        account_equity.append(total)
        account_values.append(total)

    curve = pd.Series(account_values, dtype=float)
    maximum_drawdown = float((curve / curve.cummax() - 1.0).min())
    net_return = float(account_values[-1] / starting_equity - 1.0)
    years = len(result) / 252.0
    annualized_return = (
        float((1.0 + net_return) ** (1.0 / years) - 1.0)
        if years > 0 and net_return > -1.0
        else np.nan
    )
    calmar = (
        float(annualized_return / abs(maximum_drawdown))
        if np.isfinite(annualized_return) and maximum_drawdown < 0.0
        else np.nan
    )

    result["sleeve_id"] = sleeve_ids
    result["cost_bps_per_side"] = float(cost_bps_per_side)
    result["account_equity"] = account_equity

    summary = {
        "decision_count": int(len(result)),
        "ending_equity": float(account_values[-1]),
        "net_return": net_return,
        "maximum_drawdown": maximum_drawdown,
        "annualized_return": annualized_return,
        "calmar": calmar,
        "mean_gross_exposure": float(exposure.mean()),
        "cash_fraction": float(1.0 - exposure.mean()),
    }
    return result, summary


def evaluate_folds(
    risk_periods: pd.DataFrame,
    v1_metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    metric_lookup = v1_metrics.set_index("fold_id")
    period_frames = []
    rows = []

    for fold_id, fold in risk_periods.groupby("fold_id", sort=True):
        primary, p = simulate_exposure(fold, PRIMARY_COST_BPS_PER_SIDE)
        stress, s = simulate_exposure(fold, STRESS_COST_BPS_PER_SIDE)

        v1_input = fold.copy()
        v1_input["v1_full_exposure"] = 1.0
        _, v1 = simulate_exposure(
            v1_input,
            PRIMARY_COST_BPS_PER_SIDE,
            exposure_column="v1_full_exposure",
        )
        recorded = metric_lookup.loc[fold_id]
        if not np.isclose(
            v1["net_return"],
            float(recorded["net_return"]),
            atol=1e-12,
        ):
            raise RuntimeError(f"{fold_id} V1 Ridge return does not reproduce")
        if not np.isclose(
            v1["maximum_drawdown"],
            float(recorded["maximum_drawdown"]),
            atol=1e-12,
        ):
            raise RuntimeError(f"{fold_id} V1 Ridge drawdown does not reproduce")

        primary.insert(1, "evaluation", "v5_primary_10bps")
        stress.insert(1, "evaluation", "v5_stress_20bps")
        period_frames.extend([primary, stress])

        rows.append({
            "fold_id": fold_id,
            "decision_count": p["decision_count"],
            "mean_shadow_drawdown":
                float(pd.to_numeric(fold["shadow_drawdown"]).mean()),
            "worst_shadow_drawdown":
                float(pd.to_numeric(fold["shadow_drawdown"]).min()),
            "mean_gross_exposure": p["mean_gross_exposure"],
            "cash_fraction": p["cash_fraction"],
            "primary_net_return": p["net_return"],
            "primary_maximum_drawdown": p["maximum_drawdown"],
            "primary_annualized_return": p["annualized_return"],
            "primary_calmar": p["calmar"],
            "stress_20bps_net_return": s["net_return"],
            "stress_20bps_maximum_drawdown": s["maximum_drawdown"],
            "v1_ridge_net_return": v1["net_return"],
            "v1_ridge_maximum_drawdown": v1["maximum_drawdown"],
            "v1_ridge_annualized_return": v1["annualized_return"],
            "v1_ridge_calmar": v1["calmar"],
            "spy_net_return": float(recorded["spy_net_return"]),
            "equal_weight_net_return":
                float(recorded["equal_weight_net_return"]),
            "excess_vs_spy":
                p["net_return"] - float(recorded["spy_net_return"]),
            "excess_vs_equal_weight":
                p["net_return"] - float(recorded["equal_weight_net_return"]),
            "excess_vs_v1_ridge": p["net_return"] - v1["net_return"],
            "drawdown_improvement_vs_v1_ridge":
                p["maximum_drawdown"] - v1["maximum_drawdown"],
        })

    return pd.concat(period_frames, ignore_index=True), pd.DataFrame(rows)


def evaluate_gates(
    fold_metrics: pd.DataFrame,
    contract: dict,
) -> tuple[pd.DataFrame, dict, dict]:
    thresholds = contract["preregistered_development_gates"]
    summary = {
        "fold_count": int(fold_metrics["fold_id"].nunique()),
        "median_fold_primary_net_return":
            float(fold_metrics["primary_net_return"].median()),
        "positive_primary_fold_fraction":
            float((fold_metrics["primary_net_return"] > 0.0).mean()),
        "median_fold_excess_vs_spy":
            float(fold_metrics["excess_vs_spy"].median()),
        "positive_excess_vs_spy_fold_fraction":
            float((fold_metrics["excess_vs_spy"] > 0.0).mean()),
        "median_fold_excess_vs_equal_weight":
            float(fold_metrics["excess_vs_equal_weight"].median()),
        "median_fold_excess_vs_v1_ridge":
            float(fold_metrics["excess_vs_v1_ridge"].median()),
        "worst_fold_maximum_drawdown":
            float(fold_metrics["primary_maximum_drawdown"].min()),
        "median_fold_drawdown_improvement_vs_v1_ridge":
            float(fold_metrics["drawdown_improvement_vs_v1_ridge"].median()),
        "drawdown_improvement_fold_fraction":
            float(
                (fold_metrics["drawdown_improvement_vs_v1_ridge"] > 0.0).mean()
            ),
        "median_fold_calmar": float(fold_metrics["primary_calmar"].median()),
        "median_v1_ridge_calmar":
            float(fold_metrics["v1_ridge_calmar"].median()),
        "median_fold_stress_20bps_net_return":
            float(fold_metrics["stress_20bps_net_return"].median()),
        "median_gross_exposure":
            float(fold_metrics["mean_gross_exposure"].median()),
        "median_worst_shadow_drawdown":
            float(fold_metrics["worst_shadow_drawdown"].median()),
    }

    values = {
        "gate_median_fold_primary_net_return_gt_zero":
            summary["median_fold_primary_net_return"]
            > float(thresholds["median_fold_primary_net_return_gt"]),
        "gate_positive_primary_fold_fraction_gte_70pct":
            summary["positive_primary_fold_fraction"]
            >= float(thresholds["positive_primary_fold_fraction_gte"]),
        "gate_median_fold_excess_vs_spy_gt_zero":
            summary["median_fold_excess_vs_spy"]
            > float(thresholds["median_fold_excess_vs_spy_gt"]),
        "gate_positive_excess_vs_spy_fold_fraction_gte_60pct":
            summary["positive_excess_vs_spy_fold_fraction"]
            >= float(thresholds["positive_excess_vs_spy_fold_fraction_gte"]),
        "gate_median_fold_excess_vs_equal_weight_gt_zero":
            summary["median_fold_excess_vs_equal_weight"]
            > float(thresholds["median_fold_excess_vs_equal_weight_gt"]),
        "gate_median_fold_excess_vs_v1_ridge_gte_minus_2pct":
            summary["median_fold_excess_vs_v1_ridge"]
            >= float(thresholds["median_fold_excess_vs_v1_ridge_gte"]),
        "gate_worst_fold_maximum_drawdown_gte_minus_30pct":
            summary["worst_fold_maximum_drawdown"]
            >= float(thresholds["worst_fold_maximum_drawdown_gte"]),
        "gate_median_drawdown_improvement_vs_v1_gte_5pct":
            summary["median_fold_drawdown_improvement_vs_v1_ridge"]
            >= float(
                thresholds[
                    "median_fold_drawdown_improvement_vs_v1_ridge_gte"
                ]
            ),
        "gate_drawdown_improvement_fold_fraction_gte_70pct":
            summary["drawdown_improvement_fold_fraction"]
            >= float(thresholds["drawdown_improvement_fold_fraction_gte"]),
        "gate_median_calmar_gte_v1_ridge":
            summary["median_fold_calmar"]
            >= summary["median_v1_ridge_calmar"],
        "gate_median_stress_20bps_net_return_gt_zero":
            summary["median_fold_stress_20bps_net_return"]
            > float(thresholds["median_fold_stress_20bps_net_return_gt"]),
    }

    gate_rows = pd.DataFrame([
        {"gate": gate, "passed": bool(passed)}
        for gate, passed in values.items()
    ])
    passed = int(sum(values.values()))
    total = int(len(values))
    qualified = passed == total

    qualification = {
        "status": (
            "QUALIFIES_FOR_HUMAN_REVIEW"
            if qualified
            else "REJECT_CURRENT_STOCK_EAGLE_250_V5_CANDIDATE"
        ),
        "candidate_id": V5_CANDIDATE,
        "gates_passed": passed,
        "gates_total": total,
        "failed_gates": [
            gate for gate, result in values.items() if not result
        ],
        "qualified_for_human_review": qualified,
        "development_iteration_must_stop": not qualified,
        "candidate_frozen": False,
        "paper_trading_enabled": False,
        "automatic_promotion": False,
        "brokerage_orders": False,
    }
    return gate_rows, summary, qualification


def diagnostic_summaries(
    periods: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    primary = periods.loc[
        periods["evaluation"] == "v5_primary_10bps"
    ].copy()

    drawdown = pd.to_numeric(primary["shadow_drawdown"], errors="coerce")
    primary["shadow_drawdown_band"] = pd.cut(
        drawdown,
        bins=[
            -1.000000001,
            -0.20,
            -0.15,
            -0.10,
            -0.05,
            0.000000001,
        ],
        labels=[
            "LE_MINUS_20",
            "GT_MINUS_20_TO_MINUS_15",
            "GT_MINUS_15_TO_MINUS_10",
            "GT_MINUS_10_TO_MINUS_5",
            "GT_MINUS_5_TO_0",
        ],
        include_lowest=True,
    )

    drawdown_summary = (
        primary.groupby(
            "shadow_drawdown_band",
            observed=True,
            sort=True,
        )
        .agg(
            periods=("net_return", "size"),
            mean_shadow_drawdown=("shadow_drawdown", "mean"),
            mean_gross_exposure=("gross_exposure", "mean"),
            mean_unscaled_ridge_return=("gross_return", "mean"),
            mean_v5_net_return=("net_return", "mean"),
            positive_period_fraction=(
                "net_return",
                lambda x: float((x > 0.0).mean()),
            ),
        )
        .reset_index()
    )

    primary["year"] = pd.to_datetime(
        primary["timestamp_utc"],
        utc=True,
    ).dt.year
    year = (
        primary.groupby("year", sort=True)
        .agg(
            periods=("net_return", "size"),
            mean_shadow_drawdown=("shadow_drawdown", "mean"),
            mean_gross_exposure=("gross_exposure", "mean"),
            mean_v5_net_return=("net_return", "mean"),
            positive_period_fraction=(
                "net_return",
                lambda x: float((x > 0.0).mean()),
            ),
        )
        .reset_index()
    )
    return drawdown_summary, year


def run(
    periods_path: Path = V1_PERIODS_PATH,
    fold_metrics_path: Path = V1_FOLD_METRICS_PATH,
    phase1_manifest_path: Path = PHASE1_MANIFEST_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    phase1_manifest = json.loads(
        Path(phase1_manifest_path).read_text(encoding="utf-8")
    )
    periods = pd.read_parquet(periods_path)
    v1_fold_metrics = pd.read_csv(fold_metrics_path)

    ridge, v1_metrics, risk_state = validate_sources(
        periods,
        v1_fold_metrics,
        phase1_manifest,
    )
    risk_periods = attach_risk_state(ridge, risk_state)
    period_results, fold_results = evaluate_folds(
        risk_periods,
        v1_metrics,
    )
    gates, summary, qualification = evaluate_gates(
        fold_results,
        contract,
    )
    drawdown_summary, year = diagnostic_summaries(period_results)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    period_results.to_parquet(
        output_root / "period_results.parquet",
        index=False,
    )
    risk_state.to_parquet(
        output_root / "risk_state.parquet",
        index=False,
    )
    fold_results.to_csv(output_root / "fold_metrics.csv", index=False)
    drawdown_summary.to_csv(
        output_root / "drawdown_summary.csv",
        index=False,
    )
    year.to_csv(output_root / "year_summary.csv", index=False)
    gates.to_csv(output_root / "gate_results.csv", index=False)
    (output_root / "qualification.json").write_text(
        json.dumps(qualification, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "fixed_causal_self_drawdown_development_evaluation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": V5_CANDIDATE,
        "ranking_source": V1_RANKING_CANDIDATE,
        "risk_signal_family":
            "causal_full_exposure_v1_shadow_account_drawdown",
        "fold_count": int(fold_results["fold_id"].nunique()),
        "primary_cost_bps_per_side": PRIMARY_COST_BPS_PER_SIDE,
        "stress_cost_bps_per_side": STRESS_COST_BPS_PER_SIDE,
        "minimum_gross_exposure": MINIMUM_GROSS_EXPOSURE,
        "maximum_gross_exposure": MAXIMUM_GROSS_EXPOSURE,
        "sealed_guard_band_start_utc": GUARD_BAND_START_UTC.isoformat(),
        "new_untouched_future_start_utc": FUTURE_START_UTC.isoformat(),
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": summary,
        "qualification": qualification,
        "stopping_rule": contract["scientific_motivation"]["stopping_rule"],
        "outputs": {
            "period_results": str(output_root / "period_results.parquet"),
            "risk_state": str(output_root / "risk_state.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "drawdown_summary": str(output_root / "drawdown_summary.csv"),
            "year_summary": str(output_root / "year_summary.csv"),
            "gate_results": str(output_root / "gate_results.csv"),
            "qualification": str(output_root / "qualification.json"),
        },
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
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--periods", type=Path, default=V1_PERIODS_PATH)
    parser.add_argument(
        "--fold-metrics",
        type=Path,
        default=V1_FOLD_METRICS_PATH,
    )
    parser.add_argument(
        "--phase1-manifest",
        type=Path,
        default=PHASE1_MANIFEST_PATH,
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        periods_path=args.periods,
        fold_metrics_path=args.fold_metrics,
        phase1_manifest_path=args.phase1_manifest,
        output_root=args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
