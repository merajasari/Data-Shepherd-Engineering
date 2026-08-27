"""V11 intraday development feature and ranking pipeline.

This is an auditable research baseline, not a frozen strategy or return
forecast. It reads only the isolated V11 snapshot plus completed Bronze EOD
prices, and has no brokerage or V8/V10 authority.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from ml.v11.intraday_contract import IntradayFeatures, derive_features

ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))
from v5_symbols import V5_BENCHMARK_SYMBOL, get_v5_data_symbols, get_v5_symbols  # noqa: E402

SNAPSHOT_PATH = ROOT / "data/research/v11/intraday/latest_complete_snapshot.json"
OUTPUT_PATH = ROOT / "data/research/v11/intraday/latest_development_rankings.json"
BASELINE_ID = "V11_INTRADAY_5MIN_EQUAL_WEIGHT_DIAGNOSTIC_V1"
FEATURE_NAMES = (
    "return_5m",
    "return_15m",
    "vwap_distance",
    "volume_acceleration",
    "realized_volatility_30m",
    "opening_gap",
)
BASELINE_WEIGHTS = {
    "return_5m": 1.0,
    "return_15m": 1.0,
    "vwap_distance": 1.0,
    "volume_acceleration": 1.0,
    "realized_volatility_30m": -0.25,
    "opening_gap": 1.0,
}


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _atomic_json_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _parse_timestamp(row: Mapping[str, str]) -> datetime | None:
    value = row.get("timestamp_utc")
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    value = row.get("timestamp")
    if value:
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    return None


def load_previous_closes_from_bronze(
    *,
    session_date: str,
    symbols: Sequence[str] | None = None,
) -> dict[str, float]:
    requested = tuple(symbols or get_v5_data_symbols())
    boundary = datetime.fromisoformat(session_date).date()
    closes: dict[str, float] = {}
    for symbol in requested:
        path = ROOT / f"data/bronze/stocks/{symbol}/{symbol}_prices.csv"
        if not path.exists():
            continue
        best: tuple[datetime, float] | None = None
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                stamp = _parse_timestamp(row)
                if stamp is None or stamp.date() >= boundary:
                    continue
                try:
                    close = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                if close <= 0 or not math.isfinite(close):
                    continue
                if best is None or stamp > best[0]:
                    best = (stamp, close)
        if best is not None:
            closes[symbol] = best[1]
    return closes


def _zscore(values: Mapping[str, float]) -> dict[str, float]:
    ordered = list(values.values())
    center = statistics.fmean(ordered)
    spread = statistics.pstdev(ordered)
    if spread <= 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: (value - center) / spread for symbol, value in values.items()}


def build_development_rankings(
    snapshot: Mapping[str, object],
    previous_closes: Mapping[str, float],
) -> dict[str, object]:
    reasons: list[str] = []
    expected_symbols = tuple(get_v5_data_symbols())
    candidates = tuple(get_v5_symbols())
    series = snapshot.get("series")
    if snapshot.get("contract_id") != "V11_INTRADAY_5MIN_RESEARCH_V1":
        reasons.append("SNAPSHOT_CONTRACT_MISMATCH")
    if snapshot.get("status") != "COMPLETE_RESEARCH_SNAPSHOT":
        reasons.append("SNAPSHOT_NOT_COMPLETE")
    if snapshot.get("symbol_count") != 101:
        reasons.append("SNAPSHOT_UNIVERSE_INCOMPLETE")
    if not isinstance(series, dict) or set(series) != set(expected_symbols):
        reasons.append("SNAPSHOT_SYMBOLS_MISMATCH")
        series = {}
    if snapshot.get("series_sha256") != _canonical_sha(series):
        reasons.append("SNAPSHOT_SHA_MISMATCH")
    missing_closes = sorted(set(expected_symbols) - set(previous_closes))
    if missing_closes:
        reasons.append("PREVIOUS_CLOSES_INCOMPLETE")
    if reasons:
        raise ValueError(",".join(reasons))

    features: dict[str, IntradayFeatures] = {}
    for symbol in expected_symbols:
        features[symbol] = derive_features(
            series[symbol],
            previous_close=float(previous_closes[symbol]),
        )

    benchmark = features[V5_BENCHMARK_SYMBOL]
    relative: dict[str, dict[str, float]] = {}
    for symbol in candidates:
        values = features[symbol]
        relative[symbol] = {
            "return_5m": values.return_5m - benchmark.return_5m,
            "return_15m": values.return_15m - benchmark.return_15m,
            "vwap_distance": values.vwap_distance - benchmark.vwap_distance,
            "volume_acceleration": values.volume_acceleration - benchmark.volume_acceleration,
            "realized_volatility_30m": values.realized_volatility_30m,
            "opening_gap": values.opening_gap - benchmark.opening_gap,
        }

    standardized = {
        name: _zscore({symbol: relative[symbol][name] for symbol in candidates})
        for name in FEATURE_NAMES
    }
    scores = {
        symbol: statistics.fmean(
            standardized[name][symbol] * BASELINE_WEIGHTS[name]
            for name in FEATURE_NAMES
        )
        for symbol in candidates
    }
    ordered = sorted(candidates, key=lambda symbol: (-scores[symbol], symbol))
    rankings = []
    for rank, symbol in enumerate(ordered, start=1):
        rankings.append(
            {
                "rank": rank,
                "symbol": symbol,
                "score": scores[symbol],
                "top_10": rank <= 10,
                "relative_features": relative[symbol],
                "standardized_features": {
                    name: standardized[name][symbol] for name in FEATURE_NAMES
                },
            }
        )

    payload: dict[str, object] = {
        "baseline_id": BASELINE_ID,
        "status": "DEVELOPMENT_DIAGNOSTIC_ONLY",
        "model_frozen": False,
        "return_forecast": False,
        "source_snapshot_sha256": snapshot["series_sha256"],
        "completed_bar_utc": snapshot["completed_bar_utc"],
        "session_date": snapshot["session_date"],
        "benchmark": V5_BENCHMARK_SYMBOL,
        "candidate_count": len(candidates),
        "feature_names": list(FEATURE_NAMES),
        "baseline_weights": BASELINE_WEIGHTS,
        "rankings": rankings,
        "top_10": [row["symbol"] for row in rankings[:10]],
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    payload["ranking_sha256"] = _canonical_sha(payload)
    return payload


def run_pipeline(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, object]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    previous_closes = load_previous_closes_from_bronze(
        session_date=str(snapshot["session_date"])
    )
    payload = build_development_rankings(snapshot, previous_closes)
    _atomic_json_write(output_path, payload)
    return payload


def main() -> None:
    print("V11 INTRADAY DEVELOPMENT FEATURE + RANKING PIPELINE")
    print("=" * 80)
    try:
        payload = run_pipeline()
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Ranking published: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print("Status: DEVELOPMENT_RANKING_PUBLISHED")
    print(f"Completed bar: {payload['completed_bar_utc']}")
    print(f"Candidates ranked: {payload['candidate_count']}")
    print(f"Top 10: {', '.join(payload['top_10'])}")
    print(f"Ranking SHA-256: {payload['ranking_sha256']}")
    print("Model frozen: NO")
    print("Return forecast: NO")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")


if __name__ == "__main__":
    main()
