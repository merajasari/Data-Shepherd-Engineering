"""Shared Crypto V15 Cross-Sectional Rank Phase 3.

Runs the single frozen portfolio policy preregistered before V15 Phase 2.

This phase is allowed only because all four V15 predictive ranking gates passed.
It uses only Phase 2 out-of-sample predictions and non-overlapping exact
seven-day blocks inside each validation fold.

Frozen V15 policy:
* rank eligible assets by predicted cross-sectional rank score;
* select exactly top 3 assets;
* 20% weight per selected asset;
* 40% CASH;
* maximum gross crypto exposure 60%;
* maximum turnover per seven-day decision 60%;
* primary transaction cost 25 bps;
* stress transaction cost 50 bps;
* no leverage, shorting, or derivatives.

Matched controls follow the established shared-crypto research convention:
* always BTC;
* Shared Crypto V3 frozen HGB labels sampled on the matched daily clock with
  confirm-2. V3 ALT is represented by the contemporaneous equal-weight eligible
  ALT universe, excluding BTC and XRP because Shared V3 historically excluded
  XRP.

All eight preregistered portfolio gates are evaluated. This phase cannot score
the September 1, 2026 future holdout, freeze a model automatically, modify paper
state, or place brokerage orders.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd


RESEARCH_VERSION = "shared_crypto_v15_cross_sectional_rank"

PHASE1_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase1"
)
PHASE1_CONTRACT = (
    PHASE1_ROOT
    / "preregistered_contract.json"
)
PHASE2_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase2"
)
PHASE2_PREDICTIONS = (
    PHASE2_ROOT
    / "asset_predictions.parquet"
)
PHASE2_GATE_RESULT = (
    PHASE2_ROOT
    / "predictive_gate_result.json"
)
PHASE2_MANIFEST = (
    PHASE2_ROOT
    / "manifest.json"
)

SHARED_V3_PREDICTIONS = Path(
    "data/model/crypto_15m_v2/phase2/predictions.parquet"
)

OUTPUT_ROOT = Path(
    "data/model/shared_crypto_v15_cross_sectional_rank/phase3"
)

HOLDOUT = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)
HORIZON = pd.to_timedelta(
    7,
    unit="D",
)

BTC = "BTC-USD"
XRP = "XRP-USD"
CASH = "CASH"

SHARED_V3_MODEL_ID = "hist_gradient_boosting"
SHARED_V3_CONFIRMATION = 2

RAW_TARGET = "path_utility_net25_7d"
TERMINAL_NET25 = "net_terminal_return_7d_25bps"
PREDICTED_SCORE = "predicted_rank_score"

PRIMARY_COST_BPS = 25.0
STRESS_COST_BPS = 50.0

ASSET_WEIGHT = 0.20
SELECTED_ASSET_COUNT = 3
CASH_WEIGHT = 0.40
MAXIMUM_GROSS = 0.60
MAXIMUM_TURNOVER = 0.60


def validate_pre_holdout(
    frame: pd.DataFrame,
    source: str,
) -> None:
    timestamps = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
    )
    if (
        timestamps
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            f"{source} contains future-holdout observations"
        )


def _read_parquet(
    path: Path,
    source: str,
) -> pd.DataFrame:
    path = Path(
        path
    )

    if not path.exists():
        raise FileNotFoundError(
            path
        )

    frame = pd.read_parquet(
        path
    ).copy()

    if (
        "timestamp_utc"
        not in frame.columns
    ):
        raise RuntimeError(
            f"{source} lacks timestamp_utc"
        )

    frame[
        "timestamp_utc"
    ] = pd.to_datetime(
        frame[
            "timestamp_utc"
        ],
        utc=True,
    )

    validate_pre_holdout(
        frame,
        source,
    )

    return frame


def turnover(
    old: dict[str, float],
    new: dict[str, float],
) -> float:
    keys = (
        set(
            old
        )
        | set(
            new
        )
    )

    return 0.5 * sum(
        abs(
            new.get(
                key,
                0.0,
            )
            - old.get(
                key,
                0.0,
            )
        )
        for key in keys
    )


def cap_turnover(
    old: dict[str, float],
    target: dict[str, float],
    maximum_turnover: float,
) -> tuple[
    dict[str, float],
    float,
]:
    desired = turnover(
        old,
        target,
    )

    if (
        desired
        <= maximum_turnover
        or desired == 0.0
    ):
        return (
            target.copy(),
            desired,
        )

    fraction = (
        maximum_turnover
        / desired
    )

    keys = (
        set(
            old
        )
        | set(
            target
        )
    )

    adjusted = {
        key: (
            old.get(
                key,
                0.0,
            )
            + fraction
            * (
                target.get(
                    key,
                    0.0,
                )
                - old.get(
                    key,
                    0.0,
                )
            )
        )
        for key in keys
    }

    adjusted = {
        key: value
        for key, value
        in adjusted.items()
        if value > 1e-12
    }

    return (
        adjusted,
        turnover(
            old,
            adjusted,
        ),
    )


def _drawdown(
    returns: pd.Series,
) -> float:
    equity = (
        1.0
        + pd.to_numeric(
            returns,
            errors="raise",
        )
    ).cumprod()

    if equity.empty:
        return 0.0

    return float(
        (
            equity
            / equity.cummax()
            - 1.0
        ).min()
    )


def gross_terminal_return(
    terminal_net25: float,
) -> float:
    return float(
        terminal_net25
        + PRIMARY_COST_BPS
        / 10000.0
    )


def build_target_weights(
    selected_assets: list[str],
    policy: dict,
) -> dict[str, float]:
    expected_count = int(
        policy[
            "selected_asset_count"
        ]
    )

    if len(
        selected_assets
    ) != expected_count:
        raise RuntimeError(
            "V15 policy requires exactly three selected assets"
        )

    if len(
        set(
            selected_assets
        )
    ) != expected_count:
        raise RuntimeError(
            "V15 selected assets must be unique"
        )

    asset_weight = float(
        policy[
            "asset_weight"
        ]
    )
    cash_weight = float(
        policy[
            "cash_weight"
        ]
    )
    maximum_gross = float(
        policy[
            "maximum_gross_crypto_exposure"
        ]
    )

    risky_weight = (
        asset_weight
        * expected_count
    )

    if not np.isclose(
        risky_weight,
        maximum_gross,
        atol=1e-12,
    ):
        raise RuntimeError(
            "V15 risky weights do not equal frozen maximum gross exposure"
        )

    if not np.isclose(
        risky_weight
        + cash_weight,
        1.0,
        atol=1e-12,
    ):
        raise RuntimeError(
            "V15 frozen portfolio weights do not sum to one"
        )

    weights = {
        asset: asset_weight
        for asset
        in selected_assets
    }
    weights[
        CASH
    ] = cash_weight

    return weights


def _prepare_shared_v3(
    path: Path,
) -> pd.DataFrame:
    shared = _read_parquet(
        path,
        "Shared Crypto V3 predictions",
    )

    required = {
        "timestamp_utc",
        "model_id",
        "predicted_label",
    }

    missing = (
        required
        - set(
            shared.columns
        )
    )

    if missing:
        raise RuntimeError(
            "Shared Crypto V3 predictions missing columns: "
            f"{sorted(missing)}"
        )

    shared = shared[
        shared[
            "model_id"
        ]
        == SHARED_V3_MODEL_ID
    ].copy()

    if shared.empty:
        raise RuntimeError(
            "Shared Crypto V3 HGB predictions are empty"
        )

    shared = (
        shared.sort_values(
            "timestamp_utc"
        )
        .drop_duplicates(
            "timestamp_utc",
            keep="last",
        )
        .reset_index(
            drop=True
        )
    )

    labels = set(
        shared[
            "predicted_label"
        ].astype(
            str
        ).unique()
    )

    if not labels.issubset(
        {
            "BTC",
            "ALT",
            "CASH",
        }
    ):
        raise RuntimeError(
            "Shared Crypto V3 contains unexpected sleeve labels"
        )

    return shared[
        [
            "timestamp_utc",
            "predicted_label",
        ]
    ].copy()


def select_non_overlapping_blocks(
    predictions: pd.DataFrame,
    shared: pd.DataFrame,
) -> pd.DataFrame:
    decision_rows = (
        predictions[
            [
                "fold_id",
                "timestamp_utc",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            [
                "fold_id",
                "timestamp_utc",
            ]
        )
        .reset_index(
            drop=True
        )
    )

    shared_clock = set(
        shared[
            "timestamp_utc"
        ]
    )

    decision_rows = decision_rows[
        decision_rows[
            "timestamp_utc"
        ].isin(
            shared_clock
        )
    ].copy()

    rows = []

    for fold_id, fold in decision_rows.groupby(
        "fold_id",
        sort=True,
    ):
        last_entry = None

        for row in fold.sort_values(
            "timestamp_utc"
        ).itertuples(
            index=False
        ):
            timestamp = (
                row.timestamp_utc
            )

            if (
                last_entry is None
                or timestamp
                - last_entry
                >= HORIZON
            ):
                rows.append({
                    "fold_id": (
                        fold_id
                    ),
                    "timestamp_utc": (
                        timestamp
                    ),
                })
                last_entry = (
                    timestamp
                )

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        raise RuntimeError(
            "V15 produced no matched non-overlapping seven-day blocks"
        )

    for _, fold in result.groupby(
        "fold_id",
        sort=True,
    ):
        gaps = (
            fold[
                "timestamp_utc"
            ]
            .sort_values()
            .diff()
            .dropna()
        )

        if (
            not gaps.empty
            and (
                gaps
                < HORIZON
            ).any()
        ):
            raise RuntimeError(
                "V15 Phase 3 contains overlapping seven-day blocks"
            )

    return result.sort_values(
        [
            "fold_id",
            "timestamp_utc",
        ]
    ).reset_index(
        drop=True
    )


def _prepare(
    prediction_path: Path,
    shared_v3_path: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    predictions = _read_parquet(
        prediction_path,
        "V15 Phase 2 predictions",
    )

    required = {
        "timestamp_utc",
        "product_id",
        "fold_id",
        PREDICTED_SCORE,
        RAW_TARGET,
        TERMINAL_NET25,
        "target_endpoint_utc_7d",
    }

    missing = (
        required
        - set(
            predictions.columns
        )
    )

    if missing:
        raise RuntimeError(
            "V15 predictions missing columns: "
            f"{sorted(missing)}"
        )

    predictions[
        "target_endpoint_utc_7d"
    ] = pd.to_datetime(
        predictions[
            "target_endpoint_utc_7d"
        ],
        utc=True,
    )

    if (
        predictions[
            "target_endpoint_utc_7d"
        ]
        >= HOLDOUT
    ).any():
        raise RuntimeError(
            "V15 portfolio source target path reaches the future holdout"
        )

    shared = _prepare_shared_v3(
        shared_v3_path
    )

    blocks = (
        select_non_overlapping_blocks(
            predictions,
            shared,
        )
    )

    selected_keys = (
        blocks.assign(
            _selected=True
        )
    )

    assets = predictions.merge(
        selected_keys,
        on=[
            "fold_id",
            "timestamp_utc",
        ],
        how="inner",
        validate="many_to_one",
    )

    counts = (
        assets.groupby(
            [
                "fold_id",
                "timestamp_utc",
            ]
        )[
            "product_id"
        ]
        .nunique()
    )

    if (
        counts
        < SELECTED_ASSET_COUNT
    ).any():
        raise RuntimeError(
            "V15 matched block has fewer than three eligible assets"
        )

    shared = shared[
        shared[
            "timestamp_utc"
        ].isin(
            set(
                blocks[
                    "timestamp_utc"
                ]
            )
        )
    ].copy()

    if (
        shared[
            "timestamp_utc"
        ].nunique()
        != blocks[
            "timestamp_utc"
        ].nunique()
    ):
        raise RuntimeError(
            "Shared Crypto V3 matched control clock is incomplete"
        )

    return (
        blocks,
        assets.sort_values(
            [
                "fold_id",
                "timestamp_utc",
                "product_id",
            ]
        ).reset_index(
            drop=True
        ),
        shared.sort_values(
            "timestamp_utc"
        ).reset_index(
            drop=True
        ),
    )


def simulate_candidate(
    blocks: pd.DataFrame,
    assets: pd.DataFrame,
    policy: dict,
    cost_bps: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    maximum_turnover = float(
        policy[
            "maximum_turnover_per_7d_decision"
        ]
    )

    groups = {
        (
            fold_id,
            timestamp,
        ): group
        for (
            fold_id,
            timestamp,
        ), group in assets.groupby(
            [
                "fold_id",
                "timestamp_utc",
            ],
            sort=True,
        )
    }

    period_rows = []

    for fold_id, fold in blocks.groupby(
        "fold_id",
        sort=True,
    ):
        weights = {
            CASH: 1.0
        }

        for row in fold.sort_values(
            "timestamp_utc"
        ).itertuples(
            index=False
        ):
            timestamp = (
                row.timestamp_utc
            )

            daily_assets = groups.get(
                (
                    fold_id,
                    timestamp,
                )
            )

            if (
                daily_assets is None
                or daily_assets.empty
            ):
                raise RuntimeError(
                    f"Missing V15 assets for {fold_id} {timestamp}"
                )

            ordered = daily_assets.sort_values(
                [
                    PREDICTED_SCORE,
                    "product_id",
                ],
                ascending=[
                    False,
                    True,
                ],
            )

            selected_assets = (
                ordered.head(
                    SELECTED_ASSET_COUNT
                )[
                    "product_id"
                ]
                .astype(
                    str
                )
                .tolist()
            )

            target = build_target_weights(
                selected_assets,
                policy,
            )

            new_weights, realized_turnover = (
                cap_turnover(
                    weights,
                    target,
                    maximum_turnover,
                )
            )

            gross_returns = {
                str(
                    asset_row.product_id
                ): gross_terminal_return(
                    float(
                        getattr(
                            asset_row,
                            TERMINAL_NET25,
                        )
                    )
                )
                for asset_row
                in daily_assets.itertuples(
                    index=False
                )
            }
            gross_returns[
                CASH
            ] = 0.0

            unavailable = (
                set(
                    new_weights
                )
                - set(
                    gross_returns
                )
            )

            if unavailable:
                raise RuntimeError(
                    "V15 portfolio holds unavailable assets: "
                    f"{sorted(unavailable)}"
                )

            gross_return = float(
                sum(
                    weight
                    * gross_returns[
                        asset
                    ]
                    for asset, weight
                    in new_weights.items()
                )
            )

            transaction_cost = (
                realized_turnover
                * float(
                    cost_bps
                )
                / 10000.0
            )

            net_return = (
                gross_return
                - transaction_cost
            )

            period_rows.append({
                "timestamp_utc": (
                    timestamp
                ),
                "fold_id": (
                    fold_id
                ),
                "cost_bps": float(
                    cost_bps
                ),
                "selected_assets": (
                    "|".join(
                        selected_assets
                    )
                ),
                "selected_asset_count": int(
                    len(
                        selected_assets
                    )
                ),
                "turnover": (
                    realized_turnover
                ),
                "gross_return": (
                    gross_return
                ),
                "transaction_cost": (
                    transaction_cost
                ),
                "net_return": (
                    net_return
                ),
                "cash_weight": float(
                    new_weights.get(
                        CASH,
                        0.0,
                    )
                ),
                "crypto_weight": float(
                    1.0
                    - new_weights.get(
                        CASH,
                        0.0,
                    )
                ),
                "btc_weight": float(
                    new_weights.get(
                        BTC,
                        0.0,
                    )
                ),
                "xrp_weight": float(
                    new_weights.get(
                        XRP,
                        0.0,
                    )
                ),
            })

            weights = (
                new_weights
            )

    periods = pd.DataFrame(
        period_rows
    )

    fold_rows = []

    for (
        cost,
        fold_id,
    ), group in periods.groupby(
        [
            "cost_bps",
            "fold_id",
        ],
        sort=True,
    ):
        fold_rows.append({
            "cost_bps": float(
                cost
            ),
            "fold_id": (
                fold_id
            ),
            "observations": int(
                len(
                    group
                )
            ),
            "net_return": float(
                (
                    1.0
                    + group[
                        "net_return"
                    ]
                ).prod()
                - 1.0
            ),
            "gross_return": float(
                (
                    1.0
                    + group[
                        "gross_return"
                    ]
                ).prod()
                - 1.0
            ),
            "maximum_drawdown": (
                _drawdown(
                    group[
                        "net_return"
                    ]
                )
            ),
            "total_turnover": float(
                group[
                    "turnover"
                ].sum()
            ),
            "total_transaction_cost": float(
                group[
                    "transaction_cost"
                ].sum()
            ),
            "mean_cash_weight": float(
                group[
                    "cash_weight"
                ].mean()
            ),
            "mean_crypto_weight": float(
                group[
                    "crypto_weight"
                ].mean()
            ),
            "mean_btc_weight": float(
                group[
                    "btc_weight"
                ].mean()
            ),
            "mean_xrp_weight": float(
                group[
                    "xrp_weight"
                ].mean()
            ),
        })

    return (
        periods,
        pd.DataFrame(
            fold_rows
        ),
    )


def _block_realized_controls(
    block_assets: pd.DataFrame,
) -> tuple[
    float,
    float,
]:
    gross = block_assets.assign(
        gross_terminal_return_7d=(
            pd.to_numeric(
                block_assets[
                    TERMINAL_NET25
                ],
                errors="raise",
            )
            + PRIMARY_COST_BPS
            / 10000.0
        )
    )

    btc = gross[
        gross[
            "product_id"
        ]
        == BTC
    ]

    if len(
        btc
    ) != 1:
        raise RuntimeError(
            "V15 matched control requires exactly one BTC row"
        )

    btc_return = float(
        btc.iloc[
            0
        ][
            "gross_terminal_return_7d"
        ]
    )

    alt = gross[
        ~gross[
            "product_id"
        ].isin(
            [
                BTC,
                XRP,
            ]
        )
    ]

    if alt.empty:
        raise RuntimeError(
            "Shared Crypto V3 ALT control has no eligible ALT assets"
        )

    alt_return = float(
        alt[
            "gross_terminal_return_7d"
        ].mean()
    )

    return (
        btc_return,
        alt_return,
    )


def simulate_controls(
    blocks: pd.DataFrame,
    assets: pd.DataFrame,
    shared: pd.DataFrame,
    cost_bps: float,
) -> pd.DataFrame:
    shared_map = (
        shared.set_index(
            "timestamp_utc"
        )[
            "predicted_label"
        ]
        .astype(
            str
        )
        .to_dict()
    )

    groups = {
        (
            fold_id,
            timestamp,
        ): group
        for (
            fold_id,
            timestamp,
        ), group in assets.groupby(
            [
                "fold_id",
                "timestamp_utc",
            ],
            sort=True,
        )
    }

    rows = []

    for fold_id, fold in blocks.groupby(
        "fold_id",
        sort=True,
    ):
        state = "BTC"
        pending = None
        pending_count = 0

        v3_returns = []
        btc_returns = []

        for row in fold.sort_values(
            "timestamp_utc"
        ).itertuples(
            index=False
        ):
            timestamp = (
                row.timestamp_utc
            )

            label = shared_map.get(
                timestamp
            )

            if label is None:
                raise RuntimeError(
                    f"Missing Shared V3 label for {timestamp}"
                )

            switched = False

            if label == state:
                pending = None
                pending_count = 0
            else:
                if pending == label:
                    pending_count += 1
                else:
                    pending = label
                    pending_count = 1

                if (
                    pending_count
                    >= SHARED_V3_CONFIRMATION
                ):
                    state = label
                    pending = None
                    pending_count = 0
                    switched = True

            block_assets = groups.get(
                (
                    fold_id,
                    timestamp,
                )
            )

            if (
                block_assets is None
                or block_assets.empty
            ):
                raise RuntimeError(
                    f"Missing V15 control assets for {fold_id} {timestamp}"
                )

            (
                btc_return,
                alt_return,
            ) = _block_realized_controls(
                block_assets
            )

            selected = (
                btc_return
                if state == "BTC"
                else alt_return
                if state == "ALT"
                else 0.0
            )

            v3_returns.append(
                selected
                - (
                    float(
                        cost_bps
                    )
                    / 10000.0
                    if switched
                    else 0.0
                )
            )

            btc_returns.append(
                btc_return
            )

        v3 = pd.Series(
            v3_returns,
            dtype=float,
        )
        btc = pd.Series(
            btc_returns,
            dtype=float,
        )

        rows.append({
            "cost_bps": float(
                cost_bps
            ),
            "fold_id": (
                fold_id
            ),
            "shared_v3_net_return": float(
                (
                    1.0
                    + v3
                ).prod()
                - 1.0
            ),
            "shared_v3_maximum_drawdown": (
                _drawdown(
                    v3
                )
            ),
            "btc_return": float(
                (
                    1.0
                    + btc
                ).prod()
                - 1.0
            ),
            "btc_maximum_drawdown": (
                _drawdown(
                    btc
                )
            ),
        })

    return pd.DataFrame(
        rows
    )


def summarize_and_gate(
    folds: pd.DataFrame,
    controls: pd.DataFrame,
    selection_gates: dict,
    primary_cost_bps: float,
    stress_cost_bps: float,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    dict,
]:
    joined = folds.merge(
        controls,
        on=[
            "cost_bps",
            "fold_id",
        ],
        validate="one_to_one",
    )

    joined[
        "excess_vs_shared_v3"
    ] = (
        joined[
            "net_return"
        ]
        - joined[
            "shared_v3_net_return"
        ]
    )

    joined[
        "excess_vs_btc"
    ] = (
        joined[
            "net_return"
        ]
        - joined[
            "btc_return"
        ]
    )

    summaries = []

    for cost, group in joined.groupby(
        "cost_bps",
        sort=True,
    ):
        profits = (
            group[
                "net_return"
            ]
            .clip(
                lower=0.0
            )
        )

        concentration = (
            float(
                profits.max()
                / profits.sum()
            )
            if profits.sum()
            > 0.0
            else 1.0
        )

        summaries.append({
            "cost_bps": float(
                cost
            ),
            "fold_count": int(
                len(
                    group
                )
            ),
            "median_fold_net_return": float(
                group[
                    "net_return"
                ].median()
            ),
            "mean_fold_net_return": float(
                group[
                    "net_return"
                ].mean()
            ),
            "positive_fold_fraction": float(
                (
                    group[
                        "net_return"
                    ]
                    > 0.0
                ).mean()
            ),
            "median_excess_vs_btc": float(
                group[
                    "excess_vs_btc"
                ].median()
            ),
            "median_excess_vs_shared_v3": float(
                group[
                    "excess_vs_shared_v3"
                ].median()
            ),
            "positive_excess_vs_shared_v3_fraction": float(
                (
                    group[
                        "excess_vs_shared_v3"
                    ]
                    > 0.0
                ).mean()
            ),
            "worst_maximum_drawdown": float(
                group[
                    "maximum_drawdown"
                ].min()
            ),
            "single_fold_profit_concentration": (
                concentration
            ),
            "mean_total_turnover": float(
                group[
                    "total_turnover"
                ].mean()
            ),
            "mean_cash_weight": float(
                group[
                    "mean_cash_weight"
                ].mean()
            ),
            "mean_crypto_weight": float(
                group[
                    "mean_crypto_weight"
                ].mean()
            ),
        })

    summary = pd.DataFrame(
        summaries
    )

    primary = summary[
        summary[
            "cost_bps"
        ]
        == float(
            primary_cost_bps
        )
    ]

    stress = summary[
        summary[
            "cost_bps"
        ]
        == float(
            stress_cost_bps
        )
    ]

    if (
        len(
            primary
        )
        != 1
        or len(
            stress
        )
        != 1
    ):
        raise RuntimeError(
            "Primary or stress V15 cost summary is missing"
        )

    p = primary.iloc[
        0
    ]
    s = stress.iloc[
        0
    ]

    gates = {
        "gate_median_fold_net_return_gt_zero": bool(
            p[
                "median_fold_net_return"
            ]
            > float(
                selection_gates[
                    "median_fold_net_return_gt"
                ]
            )
        ),
        "gate_positive_fold_fraction_gte_80pct": bool(
            p[
                "positive_fold_fraction"
            ]
            >= float(
                selection_gates[
                    "positive_fold_fraction_gte"
                ]
            )
        ),
        "gate_median_excess_vs_always_btc_gt_zero": bool(
            p[
                "median_excess_vs_btc"
            ]
            > float(
                selection_gates[
                    "median_excess_vs_always_btc_gt"
                ]
            )
        ),
        "gate_median_excess_vs_shared_v3_gt_zero": bool(
            p[
                "median_excess_vs_shared_v3"
            ]
            > float(
                selection_gates[
                    "median_excess_vs_shared_crypto_v3_gt"
                ]
            )
        ),
        "gate_positive_excess_vs_shared_v3_fraction_gte_80pct": bool(
            p[
                "positive_excess_vs_shared_v3_fraction"
            ]
            >= float(
                selection_gates[
                    "positive_excess_vs_shared_crypto_v3_fraction_gte"
                ]
            )
        ),
        "gate_worst_maximum_drawdown_gte_minus_20pct": bool(
            p[
                "worst_maximum_drawdown"
            ]
            >= float(
                selection_gates[
                    "worst_maximum_drawdown_gte"
                ]
            )
        ),
        "gate_single_fold_profit_concentration_lte_40pct": bool(
            p[
                "single_fold_profit_concentration"
            ]
            <= float(
                selection_gates[
                    "single_fold_profit_concentration_lte"
                ]
            )
        ),
        "gate_survives_50bps_stress": bool(
            s[
                "median_fold_net_return"
            ]
            > 0.0
            and float(
                stress_cost_bps
            )
            == float(
                selection_gates[
                    "survives_stress_cost_bps"
                ]
            )
        ),
    }

    passed = int(
        sum(
            gates.values()
        )
    )

    gate_result = {
        **gates,
        "passed_gate_count": (
            passed
        ),
        "total_gate_count": int(
            len(
                gates
            )
        ),
        "status": (
            "QUALIFIES_FOR_HUMAN_REVIEW"
            if passed
            == len(
                gates
            )
            else "DO_NOT_ADVANCE"
        ),
    }

    return (
        joined,
        summary,
        gate_result,
    )


def _validate_contract_and_permission(
    contract: dict,
    phase2_gate_result: dict,
    phase2_manifest: dict,
) -> dict:
    if (
        contract.get(
            "research_version"
        )
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V15 Phase 1 research version"
        )

    if (
        contract.get(
            "future_holdout_start_utc"
        )
        != HOLDOUT.isoformat()
    ):
        raise RuntimeError(
            "Unexpected V15 holdout boundary"
        )

    if (
        phase2_manifest.get(
            "research_version"
        )
        != RESEARCH_VERSION
    ):
        raise RuntimeError(
            "Unexpected V15 Phase 2 research version"
        )

    if (
        phase2_manifest.get(
            "predictive_gate_status"
        )
        != "ALLOW_POLICY_SIMULATION"
    ):
        raise RuntimeError(
            "V15 Phase 2 did not authorize portfolio simulation"
        )

    if (
        int(
            phase2_gate_result.get(
                "passed_predictive_gate_count",
                -1,
            )
        )
        != 4
        or int(
            phase2_gate_result.get(
                "total_predictive_gate_count",
                -1,
            )
        )
        != 4
        or phase2_gate_result.get(
            "all_predictive_gates_pass"
        )
        is not True
        or phase2_gate_result.get(
            "status"
        )
        != "ALLOW_POLICY_SIMULATION"
    ):
        raise RuntimeError(
            "V15 predictive permission is inconsistent"
        )

    phase2_safety = phase2_manifest.get(
        "safety",
        {},
    )

    for key in (
        "future_holdout_scored",
        "portfolio_simulated",
        "model_family_searched",
        "secondary_model_fit",
        "hyperparameters_tuned",
        "predictive_gate_lowered",
        "threshold_search_performed",
        "model_frozen",
        "paper_state_modified",
        "brokerage_orders",
        "automatic_promotion",
    ):
        if (
            phase2_safety.get(
                key
            )
            is not False
        ):
            raise RuntimeError(
                "V15 Phase 2 safety invariant failed: "
                f"{key}"
            )

    policy = dict(
        contract[
            "frozen_policy_for_later_simulation"
        ]
    )

    expected = {
        "evaluation_clock": (
            "non-overlapping exact 7-day blocks"
        ),
        "asset_weight": (
            ASSET_WEIGHT
        ),
        "selected_asset_count": (
            SELECTED_ASSET_COUNT
        ),
        "cash_weight": (
            CASH_WEIGHT
        ),
        "maximum_gross_crypto_exposure": (
            MAXIMUM_GROSS
        ),
        "primary_round_trip_cost_bps": (
            PRIMARY_COST_BPS
        ),
        "stress_round_trip_cost_bps": (
            STRESS_COST_BPS
        ),
        "maximum_turnover_per_7d_decision": (
            MAXIMUM_TURNOVER
        ),
        "leverage": False,
        "shorting": False,
        "derivatives": False,
    }

    for key, value in expected.items():
        if (
            policy.get(
                key
            )
            != value
        ):
            raise RuntimeError(
                "V15 frozen policy differs from preregistration: "
                f"{key}"
            )

    selection_gates = dict(
        contract[
            "selection_gates"
        ]
    )

    required_gate_keys = {
        "median_fold_net_return_gt",
        "positive_fold_fraction_gte",
        "median_excess_vs_always_btc_gt",
        "median_excess_vs_shared_crypto_v3_gt",
        "positive_excess_vs_shared_crypto_v3_fraction_gte",
        "worst_maximum_drawdown_gte",
        "single_fold_profit_concentration_lte",
        "survives_stress_cost_bps",
    }

    missing = (
        required_gate_keys
        - set(
            selection_gates
        )
    )

    if missing:
        raise RuntimeError(
            "V15 selection gates missing keys: "
            f"{sorted(missing)}"
        )

    return {
        "policy": (
            policy
        ),
        "selection_gates": (
            selection_gates
        ),
    }


def run(
    phase1_contract: Path = PHASE1_CONTRACT,
    prediction_path: Path = PHASE2_PREDICTIONS,
    phase2_gate_result_path: Path = PHASE2_GATE_RESULT,
    phase2_manifest_path: Path = PHASE2_MANIFEST,
    shared_v3_path: Path = SHARED_V3_PREDICTIONS,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_contract = Path(
        phase1_contract
    )
    prediction_path = Path(
        prediction_path
    )
    phase2_gate_result_path = Path(
        phase2_gate_result_path
    )
    phase2_manifest_path = Path(
        phase2_manifest_path
    )
    shared_v3_path = Path(
        shared_v3_path
    )
    output_root = Path(
        output_root
    )

    contract = json.loads(
        phase1_contract.read_text(
            encoding="utf-8"
        )
    )

    phase2_gate_result = json.loads(
        phase2_gate_result_path.read_text(
            encoding="utf-8"
        )
    )

    phase2_manifest = json.loads(
        phase2_manifest_path.read_text(
            encoding="utf-8"
        )
    )

    validated = (
        _validate_contract_and_permission(
            contract,
            phase2_gate_result,
            phase2_manifest,
        )
    )

    policy = validated[
        "policy"
    ]
    selection_gates = validated[
        "selection_gates"
    ]

    (
        blocks,
        assets,
        shared,
    ) = _prepare(
        prediction_path,
        shared_v3_path,
    )

    period_frames = []
    fold_frames = []
    control_frames = []

    for cost in (
        PRIMARY_COST_BPS,
        STRESS_COST_BPS,
    ):
        periods, folds = (
            simulate_candidate(
                blocks,
                assets,
                policy,
                cost,
            )
        )

        controls = simulate_controls(
            blocks,
            assets,
            shared,
            cost,
        )

        period_frames.append(
            periods
        )
        fold_frames.append(
            folds
        )
        control_frames.append(
            controls
        )

        print(
            f"[SUCCESS] frozen V15 policy "
            f"cost={cost:g}bps "
            f"folds={len(folds)} "
            f"blocks={len(periods)}"
        )

    periods = pd.concat(
        period_frames,
        ignore_index=True,
    )
    folds = pd.concat(
        fold_frames,
        ignore_index=True,
    )
    controls = pd.concat(
        control_frames,
        ignore_index=True,
    )

    (
        matched,
        summary,
        gate_result,
    ) = summarize_and_gate(
        folds,
        controls,
        selection_gates,
        PRIMARY_COST_BPS,
        STRESS_COST_BPS,
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    periods_path = (
        output_root
        / "portfolio_periods.parquet"
    )
    folds_path = (
        output_root
        / "fold_metrics.csv"
    )
    controls_path = (
        output_root
        / "matched_controls.csv"
    )
    matched_path = (
        output_root
        / "matched_fold_metrics.csv"
    )
    summary_path = (
        output_root
        / "policy_summary.csv"
    )
    gates_path = (
        output_root
        / "gate_results.json"
    )

    periods.to_parquet(
        periods_path,
        index=False,
    )
    folds.to_csv(
        folds_path,
        index=False,
    )
    controls.to_csv(
        controls_path,
        index=False,
    )
    matched.to_csv(
        matched_path,
        index=False,
    )
    summary.to_csv(
        summary_path,
        index=False,
    )
    gates_path.write_text(
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
        "phase": 3,
        "stage": (
            "single_preregistered_nonoverlapping_7d_portfolio_policy"
        ),
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "future_holdout_start_utc": (
            HOLDOUT.isoformat()
        ),
        "predictive_permission": (
            "ALLOW_POLICY_SIMULATION"
        ),
        "matched_decision_blocks": int(
            blocks[
                "timestamp_utc"
            ].nunique()
        ),
        "fold_count": int(
            blocks[
                "fold_id"
            ].nunique()
        ),
        "candidate_count": 1,
        "primary_cost_bps": (
            PRIMARY_COST_BPS
        ),
        "stress_cost_bps": (
            STRESS_COST_BPS
        ),
        "frozen_policy": (
            policy
        ),
        "matched_benchmarks": [
            "always_btc_on_exact_v15_7d_blocks",
            "shared_crypto_v3_hgb_labels_confirm2_on_matched_clock",
        ],
        "shared_v3_alt_control": (
            "equal-weight contemporaneous eligible non-BTC, non-XRP assets"
        ),
        "gate_status": (
            gate_result[
                "status"
            ]
        ),
        "passed_gate_count": (
            gate_result[
                "passed_gate_count"
            ]
        ),
        "total_gate_count": (
            gate_result[
                "total_gate_count"
            ]
        ),
        "outputs": {
            "portfolio_periods": str(
                periods_path
            ),
            "fold_metrics": str(
                folds_path
            ),
            "matched_controls": str(
                controls_path
            ),
            "matched_fold_metrics": str(
                matched_path
            ),
            "policy_summary": str(
                summary_path
            ),
            "gate_results": str(
                gates_path
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "safety": {
            "policy_changed_after_predictive_results": False,
            "portfolio_gate_changed_after_results": False,
            "threshold_search_performed": False,
            "candidate_search_performed": False,
            "future_holdout_scored": False,
            "model_refit": False,
            "model_frozen_automatically": False,
            "shared_crypto_v3_modified": False,
            "shared_crypto_v14_modified": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "human_review_required": True,
        },
        "next_step": (
            "If and only if all eight preregistered portfolio gates pass, "
            "perform a separate immutable adjudication and human review before "
            "any candidate freeze or future-holdout evaluation. If any gate "
            "fails, preserve V15 as failed portfolio evidence and do not "
            "advance it."
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
        "--phase1-contract",
        type=Path,
        default=PHASE1_CONTRACT,
    )

    parser.add_argument(
        "--predictions",
        type=Path,
        default=PHASE2_PREDICTIONS,
    )

    parser.add_argument(
        "--phase2-gate-result",
        type=Path,
        default=PHASE2_GATE_RESULT,
    )

    parser.add_argument(
        "--phase2-manifest",
        type=Path,
        default=PHASE2_MANIFEST,
    )

    parser.add_argument(
        "--shared-v3-predictions",
        type=Path,
        default=SHARED_V3_PREDICTIONS,
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
                args.phase1_contract,
                args.predictions,
                args.phase2_gate_result,
                args.phase2_manifest,
                args.shared_v3_predictions,
                args.output_root,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
