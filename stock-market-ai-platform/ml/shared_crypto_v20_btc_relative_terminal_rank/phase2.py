"""Shared Crypto V20 BTC-Relative Terminal Rank Phase 2.

OFFLINE RESEARCH ONLY.
No brokerage orders, no paper-state mutation, and no automatic promotion.

Fits only the preregistered V20 HistGradientBoostingRegressor to the within-day
percentile rank of exact seven-day BTC-relative net terminal return.

Learning target:
    target_btc_relative_terminal_percentile_rank_7d

Economic evaluation target:
    btc_relative_net_terminal_return_7d_25bps
      = asset net_terminal_return_7d_25bps
      - same-day BTC net_terminal_return_7d_25bps

The 22 features, HGB specification, seven-day purge, walk-forward protocol,
September 1, 2026 future holdout, and five predictive gates are frozen by
Phase 1.

Predictive evaluation:
* daily Spearman IC compares predicted rank score with raw BTC-relative return;
* predicted top-3 mean BTC-relative return measures actual excess versus BTC;
* daily BTC win fraction measures how often the predicted top-3 mean relative
  return is positive.

All five gates must pass before any offline portfolio simulation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor


RESEARCH_VERSION = "shared_crypto_v20_btc_relative_terminal_rank"

PHASE1_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase1"
)
OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v20_btc_relative_terminal_rank/phase2"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

RANK_TARGET = (
    "target_btc_relative_terminal_percentile_rank_7d"
)
RAW_RELATIVE_TARGET = (
    "btc_relative_net_terminal_return_7d_25bps"
)
NET_TERMINAL = (
    "net_terminal_return_7d_25bps"
)
BTC_NET_TERMINAL = (
    "btc_net_terminal_return_7d_25bps"
)

PRIMARY_MODEL = "hist_gradient_boosting_regressor"
MODEL_LEARNING_RATE = 0.05
MODEL_MAX_ITER = 200
MODEL_MAX_LEAF_NODES = 15
MODEL_MIN_SAMPLES_LEAF = 30
MODEL_L2_REGULARIZATION = 1.0
RANDOM_STATE = 1729

PURGE_DAYS = 7
MIN_TRAIN_DAYS = 730
VALIDATION_DAYS = 180
MAX_FOLDS = 8
MIN_CROSS_SECTION_ASSETS = 10


def model_template() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        learning_rate=MODEL_LEARNING_RATE,
        max_iter=MODEL_MAX_ITER,
        max_leaf_nodes=MODEL_MAX_LEAF_NODES,
        max_depth=None,
        min_samples_leaf=MODEL_MIN_SAMPLES_LEAF,
        l2_regularization=MODEL_L2_REGULARIZATION,
        random_state=RANDOM_STATE,
    )


def validate_pre_holdout(
    frame: pd.DataFrame,
    source: str,
) -> None:
    timestamps = pd.to_datetime(
        frame[
            "timestamp_utc"
        ],
        utc=True,
    )

    if (
        timestamps
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            f"{source} contains future-holdout observations"
        )


def make_folds(
    timestamps: pd.Series,
) -> list[dict]:
    timestamps = pd.to_datetime(
        timestamps,
        utc=True,
    )

    unique_dates = pd.Series(
        timestamps.drop_duplicates()
    ).sort_values().reset_index(
        drop=True
    )

    if unique_dates.empty:
        raise RuntimeError(
            "Cannot construct V20 folds from empty timestamps"
        )

    first = unique_dates.iloc[
        0
    ].floor(
        "D"
    )

    last = unique_dates.iloc[
        -1
    ]

    starts = []
    cursor = (
        first
        + pd.to_timedelta(
            MIN_TRAIN_DAYS,
            unit="D",
        )
    )

    while cursor <= last:
        starts.append(
            cursor
        )
        cursor += pd.to_timedelta(
            VALIDATION_DAYS,
            unit="D",
        )

    starts = starts[
        -MAX_FOLDS:
    ]

    folds = []

    for start in starts:
        end = min(
            start
            + pd.to_timedelta(
                VALIDATION_DAYS,
                unit="D",
            ),
            HOLDOUT,
        )

        train_end = (
            start
            - pd.to_timedelta(
                PURGE_DAYS,
                unit="D",
            )
        )

        train = (
            timestamps
            < train_end
        )

        validation = (
            (
                timestamps
                >= start
            )
            & (
                timestamps
                < end
            )
        )

        if (
            train.any()
            and validation.any()
        ):
            folds.append({
                "fold_id": (
                    f"fold_{len(folds) + 1:02d}"
                ),
                "start": start,
                "end": end,
                "train_end": train_end,
                "train": train,
                "validation": validation,
            })

    if not folds:
        raise RuntimeError(
            "No valid purged V20 folds were constructed"
        )

    return folds


def daily_ranking_metrics(
    validation: pd.DataFrame,
    predicted: np.ndarray,
) -> pd.DataFrame:
    scored = validation[
        [
            "timestamp_utc",
            "product_id",
            RAW_RELATIVE_TARGET,
            RANK_TARGET,
            NET_TERMINAL,
            BTC_NET_TERMINAL,
        ]
    ].copy()

    scored[
        "predicted_rank_score"
    ] = np.asarray(
        predicted,
        dtype=float,
    )

    rows = []

    for timestamp, day in scored.groupby(
        "timestamp_utc",
        sort=True,
    ):
        if (
            day[
                "product_id"
            ].nunique()
            < MIN_CROSS_SECTION_ASSETS
        ):
            raise RuntimeError(
                "V20 validation day violates minimum cross-section breadth"
            )

        actual_relative = pd.to_numeric(
            day[
                RAW_RELATIVE_TARGET
            ],
            errors="raise",
        )

        predicted_day = pd.to_numeric(
            day[
                "predicted_rank_score"
            ],
            errors="raise",
        )

        if (
            actual_relative.nunique()
            > 1
            and predicted_day.nunique()
            > 1
        ):
            ic = float(
                predicted_day.corr(
                    actual_relative,
                    method="spearman",
                )
            )
        else:
            ic = np.nan

        ordered = day.sort_values(
            [
                "predicted_rank_score",
                "product_id",
            ],
            ascending=[
                False,
                True,
            ],
        )

        top3 = ordered.head(
            3
        )

        top3_relative = float(
            pd.to_numeric(
                top3[
                    RAW_RELATIVE_TARGET
                ],
                errors="raise",
            ).mean()
        )

        top3_terminal = float(
            pd.to_numeric(
                top3[
                    NET_TERMINAL
                ],
                errors="raise",
            ).mean()
        )

        btc_values = pd.to_numeric(
            day[
                BTC_NET_TERMINAL
            ],
            errors="raise",
        )

        if (
            btc_values.nunique()
            != 1
        ):
            raise RuntimeError(
                "V20 validation day contains inconsistent BTC reference return"
            )

        btc_terminal = float(
            btc_values.iloc[
                0
            ]
        )

        if not np.isclose(
            top3_relative,
            top3_terminal
            - btc_terminal,
            rtol=0.0,
            atol=1e-12,
        ):
            raise RuntimeError(
                "V20 top-3 BTC-relative metric is internally inconsistent"
            )

        rows.append({
            "timestamp_utc": (
                timestamp
            ),
            "asset_count": int(
                len(
                    day
                )
            ),
            "spearman_ic": (
                ic
            ),
            "top3_mean_btc_relative_terminal_return": (
                top3_relative
            ),
            "top3_mean_net_terminal_return": (
                top3_terminal
            ),
            "btc_net_terminal_return": (
                btc_terminal
            ),
            "top3_beats_btc": bool(
                top3_relative
                > 0.0
            ),
            "mean_predicted_rank_score": float(
                predicted_day.mean()
            ),
            "maximum_predicted_rank_score": float(
                predicted_day.max()
            ),
        })

    return pd.DataFrame(
        rows
    )


def fold_ranking_metrics(
    daily: pd.DataFrame,
) -> dict:
    valid_ic = pd.to_numeric(
        daily[
            "spearman_ic"
        ],
        errors="coerce",
    ).dropna()

    if valid_ic.empty:
        raise RuntimeError(
            "V20 fold has no valid daily Spearman IC observations"
        )

    relative = pd.to_numeric(
        daily[
            "top3_mean_btc_relative_terminal_return"
        ],
        errors="raise",
    )

    return {
        "daily_metric_days": int(
            len(
                daily
            )
        ),
        "valid_ic_days": int(
            len(
                valid_ic
            )
        ),
        "median_daily_spearman_ic": float(
            valid_ic.median()
        ),
        "mean_daily_spearman_ic": float(
            valid_ic.mean()
        ),
        "positive_ic_day_fraction": float(
            (
                valid_ic
                > 0.0
            ).mean()
        ),
        "mean_top3_btc_relative_terminal_excess": float(
            relative.mean()
        ),
        "median_top3_btc_relative_terminal_excess": float(
            relative.median()
        ),
        "top3_daily_btc_win_fraction": float(
            (
                relative
                > 0.0
            ).mean()
        ),
    }


def walk_forward(
    data: pd.DataFrame,
    features: list[str],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    prediction_frames = []
    daily_frames = []
    fold_rows = []

    for fold in make_folds(
        data[
            "timestamp_utc"
        ]
    ):
        train = data.loc[
            fold[
                "train"
            ]
        ].copy()

        validation = data.loc[
            fold[
                "validation"
            ]
        ].copy()

        if (
            train.empty
            or validation.empty
        ):
            raise RuntimeError(
                f"{fold['fold_id']} contains an empty partition"
            )

        if (
            train[
                "timestamp_utc"
            ].max()
            >= fold[
                "train_end"
            ]
        ):
            raise RuntimeError(
                f"{fold['fold_id']} violates the seven-day purge"
            )

        endpoint = pd.to_datetime(
            train[
                "target_endpoint_utc_7d"
            ],
            utc=True,
        )

        if (
            endpoint.max()
            >= validation[
                "timestamp_utc"
            ].min()
        ):
            raise RuntimeError(
                f"{fold['fold_id']} target path leaks into validation"
            )

        if (
            validation[
                "timestamp_utc"
            ].max()
            >= HOLDOUT
        ):
            raise RuntimeError(
                f"{fold['fold_id']} reaches the future holdout"
            )

        model = clone(
            model_template()
        )

        model.fit(
            train[
                features
            ],
            train[
                RANK_TARGET
            ],
        )

        predicted = np.asarray(
            model.predict(
                validation[
                    features
                ]
            ),
            dtype=float,
        )

        if not np.isfinite(
            predicted
        ).all():
            raise RuntimeError(
                f"{fold['fold_id']} produced non-finite predictions"
            )

        out = validation[
            [
                "timestamp_utc",
                "product_id",
                RANK_TARGET,
                RAW_RELATIVE_TARGET,
                NET_TERMINAL,
                BTC_NET_TERMINAL,
                "eligible_asset_count",
                "target_endpoint_utc_7d",
            ]
        ].copy()

        out[
            "fold_id"
        ] = (
            fold[
                "fold_id"
            ]
        )

        out[
            "predicted_rank_score"
        ] = (
            predicted
        )

        out[
            "predicted_cross_sectional_rank"
        ] = (
            out.groupby(
                "timestamp_utc"
            )[
                "predicted_rank_score"
            ]
            .rank(
                method="first",
                ascending=False,
            )
        )

        out[
            "actual_cross_sectional_rank"
        ] = (
            out.groupby(
                "timestamp_utc"
            )[
                RAW_RELATIVE_TARGET
            ]
            .rank(
                method="average",
                ascending=False,
            )
        )

        daily = daily_ranking_metrics(
            validation,
            predicted,
        )

        daily[
            "fold_id"
        ] = (
            fold[
                "fold_id"
            ]
        )

        metrics = fold_ranking_metrics(
            daily
        )

        fold_rows.append({
            "fold_id": (
                fold[
                    "fold_id"
                ]
            ),
            "train_rows": int(
                len(
                    train
                )
            ),
            "validation_rows": int(
                len(
                    validation
                )
            ),
            "train_days": int(
                train[
                    "timestamp_utc"
                ].nunique()
            ),
            "validation_days": int(
                validation[
                    "timestamp_utc"
                ].nunique()
            ),
            "train_end_exclusive_utc": (
                fold[
                    "train_end"
                ].isoformat()
            ),
            "validation_start_utc": (
                fold[
                    "start"
                ].isoformat()
            ),
            "validation_end_utc": (
                fold[
                    "end"
                ].isoformat()
            ),
            **metrics,
        })

        prediction_frames.append(
            out
        )

        daily_frames.append(
            daily
        )

        print(
            f"[SUCCESS] {fold['fold_id']} "
            f"train_rows={len(train):,} "
            f"validation_rows={len(validation):,} "
            f"validation_days={validation['timestamp_utc'].nunique():,} "
            f"features={len(features)} "
            "purge=7d "
            "target=btc-relative-terminal-rank "
            "model=frozen-hgb "
            "research=offline-only"
        )

    return (
        pd.concat(
            prediction_frames,
            ignore_index=True,
        ),
        pd.concat(
            daily_frames,
            ignore_index=True,
        ),
        pd.DataFrame(
            fold_rows
        ),
    )


def summarize(
    fold_metrics: pd.DataFrame,
) -> pd.DataFrame:
    row = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "fold_count": int(
            fold_metrics[
                "fold_id"
            ].nunique()
        ),
        "median_fold_daily_spearman_ic": float(
            fold_metrics[
                "median_daily_spearman_ic"
            ].median()
        ),
        "mean_fold_daily_spearman_ic": float(
            fold_metrics[
                "median_daily_spearman_ic"
            ].mean()
        ),
        "median_fold_positive_ic_day_fraction": float(
            fold_metrics[
                "positive_ic_day_fraction"
            ].median()
        ),
        "median_fold_top3_btc_relative_terminal_excess": float(
            fold_metrics[
                "mean_top3_btc_relative_terminal_excess"
            ].median()
        ),
        "mean_fold_top3_btc_relative_terminal_excess": float(
            fold_metrics[
                "mean_top3_btc_relative_terminal_excess"
            ].mean()
        ),
        "positive_fold_top3_btc_relative_terminal_excess_fraction": float(
            (
                fold_metrics[
                    "mean_top3_btc_relative_terminal_excess"
                ]
                > 0.0
            ).mean()
        ),
        "median_fold_top3_daily_btc_win_fraction": float(
            fold_metrics[
                "top3_daily_btc_win_fraction"
            ].median()
        ),
    }

    return pd.DataFrame([
        row
    ])


def evaluate_predictive_gates(
    summary: pd.DataFrame,
    contract: dict,
) -> tuple[
    pd.DataFrame,
    dict,
]:
    if len(
        summary
    ) != 1:
        raise RuntimeError(
            "V20 predictive summary must contain exactly one row"
        )

    row = summary.iloc[
        0
    ]

    gates = contract[
        "predictive_quality_gates"
    ]

    checks = [
        (
            "gate_median_fold_daily_spearman_ic_gt_005",
            float(
                row[
                    "median_fold_daily_spearman_ic"
                ]
            )
            > float(
                gates[
                    "median_fold_daily_spearman_ic_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_positive_ic_day_fraction_gt_52pct",
            float(
                row[
                    "median_fold_positive_ic_day_fraction"
                ]
            )
            > float(
                gates[
                    "median_fold_positive_ic_day_fraction_gt"
                ]
            ),
        ),
        (
            "gate_median_fold_top3_btc_relative_terminal_excess_gt_zero",
            float(
                row[
                    "median_fold_top3_btc_relative_terminal_excess"
                ]
            )
            > float(
                gates[
                    "median_fold_top3_btc_relative_terminal_excess_gt"
                ]
            ),
        ),
        (
            "gate_positive_fold_top3_btc_relative_terminal_excess_fraction_gte_75pct",
            float(
                row[
                    "positive_fold_top3_btc_relative_terminal_excess_fraction"
                ]
            )
            >= float(
                gates[
                    "positive_fold_top3_btc_relative_terminal_excess_fraction_gte"
                ]
            ),
        ),
        (
            "gate_median_fold_top3_daily_btc_win_fraction_gt_50pct",
            float(
                row[
                    "median_fold_top3_daily_btc_win_fraction"
                ]
            )
            > float(
                gates[
                    "median_fold_top3_daily_btc_win_fraction_gt"
                ]
            ),
        ),
    ]

    passed = int(
        sum(
            bool(
                value
            )
            for _, value
            in checks
        )
    )

    total = len(
        checks
    )

    all_pass = bool(
        passed
        == total
    )

    detail = pd.DataFrame([
        {
            "research_version": (
                RESEARCH_VERSION
            ),
            **{
                name: bool(
                    value
                )
                for name, value
                in checks
            },
            "passed_gate_count": (
                passed
            ),
            "total_gate_count": (
                total
            ),
            "median_fold_daily_spearman_ic": float(
                row[
                    "median_fold_daily_spearman_ic"
                ]
            ),
            "median_fold_positive_ic_day_fraction": float(
                row[
                    "median_fold_positive_ic_day_fraction"
                ]
            ),
            "median_fold_top3_btc_relative_terminal_excess": float(
                row[
                    "median_fold_top3_btc_relative_terminal_excess"
                ]
            ),
            "positive_fold_top3_btc_relative_terminal_excess_fraction": float(
                row[
                    "positive_fold_top3_btc_relative_terminal_excess_fraction"
                ]
            ),
            "median_fold_top3_daily_btc_win_fraction": float(
                row[
                    "median_fold_top3_daily_btc_win_fraction"
                ]
            ),
        }
    ])

    result = {
        "target_count": 1,
        "total_predictive_gate_count": (
            total
        ),
        "passed_predictive_gate_count": (
            passed
        ),
        "all_predictive_gates_pass": (
            all_pass
        ),
        "status": (
            "ALLOW_OFFLINE_PORTFOLIO_SIMULATION"
            if all_pass
            else "STOP_BEFORE_PORTFOLIO_SIMULATION"
        ),
    }

    return (
        detail,
        result,
    )


def _validate_contract(
    contract: dict,
) -> list[str]:
    if (
        contract.get(
            "research_version"
        )
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V20 Phase 1 research version"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "V20 Phase 1 holdout differs from Phase 2"
        )

    target = contract.get(
        "learning_target",
        {},
    )

    if (
        target.get(
            "primary"
        )
        != RANK_TARGET
    ):
        raise RuntimeError(
            "Unexpected V20 learning target"
        )

    if (
        target.get(
            "raw_economic_target"
        )
        != RAW_RELATIVE_TARGET
    ):
        raise RuntimeError(
            "Unexpected V20 economic target"
        )

    if (
        target.get(
            "btc_reference_return"
        )
        != BTC_NET_TERMINAL
    ):
        raise RuntimeError(
            "Unexpected V20 BTC reference target"
        )

    expected_model = {
        "primary": (
            PRIMARY_MODEL
        ),
        "learning_rate": (
            MODEL_LEARNING_RATE
        ),
        "max_iter": (
            MODEL_MAX_ITER
        ),
        "max_leaf_nodes": (
            MODEL_MAX_LEAF_NODES
        ),
        "max_depth": None,
        "min_samples_leaf": (
            MODEL_MIN_SAMPLES_LEAF
        ),
        "l2_regularization": (
            MODEL_L2_REGULARIZATION
        ),
        "random_state": (
            RANDOM_STATE
        ),
        "secondary_models": [],
    }

    if (
        contract.get(
            "model"
        )
        != expected_model
    ):
        raise RuntimeError(
            "V20 model differs from preregistration"
        )

    expected_walk = {
        "purge_days": PURGE_DAYS,
        "minimum_train_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "max_folds": (
            MAX_FOLDS
        ),
        "minimum_cross_section_assets": (
            MIN_CROSS_SECTION_ASSETS
        ),
    }

    if (
        contract.get(
            "walk_forward"
        )
        != expected_walk
    ):
        raise RuntimeError(
            "V20 walk-forward contract differs from preregistration"
        )

    expected_gates = {
        "median_fold_daily_spearman_ic_gt": 0.05,
        "median_fold_positive_ic_day_fraction_gt": 0.52,
        "median_fold_top3_btc_relative_terminal_excess_gt": 0.0,
        "positive_fold_top3_btc_relative_terminal_excess_fraction_gte": 0.75,
        "median_fold_top3_daily_btc_win_fraction_gt": 0.50,
        "all_gates_required_before_portfolio_simulation": True,
    }

    if (
        contract.get(
            "predictive_quality_gates"
        )
        != expected_gates
    ):
        raise RuntimeError(
            "V20 predictive gates differ from preregistration"
        )

    constraints = contract.get(
        "research_constraints",
        {},
    )

    for key in (
        "offline_research_only",
        "asset_level_cross_sectional_learning",
        "same_22_features_as_v15",
        "same_model_specification_as_v15",
        "same_walk_forward_protocol_as_v15",
        "btc_relative_terminal_target_fixed_before_fit",
        "predictive_gates_fixed_before_fit",
        "no_model_family_search",
        "no_secondary_model_search",
        "no_hyperparameter_search",
        "no_probability_threshold",
        "no_post_result_threshold_search",
        "predictive_gates_required_before_portfolio_simulation",
        "future_holdout_must_remain_untouched_until_candidate_freeze",
    ):
        if (
            constraints.get(
                key
            )
            is not True
        ):
            raise RuntimeError(
                "V20 Phase 1 research constraint failed: "
                f"{key}"
            )

    for key in (
        "day_level_binary_gate",
        "paper_state_modified",
        "brokerage_orders",
        "automatic_promotion",
    ):
        if (
            constraints.get(
                key
            )
            is not False
        ):
            raise RuntimeError(
                "V20 Phase 1 negative research constraint failed: "
                f"{key}"
            )

    features = list(
        contract[
            "model_feature_columns"
        ]
    )

    if len(
        features
    ) != 22:
        raise RuntimeError(
            "V20 expected exactly 22 preregistered model features"
        )

    return features


def run(
    phase1_root: Path = PHASE1_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_root = Path(
        phase1_root
    )

    output_root = Path(
        output_root
    )

    contract = json.loads(
        (
            phase1_root
            / "preregistered_contract.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    features = _validate_contract(
        contract
    )

    data = pd.read_parquet(
        phase1_root
        / "asset_btc_relative_terminal_rank_dataset.parquet"
    ).copy()

    data[
        "timestamp_utc"
    ] = pd.to_datetime(
        data[
            "timestamp_utc"
        ],
        utc=True,
    )

    data[
        "target_endpoint_utc_7d"
    ] = pd.to_datetime(
        data[
            "target_endpoint_utc_7d"
        ],
        utc=True,
    )

    validate_pre_holdout(
        data,
        "V20 Phase 1 dataset",
    )

    required = {
        "timestamp_utc",
        "product_id",
        RANK_TARGET,
        RAW_RELATIVE_TARGET,
        NET_TERMINAL,
        BTC_NET_TERMINAL,
        "eligible_asset_count",
        "target_endpoint_utc_7d",
        *features,
    }

    missing = (
        required
        - set(
            data.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V20 Phase 1 dataset missing columns: "
            f"{sorted(missing)}"
        )

    finite = data[
        [
            *features,
            RANK_TARGET,
            RAW_RELATIVE_TARGET,
            NET_TERMINAL,
            BTC_NET_TERMINAL,
        ]
    ].replace(
        [
            np.inf,
            -np.inf,
        ],
        np.nan,
    )

    if (
        finite
        .isna()
        .any()
        .any()
    ):
        raise RuntimeError(
            "V20 Phase 1 dataset contains non-finite inputs or targets"
        )

    rank_target = pd.to_numeric(
        data[
            RANK_TARGET
        ],
        errors="raise",
    )

    if (
        (
            rank_target
            <= 0.0
        ).any()
        or (
            rank_target
            > 1.0
        ).any()
    ):
        raise RuntimeError(
            "V20 rank target must remain in (0, 1]"
        )

    predictions, daily, fold_metrics = (
        walk_forward(
            data,
            features,
        )
    )

    summary = summarize(
        fold_metrics
    )

    gate_detail, gate_result = (
        evaluate_predictive_gates(
            summary,
            contract,
        )
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    prediction_path = (
        output_root
        / "asset_predictions.parquet"
    )

    daily_path = (
        output_root
        / "daily_ranking_metrics.csv"
    )

    fold_path = (
        output_root
        / "fold_metrics.csv"
    )

    summary_path = (
        output_root
        / "metrics_summary.csv"
    )

    gate_detail_path = (
        output_root
        / "predictive_gate_detail.csv"
    )

    gate_result_path = (
        output_root
        / "predictive_gate_result.json"
    )

    predictions.to_parquet(
        prediction_path,
        index=False,
    )

    daily.to_csv(
        daily_path,
        index=False,
    )

    fold_metrics.to_csv(
        fold_path,
        index=False,
    )

    summary.to_csv(
        summary_path,
        index=False,
    )

    gate_detail.to_csv(
        gate_detail_path,
        index=False,
    )

    gate_result_path.write_text(
        json.dumps(
            gate_result,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 2,
        "stage": (
            "purged_7d_btc_relative_terminal_rank_predictive_adjudication"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "learning_target": (
            RANK_TARGET
        ),
        "economic_evaluation_target": (
            RAW_RELATIVE_TARGET
        ),
        "model": (
            PRIMARY_MODEL
        ),
        "model_feature_count": int(
            len(
                features
            )
        ),
        "purge_days": (
            PURGE_DAYS
        ),
        "minimum_train_days": (
            MIN_TRAIN_DAYS
        ),
        "validation_days": (
            VALIDATION_DAYS
        ),
        "max_folds": (
            MAX_FOLDS
        ),
        "input_rows": int(
            len(
                data
            )
        ),
        "input_products": int(
            data[
                "product_id"
            ].nunique()
        ),
        "input_days": int(
            data[
                "timestamp_utc"
            ].nunique()
        ),
        "prediction_rows": int(
            len(
                predictions
            )
        ),
        "prediction_days": int(
            predictions[
                "timestamp_utc"
            ].nunique()
        ),
        "fold_count": int(
            fold_metrics[
                "fold_id"
            ].nunique()
        ),
        "predictive_gate_status": (
            gate_result[
                "status"
            ]
        ),
        "passed_predictive_gate_count": (
            gate_result[
                "passed_predictive_gate_count"
            ]
        ),
        "total_predictive_gate_count": (
            gate_result[
                "total_predictive_gate_count"
            ]
        ),
        "outputs": {
            "asset_predictions": str(
                prediction_path
            ),
            "daily_ranking_metrics": str(
                daily_path
            ),
            "fold_metrics": str(
                fold_path
            ),
            "metrics_summary": str(
                summary_path
            ),
            "predictive_gate_detail": str(
                gate_detail_path
            ),
            "predictive_gate_result": str(
                gate_result_path
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "safety": {
            "offline_research_only": True,
            "shared_crypto_v15_modified": False,
            "shared_crypto_v19_modified": False,
            "future_holdout_scored": False,
            "portfolio_simulated": False,
            "model_family_searched": False,
            "secondary_model_fit": False,
            "hyperparameters_tuned": False,
            "predictive_gate_lowered": False,
            "threshold_search_performed": False,
            "model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Run the preregistered offline V20 portfolio policy only if all "
            "five predictive gates pass. Otherwise preserve V20 as failed "
            "predictive evidence and do not simulate the portfolio."
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

    return manifest


def main(
    argv=None,
) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--phase1-root",
        type=Path,
        default=PHASE1_ROOT,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )

    args = parser.parse_args(
        argv
    )

    print(
        json.dumps(
            run(
                args.phase1_root,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
