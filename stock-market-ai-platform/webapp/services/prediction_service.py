"""Frozen V8 DISTANCE_ONLY ranking service for the stock dashboard.

This compatibility module keeps the existing Flask/template call surface while
removing V5 inference from the stock page. It never fits, tunes, or modifies V8.
"""
from __future__ import annotations

from webapp.services.v8_holdout_service import get_v8_holdout_dashboard


def _native_v8() -> dict:
    payload=get_v8_holdout_dashboard().get("dashboard") or {}
    if not payload.get("available") or not payload.get("rankings"):
        raise RuntimeError("Frozen V8 ranking panel is not available; run V8 Phase 4 first")
    return payload


def get_v5_rankings() -> dict:
    """Compatibility alias: return frozen V8 rankings, not V5 inference."""
    v8=_native_v8()
    rows=[]
    for r in v8["rankings"]:
        score=float(r["score"])
        rows.append({
            **r,
            # Compatibility fields consumed by the legacy server template. The
            # browser replaces their labels with V8 terminology immediately.
            "predicted_relative_return_5d":score,
            "selected_top5":bool(r["rank"]<=10),
            "sector":r.get("sector", ""),
            "close":0.0,
        })
    return {
        "research_version":"v8",
        "model_id":"V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "decision_date_utc":v8.get("decision_date_utc"),
        "candidate_count":v8.get("candidate_count",100),
        "feature_count":1,
        "benchmark_symbol":"SPY",
        "top_n":10,
        "benchmark_weight":0.0,
        "stock_sleeve_weight":1.0,
        "weight_per_selected_stock":0.10,
        "frozen_sha256":v8.get("frozen_sha256"),
        "rankings":rows,
    }


def get_latest_prediction(symbol: str) -> dict:
    """Return the current frozen-V8 rank/signal for one stock."""
    symbol=symbol.upper().strip()
    payload=get_v5_rankings()
    row=next((item for item in payload["rankings"] if item.get("symbol")==symbol),None)
    if row is None:
        raise KeyError(f"Symbol is not present in current V8 rankings: {symbol}")
    score=float(row["predicted_relative_return_5d"])
    return {
        "symbol":symbol,
        "prediction":"SELECTED" if int(row["rank"])<=10 else "NOT_SELECTED",
        "predicted_relative_return_5d":score,
        "rank":int(row["rank"]),
        "rank_percentile":float(row["rank_percentile"]),
        "selected_top5":bool(int(row["rank"])<=10),
        "decision_date_utc":payload.get("decision_date_utc"),
        "model_type":"V8_DISTANCE_ONLY",
        "horizon_days":5,
        "benchmark_symbol":"SPY",
        "candidate_count":int(payload.get("candidate_count",100)),
        "close":0.0,
        "timestamp":payload.get("decision_date_utc"),
    }
