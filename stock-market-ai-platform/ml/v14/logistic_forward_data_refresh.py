"""Refresh shared market-data layers for the isolated V14 paper candidate.

This module deliberately stops before model inference.  It reuses the existing
quota-aware Tiingo ingestion and Silver/Gold/feature builders, but never calls
the V8 production inference, EOD orchestrator, or comparison refresh.  V14's
LaunchAgent can therefore keep its inputs current without changing another
model's evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = PROJECT_ROOT / "ml"
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

# These helpers own the account-wide Tiingo quota and the existing ingestion
# pipeline.  We intentionally do not import or call run_data_refresh().
from run_v5_data_refresh import (  # noqa: E402
    DEFAULT_HOURLY_REQUEST_LIMIT,
    QuotaTrackingTiingoClient,
    REQUEST_LEDGER_PATH,
    available_request_budget,
    configured_hourly_request_limit,
    propagate_price_layers,
    rebuild_data_layers,
    run_incremental_refresh,
    stale_feature_symbols,
)


STATUS_PATH = PROJECT_ROOT / "data/model/v14/logistic_forward/refresh_status.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_status(payload: dict[str, Any], path: Path = STATUS_PATH) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return payload


def run_v14_data_refresh(
    *,
    max_requests: int | None = None,
    status_path: Path = STATUS_PATH,
) -> dict[str, Any]:
    """Refresh Bronze through features and report whether V14 may collect.

    A partial or quota-blocked refresh is safe: the scheduler records the
    reason and does not run the V14 collector against an uncertain snapshot.
    """
    limit = configured_hourly_request_limit()
    available, used = available_request_budget(limit, path=REQUEST_LEDGER_PATH)
    if max_requests is not None:
        available = min(available, max(0, int(max_requests)))
    base: dict[str, Any] = {
        "checked_at_utc": _utc_now(),
        "feature_backend": os.environ.get("FEATURE_BACKEND", "pandas").strip().lower(),
        "hourly_request_limit": int(limit),
        "requests_used_before_run": int(used),
        "requests_available_before_run": int(available),
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_v10_modified": False,
    }
    if available < 1:
        return _write_status({**base, "status": "QUOTA_WAIT", "ready_for_collection": False}, status_path)

    client = QuotaTrackingTiingoClient(ledger_path=REQUEST_LEDGER_PATH)
    state = run_incremental_refresh(max_requests=available, client=client)
    updated_symbols = list(state.get("updated_symbols", []))
    if updated_symbols:
        propagate_price_layers(updated_symbols)
    result: dict[str, Any] = {**base, "refresh_state": state}
    if not bool(state.get("complete")):
        return _write_status({**result, "status": "BRONZE_PARTIAL", "ready_for_collection": False}, status_path)

    target_timestamp_ms = state.get("target_timestamp_ms")
    stale = stale_feature_symbols(target_timestamp_ms) if target_timestamp_ms is not None else []
    if stale:
        rebuild_data_layers()
        stale = stale_feature_symbols(target_timestamp_ms)
    if stale:
        return _write_status(
            {**result, "status": "FEATURES_STALE", "stale_feature_symbols": sorted(stale), "ready_for_collection": False},
            status_path,
        )
    return _write_status(
        {**result, "status": "FEATURES_CURRENT", "stale_feature_symbols": [], "ready_for_collection": True},
        status_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh V14's isolated paper-forward data layers")
    parser.add_argument("--max-requests", type=int, default=None)
    args = parser.parse_args()
    result = run_v14_data_refresh(max_requests=args.max_requests)
    print("V14 LOGISTIC DATA REFRESH")
    print("=" * 72)
    print(f"Status: {result['status']}")
    print(f"Ready for collection: {'YES' if result['ready_for_collection'] else 'NO'}")
    print(f"Feature backend: {result['feature_backend']}")
    print("V8/V10 modified: NO")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
