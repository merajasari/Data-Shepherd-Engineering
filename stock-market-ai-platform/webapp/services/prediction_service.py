"""Frozen V5 ranking service for the Stock Market AI presentation layer.

V5 uses one frozen cross-sectional HistGradientBoosting regressor and ranks
100 investable stocks by predicted 5-trading-day return relative to SPY.
This module never fits or tunes the model.
"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RANKINGS_PATH = PROJECT_ROOT / "data/live/v5_latest_rankings.json"


def get_v5_rankings() -> dict:
    """Return the current native V5 ranking artifact, generating it if absent."""
    if not RANKINGS_PATH.exists():
        from ml.run_v5_inference import run_v5_inference
        return run_v5_inference(output_path=RANKINGS_PATH)

    try:
        payload = json.loads(RANKINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Unable to read V5 rankings: {RANKINGS_PATH}") from exc

    rankings = payload.get("rankings")
    if not isinstance(rankings, list) or not rankings:
        raise RuntimeError(f"V5 rankings artifact is empty or invalid: {RANKINGS_PATH}")
    return payload


def get_latest_prediction(symbol: str) -> dict:
    """Return the latest frozen-V5 cross-sectional inference for one symbol."""
    symbol = symbol.upper().strip()
    payload = get_v5_rankings()
    row = next((item for item in payload["rankings"] if item.get("symbol") == symbol), None)
    if row is None:
        raise KeyError(f"Symbol is not present in current V5 rankings: {symbol}")

    score = float(row["predicted_relative_return_5d"])
    percentile = float(row["rank_percentile"])
    return {
        "symbol": symbol,
        "prediction": "OUTPERFORM" if score >= 0.0 else "UNDERPERFORM",
        "predicted_relative_return_5d": score,
        "rank": int(row["rank"]),
        "rank_percentile": percentile,
        "selected_top5": bool(row["selected_top5"]),
        "decision_date_utc": payload.get("decision_date_utc"),
        "model_type": payload.get("model_id", "hist_gradient_boosting"),
        "horizon_days": 5,
        "benchmark_symbol": payload.get("benchmark_symbol", "SPY"),
        "candidate_count": int(payload.get("candidate_count", 100)),
        "close": float(row["close"]),
        "timestamp": payload.get("decision_date_utc"),
    }
