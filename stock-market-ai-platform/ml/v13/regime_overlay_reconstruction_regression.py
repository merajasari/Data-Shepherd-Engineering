"""Fail-closed regression for the V13 retrospective reconstruction."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from ml.v13.regime_overlay_contract import load_contract
from ml.v13.regime_overlay_reconstruction import (
    RetrospectivePeriod,
    _canonical_sha,
    integer_allocation,
    reconstruct_periods,
    simulate_period,
    validate_historical_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("regime_overlay_reconstruction.py")


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def period(
    index: int,
    *,
    confirmed: bool,
    volatility: float | None,
    confirmations: dict[str, bool] | None,
    complete: bool = True,
) -> RetrospectivePeriod:
    symbols = tuple(f"S{value:03d}" for value in range(100))
    entry = {symbol: 50.0 + value / 10 for value, symbol in enumerate(symbols)}
    exit_prices = {symbol: price * 1.02 for symbol, price in entry.items()}
    return RetrospectivePeriod(
        decision_session=f"2020-01-{index + 1:02d}",
        entry_session=f"2020-02-{index + 1:02d}",
        exit_session=f"2020-03-{index + 1:02d}",
        decision_index=index,
        cohort_offset=index % 5,
        ranked_symbols=symbols,
        confirmed_negative_2d=confirmed,
        spy_annualized_volatility_20d=volatility,
        regime_input_complete=(not confirmed or volatility is not None),
        confirmations=confirmations,
        market_data_complete=complete,
        entry_prices=entry,
        exit_prices=exit_prices,
    )


def manifest() -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_id": "V11_INTRADAY_HISTORICAL_RESEARCH_V1",
        "status": "COMPLETE_HISTORICAL_RESEARCH_DATASET",
        "published": True,
        "source": "tiingo_iex_historical_5min",
        "start_date": "2017-08-01",
        "end_date": "2026-08-28",
        "bar_interval_minutes": 5,
        "sampling_policy": "OPENING_SIX_COMPLETED_BARS_PLUS_1555_SESSION_CLOSE",
        "bars_retained_per_complete_session": 7,
        "retained_bar_times_eastern": [
            "09:30", "09:35", "09:40", "09:45", "09:50", "09:55", "15:55"
        ],
        "full_session_bars_retained": False,
        "v13_development_only": True,
        "symbol_count": 101,
        "symbols": ["SPY", *[f"S{value:03d}" for value in range(100)]],
        "common_session_count": 100,
        "first_common_session": "2020-10-01",
        "last_common_session": "2026-08-28",
        "symbol_metadata": {},
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    payload["manifest_sha256"] = _canonical_sha(payload)
    return payload


def main() -> None:
    contract = load_contract()
    execution = contract["small_account_execution"]
    prices = {f"S{value:03d}": 50.0 for value in range(100)}
    allocation = integer_allocation(
        equity=5000.0,
        ranked_symbols=tuple(prices),
        entry_prices=prices,
        execution=execution,
    )
    require(bool(allocation), "Small-account allocation is executable")
    require(all(isinstance(value, int) for value in allocation.values()), "Shares are integers")
    require(len(allocation) <= 10, "At most ten positions are allocated")
    require(
        sum(allocation[symbol] * prices[symbol] for symbol in allocation)
        <= 5000.0 * 0.9 + 1e-9,
        "Ninety-percent deployment ceiling is enforced",
    )
    require(
        all(allocation[symbol] * prices[symbol] <= 1000.0 + 1e-9 for symbol in allocation),
        "Twenty-percent position ceiling is enforced",
    )

    outside = period(0, confirmed=False, volatility=0.40, confirmations=None)
    outside_result = simulate_period(
        period=outside, starting_equity=5000.0, contract=contract
    )
    require(outside_result["traded"] is True, "Outside-regime V10 control executes")
    require(
        outside_result["action"] == "EXECUTE_UNCHANGED_V10_CONTROL",
        "Outside-regime action remains unchanged V10",
    )

    confirmations = {symbol: index < 4 for index, symbol in enumerate(outside.ranked_symbols)}
    eligible = period(1, confirmed=True, volatility=0.30, confirmations=confirmations)
    eligible_result = simulate_period(
        period=eligible, starting_equity=5000.0, contract=contract
    )
    require(eligible_result["regime_eligible"] is True, "Locked negative/high-vol regime activates")
    require(
        eligible_result["action"] == "APPLY_V13_INTRADAY_CONFIRMATION",
        "V11 input is limited to entry confirmation",
    )
    require(
        set(eligible_result["selected_symbols"]) <= {symbol for symbol, value in confirmations.items() if value},
        "Unconfirmed symbols are excluded",
    )

    too_few = {symbol: index < 2 for index, symbol in enumerate(outside.ranked_symbols)}
    held = simulate_period(
        period=period(2, confirmed=True, volatility=0.30, confirmations=too_few),
        starting_equity=5000.0,
        contract=contract,
    )
    require(held["traded"] is False, "Insufficient confirmation holds cash")
    require(held["ending_equity"] == 5000.0, "Fail-closed hold preserves cash")

    missing_regime = simulate_period(
        period=period(3, confirmed=True, volatility=None, confirmations=None),
        starting_equity=5000.0,
        contract=contract,
    )
    require(missing_regime["traded"] is False, "Missing regime input holds cash")

    periods = [outside, eligible]
    periods.extend(
        period(
            index,
            confirmed=(index % 3 == 0),
            volatility=0.30,
            confirmations={symbol: True for symbol in outside.ranked_symbols},
        )
        for index in range(4, 10)
    )
    result = reconstruct_periods(periods, contract, source={"test": True})
    require(result["status"] == "V13_RETROSPECTIVE_DEVELOPMENT_RECONSTRUCTION", "Retrospective result is explicit")
    require(result["ten_calendar_years_available"] is False, "Unavailable pre-August-2017 history is disclosed")
    require(result["fresh_evidence_included"] is False, "Fresh evidence is excluded")
    require(result["candidate_frozen"] is False, "Reconstruction cannot freeze V13")
    require(result["brokerage_orders"] is False, "Reconstruction has no brokerage authority")
    require(len(result["history"]) > 1, "Chart-ready equity history is produced")
    require(bool(result["reconstruction_sha256"]), "Reconstruction has a SHA-256 identity")

    valid_manifest = manifest()
    validate_historical_manifest(valid_manifest)
    require(True, "Complete pre-boundary manifest validates")
    tampered = deepcopy(valid_manifest)
    tampered["symbol_count"] = 100
    try:
        validate_historical_manifest(tampered)
    except ValueError:
        require(True, "Tampered manifest fails closed")
    else:
        raise AssertionError("Tampered manifest fails closed")
    fresh = manifest()
    fresh["last_common_session"] = "2026-09-01"
    body = dict(fresh)
    body.pop("manifest_sha256", None)
    fresh["manifest_sha256"] = _canonical_sha(body)
    try:
        validate_historical_manifest(fresh)
    except RuntimeError:
        require(True, "Fresh-boundary data fails retrospective validation")
    else:
        raise AssertionError("Fresh-boundary data fails retrospective validation")

    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        "import alpaca",
        "from alpaca",
        "import robin_stocks",
        "from robin_stocks",
        "import ib_insync",
    ):
        require(forbidden not in source, f"Brokerage SDK absent: {forbidden}")
    require("regime_overlay_journal" not in source, "Fresh journal is not referenced")
    require(
        "regime_overlay_manual_approval" not in source,
        "Manual approval implementation is not imported",
    )
    require("activation_lease.json" not in source, "Activation lease path is not read")

    print("Status: PASSED")
    print("V13 retrospective reconstruction: VERIFIED DEVELOPMENT ONLY")
    print("Ten exact calendar years: UNAVAILABLE — Tiingo IEX begins August 2017")
    print("Fresh evidence read/written: NO")
    print("Candidate freeze authority: NONE")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12/V13 production evidence modified: NO")


if __name__ == "__main__":
    main()
