"""Read-only Crypto V1 dashboard service.

This presentation service consumes frozen Crypto V1 Phase 3/4 research
artifacts. It never fits models, changes research rules, or places orders.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.crypto_v1.config import CRYPTO_UNIVERSE, MODEL_ROOT

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"

PRIMARY_HORIZON_DAYS = 7
PRIMARY_MODEL_ID = "momentum"
PRIMARY_VARIANT = "top_5_equal_weight"
PRIMARY_TOP_N = 5
PRIMARY_COST_BPS = 25.0
DISPLAY_STARTING_EQUITY = 100_000.0


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_predictions() -> pd.DataFrame:
    path = PHASE3_ROOT / "predictions.parquet"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    return frame


def _primary_daily() -> pd.DataFrame:
    daily = _read_csv(PHASE4_ROOT / "portfolio_daily.csv")
    if daily.empty:
        return daily
    daily["timestamp_utc"] = pd.to_datetime(daily["timestamp_utc"], utc=True)
    mask = (
        daily["split"].eq("holdout")
        & daily["model_id"].eq(PRIMARY_MODEL_ID)
        & daily["variant"].eq(PRIMARY_VARIANT)
        & pd.to_numeric(daily["top_n"], errors="coerce").eq(PRIMARY_TOP_N)
        & pd.to_numeric(daily["cost_bps_round_trip"], errors="coerce").eq(PRIMARY_COST_BPS)
    )
    return daily.loc[mask].sort_values("timestamp_utc").reset_index(drop=True)


def _btc_daily() -> pd.DataFrame:
    daily = _read_csv(PHASE4_ROOT / "portfolio_daily.csv")
    if daily.empty:
        return daily
    daily["timestamp_utc"] = pd.to_datetime(daily["timestamp_utc"], utc=True)
    mask = (
        daily["split"].eq("holdout")
        & daily["model_id"].eq(PRIMARY_MODEL_ID)
        & daily["variant"].eq("btc_benchmark")
        & pd.to_numeric(daily["cost_bps_round_trip"], errors="coerce").eq(PRIMARY_COST_BPS)
    )
    return daily.loc[mask].sort_values("timestamp_utc").reset_index(drop=True)


def _latest_rankings() -> tuple[str | None, list[dict]]:
    predictions = _read_predictions()
    if predictions.empty:
        return None, []
    frame = predictions[
        (predictions["split"] == "holdout")
        & (predictions["model_id"] == PRIMARY_MODEL_ID)
        & (predictions["horizon_days"] == PRIMARY_HORIZON_DAYS)
    ].copy()
    if frame.empty:
        return None, []
    latest = frame["timestamp_utc"].max()
    day = frame[frame["timestamp_utc"] == latest].sort_values(
        ["predicted_score", "product_id"], ascending=[False, True]
    )
    rows = []
    count = len(day)
    for rank, row in enumerate(day.itertuples(index=False), start=1):
        score = float(row.predicted_score)
        rows.append({
            "rank": rank,
            "product_id": row.product_id,
            "score": score,
            "score_pct": score * 100.0,
            "rank_percentile": (1.0 - (rank - 1) / max(1, count - 1)) * 100.0,
            "top5": rank <= PRIMARY_TOP_N,
        })
    return latest.isoformat(), rows


def _equity_history(primary: pd.DataFrame, btc: pd.DataFrame) -> list[dict]:
    if primary.empty:
        return []
    btc_map = {}
    if not btc.empty:
        btc_map = dict(zip(btc["timestamp_utc"], pd.to_numeric(btc["equity"], errors="coerce")))
    history = []
    for row in primary.itertuples(index=False):
        equity_multiple = float(row.equity)
        benchmark_multiple = btc_map.get(row.timestamp_utc)
        history.append({
            "timestamp": row.timestamp_utc.isoformat(),
            "equity": DISPLAY_STARTING_EQUITY * equity_multiple,
            "btc_equity": (
                DISPLAY_STARTING_EQUITY * float(benchmark_multiple)
                if benchmark_multiple is not None and pd.notna(benchmark_multiple)
                else None
            ),
            "is_rebalance": bool(row.is_rebalance),
        })
    return history


def get_crypto_dashboard_payload() -> dict:
    """Return presentation-ready frozen Crypto V1 simulation state."""
    primary = _primary_daily()
    btc = _btc_daily()
    ranking_timestamp, rankings = _latest_rankings()

    if primary.empty:
        return {
            "available": False,
            "message": "Crypto V1 Phase 4 artifacts are not available on this machine.",
            "universe": list(CRYPTO_UNIVERSE),
            "rankings": rankings,
            "ranking_timestamp": ranking_timestamp,
        }

    current_multiple = float(primary["equity"].iloc[-1])
    current_equity = DISPLAY_STARTING_EQUITY * current_multiple
    cumulative_return = current_multiple - 1.0
    running_peak = pd.to_numeric(primary["equity"], errors="coerce").cummax()
    drawdown = pd.to_numeric(primary["equity"], errors="coerce") / running_peak - 1.0

    btc_multiple = float(btc["equity"].iloc[-1]) if not btc.empty else None
    btc_return = btc_multiple - 1.0 if btc_multiple is not None else None
    excess = cumulative_return - btc_return if btc_return is not None else None

    latest_rebalance = primary[primary["is_rebalance"].astype(str).str.lower().isin(["true", "1"])]
    latest_rebalance_timestamp = (
        latest_rebalance["timestamp_utc"].max().isoformat()
        if not latest_rebalance.empty else None
    )

    return {
        "available": True,
        "mode": "frozen_research_simulation",
        "starting_equity": DISPLAY_STARTING_EQUITY,
        "current_equity": current_equity,
        "net_change": current_equity - DISPLAY_STARTING_EQUITY,
        "cumulative_return": cumulative_return,
        "btc_return": btc_return,
        "excess_return_vs_btc": excess,
        "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "observation_count": max(0, len(primary) - 1),
        "rebalance_count": int(primary["is_rebalance"].astype(str).str.lower().isin(["true", "1"]).sum()),
        "latest_rebalance_timestamp": latest_rebalance_timestamp,
        "ranking_timestamp": ranking_timestamp,
        "top_five": rankings[:5],
        "rankings": rankings,
        "equity_history": _equity_history(primary, btc),
        "universe": list(CRYPTO_UNIVERSE),
        "contract": {
            "research_version": "crypto_v1",
            "model_id": PRIMARY_MODEL_ID,
            "horizon_days": PRIMARY_HORIZON_DAYS,
            "variant": PRIMARY_VARIANT,
            "top_n": PRIMARY_TOP_N,
            "round_trip_cost_bps": PRIMARY_COST_BPS,
            "benchmark": "BTC-USD",
            "leverage": False,
            "real_orders": False,
        },
    }
