"""Regression checks for V11 intraday feature and ranking publication."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_ranking import build_development_rankings, run_pipeline


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def universe() -> list[str]:
    from ml.v11.intraday_ranking import get_v5_data_symbols
    return get_v5_data_symbols()


def snapshot() -> dict[str, object]:
    from ml.v11.intraday_ranking import _canonical_sha
    start = datetime(2026, 8, 27, 13, 30, tzinfo=timezone.utc)
    series = {}
    for symbol_index, symbol in enumerate(universe()):
        rows = []
        drift = symbol_index / 100000.0
        for index in range(6):
            opening = 100.0 + symbol_index / 10.0 + index * (0.1 + drift)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp_utc": (start + timedelta(minutes=5 * index)).isoformat(),
                    "open": opening,
                    "high": opening + 0.5,
                    "low": opening - 0.5,
                    "close": opening + 0.2 + drift,
                    "volume": 1000 + symbol_index * 10 + index * (10 + symbol_index),
                }
            )
        series[symbol] = rows
    return {
        "contract_id": "V11_INTRADAY_5MIN_RESEARCH_V1",
        "status": "COMPLETE_RESEARCH_SNAPSHOT",
        "symbol_count": 101,
        "session_date": "2026-08-27",
        "completed_bar_utc": series["SPY"][-1]["timestamp_utc"],
        "series_sha256": _canonical_sha(series),
        "series": series,
    }


def main() -> None:
    source = snapshot()
    closes = {symbol: 99.0 + index / 10.0 for index, symbol in enumerate(universe())}
    first = build_development_rankings(source, closes)
    second = build_development_rankings(source, closes)
    require(first["ranking_sha256"] == second["ranking_sha256"], "Ranking is deterministic")
    require(first["candidate_count"] == 100, "Exactly 100 candidate stocks are ranked")
    require(len(first["rankings"]) == 100, "Ranking contains every candidate")
    require(len(first["top_10"]) == 10, "Exactly 10 diagnostic leaders are selected")
    require("SPY" not in first["top_10"], "SPY remains benchmark-only")
    require(first["benchmark"] == "SPY", "SPY is the declared benchmark")
    require(first["model_frozen"] is False, "Development baseline is not mislabeled frozen")
    require(first["return_forecast"] is False, "Scores are not labeled return forecasts")
    require(first["paper_trading_only"] is True, "Ranking remains paper only")
    require(first["brokerage_orders"] is False, "Ranking has no brokerage authority")
    require(len(first["ranking_sha256"]) == 64, "Ranking has a SHA-256 identity")
    require(
        all(set(row["relative_features"]) == set(first["feature_names"]) for row in first["rankings"]),
        "Every candidate has the complete registered feature vector",
    )

    tampered = json.loads(json.dumps(source))
    tampered["series"]["AAPL"][0]["close"] += 1.0
    try:
        build_development_rankings(tampered, closes)
    except ValueError as exc:
        require("SNAPSHOT_SHA_MISMATCH" in str(exc), "Tampered snapshot fails closed")
    else:
        raise AssertionError("Tampered snapshot was accepted")

    incomplete = dict(closes)
    incomplete.pop("AAPL")
    try:
        build_development_rankings(source, incomplete)
    except ValueError as exc:
        require("PREVIOUS_CLOSES_INCOMPLETE" in str(exc), "Missing prior close fails closed")
    else:
        raise AssertionError("Incomplete prior closes were accepted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        snapshot_path = root / "snapshot.json"
        output_path = root / "rankings.json"
        snapshot_path.write_text(json.dumps(source))
        import ml.v11.intraday_ranking as module
        original = module.load_previous_closes_from_bronze
        module.load_previous_closes_from_bronze = lambda **_: closes
        try:
            published = run_pipeline(snapshot_path=snapshot_path, output_path=output_path)
        finally:
            module.load_previous_closes_from_bronze = original
        require(output_path.exists(), "Development ranking is atomically published")
        require(json.loads(output_path.read_text())["ranking_sha256"] == published["ranking_sha256"], "Published ranking identity is preserved")

    module_source = Path(__file__).with_name("intraday_ranking.py").read_text()
    forbidden = ("submit_order", "place_order", "alpaca", "ib_insync")
    require(not any(value in module_source.lower() for value in forbidden), "Ranking imports no brokerage interface")
    require("data/model/v8/holdout" not in module_source and "data/model/v10" not in module_source, "Ranking references no holdout path")

    print("\nStatus: PASSED")
    print("V11 feature + development ranking: VERIFIED")
    print("Model frozen: NO")
    print("Return forecast: NO")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
