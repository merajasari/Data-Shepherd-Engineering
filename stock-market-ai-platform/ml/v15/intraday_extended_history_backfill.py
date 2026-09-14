"""Isolated V15 extended-history acquisition; never rewrites V11 evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Mapping

from ml.v11.intraday_backfill import TiingoHistoricalIntradayClient, run_backfill
from ml.v15.intraday_logistic import canonical_sha256


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = Path(__file__).with_name(
    "intraday_extended_history_contract.json"
)
OUTPUT_ROOT = ROOT / "data/research/v15/extended_intraday_backfills"
V11_LATEST_MANIFEST = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
EXPECTED_CONTRACT_SHA256 = (
    "e157e37717e0443348bbbde9fc8306acec185316896560c1958c913998d41485"
)


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if canonical_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("V15_EXTENDED_HISTORY_CONTRACT_SHA_MISMATCH")
    boundary = contract.get("boundary", {})
    storage = contract.get("storage", {})
    data = contract.get("data", {})
    purpose = contract.get("purpose", {})
    authority = contract.get("authority", {})
    if boundary.get("start_date") != "2022-01-03":
        raise ValueError("V15_EXTENDED_HISTORY_START_BOUNDARY_INVALID")
    if boundary.get("end_date") != "2025-06-17":
        raise ValueError("V15_EXTENDED_HISTORY_END_BOUNDARY_INVALID")
    if boundary.get("overlaps_v15_v1_through_v6_evaluation_window") is not False:
        raise ValueError("V15_EXTENDED_HISTORY_OVERLAP_INVALID")
    if storage.get("v11_latest_manifest_must_remain_byte_identical") is not True:
        raise ValueError("V15_EXTENDED_HISTORY_V11_PRESERVATION_MISSING")
    if int(data.get("required_universe_symbols", 0)) != 101:
        raise ValueError("V15_EXTENDED_HISTORY_UNIVERSE_INVALID")
    if int(data.get("minimum_common_sessions", 0)) < 750:
        raise ValueError("V15_EXTENDED_HISTORY_MINIMUM_TOO_SMALL")
    if purpose.get("model_selection_allowed") is not False:
        raise ValueError("V15_EXTENDED_HISTORY_SELECTION_BOUNDARY_INVALID")
    required_false = (
        "model_execution_allowed",
        "model_frozen",
        "paper_forward_allowed",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
        "scheduler_installation_allowed",
        "modify_v8",
        "modify_v10",
        "modify_v11",
        "modify_v13",
        "modify_v14",
    )
    if any(authority.get(name) is not False for name in required_false):
        raise ValueError("V15_EXTENDED_HISTORY_AUTHORITY_INVALID")
    return contract


def _file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def collect(
    *,
    client: object | None = None,
    chunk_days: int = 120,
    workers: int = 8,
) -> dict[str, object]:
    contract = load_contract()
    boundary = contract["boundary"]
    before = _file_sha256(V11_LATEST_MANIFEST)
    result = run_backfill(
        start_date=date.fromisoformat(str(boundary["start_date"])),
        end_date=date.fromisoformat(str(boundary["end_date"])),
        client=client or TiingoHistoricalIntradayClient(),
        output_root=OUTPUT_ROOT,
        chunk_days=chunk_days,
        workers=workers,
        progress=True,
    )
    after = _file_sha256(V11_LATEST_MANIFEST)
    if before != after:
        raise ValueError("V15_EXTENDED_HISTORY_V11_MANIFEST_MODIFIED")
    if result.get("published") is not True:
        raise ValueError("V15_EXTENDED_HISTORY_NOT_PUBLISHED")
    if result.get("start_date") != boundary["start_date"]:
        raise ValueError("V15_EXTENDED_HISTORY_RESULT_START_MISMATCH")
    if result.get("end_date") != boundary["end_date"]:
        raise ValueError("V15_EXTENDED_HISTORY_RESULT_END_MISMATCH")
    if int(result.get("common_session_count", 0)) < int(
        contract["data"]["minimum_common_sessions"]
    ):
        raise ValueError("V15_EXTENDED_HISTORY_INSUFFICIENT_COMMON_SESSIONS")
    if str(result.get("last_common_session")) >= str(
        boundary["previously_observed_v15_window_starts"]
    ):
        raise ValueError("V15_EXTENDED_HISTORY_RESULT_OVERLAPS_PRIOR_WINDOW")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-days", type=int, default=120)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print("V15 ISOLATED EXTENDED INTRADAY HISTORY ACQUISITION")
    print("=" * 80)
    try:
        result = collect(chunk_days=args.chunk_days, workers=args.workers)
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("V11 latest manifest modified: NO")
        print("Model execution: OFF | brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result['status']}")
    print(f"Symbols ready: {result['symbol_count']}/101")
    print(f"Common sessions: {result['common_session_count']}")
    print(f"Window: {result['first_common_session']} -> {result['last_common_session']}")
    print(f"Manifest SHA-256: {result['manifest_sha256']}")
    print("Classification: BACKWARD ROBUSTNESS DATA ONLY")
    print("V11 latest manifest modified: NO")
    print("Model execution: OFF | brokerage orders: OFF")


if __name__ == "__main__":
    main()
