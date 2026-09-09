"""Deterministic regression checks for the V8 forward dashboard service.

Uses synthetic completed cohorts only. It never reads or writes the production
holdout journal, status, frozen artifacts, market data, or brokerage state.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from webapp.services import v8_holdout_service as service


def _event(index: int, net: float, spy: float):
    return {
        "event_type": "EXIT",
        "decision_timestamp_utc": f"2026-09-{index + 1:02d}T00:00:00+00:00",
        "entry_timestamp_utc": f"2026-09-{index + 2:02d}T00:00:00+00:00",
        "exit_timestamp_utc": f"2026-10-{index + 1:02d}T00:00:00+00:00",
        "cohort_offset": index % 5,
        "net_portfolio_return": net,
        "spy_return": spy,
        "net_relative_return": net - spy,
        "brokerage_orders": False,
    }


def _assert_close(actual, expected, tolerance=1e-12):
    if actual is None or not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance):
        raise AssertionError(f"expected {expected}, found {actual}")


def _entry():
    symbols = [f"S{i}" for i in range(10)]
    return {
        "event_type": "ENTRY",
        "decision_timestamp_utc": "2026-09-01T00:00:00+00:00",
        "entry_timestamp_utc": "2026-09-02T00:00:00+00:00",
        "cohort_offset": 0,
        "symbols": symbols,
        "entry_prices": {symbol: 100.0 for symbol in symbols},
        "spy_entry_open": 100.0,
        "modeled_cost_rate": 0.001,
        "brokerage_orders": False,
    }


def _marks():
    timestamp = service._as_utc_timestamp("2026-09-03T15:00:00+00:00")
    rows = {
        f"S{i}": {
            "price": 110.0,
            "timestamp": timestamp,
            "timestamp_utc": timestamp.isoformat(),
            "source": "SYNTHETIC_TEST_CACHE",
        }
        for i in range(10)
    }
    rows["SPY"] = {
        "price": 102.0,
        "timestamp": timestamp,
        "timestamp_utc": timestamp.isoformat(),
        "source": "SYNTHETIC_TEST_CACHE",
    }
    return rows


def main():
    failures = []

    empty = service._performance_metrics([], [])
    if empty["evidence_status"] != "NO_COMPLETED_COHORTS":
        failures.append("zero-cohort evidence state is incorrect")
    if any(
        empty[key] is not None
        for key in (
            "strategy_total_return",
            "spy_total_return",
            "total_relative_return",
            "max_drawdown",
            "cohort_return_volatility",
            "diagnostic_annualized_sharpe",
        )
    ):
        failures.append("zero-cohort metrics must remain unavailable")

    one_exit = [_event(0, 0.01, 0.004)]
    one_curve = service._curve(one_exit)
    one = service._performance_metrics(one_exit, one_curve)
    if one["evidence_status"] != "INSUFFICIENT_EVIDENCE":
        failures.append("one completed cohort must be insufficient evidence")

    # Open positions must move the read-only current equity before an EXIT is
    # eligible, without being counted as completed-cohort evidence.
    entry = _entry()
    marked = service._mark_to_market([entry], [], _marks())
    try:
        _assert_close(marked["current_equity"], 109890.0)
        _assert_close(marked["current_return"], 0.0989)
        _assert_close(marked["current_spy_return"], 0.02)
        _assert_close(marked["current_excess_return"], 0.0789)
    except AssertionError as exc:
        failures.append(f"open-cohort mark-to-market failed: {exc}")
    if marked["equity_basis"] != "LIVE_MARK_TO_MARKET":
        failures.append("fully priced open cohort did not produce live mark-to-market equity")
    if marked["open_cohorts"] != 1 or marked["priced_open_cohorts"] != 1:
        failures.append("open-cohort valuation counts are incorrect")
    if marked["realized_completed_return"] != 0.0:
        failures.append("unrealized mark leaked into completed-cohort return")

    original_live_path = service.LIVE_QUOTES_PATH
    original_rolling_paths = service.ROLLING_QUOTES_PATHS
    try:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_path = root / "latest_quotes.json"
            rolling_path = root / "rolling.json"
            live_path.write_text(json.dumps({
                "updated_at": "2026-09-03T15:00:00+00:00",
                "quotes": {
                    "S0": {"reference_price": 110.0, "timestamp": "2026-09-03T15:00:00+00:00"},
                },
            }), encoding="utf-8")
            rolling_path.write_text(json.dumps({
                "updated_at": "2026-09-03T14:55:00+00:00",
                "series": {
                    "S1": [{"price": 109.0, "t": "2026-09-03T14:55:00+00:00"}],
                    "IGNORED": [{"price": 1.0, "t": "2026-09-03T14:55:00+00:00"}],
                },
            }), encoding="utf-8")
            service.LIVE_QUOTES_PATH = live_path
            service.ROLLING_QUOTES_PATHS = (rolling_path,)
            loaded_marks = service._latest_market_marks({"S0", "S1"})
            if set(loaded_marks) != {"S0", "S1"}:
                failures.append("live/rolling mark-cache merge or symbol filtering failed")
            if loaded_marks.get("S0", {}).get("source") != "TIINGO_IEX_LIVE_CACHE":
                failures.append("live quote cache was not preferred for an available symbol")
            if loaded_marks.get("S1", {}).get("source") != "TIINGO_IEX_ROLLING_CACHE":
                failures.append("rolling quote fallback did not fill missing live coverage")
    finally:
        service.LIVE_QUOTES_PATH = original_live_path
        service.ROLLING_QUOTES_PATHS = original_rolling_paths

    incomplete_marks = _marks()
    incomplete_marks.pop("S9")
    incomplete = service._mark_to_market([entry], [], incomplete_marks)
    if incomplete["mark_to_market_available"]:
        failures.append("incomplete price coverage must fail closed for current V8 equity")
    if incomplete["equity_basis"] != "BASELINE_PRICE_COVERAGE_PENDING":
        failures.append("incomplete price coverage state is incorrect")
    if "S9" not in incomplete["missing_mark_symbols"]:
        failures.append("missing mark symbol was not exposed diagnostically")

    completed = service._mark_to_market([entry], one_exit, _marks())
    if completed["open_cohorts"] != 0 or completed["equity_basis"] != "COMPLETED_COHORTS_ONLY":
        failures.append("exited entry was incorrectly treated as an open cohort")
    try:
        _assert_close(completed["current_equity"], 101000.0)
    except AssertionError as exc:
        failures.append(f"completed-cohort equity fallback failed: {exc}")

    zero_then_gain = [_event(0, 0.0, 0.0), _event(1, 0.02, 0.01)]
    zero_then_gain[1]["cohort_offset"] = 1
    zero_curve = service._curve(zero_then_gain)
    try:
        _assert_close(zero_curve[-1]["strategy_normalized"], 101000.0)
    except AssertionError as exc:
        failures.append(f"zero-return started cohort was omitted from equity: {exc}")

    twenty_exits = [
        _event(i, 0.012 if i % 2 == 0 else -0.004, 0.005 if i % 3 else -0.002)
        for i in range(20)
    ]
    twenty_curve = service._curve(twenty_exits)
    twenty = service._performance_metrics(twenty_exits, twenty_curve)
    if twenty["evidence_status"] != "EARLY_EVIDENCE":
        failures.append("20 completed cohorts must enter early-evidence state")
    if twenty["completed_cohorts"] != 20:
        failures.append("completed-cohort count mismatch")
    if twenty["cohort_return_volatility"] is None or twenty["cohort_return_volatility"] <= 0:
        failures.append("cohort volatility was not calculated")
    if twenty["diagnostic_annualized_sharpe"] is None:
        failures.append("diagnostic Sharpe was not calculated")
    expected_hit_rate = sum(event["net_relative_return"] > 0 for event in twenty_exits) / 20
    try:
        _assert_close(twenty["net_relative_hit_rate"], expected_hit_rate)
        _assert_close(
            twenty["strategy_total_return"],
            twenty_curve[-1]["strategy_normalized"] / 100000.0 - 1.0,
        )
        _assert_close(
            twenty["spy_total_return"],
            twenty_curve[-1]["spy_normalized"] / 100000.0 - 1.0,
        )
    except AssertionError as exc:
        failures.append(str(exc))

    drawdown_curve = [
        {"strategy_normalized": 110000.0, "spy_normalized": 101000.0},
        {"strategy_normalized": 99000.0, "spy_normalized": 100000.0},
    ]
    drawdown = service._performance_metrics(twenty_exits, drawdown_curve)
    try:
        _assert_close(drawdown["max_drawdown"], -0.10)
    except AssertionError as exc:
        failures.append(f"max-drawdown calculation failed: {exc}")

    sixty_exits = [
        _event(i, 0.008 if i % 2 == 0 else -0.003, 0.004 if i % 4 else -0.001)
        for i in range(60)
    ]
    sixty = service._performance_metrics(sixty_exits, service._curve(sixty_exits))
    if sixty["evidence_status"] != "EVIDENCE_ACCUMULATING":
        failures.append("60 completed cohorts must enter accumulating-evidence state")

    # Guard the web request path against the memory regression that caused
    # Gunicorn workers to be killed. This helper must remain lightweight.
    lightweight_rankings = service._latest_v8_rankings()
    if lightweight_rankings != {"timestamp_utc": None, "rows": []}:
        failures.append("web ranking helper reintroduced request-time historical data")

    # All API metrics and current valuations must remain JSON serializable.
    try:
        json.dumps(twenty, allow_nan=False)
        json.dumps(marked, allow_nan=False)
    except (TypeError, ValueError) as exc:
        failures.append(f"dashboard metrics are not strict JSON: {exc}")

    print("V8 FORWARD DASHBOARD REGRESSION")
    print("=" * 88)
    print(f"Zero cohorts: {empty['evidence_status']}")
    print(f"One cohort: {one['evidence_status']}")
    print(f"20 cohorts: {twenty['evidence_status']}")
    print(f"60 cohorts: {sixty['evidence_status']}")
    print(f"20-cohort hit rate: {twenty['net_relative_hit_rate']:.3f}")
    print(f"20-cohort volatility: {twenty['cohort_return_volatility']:.6f}")
    print(f"Open-cohort current equity: ${marked['current_equity']:,.2f}")
    print(f"Request-time historical Parquet load: DISABLED")
    print("Production holdout evidence touched: NO")
    print("Brokerage orders: OFF")

    if failures:
        print("Status: FAILED")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)

    print("Status: PASSED")


if __name__ == "__main__":
    main()
