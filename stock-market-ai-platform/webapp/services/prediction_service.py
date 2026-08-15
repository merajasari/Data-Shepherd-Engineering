"""Frozen V5 ranking service for the Stock Market AI presentation layer.

The legacy dashboard originally loaded per-symbol ``models/*_direction_model.pkl``
artifacts.  Those models are no longer the production contract.  V5 uses one
frozen cross-sectional HistGradientBoosting regressor and ranks 100 investable
stocks by predicted 5-trading-day return relative to SPY.

This service reads the current production ranking artifact.  If the artifact is
missing, it generates it from the frozen V5 model without fitting or tuning.
A small set of legacy numeric fields remains in the returned dictionary so the
existing dashboard template can render during the UI migration; they are
explicitly rank-display compatibility values, not calibrated probabilities or
historical classification metrics.
"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RANKINGS_PATH = PROJECT_ROOT / "data/live/v5_latest_rankings.json"


def _load_rankings() -> dict:
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
    payload = _load_rankings()

    row = next(
        (item for item in payload["rankings"] if item.get("symbol") == symbol),
        None,
    )
    if row is None:
        raise KeyError(f"Symbol is not present in current V5 rankings: {symbol}")

    score = float(row["predicted_relative_return_5d"])
    percentile = float(row["rank_percentile"])
    rank = int(row["rank"])
    selected_top5 = bool(row["selected_top5"])

    # Existing HTML still expects UP/DOWN and probability-shaped values.  Until
    # that presentation is fully redesigned for V5, use the sign of the
    # SPY-relative score for direction and the cross-sectional percentile only
    # as display strength.  Do not interpret these as calibrated probabilities.
    prediction = "UP" if score >= 0.0 else "DOWN"
    display_up = percentile
    display_down = 1.0 - percentile
    display_strength = max(display_up, display_down)

    return {
        "symbol": symbol,
        "prediction": prediction,
        "predicted_relative_return_5d": score,
        "rank": rank,
        "rank_percentile": percentile,
        "selected_top5": selected_top5,
        "decision_date_utc": payload.get("decision_date_utc"),
        "model_type": payload.get("model_id", "hist_gradient_boosting"),
        "horizon_days": 5,
        "benchmark_symbol": payload.get("benchmark_symbol", "SPY"),
        "candidate_count": int(payload.get("candidate_count", 100)),
        "close": float(row["close"]),
        "timestamp": payload.get("decision_date_utc"),

        # Legacy dashboard-display compatibility fields.  The probability bars
        # now visualize rank strength, while quality metrics are intentionally
        # zero rather than fabricating V5 classification statistics.
        "probability_up": display_up,
        "probability_down": display_down,
        "confidence": display_strength,
        "threshold": 0.0,
        "accuracy": 0.0,
        "majority_baseline": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
    }
