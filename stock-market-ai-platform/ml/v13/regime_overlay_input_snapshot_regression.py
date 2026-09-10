"""Regression checks for the in-memory V13 signed input builder."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.v13.regime_overlay_input_snapshot import (
    _require_contract,
    build_signed_input_bundle,
)
from ml.v13.regime_overlay_observation import canonical_sha256


SOURCE = Path(__file__).with_name("regime_overlay_input_snapshot.py")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def raw_inputs() -> dict[str, object]:
    symbols = [f"S{index:03d}" for index in range(100)]
    universe = symbols + ["SPY"]
    bars_by_symbol: dict[str, list[dict[str, object]]] = {}
    previous: dict[str, float] = {}
    prices: dict[str, float] = {}
    spreads: dict[str, float] = {}
    start = datetime(2026, 9, 3, 13, 30, tzinfo=timezone.utc)
    for index, symbol in enumerate(universe):
        base = 100.0 if symbol == "SPY" else 50.0 + index / 100.0
        previous[symbol] = base
        closes = [base] * 6
        volumes = [100.0] * 6
        if symbol != "SPY" and index < 4:
            closes = [base * (1.0 + step / 1000.0) for step in range(6)]
            volumes = [100.0, 100.0, 100.0, 200.0, 200.0, 200.0]
        elif symbol != "SPY":
            closes = [base * (1.0 - step / 2000.0) for step in range(6)]
            volumes = [200.0, 200.0, 200.0, 100.0, 100.0, 100.0]
        rows: list[dict[str, object]] = []
        prior = base
        for offset, (close, volume) in enumerate(zip(closes, volumes)):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp_utc": (start + timedelta(minutes=5 * offset)).isoformat(),
                    "open": prior,
                    "high": max(prior, close) + 0.01,
                    "low": min(prior, close) - 0.01,
                    "close": close,
                    "volume": volume,
                }
            )
            prior = close
        bars_by_symbol[symbol] = rows
        if symbol != "SPY":
            prices[symbol] = closes[-1]
            spreads[symbol] = 10.0
    return {
        "session_date": "2026-09-03",
        "decision_timestamp_utc": "2026-09-03T14:00:00+00:00",
        "collected_at_utc": "2026-09-03T14:00:05+00:00",
        "ranked_symbols": symbols,
        "bars_by_symbol": bars_by_symbol,
        "previous_closes": previous,
        "entry_prices": prices,
        "spreads_bps": spreads,
        "v10_negative_flags": [True, True],
        "spy_daily_closes": [100.0 if index % 2 == 0 else 102.0 for index in range(21)],
    }


def main() -> None:
    contract_sha = _require_contract()
    require(len(contract_sha) == 64, "Input snapshot contract identity is locked")
    inputs = raw_inputs()
    bundle = build_signed_input_bundle(**inputs)
    ranking = dict(bundle.ranking_snapshot)
    ranking_sha = ranking.pop("ranking_sha256")
    require(ranking_sha == canonical_sha256(ranking), "V10 ranking snapshot is canonically signed")
    intraday = dict(bundle.intraday_snapshot)
    intraday_sha = intraday.pop("source_snapshot_sha256")
    require(intraday_sha == canonical_sha256(intraday), "Intraday snapshot is canonically signed")
    regime = dict(bundle.regime_snapshot)
    regime_sha = regime.pop("source_regime_sha256")
    require(regime_sha == canonical_sha256(regime), "Regime snapshot is canonically signed")
    require(bundle.intraday_snapshot["symbol_count"] == 101, "Exact 101-symbol cross-section is preserved")
    require(bundle.intraday_snapshot["completed_bar_utc"] == "2026-09-03T13:55:00+00:00", "Only the 09:55 completed bar is used at 10:00 Eastern")
    require(bundle.market_data_requests == 0 and bundle.file_writes == 0, "Builder performs no market request or file write")
    require(bundle.brokerage_orders is False, "Builder has no brokerage authority")

    missing = deepcopy(inputs)
    missing["bars_by_symbol"].pop("S099")
    try:
        build_signed_input_bundle(**missing)
    except ValueError:
        require(True, "Incomplete cross-section fails closed")
    else:
        raise AssertionError("Incomplete cross-section fails closed")

    gap = deepcopy(inputs)
    gap["bars_by_symbol"]["S000"][5]["timestamp_utc"] = "2026-09-03T14:00:00+00:00"
    try:
        build_signed_input_bundle(**gap)
    except ValueError:
        require(True, "Gapped or incomplete bars fail closed")
    else:
        raise AssertionError("Gapped or incomplete bars fail closed")

    source = SOURCE.read_text(encoding="utf-8").lower()
    for prohibited in ("requests.", "httpx", "urllib", "socket", "import alpaca", "robin_stocks", "ib_insync"):
        require(prohibited not in source, f"Input builder excludes {prohibited}")
    require(".write" not in source and "open(" not in source, "Input builder exposes no file-writing surface")

    print("Status: PASSED")
    print("V13 caller-supplied raw inputs -> signed snapshots: VERIFIED IN MEMORY")
    print("Market data requested: NO")
    print("Files written: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
