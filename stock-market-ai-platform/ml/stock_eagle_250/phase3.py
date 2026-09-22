"""StockEagle250 Phase 3: fixed learned-candidate walk-forward evaluation.

Fits only the preregistered Ridge and histogram-gradient-boosting regressors on
the 14 purged Phase 2 development folds. Each fold is scored out of sample and
evaluated with the fixed Top-10, five-overlapping-cohort portfolio at 10 bps per
side against the three registered matched baselines.

This is development evidence only. It refuses future-holdout rows, performs no
hyperparameter search, freezes no model, enables no paper or live trading, and
places no brokerage orders.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from ml.stock_eagle_250 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION
from ml.stock_eagle_250.phase2 import (
    CONTRACT_PATH as PHASE2_CONTRACT_PATH,
    ENDPOINT_COLUMN,
    FUTURE_HOLDOUT_START_UTC,
    PANEL_PATH,
    FOLDS_PATH,
    MANIFEST_PATH as PHASE2_MANIFEST_PATH,
    RANK_FEATURE_COLUMNS,
    TARGET_COLUMN,
)


PHASE = 3
PHASE3_CONTRACT_PATH = Path(__file__).with_name("phase3_contract.json")
OUTPUT_ROOT = Path("data/model/stock_eagle_250/phase3")
PREDICTIONS_PATH = OUTPUT_ROOT / "walk_forward_predictions.parquet"
PORTFOLIO_PERIODS_PATH = OUTPUT_ROOT / "portfolio_periods.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
MODEL_SUMMARY_PATH = OUTPUT_ROOT / "model_summary.csv"
GATE_RESULTS_PATH = OUTPUT_ROOT / "gate_results.csv"
QUALIFICATION_PATH = OUTPUT_ROOT / "qualification.json"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

RANDOM_STATE = 1729
POSITIONS_PER_COHORT = 10
OVERLAPPING_COHORTS = 5
STARTING_EQUITY = 100_000.0
COST_BPS_PER_SIDE = 10.0
MOMENTUM_SCORE_COLUMN = "return_20d_xrank"
CANDIDATE_IDS = ("ridge_fixed_v1", "hgb_fixed_v1")
BASELINE_IDS = (
    "spy_buy_and_hold_matched_clock",
    "equal_weight_eligible_universe",
    "cross_sectional_return_20d_rank",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def load_contracts(
    phase2_contract_path: Path = PHASE2_CONTRACT_PATH,
    phase3_contract_path: Path = PHASE3_CONTRACT_PATH,
) -> tuple[dict, dict]:
    phase2 = json.loads(Path(phase2_contract_path).read_text(encoding="utf-8"))
    phase3 = json.loads(Path(phase3_contract_path).read_text(encoding="utf-8"))

    for contract, label in ((phase2, "Phase 2"), (phase3, "Phase 3")):
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
            raise RuntimeError(f"{label} identity mismatch: {mismatches}")

    phase2_ids = tuple(
        row["candidate_id"]
        for row in phase2["development"]["model_candidates"]
    )
    phase3_ids = tuple(
        row["candidate_id"] for row in phase3["fixed_candidates"]
    )
    if phase2_ids != CANDIDATE_IDS or phase3_ids != CANDIDATE_IDS:
        raise RuntimeError("Phase 2 and Phase 3 fixed candidates differ")

    boundary = _utc(phase3["input"]["future_holdout_start_utc"])
    if boundary != FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Phase 3 holdout boundary differs from Phase 2")
    if not phase3["created_before_phase3_results"]:
        raise RuntimeError("Phase 3 contract is not preregistered")
    return phase2, phase3


def model_templates(phase3_contract: dict) -> dict:
    definitions = {
        row["candidate_id"]: row
        for row in phase3_contract["fixed_candidates"]
    }
    if tuple(definitions) != CANDIDATE_IDS:
        raise RuntimeError("Unexpected Phase 3 model candidate order")

    ridge = definitions["ridge_fixed_v1"]["parameters"]
    hgb = definitions["hgb_fixed_v1"]["parameters"]
    return {
        "ridge_fixed_v1": Ridge(
            alpha=float(ridge["alpha"]),
            fit_intercept=bool(ridge["fit_intercept"]),
        ),
        "hgb_fixed_v1": HistGradientBoostingRegressor(
            loss=hgb["loss"],
            learning_rate=float(hgb["learning_rate"]),
            max_iter=int(hgb["max_iter"]),
            max_leaf_nodes=int(hgb["max_leaf_nodes"]),
            min_samples_leaf=int(hgb["min_samples_leaf"]),
            l2_regularization=float(hgb["l2_regularization"]),
            early_stopping=bool(hgb["early_stopping"]),
            random_state=int(hgb["random_state"]),
        ),
    }


def validate_development_panel(
    panel: pd.DataFrame,
    holdout_start=FUTURE_HOLDOUT_START_UTC,
) -> None:
    holdout_start = _utc(holdout_start)
    timestamps = pd.to_datetime(panel["timestamp_utc"], utc=True)
    endpoints = pd.to_datetime(panel[ENDPOINT_COLUMN], utc=True)

    problems = []
    if (timestamps >= holdout_start).any():
        problems.append("decision timestamp enters the future holdout")
    if (endpoints >= holdout_start).any():
        problems.append("target endpoint enters the future holdout")
    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        problems.append("duplicate timestamp/symbol rows")
    if not panel["model_eligible"].fillna(False).astype(bool).any():
        problems.append("no model-eligible rows")
    if problems:
        raise RuntimeError(
            "StockEagle250 Phase 3 rejected its input:\n- "
            + "\n- ".join(problems)
        )


def build_model_frame(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    frame = panel.loc[
        panel["model_eligible"].fillna(False).astype(bool)
    ].copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame[ENDPOINT_COLUMN] = pd.to_datetime(frame[ENDPOINT_COLUMN], utc=True)

    sector = pd.get_dummies(
        frame["sector"].astype(str),
        prefix="sector",
        dtype=float,
    )
    sector = sector.reindex(sorted(sector.columns), axis=1)
    frame = pd.concat([frame.reset_index(drop=True), sector.reset_index(drop=True)], axis=1)
    feature_columns = [*RANK_FEATURE_COLUMNS, *sector.columns.tolist()]

    values = frame[feature_columns].to_numpy(dtype=float)
    target = frame[TARGET_COLUMN].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise RuntimeError("Phase 3 model inputs contain non-finite values")
    if not np.isfinite(target).all():
        raise RuntimeError("Phase 3 targets contain non-finite values")
    return frame, feature_columns


def load_inputs(
    panel_path: Path = PANEL_PATH,
    folds_path: Path = FOLDS_PATH,
    phase2_manifest_path: Path = PHASE2_MANIFEST_PATH,
) -> tuple[pd.DataFrame, list[dict], dict, dict, dict, list[str]]:
    phase2_contract, phase3_contract = load_contracts()
    phase2_manifest = json.loads(
        Path(phase2_manifest_path).read_text(encoding="utf-8")
    )
    required = phase3_contract["input"]

    if int(phase2_manifest.get("candidate_count", 0)) != int(
        required["required_candidate_count"]
    ):
        raise RuntimeError("Phase 2 candidate count differs from Phase 3 contract")
    if int(phase2_manifest.get("fold_count", 0)) != int(
        required["required_fold_count"]
    ):
        raise RuntimeError("Phase 2 fold count differs from Phase 3 contract")
    if int(phase2_manifest.get("future_holdout_rows_read", -1)) != 0:
        raise RuntimeError("Phase 2 reports future-holdout rows")
    if _utc(phase2_manifest["future_holdout_start_utc"]) != FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Phase 2 manifest holdout boundary differs")
    if _utc(
        phase2_manifest["maximum_development_target_endpoint_utc"]
    ) >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Phase 2 target endpoint enters the future holdout")
    if phase2_manifest.get("contract_sha256") != _sha256(PHASE2_CONTRACT_PATH):
        raise RuntimeError("Phase 2 contract hash differs from its manifest")

    panel = pd.read_parquet(panel_path)
    validate_development_panel(panel)
    frame, feature_columns = build_model_frame(panel)

    folds = json.loads(Path(folds_path).read_text(encoding="utf-8"))
    if len(folds) != int(required["required_fold_count"]):
        raise RuntimeError("Phase 2 fold file does not contain 14 folds")
    if [row["fold_id"] for row in folds] != phase2_manifest["fold_ids"]:
        raise RuntimeError("Phase 2 fold IDs differ from its manifest")
    return (
        frame,
        folds,
        phase2_manifest,
        phase2_contract,
        phase3_contract,
        feature_columns,
    )


def _safe_correlation(actual, predicted, method="pearson") -> float:
    left = pd.Series(np.asarray(actual, dtype=float))
    right = pd.Series(np.asarray(predicted, dtype=float))
    if left.nunique(dropna=True) < 2 or right.nunique(dropna=True) < 2:
        return np.nan
    return float(left.corr(right, method=method))


def signal_metrics(
    validation: pd.DataFrame,
    prediction_column: str,
) -> dict:
    actual = validation[TARGET_COLUMN].to_numpy(dtype=float)
    predicted = validation[prediction_column].to_numpy(dtype=float)
    errors = predicted - actual

    rank_ics = []
    for _, group in validation.groupby("timestamp_utc", sort=True):
        rank_ics.append(
            _safe_correlation(
                group[TARGET_COLUMN],
                group[prediction_column],
                method="spearman",
            )
        )
    rank_ics = pd.Series(rank_ics, dtype=float).dropna()

    selected = (
        validation.sort_values(
            ["timestamp_utc", prediction_column, "symbol"],
            ascending=[True, False, True],
        )
        .groupby("timestamp_utc", sort=False)
        .head(POSITIONS_PER_COHORT)
    )
    return {
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(np.square(errors)))),
        "pearson_correlation": _safe_correlation(actual, predicted),
        "mean_daily_spearman_rank_ic":
            float(rank_ics.mean()) if not rank_ics.empty else np.nan,
        "positive_daily_rank_ic_fraction":
            float((rank_ics > 0.0).mean()) if not rank_ics.empty else np.nan,
        "top10_mean_realized_excess_vs_spy":
            float(selected[TARGET_COLUMN].mean()),
    }


def cohort_table(
    validation: pd.DataFrame,
    portfolio_id: str,
    score_column: str | None = None,
    top_n: int | None = POSITIONS_PER_COHORT,
) -> pd.DataFrame:
    if portfolio_id == "spy_buy_and_hold_matched_clock":
        rows = (
            validation.sort_values(["timestamp_utc", "symbol"])
            .drop_duplicates("timestamp_utc")
            [[
                "timestamp_utc",
                "entry_timestamp_utc_5d",
                ENDPOINT_COLUMN,
                "forward_spy_return",
            ]]
            .rename(columns={"forward_spy_return": "gross_return"})
        )
        rows["selected_symbols"] = "SPY"
        rows["selected_count"] = 1
        return rows.reset_index(drop=True)

    if portfolio_id == "equal_weight_eligible_universe":
        grouped = validation.groupby("timestamp_utc", sort=True)
        rows = grouped.agg(
            entry_timestamp_utc_5d=("entry_timestamp_utc_5d", "first"),
            target_endpoint_utc_5d=(ENDPOINT_COLUMN, "first"),
            gross_return=("forward_stock_return", "mean"),
            selected_count=("symbol", "size"),
        ).reset_index()
        rows["selected_symbols"] = "ALL_ELIGIBLE"
        return rows

    if score_column is None or top_n is None:
        raise ValueError("Ranked portfolios require score_column and top_n")

    ordered = validation.sort_values(
        ["timestamp_utc", score_column, "symbol"],
        ascending=[True, False, True],
    )
    selected = ordered.groupby("timestamp_utc", sort=False).head(top_n)
    counts = selected.groupby("timestamp_utc")["symbol"].size()
    if (counts < top_n).any():
        bad = counts[counts < top_n]
        raise RuntimeError(
            f"{portfolio_id} has decision sessions with fewer than {top_n} "
            f"eligible candidates: {bad.index[0]}"
        )

    rows = (
        selected.groupby("timestamp_utc", sort=True)
        .agg(
            entry_timestamp_utc_5d=("entry_timestamp_utc_5d", "first"),
            target_endpoint_utc_5d=(ENDPOINT_COLUMN, "first"),
            gross_return=("forward_stock_return", "mean"),
            selected_count=("symbol", "size"),
            selected_symbols=("symbol", lambda values: ",".join(values)),
        )
        .reset_index()
    )
    return rows


def simulate_overlapping_cohorts(
    cohorts: pd.DataFrame,
    portfolio_id: str,
    fold_id: str,
    cost_bps_per_side: float,
    starting_equity: float = STARTING_EQUITY,
    sleeve_count: int = OVERLAPPING_COHORTS,
) -> tuple[pd.DataFrame, dict]:
    if sleeve_count < 1:
        raise ValueError("sleeve_count must be positive")
    if starting_equity <= 0:
        raise ValueError("starting_equity must be positive")

    periods = cohorts.sort_values(
        ["timestamp_utc", ENDPOINT_COLUMN]
    ).reset_index(drop=True).copy()
    cost_rate = float(cost_bps_per_side) / 10_000.0
    periods["net_return"] = (
        (1.0 + periods["gross_return"].astype(float))
        * (1.0 - cost_rate)
        * (1.0 - cost_rate)
        - 1.0
    )

    sleeves = np.full(sleeve_count, float(starting_equity) / sleeve_count)
    account_values = [float(starting_equity)]
    sleeve_ids = []
    account_equity = []

    for index, net_return in enumerate(periods["net_return"].to_numpy(float)):
        sleeve_id = index % sleeve_count
        sleeves[sleeve_id] *= 1.0 + net_return
        total = float(sleeves.sum())
        sleeve_ids.append(sleeve_id)
        account_equity.append(total)
        account_values.append(total)

    curve = pd.Series(account_values, dtype=float)
    drawdown = curve / curve.cummax() - 1.0
    periods.insert(0, "fold_id", fold_id)
    periods.insert(1, "portfolio_id", portfolio_id)
    periods["sleeve_id"] = sleeve_ids
    periods["cost_bps_per_side"] = float(cost_bps_per_side)
    periods["account_equity"] = account_equity

    summary = {
        "portfolio_id": portfolio_id,
        "decision_count": int(len(periods)),
        "ending_equity": float(account_values[-1]),
        "net_return": float(account_values[-1] / starting_equity - 1.0),
        "maximum_drawdown": float(drawdown.min()),
        "mean_cohort_gross_return": float(periods["gross_return"].mean()),
        "mean_cohort_net_return": float(periods["net_return"].mean()),
    }
    return periods, summary


def evaluate_fold_portfolios(
    validation: pd.DataFrame,
    prediction_columns: dict[str, str],
    fold_id: str,
) -> tuple[pd.DataFrame, dict[str, dict]]:
    specifications = [
        (
            "spy_buy_and_hold_matched_clock",
            None,
            None,
            0.0,
        ),
        (
            "equal_weight_eligible_universe",
            None,
            None,
            COST_BPS_PER_SIDE,
        ),
        (
            "cross_sectional_return_20d_rank",
            MOMENTUM_SCORE_COLUMN,
            POSITIONS_PER_COHORT,
            COST_BPS_PER_SIDE,
        ),
        *[
            (
                candidate_id,
                prediction_column,
                POSITIONS_PER_COHORT,
                COST_BPS_PER_SIDE,
            )
            for candidate_id, prediction_column in prediction_columns.items()
        ],
    ]

    period_frames = []
    summaries = {}
    for portfolio_id, score_column, top_n, cost in specifications:
        cohorts = cohort_table(
            validation,
            portfolio_id,
            score_column=score_column,
            top_n=top_n,
        )
        periods, summary = simulate_overlapping_cohorts(
            cohorts,
            portfolio_id=portfolio_id,
            fold_id=fold_id,
            cost_bps_per_side=cost,
        )
        period_frames.append(periods)
        summaries[portfolio_id] = summary
    return pd.concat(period_frames, ignore_index=True), summaries


def fold_masks(frame: pd.DataFrame, fold: dict) -> tuple[pd.Series, pd.Series]:
    start = _utc(fold["validation_start_utc"])
    end = _utc(fold["validation_end_exclusive_utc"])
    train = (
        (frame["timestamp_utc"] < start)
        & (frame[ENDPOINT_COLUMN] < start)
    )
    validation = (
        (frame["timestamp_utc"] >= start)
        & (frame["timestamp_utc"] < end)
        & (frame[ENDPOINT_COLUMN] < end)
    )
    return train, validation


def run_walk_forward(
    frame: pd.DataFrame,
    folds: list[dict],
    feature_columns: list[str],
    phase3_contract: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    templates = model_templates(phase3_contract)
    prediction_frames = []
    period_frames = []
    metric_rows = []

    for fold in folds:
        fold_id = fold["fold_id"]
        train_mask, validation_mask = fold_masks(frame, fold)
        train = frame.loc[train_mask].copy()
        validation = frame.loc[validation_mask].copy()

        if len(train) != int(fold["train_rows"]):
            raise RuntimeError(
                f"{fold_id} training rows differ from frozen Phase 2 fold"
            )
        if len(validation) != int(fold["validation_rows"]):
            raise RuntimeError(
                f"{fold_id} validation rows differ from frozen Phase 2 fold"
            )
        start = _utc(fold["validation_start_utc"])
        end = _utc(fold["validation_end_exclusive_utc"])
        if train[ENDPOINT_COLUMN].max() >= start:
            raise RuntimeError(f"{fold_id} training endpoint violates purge")
        if validation[ENDPOINT_COLUMN].max() >= end:
            raise RuntimeError(f"{fold_id} validation endpoint crosses fold end")

        prediction_columns = {}
        for candidate_id, template in templates.items():
            model = clone(template)
            model.fit(
                train[feature_columns].to_numpy(dtype=float),
                train[TARGET_COLUMN].to_numpy(dtype=float),
            )
            column = f"prediction_{candidate_id}"
            validation[column] = model.predict(
                validation[feature_columns].to_numpy(dtype=float)
            )
            prediction_columns[candidate_id] = column
            print(
                f"[SUCCESS] {fold_id} {candidate_id} "
                f"train={len(train):,} validation={len(validation):,}"
            )

        periods, portfolio_summaries = evaluate_fold_portfolios(
            validation,
            prediction_columns,
            fold_id,
        )
        period_frames.append(periods)

        for candidate_id, prediction_column in prediction_columns.items():
            signal = signal_metrics(validation, prediction_column)
            portfolio = portfolio_summaries[candidate_id]
            spy = portfolio_summaries["spy_buy_and_hold_matched_clock"]
            equal_weight = portfolio_summaries[
                "equal_weight_eligible_universe"
            ]
            momentum = portfolio_summaries[
                "cross_sectional_return_20d_rank"
            ]
            metric_rows.append({
                "fold_id": fold_id,
                "candidate_id": candidate_id,
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                "validation_sessions":
                    int(validation["timestamp_utc"].nunique()),
                "validation_start_utc": start.isoformat(),
                "validation_end_exclusive_utc": end.isoformat(),
                **signal,
                "ending_equity": portfolio["ending_equity"],
                "net_return": portfolio["net_return"],
                "maximum_drawdown": portfolio["maximum_drawdown"],
                "spy_net_return": spy["net_return"],
                "equal_weight_net_return": equal_weight["net_return"],
                "return_20d_rank_net_return": momentum["net_return"],
                "excess_vs_spy":
                    portfolio["net_return"] - spy["net_return"],
                "excess_vs_equal_weight":
                    portfolio["net_return"] - equal_weight["net_return"],
                "excess_vs_return_20d_rank":
                    portfolio["net_return"] - momentum["net_return"],
            })

        prediction_frames.append(validation[[
            "timestamp_utc",
            "entry_timestamp_utc_5d",
            ENDPOINT_COLUMN,
            "symbol",
            "sector",
            "forward_stock_return",
            "forward_spy_return",
            TARGET_COLUMN,
            MOMENTUM_SCORE_COLUMN,
            *prediction_columns.values(),
        ]].assign(fold_id=fold_id))

    return (
        pd.concat(prediction_frames, ignore_index=True),
        pd.concat(period_frames, ignore_index=True),
        pd.DataFrame(metric_rows),
    )


def summarize_and_gate(
    fold_metrics: pd.DataFrame,
    phase3_contract: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    thresholds = phase3_contract["qualification_gates"]
    summaries = []
    gates = []

    for candidate_id, group in fold_metrics.groupby("candidate_id", sort=True):
        summary = {
            "candidate_id": candidate_id,
            "fold_count": int(group["fold_id"].nunique()),
            "median_fold_net_return": float(group["net_return"].median()),
            "mean_fold_net_return": float(group["net_return"].mean()),
            "positive_fold_fraction": float((group["net_return"] > 0.0).mean()),
            "median_fold_excess_vs_spy":
                float(group["excess_vs_spy"].median()),
            "positive_excess_vs_spy_fold_fraction":
                float((group["excess_vs_spy"] > 0.0).mean()),
            "median_fold_excess_vs_equal_weight":
                float(group["excess_vs_equal_weight"].median()),
            "median_fold_excess_vs_return_20d_rank":
                float(group["excess_vs_return_20d_rank"].median()),
            "median_fold_mean_rank_ic":
                float(group["mean_daily_spearman_rank_ic"].median()),
            "positive_mean_rank_ic_fold_fraction":
                float((group["mean_daily_spearman_rank_ic"] > 0.0).mean()),
            "mean_row_mae": float(group["mae"].mean()),
            "mean_row_rmse": float(group["rmse"].mean()),
            "worst_fold_maximum_drawdown":
                float(group["maximum_drawdown"].min()),
        }
        summaries.append(summary)

        gate_values = {
            "gate_median_fold_net_return_gt_zero": bool(
                summary["median_fold_net_return"]
                > float(thresholds["median_fold_net_return_gt_zero"])
            ),
            "gate_positive_fold_fraction_gte_70pct": bool(
                summary["positive_fold_fraction"]
                >= float(thresholds["positive_fold_fraction_gte"])
            ),
            "gate_median_fold_excess_vs_spy_gt_zero": bool(
                summary["median_fold_excess_vs_spy"]
                > float(thresholds["median_fold_excess_vs_spy_gt_zero"])
            ),
            "gate_positive_excess_vs_spy_fold_fraction_gte_60pct": bool(
                summary["positive_excess_vs_spy_fold_fraction"]
                >= float(
                    thresholds[
                        "positive_excess_vs_spy_fold_fraction_gte"
                    ]
                )
            ),
            "gate_median_fold_excess_vs_equal_weight_gt_zero": bool(
                summary["median_fold_excess_vs_equal_weight"]
                > float(
                    thresholds[
                        "median_fold_excess_vs_equal_weight_gt_zero"
                    ]
                )
            ),
            "gate_median_fold_mean_rank_ic_gt_zero": bool(
                summary["median_fold_mean_rank_ic"]
                > float(
                    thresholds[
                        "median_fold_mean_rank_ic_gt_zero"
                    ]
                )
            ),
            "gate_positive_mean_rank_ic_fold_fraction_gte_60pct": bool(
                summary["positive_mean_rank_ic_fold_fraction"]
                >= float(
                    thresholds[
                        "positive_mean_rank_ic_fold_fraction_gte"
                    ]
                )
            ),
            "gate_worst_fold_maximum_drawdown_gte_minus_35pct": bool(
                summary["worst_fold_maximum_drawdown"]
                >= float(
                    thresholds[
                        "worst_fold_maximum_drawdown_gte"
                    ]
                )
            ),
        }
        passed = sum(gate_values.values())
        gates.append({
            "candidate_id": candidate_id,
            **gate_values,
            "passed_gate_count": int(passed),
            "total_gate_count": int(len(gate_values)),
            "qualified_for_human_review":
                bool(passed == len(gate_values)),
        })

    summary_frame = pd.DataFrame(summaries)
    gate_frame = pd.DataFrame(gates)
    joined = summary_frame.merge(
        gate_frame[["candidate_id", "qualified_for_human_review"]],
        on="candidate_id",
        validate="one_to_one",
    )
    qualified = joined.loc[joined["qualified_for_human_review"]].sort_values(
        [
            "median_fold_excess_vs_spy",
            "median_fold_mean_rank_ic",
            "candidate_id",
        ],
        ascending=[False, False, True],
    )

    if qualified.empty:
        status = "NO_CANDIDATE_QUALIFIED"
        provisional = None
    else:
        status = "QUALIFIES_FOR_HUMAN_REVIEW"
        provisional = str(qualified.iloc[0]["candidate_id"])

    qualification = {
        "status": status,
        "provisional_candidate_for_human_review": provisional,
        "qualified_candidate_count": int(len(qualified)),
        "qualified_candidates": qualified["candidate_id"].tolist(),
        "candidate_ranking_applied_as_preregistered": True,
        "candidate_frozen": False,
        "paper_trading_enabled": False,
        "future_holdout_scored": False,
        "automatic_promotion": False,
        "brokerage_orders": False,
        "human_review_required": True,
    }
    return summary_frame, gate_frame, qualification


def run(
    panel_path: Path = PANEL_PATH,
    folds_path: Path = FOLDS_PATH,
    phase2_manifest_path: Path = PHASE2_MANIFEST_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    (
        frame,
        folds,
        phase2_manifest,
        _phase2_contract,
        phase3_contract,
        feature_columns,
    ) = load_inputs(panel_path, folds_path, phase2_manifest_path)

    predictions, periods, fold_metrics = run_walk_forward(
        frame,
        folds,
        feature_columns,
        phase3_contract,
    )
    summary, gates, qualification = summarize_and_gate(
        fold_metrics,
        phase3_contract,
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(
        output_root / PREDICTIONS_PATH.name,
        index=False,
    )
    periods.to_parquet(
        output_root / PORTFOLIO_PERIODS_PATH.name,
        index=False,
    )
    fold_metrics.to_csv(
        output_root / FOLD_METRICS_PATH.name,
        index=False,
    )
    summary.to_csv(
        output_root / MODEL_SUMMARY_PATH.name,
        index=False,
    )
    gates.to_csv(
        output_root / GATE_RESULTS_PATH.name,
        index=False,
    )
    (output_root / QUALIFICATION_PATH.name).write_text(
        json.dumps(qualification, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "fixed_learned_candidate_walk_forward_evaluation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": phase3_contract["classification"],
        "phase2_manifest_sha256": _sha256(phase2_manifest_path),
        "phase2_contract_sha256": _sha256(PHASE2_CONTRACT_PATH),
        "phase3_contract_sha256": _sha256(PHASE3_CONTRACT_PATH),
        "candidate_count": len(CANDIDATE_IDS),
        "candidate_ids": list(CANDIDATE_IDS),
        "fold_count": len(folds),
        "model_input_count": len(feature_columns),
        "rank_feature_count": len(RANK_FEATURE_COLUMNS),
        "sector_one_hot_count":
            len(feature_columns) - len(RANK_FEATURE_COLUMNS),
        "development_rows": int(len(frame)),
        "oos_prediction_rows": int(len(predictions)),
        "future_holdout_start_utc":
            phase2_manifest["future_holdout_start_utc"],
        "future_holdout_rows_read": 0,
        "maximum_target_endpoint_utc":
            frame[ENDPOINT_COLUMN].max().isoformat(),
        "transaction_cost_bps_per_side": COST_BPS_PER_SIDE,
        "overlapping_cohorts": OVERLAPPING_COHORTS,
        "qualification_status": qualification["status"],
        "provisional_candidate_for_human_review":
            qualification["provisional_candidate_for_human_review"],
        "outputs": {
            "predictions": str(output_root / PREDICTIONS_PATH.name),
            "portfolio_periods":
                str(output_root / PORTFOLIO_PERIODS_PATH.name),
            "fold_metrics": str(output_root / FOLD_METRICS_PATH.name),
            "model_summary": str(output_root / MODEL_SUMMARY_PATH.name),
            "gate_results": str(output_root / GATE_RESULTS_PATH.name),
            "qualification": str(output_root / QUALIFICATION_PATH.name),
            "manifest": str(output_root / MANIFEST_PATH.name),
        },
        "safety": {
            "hyperparameter_search_performed": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "paper_trading_enabled": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "existing_model_artifacts_modified": False,
            "existing_forward_journals_modified": False,
            "human_review_required": True,
        },
        "next_step": (
            "Review the preregistered fold metrics and qualification result. "
            "Do not freeze a candidate or begin paper evaluation automatically."
        ),
    }
    (output_root / MANIFEST_PATH.name).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    parser.add_argument("--folds", type=Path, default=FOLDS_PATH)
    parser.add_argument(
        "--phase2-manifest",
        type=Path,
        default=PHASE2_MANIFEST_PATH,
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        args.panel,
        args.folds,
        args.phase2_manifest,
        args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
