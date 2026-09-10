"""Refresh V14 inputs, then collect one isolated paper-forward cycle."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from ml.v14.logistic_forward import run_once


def _default_refresh() -> dict[str, Any]:
    # The existing shared refresh agent owns Tiingo and V8 publication. V14's
    # five-minute job only verifies that its 101 feature inputs are in sync.
    from ml.v14.logistic_forward_data_refresh import check_v14_data_readiness

    return check_v14_data_readiness()


def run_scheduler(
    *,
    refresh_fn: Callable[[], dict[str, Any]] | None = None,
    collector_fn: Callable[..., dict[str, Any]] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    refresh = (refresh_fn or _default_refresh)()
    if not bool(refresh.get("ready_for_collection")):
        return {
            "status": "WAITING_FOR_DATA_REFRESH",
            "collector_invoked": False,
            "refresh": refresh,
            "paper_trading_only": True,
            "brokerage_orders": False,
            "v8_v10_modified": False,
        }
    collector = collector_fn or run_once
    collected = collector(now_utc=now_utc) if now_utc is not None else collector()
    return {
        "status": "COLLECTED",
        "collector_invoked": True,
        "refresh": refresh,
        "collector": collected,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_v10_modified": False,
    }


def main() -> None:
    result = run_scheduler()
    refresh = result["refresh"]
    print("V14 LOGISTIC WALK-FORWARD SCHEDULER")
    print("=" * 72)
    print(f"Status: {result['status']}")
    print(f"Data refresh: {refresh.get('status', 'UNKNOWN')}")
    print(f"Collector invoked: {'YES' if result['collector_invoked'] else 'NO'}")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 modified: NO")


if __name__ == "__main__":
    main()
