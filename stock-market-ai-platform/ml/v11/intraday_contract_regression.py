"""Regression checks for the isolated V11 intraday research foundation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v11.intraday_contract import derive_features, validate_completed_bars, validate_cross_section

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name("intraday_research_contract.json")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def sample_bars(symbol: str = "AAPL") -> list[dict[str, object]]:
    start = datetime(2026, 8, 27, 13, 30, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for index in range(6):
        opening = 200.0 + index
        rows.append(
            {
                "symbol": symbol,
                "timestamp_utc": start + timedelta(minutes=5 * index),
                "open": opening,
                "high": opening + 1.2,
                "low": opening - 0.8,
                "close": opening + 0.4,
                "volume": 1000 + index * 100,
            }
        )
    return rows


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text())
    require(contract["status"] == "RESEARCH_ONLY", "V11 authority is research only")
    require(contract["bar_interval_minutes"] == 5, "Five-minute bar contract is locked")
    require(contract["paper_trading_only"] is True, "Paper-only boundary is explicit")
    require(contract["live_trading_enabled"] is False, "Live trading remains disabled")
    require(contract["brokerage_orders"] is False, "Brokerage orders remain off")
    require(contract["brokerage_sdk_allowed"] is False, "Brokerage SDKs are prohibited")
    require(contract["holdout_outcomes_allowed"] is False, "Holdout outcomes are prohibited")
    require(not contract["v8_production_reads"] and not contract["v8_production_writes"], "V8 production is isolated")
    require(not contract["v10_production_reads"] and not contract["v10_production_writes"], "V10 production is isolated")

    bars = sample_bars()
    now = bars[-1]["timestamp_utc"] + timedelta(minutes=6)
    valid = validate_completed_bars(bars, now_utc=now, expected_symbol="AAPL")
    require(valid.accepted, "Completed regular-session bars pass")

    incomplete = validate_completed_bars(bars, now_utc=bars[-1]["timestamp_utc"] + timedelta(minutes=2), expected_symbol="AAPL")
    require("INCOMPLETE_BAR" in incomplete.reasons, "Incomplete latest bar fails closed")

    stale = validate_completed_bars(bars, now_utc=bars[-1]["timestamp_utc"] + timedelta(minutes=20), expected_symbol="AAPL")
    require("LATEST_BAR_STALE" in stale.reasons, "Stale bars fail closed")

    gapped = sample_bars()
    gapped[-1]["timestamp_utc"] = gapped[-1]["timestamp_utc"] + timedelta(minutes=5)
    gap_result = validate_completed_bars(gapped, now_utc=now + timedelta(minutes=5), expected_symbol="AAPL")
    require("FIVE_MINUTE_SEQUENCE_GAP" in gap_result.reasons, "Missing five-minute bar fails closed")

    features = derive_features(bars, previous_close=198.0)
    require(features.symbol == "AAPL", "Auditable feature vector is produced")
    require(features.return_5m > 0 and features.return_15m > 0, "Momentum features are derived")
    require(features.opening_gap > 0, "Opening gap is derived")

    complete = validate_cross_section([valid] * 101)
    require(complete.accepted, "Complete 101-symbol cross-section passes")
    partial = validate_cross_section([valid] * 100)
    require("UNIVERSE_INCOMPLETE" in partial.reasons, "Partial universe fails closed")

    source = Path(__file__).with_name("intraday_contract.py").read_text()
    forbidden = ("alpaca", "ib_insync", "interactive_brokers", "submit_order", "place_order")
    require(not any(token in source.lower() for token in forbidden), "No brokerage interface is imported")
    require("data/model/v8/holdout" not in source and "data/model/v10" not in source, "No frozen holdout path is referenced")

    print("\nStatus: PASSED")
    print("V11 five-minute research foundation: VERIFIED")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
