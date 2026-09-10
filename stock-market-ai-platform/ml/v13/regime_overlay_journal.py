"""Tamper-evident append-only journal foundation for V13 fresh evidence.

The V13 contract is preregistered but activation is disabled. Consequently,
this journal permits writes only when constructed in explicit rehearsal mode
and when every event is labeled as rehearsal evidence. The production journal
can be read and validated, but cannot receive an event through this module
until a future separately approved contract authorizes activation.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL_PATH = (
    ROOT / "data/research/v13/fresh_regime_overlay/evidence.jsonl"
)
GENESIS_HASH = "0" * 64
ALLOWED_EVENT_TYPES = (
    "SESSION_DECISION",
    "PAIRED_SESSION_OBSERVATION",
)
DISABLED_ACTIVATION = "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT"
FRESH_BOUNDARY_UTC = "2026-09-01T14:00:00+00:00"
EXPECTED_COLLECTION_CONTRACT_SHA256 = (
    "c1bd50ab35efac51b0450399af167b739138a9082be6bc2c31756c918f3cb077"
)


class V13EvidenceJournalCorrupt(RuntimeError):
    pass


class V13EvidenceJournalLockTimeout(RuntimeError):
    pass


class V13EvidenceActivationDisabled(RuntimeError):
    pass


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def deterministic_event_id(
    contract_sha: str,
    session_date: str,
    event_type: str,
) -> str:
    return canonical_sha256(
        {
            "contract_sha256": contract_sha,
            "session_date": session_date,
            "event_type": event_type,
        }
    )


def _require_contract() -> dict[str, object]:
    contract = load_contract()
    failures = validate_contract(contract)
    observed_sha = contract_sha256(contract)
    if failures or observed_sha != EXPECTED_CONTRACT_SHA256:
        raise ValueError(
            "V13 contract invalid: " + ",".join(failures or ["SHA_MISMATCH"])
        )
    return contract


def _parse_timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("evidence timestamp must be timezone aware")
    return timestamp.astimezone(timezone.utc)


class RegimeOverlayEvidenceJournal:
    def __init__(
        self,
        path: Path | str = DEFAULT_JOURNAL_PATH,
        *,
        rehearsal: bool = False,
        activation_validator: Callable[[datetime], Mapping[str, object]] | None = None,
        lock_timeout_seconds: float = 5.0,
    ):
        self.path = Path(path)
        self.rehearsal = rehearsal
        self.activation_validator = activation_validator
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lockdir")
        self.lock_timeout_seconds = lock_timeout_seconds

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                self.lock_path.mkdir()
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise V13EvidenceJournalLockTimeout(str(self.lock_path))
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                self.lock_path.rmdir()
            except OSError:
                pass

    def read(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, object]] = []
        previous_hash = GENESIS_HASH
        event_ids: set[str] = set()
        session_events: set[tuple[str, str]] = set()
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise V13EvidenceJournalCorrupt(
                    f"invalid JSON line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise V13EvidenceJournalCorrupt(
                    f"record is not an object line {line_number}"
                )
            required = (
                "event_id",
                "event_type",
                "session_date",
                "timestamp_utc",
                "contract_sha256",
                "v12_disposition_sha256",
                "previous_record_sha256",
                "record_sha256",
                "rehearsal",
                "paper_trading_only",
                "live_trading_enabled",
                "brokerage_orders",
                "holdout_outcomes_read",
            )
            if any(field not in row for field in required):
                raise V13EvidenceJournalCorrupt(
                    f"required field missing line {line_number}"
                )
            if row["event_type"] not in ALLOWED_EVENT_TYPES:
                raise V13EvidenceJournalCorrupt(
                    f"event type invalid line {line_number}"
                )
            try:
                if _parse_timestamp(row["timestamp_utc"]) < _parse_timestamp(
                    FRESH_BOUNDARY_UTC
                ):
                    raise V13EvidenceJournalCorrupt(
                        f"pre-boundary record line {line_number}"
                    )
            except (TypeError, ValueError) as exc:
                raise V13EvidenceJournalCorrupt(
                    f"timestamp invalid line {line_number}"
                ) from exc
            if row["contract_sha256"] != EXPECTED_CONTRACT_SHA256:
                raise V13EvidenceJournalCorrupt(
                    f"contract identity invalid line {line_number}"
                )
            if row["v12_disposition_sha256"] != EXPECTED_V12_DISPOSITION_SHA256:
                raise V13EvidenceJournalCorrupt(
                    f"predecessor identity invalid line {line_number}"
                )
            safety_false = (
                "live_trading_enabled",
                "brokerage_orders",
                "holdout_outcomes_read",
                "v8_modified",
                "v10_modified",
                "v11_modified",
                "v12_modified",
            )
            if row.get("paper_trading_only") is not True or any(
                row.get(field) is not False for field in safety_false
            ):
                raise V13EvidenceJournalCorrupt(
                    f"safety boundary invalid line {line_number}"
                )
            rehearsal = row.get("rehearsal")
            fresh = row.get("fresh_evidence")
            lease_sha = row.get("activation_lease_sha256")
            if rehearsal is True:
                if fresh is not False or lease_sha is not None:
                    raise V13EvidenceJournalCorrupt(
                        f"rehearsal evidence boundary invalid line {line_number}"
                    )
            elif rehearsal is False:
                if (
                    fresh is not True
                    or not isinstance(lease_sha, str)
                    or len(lease_sha) != 64
                    or any(character not in "0123456789abcdef" for character in lease_sha)
                    or row.get("collection_contract_sha256")
                    != EXPECTED_COLLECTION_CONTRACT_SHA256
                ):
                    raise V13EvidenceJournalCorrupt(
                        f"production lease binding invalid line {line_number}"
                    )
            else:
                raise V13EvidenceJournalCorrupt(
                    f"evidence mode invalid line {line_number}"
                )
            if row["previous_record_sha256"] != previous_hash:
                raise V13EvidenceJournalCorrupt(
                    f"hash chain broken line {line_number}"
                )
            unsigned = dict(row)
            recorded_hash = unsigned.pop("record_sha256")
            calculated_hash = canonical_sha256(unsigned)
            if recorded_hash != calculated_hash:
                raise V13EvidenceJournalCorrupt(
                    f"record digest mismatch line {line_number}"
                )
            expected_event_id = deterministic_event_id(
                EXPECTED_CONTRACT_SHA256,
                str(row["session_date"]),
                str(row["event_type"]),
            )
            if row["event_id"] != expected_event_id:
                raise V13EvidenceJournalCorrupt(
                    f"event identity invalid line {line_number}"
                )
            session_key = (str(row["session_date"]), str(row["event_type"]))
            if row["event_type"] == "PAIRED_SESSION_OBSERVATION" and (
                str(row["session_date"]), "SESSION_DECISION"
            ) not in session_events:
                raise V13EvidenceJournalCorrupt(
                    f"observation precedes decision line {line_number}"
                )
            if expected_event_id in event_ids:
                raise V13EvidenceJournalCorrupt("duplicate event_id")
            if session_key in session_events:
                raise V13EvidenceJournalCorrupt("duplicate session event")
            event_ids.add(expected_event_id)
            session_events.add(session_key)
            rows.append(row)
            previous_hash = str(recorded_hash)
        return rows

    def append(self, event: Mapping[str, object]) -> bool:
        contract = _require_contract()
        activation = contract["fresh_evidence"]["activation_status"]
        if activation == DISABLED_ACTIVATION:
            if self.rehearsal and event.get("rehearsal") is True:
                if event.get("fresh_evidence") is not False:
                    raise V13EvidenceActivationDisabled(
                        "V13 rehearsal event cannot be fresh evidence"
                    )
            elif not self.rehearsal and event.get("rehearsal") is False:
                if event.get("fresh_evidence") is not True:
                    raise V13EvidenceActivationDisabled(
                        "V13 production event must be fresh evidence"
                    )
                timestamp = _parse_timestamp(event.get("timestamp_utc"))
                if self.activation_validator is None:
                    from ml.v13.regime_overlay_lease_renewal_apply import (
                        validate_renewal_chain,
                    )

                    state = validate_renewal_chain(now_utc=timestamp)
                else:
                    state = self.activation_validator(timestamp)
                if state.get("valid") is not True or state.get("active") is not True:
                    raise V13EvidenceActivationDisabled(
                        "V13 valid active paper-only lease required"
                    )
                if (
                    state.get("paper_trading_only") is not True
                    or state.get("live_trading_enabled") is not False
                    or state.get("brokerage_orders") is not False
                    or event.get("activation_lease_sha256")
                    != state.get("latest_lease_sha256")
                    or event.get("collection_contract_sha256")
                    != EXPECTED_COLLECTION_CONTRACT_SHA256
                ):
                    raise V13EvidenceActivationDisabled(
                        "V13 event activation lease binding invalid"
                    )
            else:
                raise V13EvidenceActivationDisabled(
                    "V13 journal mode and event mode do not match"
                )
        else:
            raise V13EvidenceActivationDisabled(
                "V13 activation state is not recognized by this preregistration"
            )

        required = (
            "event_type",
            "session_date",
            "timestamp_utc",
            "contract_sha256",
            "v12_disposition_sha256",
        )
        if any(not event.get(field) for field in required):
            raise ValueError("V13 evidence event missing required fields")
        if event["event_type"] not in ALLOWED_EVENT_TYPES:
            raise ValueError("V13 evidence event type is not allowed")
        if event["contract_sha256"] != EXPECTED_CONTRACT_SHA256:
            raise ValueError("V13 evidence contract SHA mismatch")
        if event["v12_disposition_sha256"] != EXPECTED_V12_DISPOSITION_SHA256:
            raise ValueError("V13 predecessor disposition SHA mismatch")

        boundary = _parse_timestamp(contract["fresh_evidence"]["boundary_utc"])
        timestamp = _parse_timestamp(event["timestamp_utc"])
        if timestamp < boundary:
            raise ValueError("pre-boundary V13 evidence is prohibited")

        safety_false = (
            "live_trading_enabled",
            "brokerage_orders",
            "holdout_outcomes_read",
            "v8_modified",
            "v10_modified",
            "v11_modified",
            "v12_modified",
        )
        if event.get("paper_trading_only") is not True or any(
            event.get(field) is not False for field in safety_false
        ):
            raise ValueError("V13 evidence safety boundary is invalid")

        expected_event_id = deterministic_event_id(
            EXPECTED_CONTRACT_SHA256,
            str(event["session_date"]),
            str(event["event_type"]),
        )
        supplied_event_id = event.get("event_id")
        if supplied_event_id is not None and supplied_event_id != expected_event_id:
            raise ValueError("V13 event_id does not match deterministic identity")

        with self._lock():
            rows = self.read()
            session_key = (str(event["session_date"]), str(event["event_type"]))
            if any(row["event_id"] == expected_event_id for row in rows):
                return False
            if any(
                (row["session_date"], row["event_type"]) == session_key
                for row in rows
            ):
                return False
            if event["event_type"] == "PAIRED_SESSION_OBSERVATION" and not any(
                row["session_date"] == str(event["session_date"])
                and row["event_type"] == "SESSION_DECISION"
                for row in rows
            ):
                raise ValueError(
                    "V13 paired observation requires a prior session decision"
                )
            previous_hash = (
                str(rows[-1]["record_sha256"]) if rows else GENESIS_HASH
            )
            record = dict(event)
            record["event_id"] = expected_event_id
            record["previous_record_sha256"] = previous_hash
            record["record_sha256"] = canonical_sha256(record)
            encoded = (
                json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
            ).encode("utf-8")
            fd = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                os.write(fd, encoded)
                os.fsync(fd)
            finally:
                os.close(fd)
            return True


def build_rehearsal_event(
    *,
    event_type: str = "SESSION_DECISION",
    session_date: str = "2026-09-01",
    timestamp_utc: str = "2026-09-01T14:05:00+00:00",
) -> dict[str, object]:
    _require_contract()
    event: dict[str, object] = {
        "event_type": event_type,
        "session_date": session_date,
        "timestamp_utc": timestamp_utc,
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "control_candidate": "V10_CONTROL_5K",
        "challenger_candidate": "V13_NEGATIVE_HIGH_VOL_CONFIRM_5K",
        "regime_gate": "NEGATIVE_AND_HIGH_VOL",
        "regime_eligible": True,
        "rehearsal": True,
        "fresh_evidence": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "holdout_outcomes_read": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
    }
    if event_type == "PAIRED_SESSION_OBSERVATION":
        event.update(
            {
                "control_net_return": 0.001,
                "challenger_net_return": 0.0015,
                "net_return_delta": 0.0005,
            }
        )
    return event
