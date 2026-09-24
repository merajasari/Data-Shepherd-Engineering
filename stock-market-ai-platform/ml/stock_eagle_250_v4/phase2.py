"""StockEagle250 V4 Phase 2: fixed confidence-conditioned development evaluation.

Consumes the saved StockEagle250 V1 Ridge out-of-sample predictions and portfolio
periods. Exposure is determined only by the Phase-1-preregistered cross-sectional
Ridge-confidence rule. There is no model refit, threshold search, exposure search,
SPY regime input, or use of rows from the September 23 guard band or October 1
future sample.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v4 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250_v4.phase1 import (
    CONTRACT_PATH,
    FUTURE_START_UTC,
    GUARD_BAND_START_UTC,
    MANIFEST_PATH as PHASE1_MANIFEST_PATH,
    MAXIMUM_GROSS_EXPOSURE,
    MINIMUM_GROSS_EXPOSURE,
    V1_PREDICTION_COLUMN,
    V1_PREDICTIONS_PATH,
    V1_RANKING_CANDIDATE,
    V4_CANDIDATE,
    _sha256,
    confidence_exposure_frame,
    load_contract,
    validate_prediction_source,
)


PHASE = 2
V1_PHASE3_ROOT = Path("data/model/stock_eagle_250/phase3")
V1_PERIODS_PATH = V1_PHASE3_ROOT / "portfolio_periods.parquet"
V1_FOLD_METRICS_PATH = V1_PHASE3_ROOT / "fold_metrics.csv"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_v4/phase2")
PERIOD_RESULTS_PATH = OUTPUT_ROOT / "period_results.parquet"
CONFIDENCE_SERIES_PATH = OUTPUT_ROOT / "confidence_series.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
CONFIDENCE_SUMMARY_PATH = OUTPUT_ROOT / "confidence_summary.csv"
YEAR_SUMMARY_PATH = OUTPUT_ROOT / "year_summary.csv"
GATE_RESULTS_PATH = OUTPUT_ROOT / "gate_results.csv"
QUALIFICATION_PATH = OUTPUT_ROOT / "qualification.json"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

PRIMARY_COST_BPS_PER_SIDE = 10.0
STRESS_COST_BPS_PER_SIDE = 20.0
STARTING_EQUITY = 100_000.0
SLEEVE_COUNT = 5
POSITIONS_PER_COHORT = 10
EXPECTED_FOLD_COUNT = 14

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
REQUIRED_V1_METRIC_COLUMNS = {
    "fold_id",
    "candidate_id",
    "net_return",
    "maximum_drawdown",
    "spy_net_return",
    "equal_weight_net_return",
}


def validate_sources(
    predictions: pd.DataFrame,
    periods: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    phase1_manifest: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    problems = []
    if phase1_manifest.get("research_version") != RESEARCH_VERSION:
        problems.append("unexpected Phase 1 research version")
    if phase1_manifest.get("candidate_id") != V4_CANDIDATE:
        problems.append("unexpected Phase 1 candidate")
    if phase1_manifest.get("guard_band_rows_read") != 0:
        problems.append("Phase 1 reports guard-band rows")
    if phase1_manifest.get("future_rows_read") != 0:
        problems.append("Phase 1 reports future rows")
    if phase1_manifest.get("v4_performance_calculated") is not False:
        problems.append("Phase 1 already reports V4 performance")
    if phase1_manifest.get("contract_sha256") != _sha256(CONTRACT_PATH):
        problems.append("Phase 1 contract hash differs from the current contract")
    if phase1_manifest.get("gate_policy") != "reuse_v2_v3_gates_without_relaxation":
        problems.append("Phase 1 gate policy differs from preregistration")

    missing_periods = sorted(REQUIRED_PERIOD_COLUMNS - set(periods.columns))
    missing_metrics = sorted(REQUIRED_V1_METRIC_COLUMNS - set(fold_metrics.columns))
    if missing_periods:
        problems.append(f"V1 periods missing columns: {missing_periods}")
    if missing_metrics:
        problems.append(f"V1 fold metrics missing columns: {missing_metrics}")

    # Revalidate the exact V1 OOS prediction source used to derive confidence.
    if not problems:
        validate_prediction_source(predictions)

    if problems:
        raise RuntimeError(
            "StockEagle250 V4 source validation failed:\n- "
            + "\n- ".join(problems)
        )

    ridge = periods.loc[
        periods["portfolio_id"] == V1_RANKING_CANDIDATE
    ].copy()
    metrics = fold_metrics.loc[
        fold_metrics["candidate_id"] == V1_RANKING_CANDIDATE
    ].copy()

    if ridge.empty:
        problems.append("saved V1 Ridge periods are empty")
    if ridge["fold_id"].nunique() != EXPECTED_FOLD_COUNT:
        problems.append("saved V1 Ridge periods do not contain 14 folds")
    if metrics["fold_id"].nunique() != EXPECTED_FOLD_COUNT:
        problems.append("saved V1 Ridge metrics do not contain 14 folds")
    if ridge.duplicated(["fold_id", "timestamp_utc"]).any():
        problems.append("duplicate V1 Ridge fold/timestamp periods")
    if (
        pd.to_numeric(ridge["selected_count"], errors="coerce")
        != POSITIONS_PER_COHORT
    ).any():
        problems.append("a V1 Ridge period does not contain exactly ten stocks")

    for column in (
        "timestamp_utc",
        "entry_timestamp_utc_5d",
        "target_endpoint_utc_5d",
    ):
        ridge[column] = pd.to_datetime(ridge[column], utc=True)
        if (ridge[column] >= GUARD_BAND_START_UTC).any():
            problems.append(f"{column} enters the sealed guard band")

    for column in ("gross_return", "net_return"):
        if not np.isfinite(
            pd.to_numeric(ridge[column], errors="coerce")
        ).all():
            problems.append(f"non-finite saved V1 Ridge {column}")

    expected_net = (
        (1.0 + ridge["gross_return"].astype(float))
        * (1.0 - PRIMARY_COST_BPS_PER_SIDE / 10_000.0) ** 2
        - 1.0
    )
    if not np.allclose(
        expected_net,
        ridge["net_return"].astype(float),
        rtol=0.0,
        atol=1e-12,
    ):
        problems.append("saved V1 Ridge costs differ from the fixed 10-bps contract")
    if set(ridge["fold_id"]) != set(metrics["fold_id"]):
        problems.append("V1 period folds and metric folds differ")

    # Confirm the saved V1 portfolio really is the top-10 Ridge ranking used by V4.
    prediction_frame = predictions.copy()
    prediction_frame["timestamp_utc"] = pd.to_datetime(
        prediction_frame["timestamp_utc"],
        utc=True,
    )
    prediction_frame[V1_PREDICTION_COLUMN] = pd.to_numeric(
        prediction_frame[V1_PREDICTION_COLUMN],
        errors="coerce",
    )
    selected = (
        prediction_frame.sort_values(
            ["timestamp_utc", V1_PREDICTION_COLUMN, "symbol"],
            ascending=[True, False, True],
        )
        .groupby("timestamp_utc", sort=False)
        .head(POSITIONS_PER_COHORT)
        .groupby("timestamp_utc", sort=True)["symbol"]
        .agg(lambda values: frozenset(map(str, values)))
    )
    saved = ridge.set_index("timestamp_utc")["selected_symbols"].map(
        lambda value: frozenset(
            token.strip()
            for token in str(value).split(",")
            if token.strip()
        )
    )
    if not saved.index.isin(selected.index).all():
        problems.append("V1 Ridge periods include timestamps missing from predictions")
    else:
        mismatched = [
            timestamp
            for timestamp, symbols in saved.items()
            if symbols != selected.loc[timestamp]
        ]
        if mismatched:
            problems.append(
                f"saved V1 Ridge selection differs from top-10 predictions at "
                f"{mismatched[0]}"
            )

    if problems:
        raise RuntimeError(
            "StockEagle250 V4 source validation failed:\n- "
            + "\n- ".join(problems)
        )

    confidence = confidence_exposure_frame(predictions)
    return ridge, metrics, confidence


def attach_confidence_exposure(
    ridge_periods: pd.DataFrame,
    confidence: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "timestamp_utc",
        "fold_id",
        "eligible_symbols",
        "top10_mean_prediction",
        "ranks_11_20_mean_prediction",
        "selection_margin",
        "cross_sectional_prediction_mad",
        "standardized_confidence",
        "prior_confidence_count",
        "confidence_percentile",
        "gross_exposure",
        "cash_fraction",
    ]
    confidence = confidence[columns].copy()
    confidence["timestamp_utc"] = pd.to_datetime(
        confidence["timestamp_utc"],
        utc=True,
    )
    confidence = confidence.rename(columns={"fold_id": "confidence_fold_id"})

    merged = ridge_periods.merge(
        confidence,
        on="timestamp_utc",
        how="left",
        validate="one_to_one",
    )
    if merged["gross_exposure"].isna().any():
        first = merged.loc[
            merged["gross_exposure"].isna(),
            "timestamp_utc",
        ].min()
        raise RuntimeError(f"Missing V4 confidence exposure for V1 decision {first}")
    if (
        merged["confidence_fold_id"].astype(str)
        != merged["fold_id"].astype(str)
    ).any():
        raise RuntimeError("V4 confidence fold differs from V1 portfolio fold")
    if not merged["gross_exposure"].between(
        MINIMUM_GROSS_EXPOSURE,
        MAXIMUM_GROSS_EXPOSURE,
    ).all():
        raise RuntimeError("V4 confidence exposure is outside [0.5, 1.0]")
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
    confidence_periods: pd.DataFrame,
    v1_metrics: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    metric_lookup = v1_metrics.set_index("fold_id")
    period_frames = []
    rows = []

    for fold_id, fold in confidence_periods.groupby("fold_id", sort=True):
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

        primary.insert(1, "evaluation", "v4_primary_10bps")
        stress.insert(1, "evaluation", "v4_stress_20bps")
        period_frames.extend([primary, stress])

        ready = pd.to_numeric(
            fold["confidence_percentile"],
            errors="coerce",
        ).notna()
        rows.append({
            "fold_id": fold_id,
            "decision_count": p["decision_count"],
            "confidence_ready_fraction": float(ready.mean()),
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
            "equal_weight_net_return": float(recorded["equal_weight_net_return"]),
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
        "median_confidence_ready_fraction":
            float(fold_metrics["confidence_ready_fraction"].median()),
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
            else "REJECT_CURRENT_STOCK_EAGLE_250_V4_CANDIDATE"
        ),
        "candidate_id": V4_CANDIDATE,
        "gates_passed": passed,
        "gates_total": total,
        "failed_gates": [
            gate for gate, result in values.items() if not result
        ],
        "qualified_for_human_review": qualified,
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
        periods["evaluation"] == "v4_primary_10bps"
    ].copy()

    percentile = pd.to_numeric(
        primary["confidence_percentile"],
        errors="coerce",
    )
    primary["confidence_band"] = pd.cut(
        percentile,
        bins=[-1e-12, 0.2, 0.4, 0.6, 0.8, 1.000000001],
        labels=["P00_20", "P20_40", "P40_60", "P60_80", "P80_100"],
        include_lowest=True,
    )
    primary.loc[
        percentile.isna(),
        "confidence_band",
    ] = "NOT_READY"

    confidence_summary = (
        primary.groupby("confidence_band", observed=True, sort=False)
        .agg(
            periods=("net_return", "size"),
            mean_gross_exposure=("gross_exposure", "mean"),
            mean_standardized_confidence=("standardized_confidence", "mean"),
            mean_unscaled_ridge_return=("gross_return", "mean"),
            mean_v4_net_return=("net_return", "mean"),
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
            confidence_ready_fraction=(
                "confidence_percentile",
                lambda x: float(pd.to_numeric(x, errors="coerce").notna().mean()),
            ),
            mean_gross_exposure=("gross_exposure", "mean"),
            mean_v4_net_return=("net_return", "mean"),
            positive_period_fraction=(
                "net_return",
                lambda x: float((x > 0.0).mean()),
            ),
        )
        .reset_index()
    )
    return confidence_summary, year


def run(
    predictions_path: Path = V1_PREDICTIONS_PATH,
    periods_path: Path = V1_PERIODS_PATH,
    fold_metrics_path: Path = V1_FOLD_METRICS_PATH,
    phase1_manifest_path: Path = PHASE1_MANIFEST_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    phase1_manifest = json.loads(
        Path(phase1_manifest_path).read_text(encoding="utf-8")
    )
    predictions = pd.read_parquet(predictions_path)
    periods = pd.read_parquet(periods_path)
    v1_fold_metrics = pd.read_csv(fold_metrics_path)

    ridge, v1_metrics, confidence = validate_sources(
        predictions,
        periods,
        v1_fold_metrics,
        phase1_manifest,
    )
    confidence_periods = attach_confidence_exposure(ridge, confidence)
    period_results, fold_results = evaluate_folds(
        confidence_periods,
        v1_metrics,
    )
    gates, summary, qualification = evaluate_gates(
        fold_results,
        contract,
    )
    confidence_summary, year = diagnostic_summaries(period_results)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    period_results.to_parquet(
        output_root / "period_results.parquet",
        index=False,
    )
    confidence.to_parquet(
        output_root / "confidence_series.parquet",
        index=False,
    )
    fold_results.to_csv(output_root / "fold_metrics.csv", index=False)
    confidence_summary.to_csv(
        output_root / "confidence_summary.csv",
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
        "stage": "fixed_cross_sectional_confidence_development_evaluation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": V4_CANDIDATE,
        "ranking_source": V1_RANKING_CANDIDATE,
        "prediction_source": V1_PREDICTION_COLUMN,
        "spy_trend_used": False,
        "spy_volatility_used": False,
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
        "outputs": {
            "period_results": str(output_root / "period_results.parquet"),
            "confidence_series": str(output_root / "confidence_series.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "confidence_summary": str(output_root / "confidence_summary.csv"),
            "year_summary": str(output_root / "year_summary.csv"),
            "gate_results": str(output_root / "gate_results.csv"),
            "qualification": str(output_root / "qualification.json"),
        },
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
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=V1_PREDICTIONS_PATH)
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
        predictions_path=args.predictions,
        periods_path=args.periods,
        fold_metrics_path=args.fold_metrics,
        phase1_manifest_path=args.phase1_manifest,
        output_root=args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
