"""Isolated forward/paper evaluation support for frozen Stock V5.

No brokerage orders are placed. The service scores the latest available
candidate features with the frozen Phase 5 model and appends an immutable
signal observation only when the decision timestamp is at or after the genuine
future holdout start.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "data-ingestion"))

from v5_symbols import V5_SYMBOLS  # noqa: E402
from ml.v5.config import (  # noqa: E402
    BENCHMARK_SYMBOL,
    CORE_ALLOCATION,
    POSITION_ALLOCATION,
    STRATEGY_ALLOCATION,
    TOP_COUNT,
    V5_FEATURE_COLUMNS,
)
from ml.v5.phase1 import FUTURE_HOLDOUT_START_UTC  # noqa: E402

PHASE5_ROOT = Path("data/model/v5/phase5")
MODEL_PATH = PHASE5_ROOT / "frozen_hgb.joblib"
FREEZE_MANIFEST_PATH = PHASE5_ROOT / "freeze_manifest.json"
FORWARD_ROOT = Path("data/paper_trading/v5_forward")
SIGNAL_JOURNAL_PATH = FORWARD_ROOT / "signals.jsonl"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _feature_path(symbol):
    return Path(f"data/features/stocks/{symbol}/{symbol}_features.parquet")


def load_freeze_contract():
    if not MODEL_PATH.exists() or not FREEZE_MANIFEST_PATH.exists():
        raise FileNotFoundError("Run python -m ml.v5.phase5 before forward evaluation")
    manifest = json.loads(FREEZE_MANIFEST_PATH.read_text())
    actual = _sha256(MODEL_PATH)
    expected = manifest.get("model_artifact_sha256")
    if expected and actual != expected:
        raise RuntimeError("Frozen V5 model hash does not match freeze manifest")
    return manifest


def latest_common_feature_snapshot():
    frames = []
    for symbol in V5_SYMBOLS:
        path = _feature_path(symbol)
        if not path.exists():
            raise FileNotFoundError(f"Missing V5 feature file: {path}")
        df = pd.read_parquet(path, columns=["timestamp_utc", *V5_FEATURE_COLUMNS]).copy()
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        complete = df[list(V5_FEATURE_COLUMNS)].notna().all(axis=1)
        df = df.loc[complete]
        if df.empty:
            raise ValueError(f"No complete V5 feature row for {symbol}")
        last = df.iloc[-1].copy()
        last["symbol"] = symbol
        frames.append(last)

    snapshot = pd.DataFrame(frames)
    latest_common = snapshot["timestamp_utc"].min()
    # Re-read each symbol at exactly the common timestamp so every score uses
    # the same decision date.
    rows = []
    for symbol in V5_SYMBOLS:
        df = pd.read_parquet(_feature_path(symbol), columns=["timestamp_utc", *V5_FEATURE_COLUMNS]).copy()
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        match = df.loc[df["timestamp_utc"] == latest_common]
        if match.empty or not match[list(V5_FEATURE_COLUMNS)].notna().all(axis=1).iloc[0]:
            raise ValueError(f"{symbol} lacks complete features at common timestamp {latest_common}")
        row = match.iloc[0].copy()
        row["symbol"] = symbol
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True), latest_common


def score_latest_snapshot():
    manifest = load_freeze_contract()
    model = joblib.load(MODEL_PATH)
    snapshot, decision_timestamp = latest_common_feature_snapshot()
    snapshot["predicted_relative_return_5d"] = model.predict(snapshot[list(V5_FEATURE_COLUMNS)])
    snapshot = snapshot.sort_values("predicted_relative_return_5d", ascending=False).reset_index(drop=True)
    snapshot["rank"] = range(1, len(snapshot) + 1)
    top = snapshot.head(TOP_COUNT).copy()
    return {
        "decision_timestamp": decision_timestamp,
        "top_five": [
            {
                "symbol": row.symbol,
                "rank": int(row.rank),
                "predicted_relative_return_5d": float(row.predicted_relative_return_5d),
                "target_weight": POSITION_ALLOCATION,
            }
            for row in top.itertuples(index=False)
        ],
        "portfolio": {
            BENCHMARK_SYMBOL: CORE_ALLOCATION,
            **{row.symbol: POSITION_ALLOCATION for row in top.itertuples(index=False)},
        },
        "model_sha256": manifest["model_artifact_sha256"],
        "freeze_manifest": str(FREEZE_MANIFEST_PATH),
        "holdout_start_utc": FUTURE_HOLDOUT_START_UTC,
    }


def _existing_decision_timestamps():
    if not SIGNAL_JOURNAL_PATH.exists():
        return set()
    out = set()
    for line in SIGNAL_JOURNAL_PATH.read_text().splitlines():
        if not line.strip():
            continue
        out.add(json.loads(line)["decision_timestamp_utc"])
    return out


def append_forward_signal(scored):
    decision = pd.Timestamp(scored["decision_timestamp"])
    if decision < FUTURE_HOLDOUT_START_UTC:
        return {
            "written": False,
            "reason": "future_holdout_not_started",
            "decision_timestamp_utc": decision.isoformat(),
        }

    key = decision.isoformat()
    if key in _existing_decision_timestamps():
        return {"written": False, "reason": "already_recorded", "decision_timestamp_utc": key}

    entry = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_timestamp_utc": key,
        "research_version": "v5",
        "model_id": "hist_gradient_boosting",
        "model_sha256": scored["model_sha256"],
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_weight": CORE_ALLOCATION,
        "stock_sleeve_weight": STRATEGY_ALLOCATION,
        "top_five": scored["top_five"],
        "target_portfolio": scored["portfolio"],
        "status": "signal_recorded_unsettled",
    }
    FORWARD_ROOT.mkdir(parents=True, exist_ok=True)
    with SIGNAL_JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return {"written": True, "entry": entry}
