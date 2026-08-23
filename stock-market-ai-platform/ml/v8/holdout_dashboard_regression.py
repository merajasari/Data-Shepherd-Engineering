"""Deterministic regression checks for the V8 forward dashboard service.

Uses synthetic completed cohorts only. It never reads or writes the production
holdout journal, status, frozen artifacts, market data, or brokerage state.
"""
from __future__ import annotations

import json
import math

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

    # All API metrics must remain JSON serializable.
    try:
        json.dumps(twenty, allow_nan=False)
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
