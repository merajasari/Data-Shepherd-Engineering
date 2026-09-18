"""Crypto V6 Phase 4: bounded diagnostics for the rejected news challenger.

This phase explains the completed pre-holdout result. It does not search new
hyperparameters, create a replacement candidate, score the future holdout,
modify V5, mutate paper state, update the dashboard, or contact a broker.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.crypto_v5.config import FUTURE_HOLDOUT_START_UTC
from ml.crypto_v5.phase2 import FEATURES as V5_FEATURES
from ml.crypto_v5.phase4 import (
    SELECTED_COST_BPS,
    SELECTED_HORIZON_DAYS,
    SELECTED_MODEL_ID,
    SELECTED_TOP_N,
)
from ml.crypto_v6.phase1 import (
    ALLOCATION_PREFIX,
    DEFAULT_OUTPUT as PHASE1_ROOT,
    RANKING_PREFIX,
)
from ml.crypto_v6.phase2 import (
    FEATURE_SET_V5,
    FEATURE_SET_V6,
    OUTPUT_ROOT as PHASE2_ROOT,
)
from ml.crypto_v6.phase3 import OUTPUT_ROOT as PHASE3_ROOT
from ml.news_intelligence.vector_features import FEATURE_COLUMNS


RESEARCH_VERSION = "crypto_v6"
OUTPUT_ROOT = PHASE3_ROOT.parent / "phase4"
ALLOCATION_NEWS_FEATURES = tuple(f"{ALLOCATION_PREFIX}{name}" for name in FEATURE_COLUMNS)
RANKING_NEWS_FEATURES = tuple(f"{RANKING_PREFIX}{name}" for name in FEATURE_COLUMNS)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_correlation(left, right, method="pearson"):
    pair = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(pair) < 3 or pair["left"].nunique() < 2 or pair["right"].nunique() < 2:
        return np.nan
    return float(pair["left"].corr(pair["right"], method=method))


def feature_coverage(frame, layer, features):
    rows = []
    for feature in features:
        values = pd.to_numeric(frame[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
        valid = values.dropna()
        rows.append({
            "layer": layer,
            "feature": feature,
            "rows": int(len(values)),
            "missing_fraction": float(values.isna().mean()),
            "zero_fraction": float((valid == 0).mean()) if len(valid) else np.nan,
            "nonzero_fraction": float((valid != 0).mean()) if len(valid) else np.nan,
            "unique_values": int(valid.nunique()),
            "mean": float(valid.mean()) if len(valid) else np.nan,
            "standard_deviation": float(valid.std(ddof=1)) if len(valid) > 1 else np.nan,
            "p05": float(valid.quantile(0.05)) if len(valid) else np.nan,
            "median": float(valid.median()) if len(valid) else np.nan,
            "p95": float(valid.quantile(0.95)) if len(valid) else np.nan,
        })
    return pd.DataFrame(rows)


def target_associations(frame, layer, features, targets):
    rows = []
    for feature in features:
        for target in targets:
            rows.append({
                "layer": layer,
                "feature": feature,
                "target": target,
                "pearson": _safe_correlation(frame[feature], frame[target], "pearson"),
                "spearman": _safe_correlation(frame[feature], frame[target], "spearman"),
            })
    return pd.DataFrame(rows)


def redundancy_table(frame, layer, features, threshold=0.80):
    correlation = frame[list(features)].corr(method="spearman")
    rows = []
    for left_index, left in enumerate(features):
        for right in features[left_index + 1:]:
            value = correlation.loc[left, right]
            if pd.notna(value) and abs(value) >= threshold:
                rows.append({
                    "layer": layer,
                    "feature_left": left,
                    "feature_right": right,
                    "spearman": float(value),
                    "absolute_spearman": float(abs(value)),
                })
    return pd.DataFrame(rows, columns=[
        "layer", "feature_left", "feature_right", "spearman", "absolute_spearman"
    ])


def fold_portfolio_diagnostics(periods, allocation_predictions):
    selected_periods = periods[
        (periods["model_id"] == SELECTED_MODEL_ID)
        & (periods["horizon_days"] == SELECTED_HORIZON_DAYS)
        & (periods["top_n"] == SELECTED_TOP_N)
        & np.isclose(periods["cost_bps_round_trip"], SELECTED_COST_BPS)
    ].copy()
    selected_predictions = allocation_predictions[
        (allocation_predictions["model_id"] == SELECTED_MODEL_ID)
        & (allocation_predictions["horizon_days"] == SELECTED_HORIZON_DAYS)
    ][["timestamp_utc", "feature_set", "fold_id"]].drop_duplicates()
    if selected_predictions.duplicated(["timestamp_utc", "feature_set"]).any():
        raise RuntimeError("Selected allocation predictions have ambiguous fold membership")
    merged = selected_periods.merge(
        selected_predictions,
        on=["timestamp_utc", "feature_set"],
        how="left",
        validate="many_to_one",
    )
    if merged["fold_id"].isna().any():
        raise RuntimeError("Portfolio periods are missing fold membership")
    rows = []
    for (feature_set, fold_id), group in merged.groupby(["feature_set", "fold_id"]):
        ordered = group.sort_values("timestamp_utc")
        returns = ordered["net_return"].astype(float)
        equity = (1.0 + returns).cumprod()
        drawdown = equity / equity.cummax() - 1.0
        standard_deviation = float(returns.std(ddof=1))
        rows.append({
            "feature_set": feature_set,
            "fold_id": fold_id,
            "start_utc": ordered["timestamp_utc"].min().isoformat(),
            "end_utc": ordered["timestamp_utc"].max().isoformat(),
            "observations": int(len(ordered)),
            "ending_equity": float(equity.iloc[-1]),
            "cumulative_return": float(equity.iloc[-1] - 1.0),
            "sharpe": (
                float(returns.mean() / standard_deviation * np.sqrt(365.25 / SELECTED_HORIZON_DAYS))
                if standard_deviation else np.nan
            ),
            "maximum_drawdown": float(drawdown.min()),
            "total_turnover": float(ordered["turnover"].sum()),
        })
    result = pd.DataFrame(rows)
    counts = result.groupby("fold_id")["feature_set"].nunique()
    if not (counts == 2).all():
        raise RuntimeError("Fold diagnostics require paired V5 and V6 portfolios")
    return result.sort_values(["fold_id", "feature_set"]).reset_index(drop=True)


def paired_fold_deltas(fold_metrics):
    value_columns = ["ending_equity", "cumulative_return", "sharpe", "maximum_drawdown", "total_turnover"]
    rows = []
    for fold_id, group in fold_metrics.groupby("fold_id"):
        indexed = group.set_index("feature_set")
        if FEATURE_SET_V5 not in indexed.index or FEATURE_SET_V6 not in indexed.index:
            raise RuntimeError(f"Missing paired fold row for {fold_id}")
        row = {"fold_id": fold_id}
        for column in value_columns:
            v5, v6 = indexed.loc[FEATURE_SET_V5, column], indexed.loc[FEATURE_SET_V6, column]
            row[f"v5_{column}"] = float(v5) if pd.notna(v5) else np.nan
            row[f"v6_{column}"] = float(v6) if pd.notna(v6) else np.nan
            row[f"v6_minus_v5_{column}"] = float(v6 - v5) if pd.notna(v5) and pd.notna(v6) else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values("fold_id").reset_index(drop=True)


def ridge_news_coefficients(phase2_root, fold_ids):
    phase2_root = Path(phase2_root)
    rows = []
    definitions = (
        ("allocation", ALLOCATION_NEWS_FEATURES, ("btc", "alt", "cash")),
        ("ranking", RANKING_NEWS_FEATURES, ("ranking",)),
    )
    for fold_id in fold_ids:
        for layer, news_features, targets in definitions:
            all_features = tuple(V5_FEATURES) + tuple(news_features)
            for target in targets:
                filename = f"{target}_{SELECTED_HORIZON_DAYS}d.joblib"
                artifact = (
                    phase2_root / "artifacts" / FEATURE_SET_V6 / layer /
                    fold_id / SELECTED_MODEL_ID / filename
                )
                if not artifact.exists():
                    raise FileNotFoundError(artifact)
                pipeline = joblib.load(artifact)
                coefficients = np.asarray(pipeline.named_steps["model"].coef_).reshape(-1)
                if len(coefficients) != len(all_features):
                    raise RuntimeError(f"Coefficient count mismatch for {artifact}")
                for feature, coefficient in zip(all_features, coefficients):
                    if feature in news_features:
                        rows.append({
                            "layer": layer,
                            "fold_id": fold_id,
                            "target": target,
                            "feature": feature,
                            "standardized_coefficient": float(coefficient),
                            "absolute_standardized_coefficient": float(abs(coefficient)),
                            "artifact": str(artifact),
                        })
    return pd.DataFrame(rows)


def run(phase1_root=PHASE1_ROOT, phase2_root=PHASE2_ROOT,
        phase3_root=PHASE3_ROOT, output_root=OUTPUT_ROOT):
    phase1_root, phase2_root, phase3_root, output_root = map(
        Path, (phase1_root, phase2_root, phase3_root, output_root)
    )
    inputs = {
        "allocation_dataset": phase1_root / "allocation_dataset.parquet",
        "ranking_dataset": phase1_root / "ranking_dataset.parquet",
        "phase1_manifest": phase1_root / "manifest.json",
        "allocation_predictions": phase2_root / "allocation_predictions.parquet",
        "ranking_predictions": phase2_root / "ranking_predictions.parquet",
        "phase2_manifest": phase2_root / "manifest.json",
        "paired_portfolio_periods": phase3_root / "paired_portfolio_periods.parquet",
        "phase3_comparison": phase3_root / "v6_vs_v5_comparison.json",
        "phase3_manifest": phase3_root / "manifest.json",
    }
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Crypto V6 diagnostic inputs: " + ", ".join(missing))
    input_hashes = {name: _sha256(path) for name, path in inputs.items()}
    allocation = pd.read_parquet(inputs["allocation_dataset"])
    ranking = pd.read_parquet(inputs["ranking_dataset"])
    allocation_predictions = pd.read_parquet(inputs["allocation_predictions"])
    ranking_predictions = pd.read_parquet(inputs["ranking_predictions"])
    periods = pd.read_parquet(inputs["paired_portfolio_periods"])
    comparison = json.loads(inputs["phase3_comparison"].read_text())
    for frame in (allocation, ranking, allocation_predictions, ranking_predictions, periods):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
        if (frame["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
            raise RuntimeError("Crypto V6 diagnostics refuse future-holdout rows")

    coverage = pd.concat([
        feature_coverage(allocation, "allocation", ALLOCATION_NEWS_FEATURES),
        feature_coverage(ranking, "ranking", RANKING_NEWS_FEATURES),
    ], ignore_index=True)
    associations = pd.concat([
        target_associations(
            allocation,
            "allocation",
            ALLOCATION_NEWS_FEATURES,
            [f"{sleeve}_forward_return_{SELECTED_HORIZON_DAYS}d" for sleeve in ("btc", "alt", "cash")],
        ),
        target_associations(
            ranking,
            "ranking",
            RANKING_NEWS_FEATURES,
            [f"risk_adjusted_forward_return_{SELECTED_HORIZON_DAYS}d"],
        ),
    ], ignore_index=True)
    redundancy = pd.concat([
        redundancy_table(allocation, "allocation", ALLOCATION_NEWS_FEATURES),
        redundancy_table(ranking, "ranking", RANKING_NEWS_FEATURES),
    ], ignore_index=True)
    fold_metrics = fold_portfolio_diagnostics(periods, allocation_predictions)
    fold_deltas = paired_fold_deltas(fold_metrics)
    fold_ids = sorted(allocation_predictions["fold_id"].dropna().unique())
    coefficients = ridge_news_coefficients(phase2_root, fold_ids)
    coefficient_summary = coefficients.groupby(
        ["layer", "target", "feature"], as_index=False
    ).agg(
        mean_coefficient=("standardized_coefficient", "mean"),
        mean_absolute_coefficient=("absolute_standardized_coefficient", "mean"),
        maximum_absolute_coefficient=("absolute_standardized_coefficient", "max"),
        folds=("fold_id", "nunique"),
    ).sort_values("mean_absolute_coefficient", ascending=False)

    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "feature_coverage": output_root / "feature_coverage.csv",
        "target_associations": output_root / "target_associations.csv",
        "feature_redundancy": output_root / "feature_redundancy.csv",
        "fold_metrics": output_root / "fold_metrics.csv",
        "paired_fold_deltas": output_root / "paired_fold_deltas.csv",
        "ridge_news_coefficients": output_root / "ridge_news_coefficients.csv",
        "ridge_coefficient_summary": output_root / "ridge_coefficient_summary.csv",
    }
    for name, frame in (
        ("feature_coverage", coverage),
        ("target_associations", associations),
        ("feature_redundancy", redundancy),
        ("fold_metrics", fold_metrics),
        ("paired_fold_deltas", fold_deltas),
        ("ridge_news_coefficients", coefficients),
        ("ridge_coefficient_summary", coefficient_summary),
    ):
        frame.to_csv(outputs[name], index=False)

    v6_winning_folds = int((fold_deltas["v6_minus_v5_ending_equity"] > 0).sum())
    summary = {
        "research_version": RESEARCH_VERSION,
        "phase": 4,
        "stage": "bounded_rejected_challenger_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "DIAGNOSTIC_ONLY_V6_REMAINS_REJECTED",
        "phase3_passed": bool(comparison["passed_all_development_checks"]),
        "folds": len(fold_deltas),
        "v6_winning_folds_by_ending_equity": v6_winning_folds,
        "v5_winning_or_tied_folds_by_ending_equity": int(len(fold_deltas) - v6_winning_folds),
        "coverage": {
            "minimum_nonzero_fraction": float(coverage["nonzero_fraction"].min()),
            "maximum_nonzero_fraction": float(coverage["nonzero_fraction"].max()),
            "features_with_over_95_pct_zeros": int((coverage["zero_fraction"] > 0.95).sum()),
        },
        "high_redundancy_pairs_abs_spearman_gte_0_80": int(len(redundancy)),
        "largest_mean_absolute_ridge_news_coefficients": coefficient_summary.head(10).to_dict("records"),
        "interpretation_boundary": (
            "These diagnostics may explain the rejected result but may not be used to claim a new "
            "validated V6 candidate without a new preregistered experiment."
        ),
        "dashboard_eligibility": False,
        "automatic_promotion": False,
        "holdout_scored": False,
        "brokerage_orders": False,
    }
    summary_path = output_root / "diagnostic_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    if input_hashes != {name: _sha256(path) for name, path in inputs.items()}:
        raise RuntimeError("A frozen Crypto V6 diagnostic input changed during analysis")
    manifest = {
        **summary,
        "inputs": {name: {"path": str(path), "sha256": input_hashes[name]}
                   for name, path in inputs.items()},
        "outputs": {name: str(path) for name, path in outputs.items()} | {
            "diagnostic_summary": str(summary_path)
        },
        "safety": {
            "hyperparameter_search": False,
            "new_candidate_created": False,
            "crypto_v5_modified": False,
            "holdout_scored": False,
            "paper_state_modified": False,
            "dashboard_modified": False,
            "automatic_promotion": False,
            "brokerage_orders": False,
        },
        "next_step": "Human review only; any revised news challenger requires a new preregistered contract.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    parser.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase1_root, args.phase2_root, args.phase3_root, args.output), indent=2))


if __name__ == "__main__":
    main()
