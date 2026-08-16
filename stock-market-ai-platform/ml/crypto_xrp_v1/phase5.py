"""Crypto XRP V1 Phase 5: exploratory turnover-controlled policy research.

IMPORTANT RESEARCH STATUS
-------------------------
This phase is exploratory development evidence.

It is designed after inspection of Phase 4 economic results, specifically to
test whether persistence, hysteresis, and minimum holding periods can reduce
turnover enough to preserve the XRP Ridge signal after realistic switching
costs.

Untouched future evaluation remains reserved for timestamps beginning
2026-09-01 00:00 UTC.

Inputs
------
Phase 4 uses non-overlapping four-hour Ridge decisions. Phase 5 consumes the
same underlying Ridge OOS predictions and Phase 1 return panel directly.

No model fitting occurs.

Decision cadence
----------------
One decision every four hours:
00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.

State space
-----------
XRP
BTC
CASH

Policy concept
--------------
Hysteresis uses different thresholds for entering and exiting risk states.

Example:
- enter XRP only when score >= +entry_threshold
- remain XRP until score <= +exit_threshold
- enter CASH only when score <= -entry_threshold
- remain CASH until score >= -exit_threshold
- otherwise use BTC

Minimum holding periods further prevent rapid state flipping.

Pre-registered exploratory family
---------------------------------
hyst_10_05_hold8
    entry = 0.0010
    exit = 0.0005
    minimum hold = 8 hours

hyst_10_05_hold12
    entry = 0.0010
    exit = 0.0005
    minimum hold = 12 hours

hyst_10_05_hold24
    entry = 0.0010
    exit = 0.0005
    minimum hold = 24 hours

hyst_20_10_hold8
    entry = 0.0020
    exit = 0.0010
    minimum hold = 8 hours

hyst_20_10_hold12
    entry = 0.0020
    exit = 0.0010
    minimum hold = 12 hours

hyst_20_10_hold24
    entry = 0.0020
    exit = 0.0010
    minimum hold = 24 hours

Reference policies
------------------
always_xrp
always_btc
always_cash

Costs
-----
0, 5, 10, and 20 bps per state change.

State is reset at every:
- fold boundary
- discontinuity
- missing four-hour decision interval

This phase does NOT:
- refit Ridge
- optimize thresholds
- promote a policy
- inspect Sep. 1+ data
- place orders
- use leverage
- short crypto
- use derivatives
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
    "data/model/crypto_xrp_v1/phase5"
)

DECISIONS_PATH = OUTPUT_ROOT / "policy_decisions.parquet"
SUMMARY_PATH = OUTPUT_ROOT / "policy_summary.csv"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
STATE_COUNTS_PATH = OUTPUT_ROOT / "state_counts.csv"
TRANSITIONS_PATH = OUTPUT_ROOT / "transition_counts.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


MODEL_ID = "ridge"

FUTURE_HOLDOUT_START = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

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
    "hyst_10_05_hold8": {
        "entry_threshold": 0.0010,
        "exit_threshold": 0.0005,
        "minimum_hold_hours": 8,
    },
    "hyst_10_05_hold12": {
        "entry_threshold": 0.0010,
        "exit_threshold": 0.0005,
        "minimum_hold_hours": 12,
    },
    "hyst_10_05_hold24": {
        "entry_threshold": 0.0010,
        "exit_threshold": 0.0005,
        "minimum_hold_hours": 24,
    },
    "hyst_20_10_hold8": {
        "entry_threshold": 0.0020,
        "exit_threshold": 0.0010,
        "minimum_hold_hours": 8,
    },
    "hyst_20_10_hold12": {
        "entry_threshold": 0.0020,
        "exit_threshold": 0.0010,
        "minimum_hold_hours": 12,
    },
    "hyst_20_10_hold24": {
        "entry_threshold": 0.0020,
        "exit_threshold": 0.0010,
        "minimum_hold_hours": 24,
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
            f"Missing Phase 1 XRP primary panel: {primary_path}"
        )

    predictions = pd.read_parquet(
        predictions_path
    ).copy()

    primary = pd.read_parquet(
        primary_path
    ).copy()

    required_predictions = {
        "timestamp_utc",
        "product_id",
        "segment_id",
        "actual",
        "predicted_score",
        "model_id",
        "fold_id",
    }

    required_primary = {
        "timestamp_utc",
        "product_id",
        "segment_id",
        "forward_return_4h",
        "btc_forward_return_4h",
        "btc_relative_forward_return_4h",
    }

    missing_predictions = (
        required_predictions
        - set(predictions.columns)
    )

    missing_primary = (
        required_primary
        - set(primary.columns)
    )

    if missing_predictions:
        raise RuntimeError(
            "Predictions missing required columns: "
            f"{sorted(missing_predictions)}"
        )

    if missing_primary:
        raise RuntimeError(
            "Primary panel missing required columns: "
            f"{sorted(missing_primary)}"
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
            "No Ridge predictions found"
        )

    if (
        predictions["timestamp_utc"]
        >= FUTURE_HOLDOUT_START
    ).any():
        raise RuntimeError(
            "Phase 5 predictions contain future-holdout rows"
        )

    if (
        primary["timestamp_utc"]
        >= FUTURE_HOLDOUT_START
    ).any():
        raise RuntimeError(
            "Phase 5 primary panel contains future-holdout rows"
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

    panel = primary[
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
        panel,
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
            "Some Ridge predictions did not match "
            "Phase 1 XRP returns"
        )

    consistency_error = (
        merged["actual"]
        - merged[
            "btc_relative_forward_return_4h"
        ]
    ).abs()

    if float(
        consistency_error.max()
    ) > 1e-12:
        raise RuntimeError(
            "Phase 2 target does not match "
            "Phase 1 BTC-relative 4h return"
        )

    ts = merged[
        "timestamp_utc"
    ]

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
            "No valid four-hour decisions"
        )

    return merged


def return_for_state(
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


def next_state(
    current_state: str,
    score: float,
    entry_threshold: float,
    exit_threshold: float,
) -> str:
    """Hysteresis state machine without minimum-hold restriction."""

    if current_state == "XRP":
        # Strong negative signal can directly move to CASH.
        if score <= -entry_threshold:
            return "CASH"

        # Stay XRP while score remains above exit threshold.
        if score > exit_threshold:
            return "XRP"

        return "BTC"

    if current_state == "CASH":
        # Strong positive signal can directly move to XRP.
        if score >= entry_threshold:
            return "XRP"

        # Stay CASH while sufficiently negative.
        if score < -exit_threshold:
            return "CASH"

        return "BTC"

    # Current state BTC.
    if score >= entry_threshold:
        return "XRP"

    if score <= -entry_threshold:
        return "CASH"

    return "BTC"


def run_hysteresis_policy(
    frame: pd.DataFrame,
    policy_id: str,
) -> pd.DataFrame:
    if policy_id not in POLICIES:
        raise KeyError(
            f"Unknown policy: {policy_id}"
        )

    config = POLICIES[
        policy_id
    ]

    entry_threshold = float(
        config[
            "entry_threshold"
        ]
    )

    exit_threshold = float(
        config[
            "exit_threshold"
        ]
    )

    minimum_hold = pd.Timedelta(
        hours=int(
            config[
                "minimum_hold_hours"
            ]
        )
    )

    output_parts = []

    for fold_id, fold in frame.groupby(
        "fold_id",
        sort=True,
    ):
        fold = (
            fold.sort_values(
                "timestamp_utc"
            )
            .copy()
        )

        states = []
        switches = []
        reset_flags = []
        hold_elapsed_hours = []

        current_state = "BTC"
        current_state_since = None
        previous_timestamp = None
        previous_segment_id = None

        for _, row in fold.iterrows():
            timestamp = row[
                "timestamp_utc"
            ]

            segment_id = row[
                "segment_id"
            ]

            score = float(
                row[
                    "predicted_score"
                ]
            )

            reset = False

            if previous_timestamp is None:
                reset = True

            elif (
                timestamp
                - previous_timestamp
            ) != EXPECTED_STEP:
                reset = True

            elif (
                segment_id
                != previous_segment_id
            ):
                reset = True

            if reset:
                # Neutral reset ensures no state carries across gaps.
                current_state = "BTC"
                current_state_since = timestamp
                switched = False

            else:
                elapsed = (
                    timestamp
                    - current_state_since
                )

                proposed = next_state(
                    current_state,
                    score,
                    entry_threshold,
                    exit_threshold,
                )

                if (
                    proposed
                    != current_state
                    and elapsed
                    < minimum_hold
                ):
                    proposed = current_state

                switched = (
                    proposed
                    != current_state
                )

                if switched:
                    current_state = proposed
                    current_state_since = timestamp

            elapsed_hours = float(
                (
                    timestamp
                    - current_state_since
                ).total_seconds()
                / 3600.0
            )

            states.append(
                current_state
            )

            switches.append(
                switched
            )

            reset_flags.append(
                reset
            )

            hold_elapsed_hours.append(
                elapsed_hours
            )

            previous_timestamp = timestamp
            previous_segment_id = segment_id

        fold["state"] = states
        fold["state_switch"] = switches
        fold["state_reset"] = reset_flags
        fold[
            "hours_since_state_change"
        ] = hold_elapsed_hours

        fold[
            "gross_return"
        ] = fold.apply(
            lambda row: return_for_state(
                row,
                row["state"],
            ),
            axis=1,
        )

        fold[
            "policy_id"
        ] = policy_id

        output_parts.append(
            fold
        )

    return pd.concat(
        output_parts,
        ignore_index=True,
    )


def run_reference_policy(
    frame: pd.DataFrame,
    policy_id: str,
    state: str,
) -> pd.DataFrame:
    work = frame.copy()

    work[
        "state"
    ] = state

    work[
        "state_switch"
    ] = False

    work[
        "state_reset"
    ] = False

    work[
        "hours_since_state_change"
    ] = np.nan

    work[
        "gross_return"
    ] = work.apply(
        lambda row: return_for_state(
            row,
            state,
        ),
        axis=1,
    )

    work[
        "policy_id"
    ] = policy_id

    return work


def build_decisions(
    base: pd.DataFrame,
) -> pd.DataFrame:
    outputs = []

    for policy_id in POLICIES:
        outputs.append(
            run_hysteresis_policy(
                base,
                policy_id,
            )
        )

    outputs.append(
        run_reference_policy(
            base,
            "always_xrp",
            "XRP",
        )
    )

    outputs.append(
        run_reference_policy(
            base,
            "always_btc",
            "BTC",
        )
    )

    outputs.append(
        run_reference_policy(
            base,
            "always_cash",
            "CASH",
        )
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
        equity
        / peak
        - 1.0
    )

    return float(
        drawdown.min()
    )


def summarize(
    frame: pd.DataFrame,
    cost_bps: int,
) -> dict:
    cost_rate = (
        cost_bps
        / 10_000.0
    )

    gross = frame[
        "gross_return"
    ].astype(float)

    net = (
        gross
        - frame[
            "state_switch"
        ].astype(float)
        * cost_rate
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
        "reset_count": int(
            frame[
                "state_reset"
            ].sum()
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
            (
                net > 0
            ).mean()
        ),
    }


def evaluate(
    decisions: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    summary_rows = []
    fold_rows = []
    state_rows = []
    transition_rows = []

    for policy_id, policy in (
        decisions.groupby(
            "policy_id",
            sort=True,
        )
    ):
        for state, group in (
            policy.groupby(
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
                        / len(policy)
                    ),
                    "mean_gross_return": float(
                        group[
                            "gross_return"
                        ].mean()
                    ),
                }
            )

        # Transition counts.
        for fold_id, fold in (
            policy.groupby(
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

            previous_state = (
                fold["state"].shift(1)
            )

            transitions = pd.DataFrame(
                {
                    "from_state": (
                        previous_state
                    ),
                    "to_state": (
                        fold["state"]
                    ),
                    "switched": (
                        fold[
                            "state_switch"
                        ]
                    ),
                }
            )

            transitions = transitions[
                transitions["switched"]
            ]

            for (
                from_state,
                to_state,
            ), group in transitions.groupby(
                [
                    "from_state",
                    "to_state",
                ],
                dropna=False,
            ):
                transition_rows.append(
                    {
                        "policy_id": (
                            policy_id
                        ),
                        "fold_id": fold_id,
                        "from_state": (
                            from_state
                        ),
                        "to_state": (
                            to_state
                        ),
                        "count": int(
                            len(group)
                        ),
                    }
                )

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
                        **summarize(
                            fold,
                            cost_bps,
                        ),
                    }
                )

        for cost_bps in (
            COST_BPS_SCENARIOS
        ):
            parts = []

            for _, fold in (
                policy.groupby(
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

                parts.append(
                    fold
                )

            combined = pd.concat(
                parts,
                ignore_index=True,
            )

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
                    **summarize(
                        combined,
                        cost_bps,
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
        pd.DataFrame(
            transition_rows
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

    decisions = build_decisions(
        base
    )

    (
        summary,
        fold_metrics,
        state_counts,
        transition_counts,
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

    transition_counts.to_csv(
        output_root
        / "transition_counts.csv",
        index=False,
    )

    manifest = {
        "research_version": (
            RESEARCH_VERSION
        ),
        "phase": 5,
        "stage": (
            "exploratory_turnover_controlled_policy_research"
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
            "Phase 5 was designed after "
            "inspection of Phase 4 economic "
            "results and specifically targets "
            "Phase 4 turnover weakness."
        ),
        "model_id": MODEL_ID,
        "decision_cadence": (
            "4 hours"
        ),
        "economic_horizon": (
            "4 hours"
        ),
        "non_overlapping_returns": True,
        "decision_hours_utc": sorted(
            DECISION_HOURS_UTC
        ),
        "state_space": [
            "XRP",
            "BTC",
            "CASH",
        ],
        "policy_family": POLICIES,
        "reference_policies": [
            "always_xrp",
            "always_btc",
            "always_cash",
        ],
        "switch_cost_bps": list(
            COST_BPS_SCENARIOS
        ),
        "hysteresis_policy": (
            "Separate entry and exit thresholds "
            "reduce flip-flopping around zero."
        ),
        "minimum_hold_policy": (
            "Once a state is entered, it cannot "
            "change until the configured minimum "
            "holding interval has elapsed."
        ),
        "reset_policy": (
            "Policy state resets to BTC at fold "
            "boundaries, segment changes, or "
            "missing four-hour decision intervals."
        ),
        "future_holdout_start_utc": (
            FUTURE_HOLDOUT_START
            .isoformat()
        ),
        "future_holdout_policy": (
            "No observations on or after "
            "2026-09-01 UTC are used."
        ),
        "threshold_selection_policy": (
            "Thresholds and minimum-hold variants "
            "are fixed before Phase 5 results are "
            "inspected. Phase 5 does not optimize "
            "parameters after execution."
        ),
        "interpretation_policy": (
            "Phase 5 is exploratory because its "
            "design follows Phase 4 inspection. "
            "No policy may be promoted solely "
            "from Phase 5 results."
        ),
        "shared_v2_policy": (
            "Frozen Crypto 15m V2 Phase 5 is "
            "not modified. XRP remains a separate "
            "research track."
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
            "transition_counts": str(
                output_root
                / "transition_counts.csv"
            ),
            "manifest": str(
                output_root
                / "manifest.json"
            ),
        },
        "next_step": (
            "Evaluate whether hysteresis and "
            "minimum holding periods materially "
            "reduce turnover while preserving "
            "fold-level net performance after "
            "5-20 bps switching costs. Do not "
            "promote a policy from aggregate "
            "equity alone."
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
        "CRYPTO XRP V1 PHASE 5"
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
            "switch_rate",
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
        "No thresholds were optimized "
        "after execution."
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
