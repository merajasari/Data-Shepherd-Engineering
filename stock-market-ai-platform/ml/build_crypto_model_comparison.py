"""Build the research-only Crypto Model Research comparison artifact.

Only completed, causal reconstruction artifacts are admitted. Missing or
incompatible model outputs are reported as unavailable; they are never replaced
with synthetic dashboard curves. All admitted paths are rebased to $100,000.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

STARTING_CAPITAL = 100_000.0
TEN_YEARS_AGO = pd.Timestamp("2016-09-15T00:00:00Z")
DEFAULT_OUTPUT = Path("webapp/static/generated/crypto_model_comparison.json")
TRADING_DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class StrategySpec:
    model_id: str
    label: str
    path: Path
    variant: str
    timestamp_column: str
    equity_column: str
    cost_bps: float = 25.0
    status: str = "historical reconstruction"
    model_filter: Optional[str] = None
    split_filter: Optional[str] = None
    horizon_days: Optional[int] = None
    top_n: Optional[int] = None
    observation_interval_days: float = 1.0


STRATEGIES = (
    StrategySpec("CRYPTO_V1", "Crypto V1", Path("data/model/crypto_v1/phase4/portfolio_daily.csv"), "top_5_equal_weight", "timestamp_utc", "equity", model_filter="momentum", split_filter="development"),
    StrategySpec("CRYPTO_V2", "Crypto V2", Path("data/model/crypto_v2/phase4/portfolio_daily.csv"), "top_5_equal_weight", "timestamp_utc", "equity", model_filter="hist_gradient_boosting", split_filter="development"),
    StrategySpec("CRYPTO_V3", "Crypto V3", Path("data/model/crypto_v3/phase3/portfolio_daily.csv"), "gated_top_5", "timestamp_utc", "equity"),
    StrategySpec("CRYPTO_V4", "Crypto V4 allocator", Path("data/model/crypto_v4/phase3/portfolio_periods.csv"), "v4_hgb_allocator", "timestamp_utc", "ending_equity"),
    StrategySpec("CRYPTO_V5", "Crypto V5 Ridge Top-3", Path("data/research/crypto_ten_year/reconstruction/crypto_v5/phase3/portfolio_periods.parquet"), "", "timestamp_utc", "ending_equity", status="selected for forward paper evaluation", model_filter="ridge", horizon_days=3, top_n=3, observation_interval_days=3.0),
    StrategySpec("BTC", "Bitcoin buy and hold", Path("data/model/crypto_v1/phase4/portfolio_daily.csv"), "btc_benchmark", "timestamp_utc", "equity", status="benchmark", model_filter="momentum", split_filter="development"),
    StrategySpec("ETH", "Ethereum buy and hold", Path("data/model/crypto_v2/phase4/portfolio_daily.csv"), "eth_buy_and_hold", "timestamp_utc", "equity", status="benchmark", model_filter="hist_gradient_boosting", split_filter="development"),
)


def _finite(value):
    return None if value is None or not np.isfinite(value) else float(value)


def _select_frame(spec: StrategySpec) -> pd.DataFrame:
    if not spec.path.exists():
        raise FileNotFoundError(spec.path)
    frame = pd.read_parquet(spec.path) if spec.path.suffix == ".parquet" else pd.read_csv(spec.path)
    required = {spec.timestamp_column, spec.equity_column}
    if spec.variant:
        required.add("variant")
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("missing columns: " + ", ".join(missing))
    if spec.variant:
        frame = frame[frame["variant"].astype(str) == spec.variant].copy()
    if spec.model_filter is not None:
        if "model_id" not in frame:
            raise ValueError("missing model_id required by strategy contract")
        frame = frame[frame["model_id"].astype(str) == spec.model_filter].copy()
    if spec.split_filter is not None:
        if "split" not in frame:
            raise ValueError("missing split required by strategy contract")
        frame = frame[frame["split"].astype(str) == spec.split_filter].copy()
    if spec.horizon_days is not None:
        if "horizon_days" not in frame:
            raise ValueError("missing horizon_days required by strategy contract")
        frame = frame[pd.to_numeric(frame["horizon_days"], errors="coerce") == spec.horizon_days].copy()
    if spec.top_n is not None:
        if "top_n" not in frame:
            raise ValueError("missing top_n required by strategy contract")
        frame = frame[pd.to_numeric(frame["top_n"], errors="coerce") == spec.top_n].copy()
    if "cost_bps_round_trip" in frame.columns:
        costs = pd.to_numeric(frame["cost_bps_round_trip"], errors="coerce")
        frame = frame[np.isclose(costs, spec.cost_bps, equal_nan=False)].copy()
    if frame.empty:
        raise ValueError(f"no rows for variant={spec.variant!r}, cost_bps={spec.cost_bps:g}")
    frame["timestamp"] = pd.to_datetime(frame[spec.timestamp_column], utc=True, errors="coerce")
    frame["raw_equity"] = pd.to_numeric(frame[spec.equity_column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "raw_equity"])
    frame = frame[np.isfinite(frame["raw_equity"]) & (frame["raw_equity"] > 0)]
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    if len(frame) < 2:
        raise ValueError("fewer than two usable equity observations")
    return frame


def _series(spec: StrategySpec) -> dict:
    frame = _select_frame(spec)
    scale = STARTING_CAPITAL / float(frame.iloc[0]["raw_equity"])
    frame["equity"] = frame["raw_equity"] * scale
    returns = frame["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    years = max((frame.iloc[-1]["timestamp"] - frame.iloc[0]["timestamp"]).total_seconds() / (365.25 * 86400), 0.0)
    ending = float(frame.iloc[-1]["equity"])
    cagr = (ending / STARTING_CAPITAL) ** (1 / years) - 1 if years > 0 else np.nan
    periods_per_year = TRADING_DAYS_PER_YEAR / spec.observation_interval_days
    annual_vol = returns.std(ddof=1) * np.sqrt(periods_per_year) if len(returns) > 1 else np.nan
    sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(periods_per_year) if len(returns) > 1 and returns.std(ddof=1) > 0 else np.nan
    drawdown = frame["equity"] / frame["equity"].cummax() - 1
    turnover = pd.to_numeric(frame.get("turnover"), errors="coerce") if "turnover" in frame else pd.Series(dtype=float)
    costs = pd.to_numeric(frame.get("transaction_cost"), errors="coerce") if "transaction_cost" in frame else pd.Series(dtype=float)
    return {
        "model_id": spec.model_id,
        "label": spec.label,
        "status": spec.status,
        "variant": spec.variant,
        "start_timestamp": frame.iloc[0]["timestamp"].isoformat(),
        "end_timestamp": frame.iloc[-1]["timestamp"].isoformat(),
        "starting_capital": STARTING_CAPITAL,
        "ending_equity": ending,
        "total_return_pct": (ending / STARTING_CAPITAL - 1) * 100,
        "cagr_pct": _finite(cagr * 100),
        "annualized_volatility_pct": _finite(annual_vol * 100),
        "sharpe": _finite(sharpe),
        "max_drawdown_pct": _finite(float(drawdown.min()) * 100),
        "observations": int(len(frame)),
        "total_turnover": _finite(turnover.sum()) if len(turnover) else None,
        "transaction_costs_rebased": _finite(costs.sum() * scale) if len(costs) else None,
        "history": [{"timestamp": row.timestamp.isoformat(), "equity": float(row.equity)} for row in frame.itertuples(index=False)],
    }


def build_payload(specs=STRATEGIES, generated_at=None) -> dict:
    admitted, unavailable = [], []
    for spec in specs:
        try:
            admitted.append(_series(spec))
        except (FileNotFoundError, ValueError, KeyError) as exc:
            unavailable.append({"model_id": spec.model_id, "label": spec.label, "reason": str(exc)})
    starts = [pd.Timestamp(row["start_timestamp"]) for row in admitted]
    ends = [pd.Timestamp(row["end_timestamp"]) for row in admitted]
    return {
        "schema_version": 1,
        "generated_at_utc": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "title": "Crypto model performance comparison",
        "question": "If $100,000 had been invested ten years ago, what would each reconstructable strategy be worth today?",
        "requested_start_timestamp": TEN_YEARS_AGO.isoformat(),
        "starting_capital": STARTING_CAPITAL,
        "common_clock_policy": "The comparison clock begins ten years ago. A strategy starts only at its first scientifically eligible causal observation; no pre-eligibility history is backfilled.",
        "disclosure": "HISTORICAL RECONSTRUCTION — NOT LIVE PERFORMANCE",
        "series": admitted,
        "unavailable_series": unavailable,
        "earliest_admitted_timestamp": min(starts).isoformat() if starts else None,
        "latest_timestamp": max(ends).isoformat() if ends else None,
        "research_safety": {"paper_state_modified": False, "frozen_models_modified": False, "future_holdout_scored": False, "brokerage_orders": False},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = build_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Output: {args.output}")
    print(f"Admitted: {len(payload['series'])}; unavailable: {len(payload['unavailable_series'])}")


if __name__ == "__main__":
    main()
