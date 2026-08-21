"""Generate current frozen V5 cross-sectional rankings without fitting.

This production inference path intentionally keeps the V5 research contract
frozen.  It loads the frozen HistGradientBoosting pipeline and the registered
26-feature contract, reads current production feature files for the 100
investable V5 candidates, finds the latest decision date shared by every
candidate and SPY, scores the candidates, ranks them cross-sectionally, and
atomically writes ``data/live/v5_latest_rankings.json``.

The output is an inference/ranking artifact only.  It does not fit or tune a
model, create forward targets, record realized holdout observations, place
orders, or modify frozen research artifacts.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

from feature_source import feature_dataset_exists, get_feature_dataset_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"
sys.path.insert(0, str(DATA_INGESTION))

from v5_symbols import (  # noqa: E402
    V5_BENCHMARK_SYMBOL,
    get_v5_data_symbols,
    get_v5_sector,
    get_v5_symbols,
)


FREEZE_MANIFEST_PATH = PROJECT_ROOT / "data/model/v5/phase5/freeze_manifest.json"
MODEL_PATH = PROJECT_ROOT / "data/model/v5/phase5/frozen_hgb.joblib"
OUTPUT_PATH = PROJECT_ROOT / "data/live/v5_latest_rankings.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path = FREEZE_MANIFEST_PATH) -> dict:
    if not feature_dataset_exists(path):
        raise FileNotFoundError(f"V5 freeze manifest not found: {path}")
    payload = json.loads(path.read_text())
    features = payload.get("feature_columns")
    if not isinstance(features, list) or not features:
        raise ValueError("V5 freeze manifest does not contain feature_columns")
    return payload


def _feature_path(symbol: str) -> Path:
    return get_feature_dataset_path(symbol, project_root=PROJECT_ROOT)


def _read_feature_frame(symbol: str, feature_columns: list[str]) -> pd.DataFrame:
    path = _feature_path(symbol)
    if not path.exists():
        raise FileNotFoundError(f"Feature file not found for {symbol}: {path}")

    frame = pd.read_parquet(path)
    missing = [column for column in ["timestamp_utc", "close", *feature_columns] if column not in frame.columns]
    if missing:
        raise ValueError(f"{symbol} feature file missing columns: {', '.join(missing)}")

    frame = frame.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc")
    if frame.empty:
        raise ValueError(f"No timestamped feature rows for {symbol}")
    return frame


def _latest_common_decision_date(frames: dict[str, pd.DataFrame]) -> pd.Timestamp:
    latest_by_symbol = {
        symbol: frame["timestamp_utc"].max()
        for symbol, frame in frames.items()
    }
    common = min(latest_by_symbol.values())

    missing_at_common = [
        symbol
        for symbol, frame in frames.items()
        if not (frame["timestamp_utc"] == common).any()
    ]
    if missing_at_common:
        raise RuntimeError(
            "V5 inference failed closed because the latest common decision date "
            f"{common.isoformat()} is missing for: {', '.join(sorted(missing_at_common))}"
        )
    return common


def build_v5_rankings(
    manifest_path: Path = FREEZE_MANIFEST_PATH,
    model_path: Path = MODEL_PATH,
) -> dict:
    """Build one current V5 ranking snapshot from frozen model + current features."""

    manifest = _load_manifest(manifest_path)
    feature_columns = list(manifest["feature_columns"])
    candidates = get_v5_symbols()
    data_symbols = get_v5_data_symbols()

    if len(candidates) != 100:
        raise RuntimeError(f"Expected 100 V5 candidates, found {len(candidates)}")
    if V5_BENCHMARK_SYMBOL in candidates:
        raise RuntimeError("SPY must remain outside the investable V5 candidate universe")

    frames = {
        symbol: _read_feature_frame(symbol, feature_columns)
        for symbol in data_symbols
    }
    decision_date = _latest_common_decision_date(frames)

    rows = []
    for symbol in candidates:
        row = frames[symbol].loc[
            frames[symbol]["timestamp_utc"] == decision_date
        ].iloc[-1]

        missing_values = [column for column in feature_columns if pd.isna(row[column])]
        if missing_values:
            raise RuntimeError(
                f"{symbol} has incomplete frozen V5 features at {decision_date.isoformat()}: "
                + ", ".join(missing_values)
            )

        rows.append({
            "symbol": symbol,
            "sector": get_v5_sector(symbol),
            "close": float(row["close"]),
            **{column: float(row[column]) for column in feature_columns},
        })

    scoring_frame = pd.DataFrame(rows)
    if not model_path.exists():
        raise FileNotFoundError(f"Frozen V5 model not found: {model_path}")

    model = joblib.load(model_path)
    scores = model.predict(scoring_frame[feature_columns])
    scoring_frame["predicted_relative_return_5d"] = [float(value) for value in scores]
    scoring_frame = scoring_frame.sort_values(
        ["predicted_relative_return_5d", "symbol"],
        ascending=[False, True],
    ).reset_index(drop=True)
    scoring_frame["rank"] = range(1, len(scoring_frame) + 1)
    denominator = max(1, len(scoring_frame) - 1)
    scoring_frame["rank_percentile"] = (
        (len(scoring_frame) - scoring_frame["rank"]) / denominator
    )
    scoring_frame["selected_top5"] = scoring_frame["rank"] <= 5

    portfolio = manifest.get("portfolio_contract", {})
    rankings = []
    for row in scoring_frame.itertuples(index=False):
        rankings.append({
            "symbol": row.symbol,
            "sector": row.sector,
            "rank": int(row.rank),
            "rank_percentile": float(row.rank_percentile),
            "predicted_relative_return_5d": float(row.predicted_relative_return_5d),
            "selected_top5": bool(row.selected_top5),
            "close": float(row.close),
        })

    generated_at = datetime.now(timezone.utc)
    holdout_start = manifest.get("future_holdout_start_utc")
    payload = {
        "research_version": "v5",
        "artifact_type": "production_cross_sectional_inference",
        "generated_at_utc": generated_at.isoformat(),
        "decision_date_utc": decision_date.isoformat(),
        "model_id": manifest.get("model_id", "hist_gradient_boosting"),
        "model_artifact": str(model_path.relative_to(PROJECT_ROOT)),
        "model_artifact_sha256": _sha256(model_path),
        "freeze_manifest": str(manifest_path.relative_to(PROJECT_ROOT)),
        "freeze_manifest_sha256": _sha256(manifest_path),
        "feature_count": len(feature_columns),
        "feature_columns": feature_columns,
        "candidate_count": len(candidates),
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "benchmark_is_investable": False,
        "top_n": int(portfolio.get("top_n", 5)),
        "benchmark_weight": float(portfolio.get("benchmark_weight", 0.60)),
        "stock_sleeve_weight": float(portfolio.get("stock_sleeve_weight", 0.40)),
        "weight_per_selected_stock": float(portfolio.get("weight_per_selected_stock", 0.08)),
        "rebalance_trading_days": int(portfolio.get("rebalance_trading_days", 5)),
        "future_holdout_start_utc": holdout_start,
        "records_realized_holdout_observations": False,
        "refits_or_tunes_model": False,
        "data_lineage": (
            "Current production feature files are used for forward inference. Frozen research "
            "artifacts remain unchanged; current vendor history may contain legitimate post-freeze restatements."
        ),
        "rankings": rankings,
    }
    return payload


def write_v5_rankings(payload: dict, output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    temp.replace(output_path)
    return output_path


def run_v5_inference(output_path: Path = OUTPUT_PATH) -> dict:
    payload = build_v5_rankings()
    write_v5_rankings(payload, output_path=output_path)
    print("V5 PRODUCTION INFERENCE")
    print(f"Decision date: {payload['decision_date_utc']}")
    print(f"Candidates ranked: {payload['candidate_count']}")
    print("Top 5: " + ", ".join(row["symbol"] for row in payload["rankings"][:5]))
    print(f"Output: {output_path}")
    return payload


def main():
    run_v5_inference()


if __name__ == "__main__":
    main()
