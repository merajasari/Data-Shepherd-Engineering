"""Crypto XRP V1 Phase 2: leakage-safe walk-forward XRP model research.

Primary research population
---------------------------
Only the post-discontinuity XRP primary era produced by Phase 1 is used.

Primary target
--------------
btc_relative_forward_return_4h

Candidate models
----------------
- trailing 4-hour BTC-relative momentum baseline
- Ridge regression
- HistGradientBoostingRegressor

Validation
----------
Expanding walk-forward validation entirely inside the post-gap primary era.
A 4-hour purge is applied before each validation interval so training targets
cannot overlap the validation start.

This phase produces out-of-sample research predictions and diagnostics only.

It does NOT:
- use legacy-era rows in the primary model
- inspect or use timestamps on/after 2026-09-01 UTC
- simulate a trading portfolio
- tune thresholds
- promote a model
- modify Crypto 15m V2
- place brokerage orders
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_xrp_v1 import RESEARCH_VERSION


PHASE1_ROOT = Path(
    "data/model/crypto_xrp_v1/phase1"
)

PRIMARY_DATASET = PHASE1_ROOT / "xrp_primary.parquet"

OUTPUT_ROOT = Path(
    "data/model/crypto_xrp_v1/phase2"
)

PREDICTIONS_PATH = OUTPUT_ROOT / "predictions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
FOLD_CATALOG_PATH = OUTPUT_ROOT / "fold_catalog.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


PRIMARY_TARGET = "btc_relative_forward_return_4h"
BASELINE_FEATURE = "btc_relative_return_16bar"

FUTURE_HOLDOUT_START = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

PRIMARY_HORIZON_MINUTES = 240
PURGE_MINUTES = PRIMARY_HORIZON_MINUTES

# XRP primary era begins in July 2023.
# Require about one year before the first validation.
MIN_TRAIN_DAYS = 365

# Quarterly validation windows.
VALIDATION_DAYS = 90

# Keep the most recent 8 valid OOS folds.
MAX_FOLDS = 8


ID_COLUMNS = {
    "timestamp_utc",
    "product_id",
    "segment_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
}

TARGET_PREFIXES = (
    "forward_return_",
    "btc_forward_return_",
    "btc_relative_forward_return_",
)


def load_primary(
    path: Path = PRIMARY_DATASET,
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing XRP Phase 1 primary dataset: {path}"
        )

    df = pd.read_parquet(path).copy()

    required = {
        "timestamp_utc",
        "product_id",
        "segment_id",
        PRIMARY_TARGET,
        BASELINE_FEATURE,
    }

    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            "XRP primary dataset missing required columns: "
            f"{sorted(missing)}"
        )

    df["timestamp_utc"] = pd.to_datetime(
        df["timestamp_utc"],
        utc=True,
    )

    if set(df["product_id"].dropna().unique()) != {"XRP-USD"}:
        raise RuntimeError(
            "XRP Phase 2 input contains non-XRP products"
        )

    # Hard safety boundary.
    if (
        df["timestamp_utc"] >= FUTURE_HOLDOUT_START
    ).any():
        raise RuntimeError(
            "XRP Phase 2 input contains future-holdout rows"
        )

    df = (
        df.sort_values("timestamp_utc")
        .reset_index(drop=True)
    )

    if df.empty:
        raise RuntimeError(
            "XRP Phase 2 primary dataset is empty"
        )

    return df


def feature_columns(
    df: pd.DataFrame,
) -> list[str]:
    features = [
        c
        for c in df.columns
        if c not in ID_COLUMNS
        and not c.startswith(TARGET_PREFIXES)
    ]

    if PRIMARY_TARGET in features:
        raise RuntimeError(
            "Primary target leaked into feature list"
        )

    if BASELINE_FEATURE not in features:
        raise RuntimeError(
            f"Expected baseline feature missing: "
            f"{BASELINE_FEATURE}"
        )

    return features


def make_folds(
    df: pd.DataFrame,
) -> list[dict]:
    first = (
        df["timestamp_utc"]
        .min()
        .floor("D")
    )

    last = (
        df["timestamp_utc"]
        .max()
        .floor("D")
    )

    first_validation = (
        first
        + pd.Timedelta(days=MIN_TRAIN_DAYS)
    )

    candidate_starts = list(
        pd.date_range(
            first_validation,
            last,
            freq=f"{VALIDATION_DAYS}D",
            tz="UTC",
        )
    )

    folds = []

    purge = pd.Timedelta(
        minutes=PURGE_MINUTES
    )

    for start in candidate_starts:
        end = min(
            start
            + pd.Timedelta(
                days=VALIDATION_DAYS
            ),
            FUTURE_HOLDOUT_START,
        )

        train_end = start - purge

        train_mask = (
            df["timestamp_utc"] < train_end
        )

        validation_mask = (
            (df["timestamp_utc"] >= start)
            & (df["timestamp_utc"] < end)
        )

        train_rows = int(train_mask.sum())
        validation_rows = int(
            validation_mask.sum()
        )

        if train_rows == 0:
            continue

        if validation_rows == 0:
            continue

        folds.append(
            {
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train_mask,
                "validation": validation_mask,
                "train_rows": train_rows,
                "validation_rows": validation_rows,
            }
        )

    folds = folds[-MAX_FOLDS:]

    for i, fold in enumerate(
        folds,
        start=1,
    ):
        fold["fold_id"] = f"fold_{i:02d}"

    if not folds:
        raise RuntimeError(
            "No valid XRP walk-forward folds"
        )

    return folds


def model_candidates() -> dict:
    return {
        "ridge": Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median"
                    ),
                ),
                (
                    "scaler",
                    StandardScaler(),
                ),
                (
                    "model",
                    Ridge(
                        alpha=10.0
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": Pipeline(
            [
                (
                    "imputer",
                    SimpleImputer(
                        strategy="median"
                    ),
                ),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        max_iter=150,
                        learning_rate=0.05,
                        max_leaf_nodes=31,
                        l2_regularization=1.0,
                        random_state=42,
                    ),
                ),
            ]
        ),
    }


def correlation_safe(
    a: pd.Series,
    b: pd.Series,
) -> float:
    x = pd.to_numeric(
        a,
        errors="coerce",
    )

    y = pd.to_numeric(
        b,
        errors="coerce",
    )

    mask = x.notna() & y.notna()

    if mask.sum() < 2:
        return np.nan

    x = x.loc[mask]
    y = y.loc[mask]

    if x.nunique() < 2:
        return np.nan

    if y.nunique() < 2:
        return np.nan

    return float(
        x.corr(
            y,
            method="spearman",
        )
    )


def summarize_predictions(
    frame: pd.DataFrame,
) -> dict:
    actual = frame["actual"].astype(float)
    predicted = frame[
        "predicted_score"
    ].astype(float)

    mae = mean_absolute_error(
        actual,
        predicted,
    )

    rmse = float(
        np.sqrt(
            mean_squared_error(
                actual,
                predicted,
            )
        )
    )

    sign_accuracy = float(
        (
            np.sign(predicted)
            == np.sign(actual)
        ).mean()
    )

    direction_hit_rate_nonzero = float(
        (
            np.sign(predicted[actual != 0])
            == np.sign(actual[actual != 0])
        ).mean()
    ) if (actual != 0).any() else np.nan

    spearman = correlation_safe(
        predicted,
        actual,
    )

    pearson = float(
        predicted.corr(actual)
    ) if (
        predicted.nunique() > 1
        and actual.nunique() > 1
    ) else np.nan

    prediction_mean = float(
        predicted.mean()
    )

    actual_mean = float(
        actual.mean()
    )

    predicted_positive_fraction = float(
        (predicted > 0).mean()
    )

    actual_positive_fraction = float(
        (actual > 0).mean()
    )

    return {
        "observation_count": int(
            len(frame)
        ),
        "mae": float(mae),
        "rmse": rmse,
        "spearman": spearman,
        "pearson": pearson,
        "sign_accuracy": sign_accuracy,
        "direction_hit_rate_nonzero": (
            direction_hit_rate_nonzero
        ),
        "prediction_mean": (
            prediction_mean
        ),
        "actual_mean": actual_mean,
        "predicted_positive_fraction": (
            predicted_positive_fraction
        ),
        "actual_positive_fraction": (
            actual_positive_fraction
        ),
    }


def build_prediction_frame(
    validation: pd.DataFrame,
    predicted_score,
    model_id: str,
    fold_id: str,
) -> pd.DataFrame:
    out = validation[
        [
            "timestamp_utc",
            "product_id",
            "segment_id",
        ]
    ].copy()

    out["actual"] = validation[
        PRIMARY_TARGET
    ].to_numpy()

    out["predicted_score"] = (
        np.asarray(
            predicted_score,
            dtype=float,
        )
    )

    out["model_id"] = model_id
    out["fold_id"] = fold_id

    return out


def run(
    primary_dataset: Path = PRIMARY_DATASET,
    output_root: Path = OUTPUT_ROOT,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    output_root = Path(
        output_root
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    df = load_primary(
        primary_dataset
    )

    features = feature_columns(
        df
    )

    folds = make_folds(
        df
    )

    predictions = []
    fold_metric_rows = []
    fold_catalog_rows = []

    for fold in folds:
        fold_id = fold[
            "fold_id"
        ]

        train = df.loc[
            fold["train"]
        ].copy()

        validation = df.loc[
            fold["validation"]
        ].copy()

        # Verify purge contract directly.
        max_train_timestamp = train[
            "timestamp_utc"
        ].max()

        min_validation_timestamp = (
            validation[
                "timestamp_utc"
            ].min()
        )

        actual_gap_minutes = (
            (
                min_validation_timestamp
                - max_train_timestamp
            ).total_seconds()
            / 60.0
        )

        if (
            max_train_timestamp
            >= fold["train_end"]
        ):
            raise RuntimeError(
                f"{fold_id}: training "
                "extends into purge zone"
            )

        if (
            min_validation_timestamp
            < fold["start"]
        ):
            raise RuntimeError(
                f"{fold_id}: validation "
                "starts too early"
            )

        X_train = train[
            features
        ]

        y_train = train[
            PRIMARY_TARGET
        ]

        X_validation = validation[
            features
        ]

        y_validation = validation[
            PRIMARY_TARGET
        ]

        # Pre-registered momentum baseline.
        baseline = (
            validation[
                BASELINE_FEATURE
            ]
            .astype(float)
            .to_numpy()
        )

        baseline_frame = (
            build_prediction_frame(
                validation,
                baseline,
                "momentum_4h",
                fold_id,
            )
        )

        predictions.append(
            baseline_frame
        )

        fold_metric_rows.append(
            {
                "fold_id": fold_id,
                "model_id": (
                    "momentum_4h"
                ),
                "train_rows": int(
                    len(train)
                ),
                "validation_rows": int(
                    len(validation)
                ),
                **summarize_predictions(
                    baseline_frame
                ),
            }
        )

        for (
            model_id,
            model,
        ) in model_candidates().items():
            model.fit(
                X_train,
                y_train,
            )

            predicted = model.predict(
                X_validation
            )

            frame = (
                build_prediction_frame(
                    validation,
                    predicted,
                    model_id,
                    fold_id,
                )
            )

            predictions.append(
                frame
            )

            fold_metric_rows.append(
                {
                    "fold_id": fold_id,
                    "model_id": model_id,
                    "train_rows": int(
                        len(train)
                    ),
                    "validation_rows": int(
                        len(validation)
                    ),
                    **summarize_predictions(
                        frame
                    ),
                }
            )

        fold_catalog_rows.append(
            {
                "fold_id": fold_id,
                "validation_start_utc": (
                    fold["start"].isoformat()
                ),
                "validation_end_utc": (
                    fold["end"].isoformat()
                ),
                "train_end_exclusive_utc": (
                    fold[
                        "train_end"
                    ].isoformat()
                ),
                "max_train_timestamp_utc": (
                    max_train_timestamp
                    .isoformat()
                ),
                "min_validation_timestamp_utc": (
                    min_validation_timestamp
                    .isoformat()
                ),
                "actual_gap_minutes": float(
                    actual_gap_minutes
                ),
                "train_rows": int(
                    len(train)
                ),
                "validation_rows": int(
                    len(validation)
                ),
                "train_segment_count": int(
                    train[
                        "segment_id"
                    ].nunique()
                ),
                "validation_segment_count": int(
                    validation[
                        "segment_id"
                    ].nunique()
                ),
            }
        )

        print(
            "[SUCCESS] "
            f"{fold_id} "
            f"train={len(train):,} "
            f"validation={len(validation):,} "
            f"{fold['start']} "
            "-> "
            f"{fold['end']}"
        )

    prediction_df = (
        pd.concat(
            predictions,
            ignore_index=True,
        )
        .sort_values(
            [
                "timestamp_utc",
                "model_id",
            ]
        )
        .reset_index(drop=True)
    )

    fold_metrics = pd.DataFrame(
        fold_metric_rows
    )

    fold_catalog = pd.DataFrame(
        fold_catalog_rows
    )

    summary_rows = []

    for (
        model_id,
        group,
    ) in prediction_df.groupby(
        "model_id",
        sort=True,
    ):
        summary_rows.append(
            {
                "model_id": model_id,
                "fold_count": int(
                    group[
                        "fold_id"
                    ].nunique()
                ),
                **summarize_predictions(
                    group
                ),
            }
        )

    summary = (
        pd.DataFrame(
            summary_rows
        )
        .sort_values(
            [
                "spearman",
                "sign_accuracy",
            ],
            ascending=False,
        )
        .reset_index(drop=True)
    )

    prediction_df.to_parquet(
        output_root
        / "predictions.parquet",
        index=False,
    )

    fold_metrics.to_csv(
        output_root
        / "fold_metrics.csv",
        index=False,
    )

    summary.to_csv(
        output_root
        / "metrics_summary.csv",
        index=False,
    )

    fold_catalog.to_csv(
        output_root
        / "fold_catalog.csv",
        index=False,
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 2,
        "stage": (
            "primary_era_walk_forward_model_research"
        ),
        "generated_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "source": str(
            primary_dataset
        ),
        "population": (
            "post-major-discontinuity "
            "XRP primary era only"
        ),
        "primary_target": (
            PRIMARY_TARGET
        ),
        "baseline_feature": (
            BASELINE_FEATURE
        ),
        "candidate_models": [
            "momentum_4h",
            "ridge",
            "hist_gradient_boosting",
        ],
        "feature_count": int(
            len(features)
        ),
        "feature_columns": (
            features
        ),
        "minimum_training_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "maximum_folds": (
            MAX_FOLDS
        ),
        "fold_count": int(
            len(folds)
        ),
        "primary_horizon_minutes": (
            PRIMARY_HORIZON_MINUTES
        ),
        "purge_minutes": (
            PURGE_MINUTES
        ),
        "future_holdout_start_utc": (
            FUTURE_HOLDOUT_START
            .isoformat()
        ),
        "future_holdout_policy": (
            "No observations on or after "
            "2026-09-01 00:00 UTC are "
            "loaded, trained on, predicted, "
            "or evaluated."
        ),
        "legacy_policy": (
            "Legacy pre-discontinuity XRP "
            "history is excluded entirely "
            "from primary Phase 2 training "
            "and validation."
        ),
        "model_selection_policy": (
            "Phase 2 reports OOS research "
            "diagnostics only. No model is "
            "promoted or frozen from this "
            "phase."
        ),
        "portfolio_policy": (
            "No portfolio simulation, "
            "position sizing, transaction "
            "cost modeling, or brokerage "
            "execution occurs."
        ),
        "shared_v2_policy": (
            "Frozen Crypto 15m V2 Phase 5 "
            "is not modified and XRP is not "
            "added to its shared universe."
        ),
        "outputs": {
            "predictions": str(
                output_root
                / "predictions.parquet"
            ),
            "fold_metrics": str(
                output_root
                / "fold_metrics.csv"
            ),
            "metrics_summary": str(
                output_root
                / "metrics_summary.csv"
            ),
            "fold_catalog": str(
                output_root
                / "fold_catalog.csv"
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "policy": (
            "walk-forward model research "
            "only; no threshold tuning, "
            "portfolio simulation, "
            "promotion, live execution, "
            "leverage, shorting, "
            "derivatives, or future-holdout "
            "evaluation"
        ),
        "next_step": (
            "Review OOS diagnostics across "
            "folds and compare stability "
            "versus the momentum baseline "
            "before defining any XRP "
            "economic strategy."
        ),
    }

    (
        output_root
        / "manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return (
        summary,
        fold_metrics,
        fold_catalog,
    )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__
    )

    ap.add_argument(
        "--primary-dataset",
        type=Path,
        default=PRIMARY_DATASET,
    )

    ap.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )

    args = ap.parse_args(
        argv
    )

    (
        summary,
        _,
        fold_catalog,
    ) = run(
        args.primary_dataset,
        args.output_root,
    )

    print()
    print(
        "CRYPTO XRP V1 PHASE 2"
    )

    print(
        "=" * 80
    )

    print()

    print(
        "Walk-forward folds:"
    )

    print(
        fold_catalog[
            [
                "fold_id",
                "validation_start_utc",
                "validation_end_utc",
                "train_rows",
                "validation_rows",
            ]
        ].to_string(
            index=False
        )
    )

    print()

    print(
        "OOS MODEL SUMMARY"
    )

    print(
        summary.to_string(
            index=False
        )
    )

    print()

    print(
        "Primary target: "
        f"{PRIMARY_TARGET}"
    )

    print(
        "Primary population: "
        "post-gap XRP era only"
    )

    print(
        f"Purge: {PURGE_MINUTES} minutes"
    )

    print(
        "Future holdout remains untouched "
        "from 2026-09-01 UTC."
    )

    print(
        "No portfolio simulation or model "
        "promotion was performed."
    )


if __name__ == "__main__":
    main()
