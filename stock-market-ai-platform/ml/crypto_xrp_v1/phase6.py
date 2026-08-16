"""Crypto XRP V1 Phase 6: reproducible exploratory forward-candidate freeze.

This phase performs NO model selection and NO policy tuning.

It refits the already-selected XRP V1 Ridge specification on the complete
post-discontinuity development population available strictly before the frozen
future boundary and records the exact exploratory Phase 5 execution rule.

Research status
---------------
EXPLORATORY FORWARD CANDIDATE ONLY.

The Ridge model and hyst_10_05_hold24 policy were selected after inspection of
historical development results. Phase 6 therefore creates a reproducible
forward-monitoring artifact; it does not convert the candidate into untouched
historical validation or a production trading strategy.

Frozen model contract
---------------------
Pipeline is identical to XRP V1 Phase 2:

    SimpleImputer(strategy="median")
    StandardScaler()
    Ridge(alpha=10.0)

Primary target:

    btc_relative_forward_return_4h

Frozen exploratory execution rule
----------------------------------
policy: hyst_10_05_hold24

- decision cadence: 4 hours
- enter XRP:  score >= +0.0010
- enter CASH: score <= -0.0010
- leave XRP:  score <= +0.0005
- leave CASH: score >= -0.0005
- neutral state: BTC
- minimum hold: 24 hours

Safety boundaries
-----------------
- no timestamps on/after 2026-09-01 00:00 UTC
- no target endpoint on/after 2026-09-01 00:00 UTC
- post-gap primary XRP era only
- no legacy-era training
- no threshold tuning
- no model comparison
- no portfolio simulation
- no brokerage orders
- no leverage
- no shorting
- no derivatives
- no modification of frozen Crypto 15m V2
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.crypto_xrp_v1 import RESEARCH_VERSION


PHASE = 6

PRIMARY_DATASET = Path(
    "data/model/crypto_xrp_v1/phase1/xrp_primary.parquet"
)

OUTPUT_ROOT = Path(
    "data/model/crypto_xrp_v1/phase6"
)

MODEL_PATH = OUTPUT_ROOT / "frozen_ridge.joblib"
MANIFEST_PATH = OUTPUT_ROOT / "freeze_manifest.json"

PRIMARY_TARGET = "btc_relative_forward_return_4h"

FUTURE_HOLDOUT_START = pd.Timestamp(
    "2026-09-01T00:00:00Z"
)

TARGET_HORIZON = pd.Timedelta(hours=4)

POLICY_ID = "hyst_10_05_hold24"
DECISION_CADENCE_HOURS = 4
ENTRY_THRESHOLD = 0.0010
EXIT_THRESHOLD = 0.0005
MINIMUM_HOLD_HOURS = 24
INITIAL_STATE = "BTC"

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


def _git_hash() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with Path(path).open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def load_training_data(
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
    }

    missing = required - set(df.columns)

    if missing:
        raise RuntimeError(
            "XRP Phase 6 input is missing required columns: "
            f"{sorted(missing)}"
        )

    df["timestamp_utc"] = pd.to_datetime(
        df["timestamp_utc"],
        utc=True,
    )

    if set(
        df["product_id"].dropna().unique()
    ) != {"XRP-USD"}:
        raise RuntimeError(
            "XRP Phase 6 input contains non-XRP products"
        )

    if (
        df["timestamp_utc"] >= FUTURE_HOLDOUT_START
    ).any():
        raise RuntimeError(
            "XRP Phase 6 input contains future-holdout rows"
        )

    df = df[
        df[PRIMARY_TARGET].notna()
    ].copy()

    # Stronger boundary: even the 4-hour target endpoint must remain strictly
    # before the untouched future boundary.
    target_endpoint = (
        df["timestamp_utc"] + TARGET_HORIZON
    )

    df = df[
        target_endpoint < FUTURE_HOLDOUT_START
    ].copy()

    df = (
        df.sort_values("timestamp_utc")
        .drop_duplicates(
            ["timestamp_utc", "product_id"]
        )
        .reset_index(drop=True)
    )

    if df.empty:
        raise RuntimeError(
            "No eligible XRP Phase 6 training rows"
        )

    return df


def feature_columns(
    df: pd.DataFrame,
) -> list[str]:
    features = [
        column
        for column in df.columns
        if column not in ID_COLUMNS
        and not column.startswith(TARGET_PREFIXES)
    ]

    if PRIMARY_TARGET in features:
        raise RuntimeError(
            "Primary target leaked into feature list"
        )

    if len(features) != 44:
        raise RuntimeError(
            "Unexpected XRP feature count: "
            f"expected 44, found {len(features)}"
        )

    return features


def build_frozen_model() -> Pipeline:
    """Return the exact Ridge pipeline used in XRP V1 Phase 2."""
    return Pipeline(
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
    )


def freeze_candidate(
    primary_dataset: Path = PRIMARY_DATASET,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    primary_dataset = Path(primary_dataset)
    output_root = Path(output_root)

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    training = load_training_data(
        primary_dataset
    )

    features = feature_columns(
        training
    )

    X = training[features]
    y = training[PRIMARY_TARGET].astype(float)

    if y.isna().any():
        raise RuntimeError(
            "Phase 6 target contains missing values"
        )

    model = build_frozen_model()
    model.fit(X, y)

    model_path = output_root / "frozen_ridge.joblib"
    manifest_path = output_root / "freeze_manifest.json"

    joblib.dump(
        model,
        model_path,
        compress=3,
    )

    model_sha256 = _sha256(
        model_path
    )

    source_sha256 = _sha256(
        primary_dataset
    )

    # A small deterministic sanity prediction confirms the serialized artifact
    # can be loaded and used with the frozen feature order.
    reloaded = joblib.load(
        model_path
    )

    sample = X.tail(
        min(128, len(X))
    )

    original_prediction = model.predict(
        sample
    )

    reloaded_prediction = reloaded.predict(
        sample
    )

    max_reload_difference = float(
        np.max(
            np.abs(
                original_prediction
                - reloaded_prediction
            )
        )
    )

    if max_reload_difference > 1e-12:
        raise RuntimeError(
            "Serialized Ridge artifact failed reload equivalence check"
        )

    latest_timestamp = training[
        "timestamp_utc"
    ].max()

    latest_target_endpoint = (
        latest_timestamp + TARGET_HORIZON
    )

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "exploratory_forward_candidate_freeze",
        "research_status": "EXPLORATORY FORWARD CANDIDATE",
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "git_commit_hash_at_generation": _git_hash(),
        "product": "XRP-USD",
        "source_dataset": str(primary_dataset),
        "source_dataset_sha256": source_sha256,
        "training_population": (
            "post-major-discontinuity XRP primary era only"
        ),
        "training_rows": int(len(training)),
        "training_start_utc": training[
            "timestamp_utc"
        ].min().isoformat(),
        "training_end_utc": latest_timestamp.isoformat(),
        "latest_training_target_endpoint_utc": (
            latest_target_endpoint.isoformat()
        ),
        "primary_target": PRIMARY_TARGET,
        "target_horizon_hours": 4,
        "feature_count": len(features),
        "feature_columns": features,
        "model": {
            "model_id": "ridge",
            "artifact_path": str(model_path),
            "artifact_sha256": model_sha256,
            "pipeline": [
                {
                    "step": "imputer",
                    "class": "SimpleImputer",
                    "strategy": "median",
                },
                {
                    "step": "scaler",
                    "class": "StandardScaler",
                },
                {
                    "step": "model",
                    "class": "Ridge",
                    "alpha": 10.0,
                },
            ],
            "reload_equivalence_max_abs_diff": (
                max_reload_difference
            ),
        },
        "execution_policy": {
            "policy_id": POLICY_ID,
            "decision_cadence_hours": (
                DECISION_CADENCE_HOURS
            ),
            "state_space": [
                "XRP",
                "BTC",
                "CASH",
            ],
            "initial_state": INITIAL_STATE,
            "entry_threshold_positive": (
                ENTRY_THRESHOLD
            ),
            "entry_threshold_negative": (
                -ENTRY_THRESHOLD
            ),
            "exit_threshold_from_xrp": (
                EXIT_THRESHOLD
            ),
            "exit_threshold_from_cash": (
                -EXIT_THRESHOLD
            ),
            "neutral_state": "BTC",
            "minimum_hold_hours": (
                MINIMUM_HOLD_HOURS
            ),
            "rules": {
                "enter_xrp": "score >= +0.0010",
                "enter_cash": "score <= -0.0010",
                "leave_xrp": "score <= +0.0005",
                "leave_cash": "score >= -0.0005",
                "otherwise": "BTC",
            },
        },
        "future_holdout_start_utc": (
            FUTURE_HOLDOUT_START.isoformat()
        ),
        "future_holdout_policy": (
            "No timestamps or 4-hour target endpoints on/after "
            "2026-09-01 00:00 UTC are used for fitting or selection."
        ),
        "selection_history": (
            "Ridge and hyst_10_05_hold24 were selected using exploratory "
            "historical development Phases 2-5. Phase 6 performs no new "
            "selection or tuning."
        ),
        "promotion_status": (
            "NOT PROMOTED FOR REAL TRADING"
        ),
        "shadow_forward_only": True,
        "brokerage_orders": False,
        "leverage": False,
        "shorting": False,
        "derivatives": False,
        "shared_crypto_v2_modified": False,
        "library_versions": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "outputs": {
            "model": str(model_path),
            "manifest": str(manifest_path),
        },
        "next_step": (
            "Build shadow-only XRP forward inference that verifies this "
            "artifact hash and applies exactly this frozen policy."
        ),
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--primary-dataset",
        type=Path,
        default=PRIMARY_DATASET,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
    )

    args = parser.parse_args(argv)

    manifest = freeze_candidate(
        primary_dataset=args.primary_dataset,
        output_root=args.output_root,
    )

    model = manifest["model"]
    policy = manifest["execution_policy"]

    print()
    print("CRYPTO XRP V1 PHASE 6")
    print("=" * 80)
    print()
    print(
        "RESEARCH STATUS: "
        f"{manifest['research_status']}"
    )
    print()
    print(
        f"Training rows: {manifest['training_rows']:,}"
    )
    print(
        "Training range: "
        f"{manifest['training_start_utc']} -> "
        f"{manifest['training_end_utc']}"
    )
    print(
        "Latest target endpoint: "
        f"{manifest['latest_training_target_endpoint_utc']}"
    )
    print(
        f"Features: {manifest['feature_count']}"
    )
    print(
        f"Target: {manifest['primary_target']}"
    )
    print()
    print("Frozen model:")
    print(
        f"  artifact: {model['artifact_path']}"
    )
    print(
        f"  SHA-256:  {model['artifact_sha256']}"
    )
    print()
    print("Frozen exploratory policy:")
    print(
        f"  policy: {policy['policy_id']}"
    )
    print(
        "  entry:  XRP >= +0.0010 / "
        "CASH <= -0.0010"
    )
    print(
        "  exit:   XRP <= +0.0005 / "
        "CASH >= -0.0005"
    )
    print(
        f"  neutral: {policy['neutral_state']}"
    )
    print(
        "  minimum hold: "
        f"{policy['minimum_hold_hours']} hours"
    )
    print()
    print(
        "No model selection or threshold tuning occurred."
    )
    print(
        "No real orders were placed."
    )
    print(
        "Future holdout remains untouched from "
        "2026-09-01 UTC."
    )


if __name__ == "__main__":
    main()
