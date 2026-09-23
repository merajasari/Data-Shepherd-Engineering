"""Shared Crypto V7 Weekly Return Regression Phase 2 models.

Fits the two preregistered primary HistGradientBoosting absolute-error
regressors and the two Ridge diagnostics on expanding chronological folds.
Every training window is purged by the full exact 168-hour target horizon.
This phase measures prediction quality only; it does not simulate a portfolio,
inspect the future holdout, freeze a model, write paper state, or place orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


RESEARCH_VERSION = "shared_crypto_v7_weekly_return_regression"
PHASE1_ROOT = Path("data/model/shared_crypto_v7_weekly_return_regression/phase1")
OUTPUT_ROOT = Path("data/model/shared_crypto_v7_weekly_return_regression/phase2")
HOLDOUT = pd.Timestamp("2026-09-01T00:00:00Z")
BTC_TARGET = "btc_net_entry_return_168h"
ALT_TARGET = "alt_net_entry_return_168h"
TARGETS = (BTC_TARGET, ALT_TARGET)
PURGE = timedelta(hours=168)
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 6
RANDOM_STATE = 1729
PRIMARY_MODEL = "hist_gradient_boosting_absolute_error_regressor"
DIAGNOSTIC_MODEL = "ridge_regression_diagnostic"


def model_candidates() -> dict[str, Pipeline]:
    return {
        PRIMARY_MODEL: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", HistGradientBoostingRegressor(
                loss="absolute_error",
                learning_rate=0.04,
                max_iter=200,
                max_leaf_nodes=15,
                min_samples_leaf=40,
                l2_regularization=5.0,
                random_state=RANDOM_STATE,
            )),
        ]),
        DIAGNOSTIC_MODEL: Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=10.0)),
        ]),
    }


def validate_pre_holdout(frame: pd.DataFrame, source: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (timestamps >= HOLDOUT).any():
        raise RuntimeError(f"{source} contains future-holdout observations")


def _read(path: Path, source: str) -> pd.DataFrame:
    if not Path(path).exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    validate_pre_holdout(frame, source)
    return frame.sort_values("timestamp_utc").reset_index(drop=True)


def make_folds(timestamps: pd.Series) -> list[dict]:
    clock = pd.to_datetime(timestamps, utc=True)
    unique = pd.Series(clock.drop_duplicates()).sort_values().reset_index(drop=True)
    if unique.empty:
        raise RuntimeError("Cannot construct V7 folds from empty timestamps")
    first = unique.iloc[0].floor("D")
    last = unique.iloc[-1]
    starts = []
    cursor = first + timedelta(days=MIN_TRAIN_DAYS)
    while cursor <= last:
        starts.append(cursor)
        cursor += timedelta(days=VALIDATION_DAYS)
    starts = starts[-MAX_FOLDS:]
    folds = []
    for start in starts:
        end = min(start + timedelta(days=VALIDATION_DAYS), HOLDOUT)
        train_end = start - PURGE
        train = clock < train_end
        validation = (clock >= start) & (clock < end)
        if train.any() and validation.any():
            folds.append({
                "fold_id": f"fold_{len(folds) + 1:02d}",
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train,
                "validation": validation,
            })
    if not folds:
        raise RuntimeError("No valid 168-hour-purged V7 folds were constructed")
    return folds


def choose_sleeve(
    predicted_btc: np.ndarray | pd.Series,
    predicted_alt: np.ndarray | pd.Series,
    minimum_net_return: float = 0.0,
) -> np.ndarray:
    btc = np.asarray(predicted_btc, dtype=float)
    alt = np.asarray(predicted_alt, dtype=float)
    if btc.shape != alt.shape:
        raise RuntimeError("V7 BTC and ALT prediction shapes differ")
    best = np.maximum(btc, alt)
    return np.where(
        best <= float(minimum_net_return),
        "CASH",
        np.where(btc >= alt, "BTC", "ALT"),
    )


def _rank_correlation(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual_rank = pd.Series(actual, dtype=float).rank(method="average")
    predicted_rank = pd.Series(predicted, dtype=float).rank(method="average")
    value = actual_rank.corr(predicted_rank)
    return float(value) if pd.notna(value) else 0.0


def _regression_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    baseline: np.ndarray,
) -> dict[str, float]:
    mae = float(mean_absolute_error(actual, predicted))
    baseline_mae = float(mean_absolute_error(actual, baseline))
    return {
        "mae": mae,
        "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
        "r2": float(r2_score(actual, predicted)),
        "spearman": _rank_correlation(actual, predicted),
        "sign_accuracy": float(
            ((np.asarray(actual) > 0.0) == (np.asarray(predicted) > 0.0)).mean()
        ),
        "baseline_train_mean_mae": baseline_mae,
        "mae_improvement_vs_train_mean": baseline_mae - mae,
        "mean_actual": float(np.mean(actual)),
        "mean_predicted": float(np.mean(predicted)),
    }


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
    minimum_net_return: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = []
    metrics = []
    base_columns = [
        "timestamp_utc", "btc_forward_return_168h", "alt_forward_return_168h",
        BTC_TARGET, ALT_TARGET, "alt_basket_assets",
        "realized_best_net_sleeve_168h",
    ]
    for fold in make_folds(data["timestamp_utc"]):
        train = data.loc[fold["train"]]
        validation = data.loc[fold["validation"]]
        if train["timestamp_utc"].max() >= fold["train_end"]:
            raise RuntimeError(f"{fold['fold_id']} violates the 168-hour purge")
        out = validation[base_columns].copy()
        out["fold_id"] = fold["fold_id"]
        actual_btc = validation[BTC_TARGET].to_numpy(float)
        actual_alt = validation[ALT_TARGET].to_numpy(float)
        actual_sleeve = choose_sleeve(actual_btc, actual_alt, minimum_net_return)

        for model_id, template in model_candidates().items():
            btc_model = clone(template).fit(train[features], train[BTC_TARGET])
            alt_model = clone(template).fit(train[features], train[ALT_TARGET])
            predicted_btc = np.asarray(
                btc_model.predict(validation[features]), dtype=float
            )
            predicted_alt = np.asarray(
                alt_model.predict(validation[features]), dtype=float
            )
            predicted_sleeve = choose_sleeve(
                predicted_btc, predicted_alt, minimum_net_return
            )
            out[f"predicted_btc_net_return_{model_id}"] = predicted_btc
            out[f"predicted_alt_net_return_{model_id}"] = predicted_alt
            out[f"predicted_sleeve_{model_id}"] = predicted_sleeve

            btc_baseline = np.full(len(validation), float(train[BTC_TARGET].mean()))
            alt_baseline = np.full(len(validation), float(train[ALT_TARGET].mean()))
            btc_metrics = _regression_metrics(
                actual_btc, predicted_btc, btc_baseline
            )
            alt_metrics = _regression_metrics(
                actual_alt, predicted_alt, alt_baseline
            )
            metrics.append({
                "fold_id": fold["fold_id"],
                "model_id": model_id,
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                "validation_start_utc": fold["start"].isoformat(),
                "validation_end_utc": fold["end"].isoformat(),
                **{f"btc_{key}": value for key, value in btc_metrics.items()},
                **{f"alt_{key}": value for key, value in alt_metrics.items()},
                "mean_two_target_mae": float(
                    (btc_metrics["mae"] + alt_metrics["mae"]) / 2.0
                ),
                "mean_mae_improvement_vs_train_mean": float(
                    (
                        btc_metrics["mae_improvement_vs_train_mean"]
                        + alt_metrics["mae_improvement_vs_train_mean"]
                    ) / 2.0
                ),
                "sleeve_accuracy": float((predicted_sleeve == actual_sleeve).mean()),
                "prediction_fraction_btc": float((predicted_sleeve == "BTC").mean()),
                "prediction_fraction_alt": float((predicted_sleeve == "ALT").mean()),
                "prediction_fraction_cash": float((predicted_sleeve == "CASH").mean()),
            })
        predictions.append(out)
        print(
            f"[SUCCESS] {fold['fold_id']} train={len(train):,} "
            f"validation={len(validation):,} purge=168h"
        )
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(metrics)


def _summary(metrics: pd.DataFrame) -> pd.DataFrame:
    identity = {
        "fold_id", "model_id", "validation_start_utc", "validation_end_utc",
    }
    numeric = [column for column in metrics.columns if column not in identity]
    rows = []
    for model_id, group in metrics.groupby("model_id", sort=True):
        row = {
            "model_id": model_id,
            "fold_count": int(group["fold_id"].nunique()),
        }
        for column in numeric:
            row[f"mean_{column}"] = float(pd.to_numeric(
                group[column], errors="coerce"
            ).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def run(
    phase1_root: Path = PHASE1_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_root = Path(phase1_root)
    output_root = Path(output_root)
    contract = json.loads(
        (phase1_root / "preregistered_contract.json").read_text(encoding="utf-8")
    )
    if contract.get("research_version") != RESEARCH_VERSION:
        raise RuntimeError("Unexpected V7 Phase 1 research version")
    if contract.get("future_holdout_start_utc") != HOLDOUT.isoformat():
        raise RuntimeError("V7 Phase 1 holdout boundary differs from Phase 2")
    walk_contract = contract.get("walk_forward_contract", {})
    if int(walk_contract.get("purge_hours", 0)) != 168:
        raise RuntimeError("V7 Phase 1 did not preregister the 168-hour purge")
    data = _read(
        phase1_root / "daily_regression_dataset.parquet",
        "V7 daily regression dataset",
    )
    features = list(contract["regime_feature_columns"])
    missing = set(features + list(TARGETS)) - set(data.columns)
    if missing:
        raise RuntimeError(f"V7 Phase 1 dataset missing columns: {sorted(missing)}")
    minimum_net_return = float(
        contract["frozen_policy_for_later_simulation"][
            "minimum_predicted_net_return"
        ]
    )
    predictions, metrics = walk_forward(data, features, minimum_net_return)
    summary = _summary(metrics)

    output_root.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output_root / "daily_predictions.parquet", index=False)
    metrics.to_csv(output_root / "fold_metrics.csv", index=False)
    summary.to_csv(output_root / "metrics_summary.csv", index=False)
    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 2,
        "stage": "purged_weekly_return_walk_forward_regressors",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "targets": list(TARGETS),
        "purge_hours": int(PURGE.total_seconds() // 3600),
        "minimum_train_days": MIN_TRAIN_DAYS,
        "validation_days": VALIDATION_DAYS,
        "max_folds": MAX_FOLDS,
        "primary_model": PRIMARY_MODEL,
        "diagnostic_model": DIAGNOSTIC_MODEL,
        "input_rows": int(len(data)),
        "prediction_rows": int(len(predictions)),
        "outputs": {
            "daily_predictions": str(output_root / "daily_predictions.parquet"),
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "metrics_summary": str(output_root / "metrics_summary.csv"),
            "manifest": str(output_root / "manifest.json"),
        },
        "safety": {
            "v5_modified": False,
            "v6_modified": False,
            "shared_crypto_v3_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
        },
        "next_step": (
            "Review both target regressions and sleeve stability before running "
            "the single preregistered seven-day-hold portfolio policy."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase1_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
