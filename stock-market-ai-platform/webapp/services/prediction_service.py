"""Frozen V8 ranking service for the stock presentation layer.

V8 ranks the registered 100-stock universe with the exact frozen DISTANCE_ONLY
Top-10 policy. This module never fits, tunes, writes holdout evidence, or places
orders.
"""
from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RANKINGS_PATH = PROJECT_ROOT / "data/live/v8_latest_rankings.json"


def get_v8_rankings() -> dict:
    """Return current V8 rankings, generating them atomically if absent."""

    if not RANKINGS_PATH.exists():
        from ml.run_v8_inference import run_v8_inference
        return run_v8_inference(output_path=RANKINGS_PATH)

    try:
        payload = json.loads(RANKINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Unable to read V8 rankings: {RANKINGS_PATH}") from exc

    rankings = payload.get("rankings")
    if not isinstance(rankings, list) or len(rankings) != 100:
        raise RuntimeError(f"V8 rankings artifact is incomplete or invalid: {RANKINGS_PATH}")
    return payload


def get_latest_prediction(symbol: str) -> dict:
    """Return the current frozen-V8 cross-sectional signal for one symbol."""

    symbol = symbol.upper().strip()
    payload = get_v8_rankings()
    row = next((item for item in payload["rankings"] if item.get("symbol") == symbol), None)
    if row is None:
        raise KeyError(f"Symbol is not present in current V8 rankings: {symbol}")

    score = float(row["signal_score"])
    selected = bool(row["selected_top10"])
    return {
        "symbol": symbol,
        "prediction": "TOP 10" if selected else "NOT SELECTED",
        "signal_score": score,
        "rank": int(row["rank"]),
        "rank_percentile": float(row["rank_percentile"]),
        "selected_top10": selected,
        "target_weight": float(row["target_weight"]),
        "decision_date_utc": payload.get("decision_date_utc"),
        "model_type": payload.get("signal_id", "DISTANCE_ONLY"),
        "horizon_days": int(payload.get("holding_sessions", 5)),
        "benchmark_symbol": payload.get("benchmark_symbol", "SPY"),
        "candidate_count": int(payload.get("candidate_count", 100)),
        "close": float(row["close"]),
        "timestamp": payload.get("decision_date_utc"),
    }


# Temporary compatibility alias for callers migrating from the former endpoint.
get_v5_rankings = get_v8_rankings
