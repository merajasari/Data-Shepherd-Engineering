"""Tamper-evident provenance for frozen-model signal snapshots."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping


class SignalProvenanceRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenSignalSnapshot:
    strategy_id: str
    frozen_strategy_sha256: str
    decision_timestamp_utc: datetime
    symbol: str
    reference_price: Decimal
    spread_bps: Decimal
    rank: int
    target_weight: Decimal
    universe_sha256: str
    ranking_artifact_sha256: str
    provenance_sha256: str | None = None


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def canonical_signal_payload(signal: FrozenSignalSnapshot) -> dict[str, Any]:
    timestamp = signal.decision_timestamp_utc
    if timestamp.tzinfo is None:
        raise SignalProvenanceRejected("decision timestamp must be timezone aware")
    return {
        "strategy_id": signal.strategy_id,
        "frozen_strategy_sha256": signal.frozen_strategy_sha256.lower(),
        "decision_timestamp_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "symbol": signal.symbol.upper(),
        "reference_price": str(signal.reference_price),
        "spread_bps": str(signal.spread_bps),
        "rank": signal.rank,
        "target_weight": str(signal.target_weight),
        "universe_sha256": signal.universe_sha256.lower(),
        "ranking_artifact_sha256": signal.ranking_artifact_sha256.lower(),
    }


def calculate_provenance_sha256(signal: FrozenSignalSnapshot) -> str:
    encoded = json.dumps(
        canonical_signal_payload(signal),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_signal(signal: FrozenSignalSnapshot) -> FrozenSignalSnapshot:
    if signal.provenance_sha256 is not None:
        raise SignalProvenanceRejected("signal is already sealed")
    return replace(signal, provenance_sha256=calculate_provenance_sha256(signal))


class FrozenSignalVerifier:
    def __init__(self, approved_model_identities: Mapping[str, str]):
        self._approved = {
            str(strategy_id): str(model_sha).lower()
            for strategy_id, model_sha in approved_model_identities.items()
        }
        if not self._approved:
            raise SignalProvenanceRejected("approved model registry is empty")
        if not all(_is_sha256(value) for value in self._approved.values()):
            raise SignalProvenanceRejected("approved model registry contains an invalid SHA-256")

    def verify(self, signal: FrozenSignalSnapshot) -> dict[str, Any]:
        expected_model_sha = self._approved.get(signal.strategy_id)
        if expected_model_sha is None:
            raise SignalProvenanceRejected("strategy identity is not approved")
        if not _is_sha256(signal.frozen_strategy_sha256):
            raise SignalProvenanceRejected("frozen model SHA-256 is invalid")
        if signal.frozen_strategy_sha256.lower() != expected_model_sha:
            raise SignalProvenanceRejected("frozen model identity does not match registry")
        if not _is_sha256(signal.universe_sha256):
            raise SignalProvenanceRejected("universe SHA-256 is invalid")
        if not _is_sha256(signal.ranking_artifact_sha256):
            raise SignalProvenanceRejected("ranking artifact SHA-256 is invalid")
        if not _is_sha256(signal.provenance_sha256):
            raise SignalProvenanceRejected("signal provenance seal is missing or invalid")
        calculated = calculate_provenance_sha256(signal)
        if signal.provenance_sha256.lower() != calculated:
            raise SignalProvenanceRejected("signal payload does not match provenance seal")
        return {
            "verified": True,
            "strategy_id": signal.strategy_id,
            "frozen_strategy_sha256": expected_model_sha,
            "provenance_sha256": calculated,
            "brokerage_orders": False,
        }
