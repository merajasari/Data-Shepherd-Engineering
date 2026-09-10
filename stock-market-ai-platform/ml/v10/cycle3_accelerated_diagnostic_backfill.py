"""Auditable September 8 diagnostic reconstruction for accelerated V10.

This utility reconstructs the missed decision into a separate diagnostic artifact.
It never appends to the prospective V1 journal and can never satisfy a promotion
gate. The original miss and frozen contract remain immutable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping

import pandas as pd

from ml.v10.cycle3_accelerated_forward_contract import (
    EXPECTED_CANDIDATE_ID,
    EXPECTED_FROZEN_SHA256,
    load_contract as load_accelerated_contract,
    verify_frozen_source,
)
from ml.v10.cycle3_accelerated_forward_journal import DEFAULT_JOURNAL_PATH, DEFAULT_ROOT
from ml.v10.cycle3_accelerated_forward_runner import (
    _closure_dates,
    _normalize_timestamp,
    _session_lock_window,
)
from ml.v10.cycle3_holdout_runner import TOP_N, _load_market, _rank_for_date

CONTRACT_PATH = Path(__file__).with_name(
    "cycle3_accelerated_diagnostic_backfill_contract.json"
)
EXPECTED_CONTRACT_SHA256 = "98096f2729e294d9747ffef42838d3af1599ee63c8ee50fe363b8096ceb0a709"
TARGET_SESSION = pd.Timestamp("2026-09-08", tz="UTC")
ACKNOWLEDGEMENT = (
    "I AUTHORIZE A V10 SEPTEMBER 8 DIAGNOSTIC RECONSTRUCTION ONLY; "
    "IT IS NOT PROSPECTIVE OR PROMOTION EVIDENCE"
)
DEFAULT_ARTIFACT_PATH = (
    DEFAULT_ROOT / "diagnostics/2026-09-08/decision_reconstruction.json"
)


class DiagnosticReconstructionRejected(RuntimeError):
    """Raised when a diagnostic-only reconstruction fails closed."""


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _file_sha(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract() -> dict[str, object]:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or _sha(payload) != EXPECTED_CONTRACT_SHA256:
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_CONTRACT_IDENTITY_INVALID")
    if payload.get("required_acknowledgement") != ACKNOWLEDGEMENT:
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_ACKNOWLEDGEMENT_CONTRACT_INVALID")
    return payload


def _atomic_create(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise DiagnosticReconstructionRejected(
                "DIAGNOSTIC_ARTIFACT_ALREADY_EXISTS_DIFFERENT"
            )
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate_artifact(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    recorded = unsigned.pop("artifact_sha256", None)
    checks = (
        payload.get("classification")
        == "RETROSPECTIVE_DIAGNOSTIC_BACKFILL_NOT_PROSPECTIVE_EVIDENCE",
        payload.get("target_decision_session_utc") == TARGET_SESSION.isoformat(),
        payload.get("candidate_id") == EXPECTED_CANDIDATE_ID,
        payload.get("frozen_sha256") == EXPECTED_FROZEN_SHA256,
        payload.get("prospective_evidence") is False,
        payload.get("promotion_eligible") is False,
        payload.get("v1_journal_appended") is False,
        payload.get("paper_trading_only") is True,
        payload.get("live_trading_enabled") is False,
        payload.get("brokerage_orders") is False,
        recorded == _sha(unsigned),
    )
    if not all(checks):
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_ARTIFACT_INVALID")


def reconstruct(
    *,
    operator: str,
    acknowledgement: str,
    apply: bool = False,
    now_utc: datetime | None = None,
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    load_market: Callable[[], tuple[object, object, object, object]] = _load_market,
    rank_for_date: Callable[..., pd.DataFrame] = _rank_for_date,
    verify_source: Callable[[], None] = verify_frozen_source,
) -> dict[str, object]:
    load_contract()
    accelerated_contract = load_accelerated_contract()
    if not apply:
        return {
            "status": "IMPLEMENTED_NOT_INVOKED",
            "artifact_path": str(artifact_path),
            "prospective_evidence": False,
            "promotion_eligible": False,
            "v1_journal_appended": False,
            "paper_trading_only": True,
            "live_trading_enabled": False,
            "brokerage_orders": False,
        }
    if not operator.strip():
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_OPERATOR_REQUIRED")
    if acknowledgement != ACKNOWLEDGEMENT:
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_EXACT_ACKNOWLEDGEMENT_REQUIRED")

    if artifact_path.exists():
        existing = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise DiagnosticReconstructionRejected("DIAGNOSTIC_ARTIFACT_INVALID")
        _validate_artifact(existing)
        return {**existing, "status": "DIAGNOSTIC_ALREADY_RECONSTRUCTED"}

    verify_source()
    journal_before = _file_sha(journal_path)
    symbols, frames, dates, date_to_idx = load_market()
    dates = [_normalize_timestamp(value) for value in dates]
    date_to_idx = {value: index for index, value in enumerate(dates)}
    if TARGET_SESSION not in date_to_idx:
        raise DiagnosticReconstructionRejected("SEPTEMBER_8_SOURCE_SESSION_UNAVAILABLE")
    if len(symbols) != 100:
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_REQUIRES_EXACTLY_100_SYMBOLS")

    ranking = rank_for_date(
        TARGET_SESSION,
        symbols,
        frames,
        dates,
        date_to_idx,
    )
    if len(ranking) != 100:
        raise DiagnosticReconstructionRejected("DIAGNOSTIC_RANKING_INCOMPLETE")
    v10_rows = ranking.sort_values(
        ["score", "symbol"], ascending=[False, True]
    ).head(TOP_N)
    v8_rows = ranking.sort_values(
        ["raw", "symbol"], ascending=[False, True]
    ).head(TOP_N)
    closures = _closure_dates(accelerated_contract)
    close, next_open = _session_lock_window(TARGET_SESSION, closures)
    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)

    payload: dict[str, object] = {
        "classification": "RETROSPECTIVE_DIAGNOSTIC_BACKFILL_NOT_PROSPECTIVE_EVIDENCE",
        "diagnostic_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "target_decision_session_utc": TARGET_SESSION.isoformat(),
        "reconstructed_at_utc": now.isoformat(),
        "operator": operator.strip(),
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "frozen_sha256": EXPECTED_FROZEN_SHA256,
        "decision_session_close_utc": close.isoformat(),
        "next_session_open_utc": next_open.isoformat(),
        "decision_locked_prospectively": False,
        "reconstructed_after_decision_window": True,
        "symbols": v10_rows["symbol"].tolist(),
        "scores": {
            row.symbol: float(row.score) for row in v10_rows.itertuples()
        },
        "v8_control_symbols": v8_rows["symbol"].tolist(),
        "v8_control_scores": {
            row.symbol: float(row.raw) for row in v8_rows.itertuples()
        },
        "defensive_active": bool(ranking["defensive_active"].iloc[0]),
        "prospective_evidence": False,
        "promotion_eligible": False,
        "v1_journal_appended": False,
        "v1_miss_cleared": False,
        "diagnostic_only": True,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "january_confirmation_modified": False,
    }
    payload["artifact_sha256"] = _sha(payload)
    _validate_artifact(payload)
    _atomic_create(artifact_path, payload)
    if _file_sha(journal_path) != journal_before:
        raise DiagnosticReconstructionRejected("V1_JOURNAL_CHANGED_DURING_DIAGNOSTIC")
    return {**payload, "status": "DIAGNOSTIC_RECONSTRUCTED_OUTSIDE_V1_EVIDENCE"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", default="")
    parser.add_argument("--acknowledgement", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = reconstruct(
        operator=args.operator,
        acknowledgement=args.acknowledgement,
        apply=args.apply,
    )
    print("V10 SEPTEMBER 8 DIAGNOSTIC RECONSTRUCTION")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Artifact: {result.get('artifact_path', DEFAULT_ARTIFACT_PATH)}")
    print("Prospective evidence: NO")
    print("Promotion eligible: NO")
    print("V1 journal appended: NO")
    print("Current scheduled collection may continue: YES")
    print("Paper trading only: YES")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
