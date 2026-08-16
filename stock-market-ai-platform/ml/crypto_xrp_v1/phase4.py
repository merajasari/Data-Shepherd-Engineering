"""Crypto XRP V1 Phase 4: exploratory XRP / BTC / CASH economic policy study.

IMPORTANT RESEARCH STATUS
-------------------------
This phase is exploratory development evidence.

The policy family and thresholds were defined after inspecting XRP V1 Phase 2
and Phase 3 OOS diagnostics. Therefore Phase 4 results MUST NOT be described as
untouched validation.

Untouched future evaluation remains reserved for observations beginning
2026-09-01 00:00 UTC.

Inputs
------
- Phase 2 Ridge OOS predictions
- Phase 1 post-discontinuity XRP primary panel

Decision cadence
----------------
One decision every 4 hours using exact UTC decision timestamps:
00:00, 04:00, 08:00, 12:00, 16:00, 20:00.

This prevents overlapping 4-hour target returns.

Frozen exploratory policy family
--------------------------------
policy_zero
    XRP  if score > 0
    CASH if score < 0
    BTC  if score == 0

policy_05
    XRP  if score >= +0.0005
    CASH if score <= -0.0005
    BTC  otherwise

policy_10
    XRP  if score >= +0.0010
    CASH if score <= -0.0010
    BTC  otherwise

policy_20
    XRP  if score >= +0.0020
    CASH if score <= -0.0020
    BTC  otherwise

Reference policies
------------------
- always_xrp
- always_btc
- always_cash

Costs
-----
Switching-cost scenarios:
0, 5, 10, and 20 basis points per sleeve/state change.

A cost is charged only when the selected state changes from the immediately
previous valid 4-hour decision inside the same fold and continuous 4-hour
decision sequence.

No cost is carried across:
- fold boundaries
- missing-data gaps
- discontinuities

This phase does NOT:
- fit or retrain a model
- optimize thresholds
- promote a policy
- use timestamps on/after 2026-09-01 UTC
- use leverage
- short XRP or BTC
- use derivatives
- place brokerage orders
- modify frozen Crypto 15m V2
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_xrp_v1 import RESEARCH_VERSION


PHASE2_PREDICTIONS = Path(
    "data/model/crypto_xrp_v1/phase2/predictions.parquet"
)

PHASE1_PRIMARY = Path(
    "data/model/crypto_xrp_v1/phase1/xrp_primary.parquet"
)

OUTPUT_ROOT = Path(
    "data/model/crypto_xrp_v1/phase4"
)

DECISIONS_PATH = OUTPUT_ROOT / "policy_decisions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "policy_summary.csv"
STATE_COUNTS_PATH = OUTPUT_ROOT / "state_counts.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

FUTURE_HOLDOUT_START = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

MODEL_ID = "ridge"

DECISION_HOURS_UTC = {
    0,
    4,
    8,
    12,
    16,
    20,
}

EXPECTED_STEP = pd.Timedelta(hours=4)

COST_BPS_SCENARIOS = (
    0,
    5,
    10,
    20,
)


POLICIES = {
    "policy_zero": {
        "positive_threshold": 0.0,
        "negative_threshold": 0.0,
        "strict_zero": True,
    },
    "policy_05": {
        "positive_threshold": 0.0005,
        "negative_threshold": -0.0005,
        "strict_zero": False,
    },
    "policy_10": {
        "positive_threshold": 0.0010,
        "negative_threshold": -0.0010,
        "strict_zero": False,
    },
    "policy_20": {
        "positive_threshold": 0.0020,
        "negative_threshold": -0.0020,
        "strict_zero": False,
    },
}


def load_inputs(
    predictions_path: Path,
    primary_path: Path,
) -> pd.DataFrame:
    if not predictions_path.exists():
        raise FileNotFoundError(
            f"Missing Phase 2 predictions: {predictions_path}"
        )

    if not primary_path.exists():
        raise FileNotFoundError(
            f"Missing Phase 1 primary panel: {primary_path}"
        )

    predictions = pd.read_parquet(
        predictions_path
    ).copy()

    primary = pd.read_parquet(
        primary_path
    ).copy()

    pred_required = {
        "timestamp_utc",
        "product_id",
        "segment_id",
        "actual",
        "predicted_score",
        "model_id",
        "fold_id",
    }

    panel_required = {
        "timestamp_utc",
        "product_id",
        "segment_id",
        "forward_return_4h",
        "btc_forward_return_4h",
        "btc_relative_forward_return_4h",
    }

    missing_pred = (
        pred_required
        - set(predictions.columns)
    )

    missing_panel = (
        panel_required
        - set(primary.columns)
    )

    if missing_pred:
        raise RuntimeError(
            "Predictions missing columns: "
            f"{sorted(missing_pred)}"
        )

    if missing_panel:
        raise RuntimeError(
            "Primary panel missing columns: "
            f"{sorted(missing_panel)}"
        )

    predictions[
        "timestamp_utc"
    ] = pd.to_datetime(
        predictions["timestamp_utc"],
        utc=True,
    )

    primary[
        "timestamp_utc"
    ] = pd.to_datetime(
        primary["timestamp_utc"],
        utc=True,
    )

    predictions = predictions[
        predictions["model_id"] == MODEL_ID
    ].copy()

    if predictions.empty:
        raise RuntimeError(
            "No Ridge Phase 2 predictions found"
        )

    if (
        predictions["timestamp_utc"]
        >= FUTURE_HOLDOUT_START
    ).any():
        raise RuntimeError(
            "Predictions contain future-holdout rows"
        )

    if (
        primary["timestamp_utc"]
        >= FUTURE_HOLDOUT_START
    ).any():
        raise RuntimeError(
            "Primary panel contains future-holdout rows"
        )

    if set(
        predictions["product_id"]
        .dropna()
        .unique()
    ) != {"XRP-USD"}:
        raise RuntimeError(
            "Predictions contain non-XRP products"
        )

    if set(
        primary["product_id"]
        .dropna()
        .unique()
    ) != {"XRP-USD"}:
        raise RuntimeError(
            "Primary panel contains non-XRP products"
        )

    keep_panel = primary[
        [
            "timestamp_utc",
            "product_id",
            "segment_id",
            "forward_return_4h",
            "btc_forward_return_4h",
            "btc_relative_forward_return_4h",
        ]
    ].copy()

    merged = predictions.merge(
        keep_panel,
        on=[
            "timestamp_utc",
            "product_id",
            "segment_id",
        ],
        how="inner",
        validate="one_to_one",
    )

    if len(merged) != len(predictions):
        raise RuntimeError(
            "Not all Ridge predictions matched "
            "Phase 1 primary returns"
        )

    # Internal consistency check.
    error = (
        merged["actual"]
        - merged[
            "btc_relative_forward_return_4h"
        ]
    ).abs()

    if float(error.max()) > 1e-12:
        raise RuntimeError(
            "Phase 2 actual target does not match "
            "Phase 1 BTC-relative 4h return"
        )

    # Non-overlapping 4-hour evaluation grid.
    ts = merged["timestamp_utc"]

    merged = merged[
        ts.dt.minute.eq(0)
        & ts.dt.second.eq(0)
        & ts.dt.hour.isin(
            DECISION_HOURS_UTC
        )
    ].copy()

    merged = (
        merged.sort_values(
            [
                "fold_id",
                "timestamp_utc",
            ]
        )
        .reset_index(drop=True)
    )

    if merged.empty:
        raise RuntimeError(
            "No valid 4-hour XRP decisions"
        )

    return merged


def policy_state(
    score: float,
    policy_id: str,
) -> str:
    if policy_id not in POLICIES:
        raise KeyError(
            f"Unknown policy: {policy_id}"
        )

    config = POLICIES[
        policy_id
    ]

    if config["strict_zero"]:
        if score > 0:
            return "XRP"

        if score < 0:
            return "CASH"

        return "BTC"

    if (
        score
        >= config[
            "positive_threshold"
        ]
    ):
        return "XRP"

    if (
        score
        <= config[
            "negative_threshold"
        ]
    ):
        return "CASH"

    return "BTC"


def state_return(
    row: pd.Series,
    state: str,
) -> float:
    if state == "XRP":
        return float(
            row[
                "forward_return_4h"
            ]
        )

    if state == "BTC":
        return float(
            row[
                "btc_forward_return_4h"
            ]
        )

    if state == "CASH":
        return 0.0

    raise RuntimeError(
        f"Unknown state: {state}"
    )


def build_policy_rows(
    base: pd.DataFrame,
) -> pd.DataFrame:
    outputs = []

    policy_ids = list(
        POLICIES
    ) + [
        "always_xrp",
        "always_btc",
        "always_cash",
    ]

    for policy_id in policy_ids:
        work = base.copy()

        if policy_id == "always_xrp":
            work["state"] = "XRP"

        elif policy_id == "always_btc":
            work["state"] = "BTC"

        elif policy_id == "always_cash":
            work["state"] = "CASH"

        else:
            work[
                "state"
            ] = work[
                "predicted_score"
            ].apply(
                lambda score: policy_state(
                    float(score),
                    policy_id,
                )
            )

        work[
            "gross_return"
        ] = work.apply(
            lambda row: state_return(
                row,
                row["state"],
            ),
            axis=1,
        )

        work[
            "previous_timestamp"
        ] = work.groupby(
            "fold_id",
            sort=False,
        )[
            "timestamp_utc"
        ].shift(1)

        work[
            "previous_segment_id"
        ] = work.groupby(
            "fold_id",
            sort=False,
        )[
            "segment_id"
        ].shift(1)

        work[
            "previous_state"
        ] = work.groupby(
            "fold_id",
            sort=False,
        )[
            "state"
        ].shift(1)

        work[
            "continuous_previous"
        ] = (
            (
                work[
                    "timestamp_utc"
                ]
                - work[
                    "previous_timestamp"
                ]
            )
            == EXPECTED_STEP
        ) & (
            work["segment_id"]
            == work[
                "previous_segment_id"
            ]
        )

        work[
            "state_switch"
        ] = (
            work[
                "continuous_previous"
            ]
            & work[
                "previous_state"
            ].notna()
            & (
                work["state"]
                != work[
                    "previous_state"
                ]
            )
        )

        work["policy_id"] = (
            policy_id
        )

        outputs.append(
            work
        )

    return pd.concat(
        outputs,
        ignore_index=True,
    )


def maximum_drawdown(
    returns: pd.Series,
) -> float:
    if len(returns) == 0:
        return np.nan

    equity = (
        1.0
        + returns.astype(float)
    ).cumprod()

    peak = equity.cummax()

    drawdown = (
        equity / peak
        - 1.0
    )

    return float(
        drawdown.min()
    )


def summarize_returns(
    frame: pd.DataFrame,
    cost_bps: int,
) -> dict:
    cost_rate = (
        cost_bps
        / 10_000.0
    )

    net = (
        frame[
            "gross_return"
        ].astype(float)
        - frame[
            "state_switch"
        ].astype(float)
        * cost_rate
    )

    gross = frame[
        "gross_return"
    ].astype(float)

    ending_equity = float(
        (
            1.0 + net
        ).prod()
    )

    gross_equity = float(
        (
            1.0 + gross
        ).prod()
    )

    return {
        "decision_count": int(
            len(frame)
        ),
        "switch_count": int(
            frame[
                "state_switch"
            ].sum()
        ),
        "switch_rate": float(
            frame[
                "state_switch"
            ].mean()
        ),
        "mean_gross_return": float(
            gross.mean()
        ),
        "mean_net_return": float(
            net.mean()
        ),
        "gross_ending_equity": (
            gross_equity
        ),
        "net_ending_equity": (
            ending_equity
        ),
        "max_drawdown": (
            maximum_drawdown(
                net
            )
        ),
        "positive_net_fraction": float(
            (net > 0).mean()
        ),
    }


def evaluate(
    decisions: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    fold_rows = []
    summary_rows = []
    state_rows = []

    for (
        policy_id,
        policy_frame,
    ) in decisions.groupby(
        "policy_id",
        sort=True,
    ):
        for state, group in (
            policy_frame.groupby(
                "state",
                sort=True,
            )
        ):
            state_rows.append(
                {
                    "policy_id": (
                        policy_id
                    ),
                    "state": state,
                    "decisions": int(
                        len(group)
                    ),
                    "fraction": float(
                        len(group)
                        / len(
                            policy_frame
                        )
                    ),
                    "mean_gross_return": float(
                        group[
                            "gross_return"
                        ].mean()
                    ),
                }
            )

        for (
            fold_id,
            fold,
        ) in policy_frame.groupby(
            "fold_id",
            sort=True,
        ):
            for cost_bps in (
                COST_BPS_SCENARIOS
            ):
                fold_rows.append(
                    {
                        "policy_id": (
                            policy_id
                        ),
                        "fold_id": (
                            fold_id
                        ),
                        "cost_bps": (
                            cost_bps
                        ),
                        **summarize_returns(
                            fold,
                            cost_bps,
                        ),
                    }
                )

        for cost_bps in (
            COST_BPS_SCENARIOS
        ):
            # Aggregate metrics are calculated
            # fold-by-fold to prevent carrying
            # state across fold boundaries.
            fold_parts = []

            for _, fold in (
                policy_frame.groupby(
                    "fold_id",
                    sort=True,
                )
            ):
                fold = (
                    fold.sort_values(
                        "timestamp_utc"
                    )
                    .copy()
                )

                cost_rate = (
                    cost_bps
                    / 10_000.0
                )

                fold[
                    "net_return"
                ] = (
                    fold[
                        "gross_return"
                    ]
                    - fold[
                        "state_switch"
                    ].astype(float)
                    * cost_rate
                )

                fold_parts.append(
                    fold
                )

            combined = pd.concat(
                fold_parts,
                ignore_index=True,
            )

            net = combined[
                "net_return"
            ].astype(float)

            gross = combined[
                "gross_return"
            ].astype(float)

            # Full compounded result is still
            # descriptive because Phase 4 is
            # exploratory.
            summary_rows.append(
                {
                    "policy_id": (
                        policy_id
                    ),
                    "cost_bps": (
                        cost_bps
                    ),
                    "fold_count": int(
                        combined[
                            "fold_id"
                        ].nunique()
                    ),
                    "decision_count": int(
                        len(combined)
                    ),
                    "switch_count": int(
                        combined[
                            "state_switch"
                        ].sum()
                    ),
                    "switch_rate": float(
                        combined[
                            "state_switch"
                        ].mean()
                    ),
                    "mean_gross_return": float(
                        gross.mean()
                    ),
                    "mean_net_return": float(
                        net.mean()
                    ),
                    "gross_ending_equity": float(
                        (
                            1.0 + gross
                        ).prod()
                    ),
                    "net_ending_equity": float(
                        (
                            1.0 + net
                        ).prod()
                    ),
                    "max_drawdown": (
                        maximum_drawdown(
                            net
                        )
                    ),
                    "positive_net_fraction": float(
                        (net > 0).mean()
                    ),
                }
            )

    return (
        pd.DataFrame(
            summary_rows
        ),
        pd.DataFrame(
            fold_rows
        ),
        pd.DataFrame(
            state_rows
        ),
    )


def run(
    predictions_path: Path = PHASE2_PREDICTIONS,
    primary_path: Path = PHASE1_PRIMARY,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    output_root = Path(
        output_root
    )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    base = load_inputs(
        predictions_path,
        primary_path,
    )

    decisions = build_policy_rows(
        base
    )

    (
        summary,
        fold_metrics,
        state_counts,
    ) = evaluate(
        decisions
    )

    decisions.to_parquet(
        output_root
        / "policy_decisions.parquet",
        index=False,
    )

    summary.to_csv(
        output_root
        / "policy_summary.csv",
        index=False,
    )

    fold_metrics.to_csv(
        output_root
        / "fold_metrics.csv",
        index=False,
    )

    state_counts.to_csv(
        output_root
        / "state_counts.csv",
        index=False,
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 4,
        "stage": (
            "exploratory_three_state_economic_policy"
        ),
        "generated_at_utc": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "research_status": (
            "EXPLORATORY DEVELOPMENT EVIDENCE"
        ),
        "research_status_reason": (
            "Phase 4 policies and thresholds "
            "were defined after inspection of "
            "Phase 2 and Phase 3 OOS results. "
            "Therefore Phase 4 is not untouched "
            "validation."
        ),
        "source_predictions": str(
            predictions_path
        ),
        "source_primary_panel": str(
            primary_path
        ),
        "model_id": MODEL_ID,
        "decision_cadence": (
            "4 hours"
        ),
        "decision_hours_utc": sorted(
            DECISION_HOURS_UTC
        ),
        "non_overlapping_returns": True,
        "economic_horizon": (
            "4 hours"
        ),
        "state_space": [
            "XRP",
            "BTC",
            "CASH",
        ],
        "policy_family": {
            policy_id: {
                key: value
                for key, value
                in config.items()
            }
            for (
                policy_id,
                config,
            ) in POLICIES.items()
        },
        "reference_policies": [
            "always_xrp",
            "always_btc",
            "always_cash",
        ],
        "switch_cost_bps": list(
            COST_BPS_SCENARIOS
        ),
        "switch_cost_policy": (
            "One sleeve-level cost is deducted "
            "when state changes between adjacent "
            "valid four-hour decisions inside "
            "the same fold and contiguous "
            "segment. State is reset across "
            "fold boundaries and data gaps."
        ),
        "future_holdout_start_utc": (
            FUTURE_HOLDOUT_START
            .isoformat()
        ),
        "future_holdout_policy": (
            "No timestamps on or after "
            "2026-09-01 UTC are used."
        ),
        "threshold_selection_policy": (
            "No thresholds are optimized in "
            "Phase 4. The frozen exploratory "
            "family is policy_zero, policy_05, "
            "policy_10, and policy_20."
        ),
        "interpretation_policy": (
            "Phase 4 may identify hypotheses "
            "for later research but cannot "
            "promote a policy. Genuine forward "
            "or newly frozen validation is "
            "required before promotion."
        ),
        "shared_v2_policy": (
            "Frozen Crypto 15m V2 Phase 5 "
            "remains unchanged and XRP remains "
            "outside the shared model."
        ),
        "brokerage_orders": False,
        "leverage": False,
        "shorting": False,
        "derivatives": False,
        "outputs": {
            "policy_decisions": str(
                output_root
                / "policy_decisions.parquet"
            ),
            "policy_summary": str(
                output_root
                / "policy_summary.csv"
            ),
            "fold_metrics": str(
                output_root
                / "fold_metrics.csv"
            ),
            "state_counts": str(
                output_root
                / "state_counts.csv"
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "next_step": (
            "Inspect policy economics across "
            "all cost assumptions and folds. "
            "Do not choose a promoted policy "
            "from aggregate ending equity alone; "
            "require fold stability and preserve "
            "the untouched Sep. 1 future boundary."
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


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__
    )

    ap.add_argument(
        "--predictions",
        type=Path,
        default=PHASE2_PREDICTIONS,
    )

    ap.add_argument(
        "--primary",
        type=Path,
        default=PHASE1_PRIMARY,
    )

    ap.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )

    args = ap.parse_args(
        argv
    )

    manifest = run(
        args.predictions,
        args.primary,
        args.output_root,
    )

    summary = pd.read_csv(
        manifest[
            "outputs"
        ][
            "policy_summary"
        ]
    )

    print()
    print(
        "CRYPTO XRP V1 PHASE 4"
    )

    print(
        "=" * 80
    )

    print(
        "RESEARCH STATUS: "
        "EXPLORATORY DEVELOPMENT EVIDENCE"
    )

    print()

    display = summary[
        [
            "policy_id",
            "cost_bps",
            "decision_count",
            "switch_count",
            "mean_net_return",
            "net_ending_equity",
            "max_drawdown",
        ]
    ].copy()

    print(
        display.to_string(
            index=False
        )
    )

    print()

    print(
        "No model fitting occurred."
    )

    print(
        "No threshold was optimized."
    )

    print(
        "No policy was promoted."
    )

    print(
        "No real orders were placed."
    )

    print(
        "Future holdout remains untouched "
        "from 2026-09-01 UTC."
    )


if __name__ == "__main__":
    main()
