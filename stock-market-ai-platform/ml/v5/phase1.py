"""V5 Phase 1: pre-registered leakage-safe walk-forward fold generation.

This phase defines development validation folds only. It does not fit models,
inspect model outcomes, run portfolio simulations, or evaluate the future
holdout. Training rows are purged whenever their 5-day target endpoint reaches
or crosses the validation start.
"""

import json
from pathlib import Path

import pandas as pd

from ml.v5.config import RESEARCH_PANEL_PATH


PHASE = 1
PRIMARY_HORIZON_DAYS = 5
DEVELOPMENT_VALIDATION_START_UTC = pd.Timestamp("2021-07-01", tz="UTC")
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-09-01", tz="UTC")
VALIDATION_MONTHS = 6

PHASE_ROOT = Path("data/model/v5/phase1")
FOLDS_PATH = PHASE_ROOT / "folds.json"
MANIFEST_PATH = PHASE_ROOT / "manifest.json"


def _utc(value):
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def validate_panel_contract(panel):
    required = {
        "symbol",
        "timestamp_utc",
        "feature_complete",
        f"is_labeled_{PRIMARY_HORIZON_DAYS}d",
        f"target_endpoint_utc_{PRIMARY_HORIZON_DAYS}d",
        f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V5 Phase 1 panel is missing columns: " + ", ".join(missing))

    if panel.duplicated(["timestamp_utc", "symbol"]).any():
        raise ValueError("V5 Phase 1 requires unique timestamp_utc/symbol rows")


def modeling_mask(panel):
    horizon = PRIMARY_HORIZON_DAYS
    return (
        panel["feature_complete"].fillna(False).astype(bool)
        & panel[f"is_labeled_{horizon}d"].fillna(False).astype(bool)
        & panel[f"forward_relative_return_{horizon}d"].notna()
        & panel[f"target_endpoint_utc_{horizon}d"].notna()
    )


def generate_folds(
    panel,
    development_start=DEVELOPMENT_VALIDATION_START_UTC,
    holdout_start=FUTURE_HOLDOUT_START_UTC,
    validation_months=VALIDATION_MONTHS,
):
    """Return expanding-window development folds with endpoint-based purge."""
    validate_panel_contract(panel)
    if validation_months <= 0:
        raise ValueError("validation_months must be positive")

    x = panel.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    endpoint_col = f"target_endpoint_utc_{PRIMARY_HORIZON_DAYS}d"
    x[endpoint_col] = pd.to_datetime(x[endpoint_col], utc=True)

    development_start = _utc(development_start)
    holdout_start = _utc(holdout_start)
    if development_start >= holdout_start:
        raise ValueError("development_start must precede holdout_start")

    usable = modeling_mask(x)
    last_decision = x.loc[usable & (x["timestamp_utc"] < holdout_start), "timestamp_utc"].max()
    if pd.isna(last_decision) or last_decision < development_start:
        raise ValueError("No usable development validation rows are available")

    folds = []
    validation_start = development_start
    fold_number = 1

    while validation_start < holdout_start and validation_start <= last_decision:
        scheduled_end = validation_start + pd.DateOffset(months=validation_months)
        validation_end = min(scheduled_end, holdout_start)

        train_mask = (
            usable
            & (x["timestamp_utc"] < validation_start)
            & (x[endpoint_col] < validation_start)
        )
        validation_mask = (
            usable
            & (x["timestamp_utc"] >= validation_start)
            & (x["timestamp_utc"] < validation_end)
            & (x["timestamp_utc"] < holdout_start)
            & (x[endpoint_col] < holdout_start)
        )

        train = x.loc[train_mask]
        validation = x.loc[validation_mask]
        if validation.empty:
            validation_start = validation_end
            fold_number += 1
            continue
        if train.empty:
            raise ValueError(
                f"Fold starting {validation_start.isoformat()} has no purged training rows"
            )

        max_train_endpoint = train[endpoint_col].max()
        if max_train_endpoint >= validation_start:
            raise AssertionError("Training target endpoint overlaps validation start")

        folds.append(
            {
                "fold_id": f"dev_{fold_number:02d}",
                "split": "development",
                "train_start_utc": train["timestamp_utc"].min().isoformat(),
                "train_end_utc": train["timestamp_utc"].max().isoformat(),
                "max_train_target_endpoint_utc": max_train_endpoint.isoformat(),
                "validation_start_utc": validation_start.isoformat(),
                "validation_end_exclusive_utc": validation_end.isoformat(),
                "actual_validation_start_utc": validation["timestamp_utc"].min().isoformat(),
                "actual_validation_end_utc": validation["timestamp_utc"].max().isoformat(),
                "train_rows": int(len(train)),
                "validation_rows": int(len(validation)),
                "train_days": int(train["timestamp_utc"].nunique()),
                "validation_days": int(validation["timestamp_utc"].nunique()),
                "train_symbols": int(train["symbol"].nunique()),
                "validation_symbols": int(validation["symbol"].nunique()),
            }
        )

        validation_start = validation_end
        fold_number += 1

    if not folds:
        raise ValueError("No V5 development folds were generated")
    return folds


def build_manifest(panel, folds):
    x = panel.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    endpoint_col = f"target_endpoint_utc_{PRIMARY_HORIZON_DAYS}d"
    x[endpoint_col] = pd.to_datetime(x[endpoint_col], utc=True)
    usable = modeling_mask(x)

    development = x.loc[
        usable
        & (x["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
        & (x[endpoint_col] < FUTURE_HOLDOUT_START_UTC)
    ]

    return {
        "research_version": "v5",
        "phase": PHASE,
        "stage": "pre_registered_walk_forward_fold_generation",
        "primary_horizon_days": PRIMARY_HORIZON_DAYS,
        "primary_target": f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d",
        "development_validation_start_utc": DEVELOPMENT_VALIDATION_START_UTC.isoformat(),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "validation_months": VALIDATION_MONTHS,
        "purge_policy": (
            "A training row is eligible only when its exact 5-trading-day target "
            "endpoint is strictly earlier than the validation start."
        ),
        "future_holdout_policy": (
            "Decision timestamps and target endpoints at or after 2026-09-01 are "
            "excluded from development and reserved for genuinely future evaluation."
        ),
        "feature_policy": (
            "Only rows with all registered V5 predictive features observed at the "
            "decision timestamp are eligible for modeling."
        ),
        "source_panel": str(RESEARCH_PANEL_PATH),
        "source_rows": int(len(x)),
        "development_usable_rows": int(len(development)),
        "development_usable_start_utc": development["timestamp_utc"].min().isoformat(),
        "development_usable_end_utc": development["timestamp_utc"].max().isoformat(),
        "fold_count": len(folds),
        "fold_ids": [fold["fold_id"] for fold in folds],
        "next_step": (
            "Review fold boundaries and purge diagnostics only. After the fold contract "
            "is frozen, define V5 baseline cross-sectional models without inspecting "
            "the future holdout."
        ),
    }


def main():
    if not RESEARCH_PANEL_PATH.exists():
        raise FileNotFoundError(
            f"V5 research panel not found: {RESEARCH_PANEL_PATH}. Run ml.v5.prepare_dataset first."
        )

    panel = pd.read_parquet(RESEARCH_PANEL_PATH)
    folds = generate_folds(panel)
    manifest = build_manifest(panel, folds)

    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    FOLDS_PATH.write_text(json.dumps(folds, indent=2) + "\n")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print(json.dumps({**manifest, "outputs": {"folds": str(FOLDS_PATH), "manifest": str(MANIFEST_PATH)}}, indent=2))


if __name__ == "__main__":
    main()
