"""Generate current frozen V8 cross-sectional rankings without fitting or tuning.

The runner verifies the exact Phase-7 freeze, reads the selected production
feature backend, ranks the frozen 100-stock universe with the registered
DISTANCE_ONLY residual signal, and atomically publishes the site's current V8
Top-10 artifact. It never writes holdout evidence or places brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.v8.holdout_runner import (
    EXPECTED_SHA,
    _load_market,
    _rank_for_date,
    _verify_freeze,
)

OUTPUT_PATH = PROJECT_ROOT / "data/live/v8_latest_rankings.json"


def build_v8_rankings() -> dict:
    spec = _verify_freeze()
    symbols, frames, _, _ = _load_market()
    latest_by_symbol = {
        symbol: frame.index[frame["close"].notna()].max()
        for symbol, frame in frames.items()
    }
    latest_sessions = set(latest_by_symbol.values())
    if len(latest_sessions) != 1:
        newest = max(latest_sessions)
        lagging = sorted(
            symbol
            for symbol, timestamp in latest_by_symbol.items()
            if timestamp < newest
        )
        raise RuntimeError(
            "V8 production inference failed closed because feature sessions are "
            f"not aligned. newest={newest.isoformat()} lagging={', '.join(lagging)}"
        )

    decision_date = latest_sessions.pop()
    ranking = _rank_for_date(decision_date, symbols, frames)
    if len(ranking) != 100:
        raise RuntimeError(
            f"V8 production inference requires 100 rankable stocks; found {len(ranking)}"
        )

    ranking = ranking.reset_index(drop=True)
    denominator = max(1, len(ranking) - 1)
    rows = []
    for index, row in ranking.iterrows():
        symbol = str(row["symbol"])
        rank = index + 1
        rows.append(
            {
                "symbol": symbol,
                "rank": rank,
                "rank_percentile": float((len(ranking) - rank) / denominator),
                "signal_score": float(row["orthogonal_signal"]),
                "raw_distance_from_low_20d": float(row["raw"]),
                "volatility_20d": float(row["volatility_20d"]),
                "beta_60": float(row["beta_60"]),
                "selected_top10": rank <= 10,
                "target_weight": 0.10 if rank <= 10 else 0.0,
                "close": float(frames[symbol].loc[decision_date, "close"]),
            }
        )

    return {
        "research_version": "v8",
        "artifact_type": "production_cross_sectional_ranking",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_date_utc": decision_date.isoformat(),
        "candidate_id": spec["candidate_id"],
        "frozen_sha256": EXPECTED_SHA,
        "signal_id": "DISTANCE_ONLY",
        "signal_description": (
            "distance_from_low_20d residualized cross-sectionally against "
            "volatility_20d and beta_60"
        ),
        "candidate_count": len(rows),
        "feature_count": 3,
        "benchmark_symbol": "SPY",
        "benchmark_is_investable": False,
        "top_n": 10,
        "holding_sessions": 5,
        "entry": "next trading-session open",
        "cost_bps_per_dollar_traded": 10,
        "records_holdout_evidence": False,
        "refits_or_tunes_model": False,
        "brokerage_orders": False,
        "rankings": rows,
    }


def write_v8_rankings(payload: dict, output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    temp.replace(output_path)
    return output_path


def run_v8_inference(output_path: Path = OUTPUT_PATH) -> dict:
    payload = build_v8_rankings()
    write_v8_rankings(payload, output_path)
    print("V8 PRODUCTION INFERENCE")
    print(f"Decision date: {payload['decision_date_utc']}")
    print(f"Candidates ranked: {payload['candidate_count']}")
    print("Top 10: " + ", ".join(row["symbol"] for row in payload["rankings"][:10]))
    print(f"Frozen SHA: {payload['frozen_sha256']}")
    print(f"Output: {output_path}")
    print("No tuning. No holdout evidence. No brokerage orders.")
    return payload


def main():
    run_v8_inference()


if __name__ == "__main__":
    main()
