"""V5 Phase 5: freeze the stock candidate before the genuine future holdout.

This phase fits one final HistGradientBoosting model using only rows whose
5-trading-day labels are fully realized before the pre-registered holdout start.
It writes a frozen model artifact plus an immutable contract manifest. It does
not evaluate any row at or after the future holdout start and does not run a
portfolio simulation.
"""

import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from ml.v5.config import (
    BENCHMARK_SYMBOL,
    CORE_ALLOCATION,
    POSITION_ALLOCATION,
    RESEARCH_PANEL_PATH,
    STRATEGY_ALLOCATION,
    TOP_COUNT,
    V5_FEATURE_COLUMNS,
)
from ml.v5.phase1 import FUTURE_HOLDOUT_START_UTC, PRIMARY_HORIZON_DAYS
from ml.v5.phase2 import HGB_PARAMS

PHASE = 5
TARGET = f"forward_relative_return_{PRIMARY_HORIZON_DAYS}d"
ENDPOINT = f"target_endpoint_utc_{PRIMARY_HORIZON_DAYS}d"
PHASE_ROOT = Path("data/model/v5/phase5")
MODEL_PATH = PHASE_ROOT / "frozen_hgb.joblib"
MANIFEST_PATH = PHASE_ROOT / "freeze_manifest.json"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def training_mask(panel):
    ts = pd.to_datetime(panel["timestamp_utc"], utc=True)
    endpoint = pd.to_datetime(panel[ENDPOINT], utc=True)
    return (
        panel["feature_complete"].fillna(False).astype(bool)
        & panel[TARGET].notna()
        & endpoint.notna()
        & (ts < FUTURE_HOLDOUT_START_UTC)
        & (endpoint < FUTURE_HOLDOUT_START_UTC)
    )


def make_frozen_model():
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", HistGradientBoostingRegressor(**HGB_PARAMS)),
    ])


def build_freeze(panel):
    required = {
        "symbol", "timestamp_utc", "feature_complete", TARGET, ENDPOINT,
        *V5_FEATURE_COLUMNS,
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError("V5 Phase 5 panel missing: " + ", ".join(missing))

    x = panel.copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    x[ENDPOINT] = pd.to_datetime(x[ENDPOINT], utc=True)
    train = x.loc[training_mask(x)].copy()
    if train.empty:
        raise ValueError("No pre-holdout rows available to freeze V5")
    if train[ENDPOINT].max() >= FUTURE_HOLDOUT_START_UTC:
        raise AssertionError("Freeze training endpoint reaches future holdout")

    model = make_frozen_model()
    model.fit(train[list(V5_FEATURE_COLUMNS)], train[TARGET])

    manifest = {
        "research_version": "v5",
        "phase": PHASE,
        "stage": "frozen_candidate_before_genuine_future_holdout",
        "model_id": "hist_gradient_boosting",
        "model_parameters": HGB_PARAMS,
        "target": TARGET,
        "feature_columns": list(V5_FEATURE_COLUMNS),
        "training_rows": int(len(train)),
        "training_symbols": int(train["symbol"].nunique()),
        "training_start_utc": train["timestamp_utc"].min().isoformat(),
        "training_last_decision_utc": train["timestamp_utc"].max().isoformat(),
        "training_last_target_endpoint_utc": train[ENDPOINT].max().isoformat(),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "portfolio_contract": {
            "benchmark_symbol": BENCHMARK_SYMBOL,
            "benchmark_weight": CORE_ALLOCATION,
            "stock_sleeve_weight": STRATEGY_ALLOCATION,
            "top_n": TOP_COUNT,
            "weight_per_selected_stock": POSITION_ALLOCATION,
            "rebalance_trading_days": PRIMARY_HORIZON_DAYS,
        },
        "freeze_policy": (
            "Model, feature set, target, 60/40 portfolio weights, Top-5 selection, "
            "and 5-trading-day cadence are frozen before 2026-09-01. No data with a "
            "decision timestamp or target endpoint at/after the future holdout start "
            "is used to fit or select this candidate."
        ),
        "source_panel": str(RESEARCH_PANEL_PATH),
    }
    return model, manifest


def main():
    if not RESEARCH_PANEL_PATH.exists():
        raise FileNotFoundError("Run ml.v5.prepare_dataset before V5 Phase 5")
    panel = pd.read_parquet(RESEARCH_PANEL_PATH)
    model, manifest = build_freeze(panel)

    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    manifest["source_panel_sha256"] = sha256_file(RESEARCH_PANEL_PATH)
    manifest["model_artifact"] = str(MODEL_PATH)
    manifest["model_artifact_sha256"] = sha256_file(MODEL_PATH)
    manifest["next_step"] = (
        "Use the isolated V5 forward/paper runner. Before 2026-09-01 it must not "
        "write holdout observations. At/after the holdout start, append-only signal "
        "observations may be recorded without refitting or tuning the frozen model."
    )
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
