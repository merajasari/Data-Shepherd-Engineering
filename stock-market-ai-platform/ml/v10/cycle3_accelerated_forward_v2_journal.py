"""Tamper-evident journal for clean V10 Cycle 3 V2 paper evidence."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Mapping

from ml.v10.cycle3_accelerated_forward_v2_contract import (
    EXPECTED_CANDIDATE_ID,
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_FROZEN_SHA256,
    FIRST_DECISION_SESSION_UTC,
    LAST_DECISION_SESSION_UTC,
    load_contract,
)

DEFAULT_ROOT = Path("data/model/v10/cycle3/accelerated_forward_v2")
DEFAULT_JOURNAL_PATH = DEFAULT_ROOT / "journal.jsonl"
GENESIS_HASH = "0" * 64
ALLOWED_EVENT_TYPES = ("DECISION", "ENTRY", "EXIT")


class AcceleratedEvidenceCorrupt(RuntimeError):
    pass


class AcceleratedEvidenceLockTimeout(RuntimeError):
    pass


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_event_id(event: Mapping[str, object]) -> str:
    return canonical_sha256(
        {
            "contract_sha256": event.get("contract_sha256"),
            "candidate_id": event.get("candidate_id"),
            "frozen_sha256": event.get("frozen_sha256"),
            "event_type": event.get("event_type"),
            "decision_timestamp_utc": event.get("decision_timestamp_utc"),
            "cohort_offset": event.get("cohort_offset"),
        }
    )


def _parse_aware(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)


class AcceleratedEvidenceJournal:
    def __init__(
        self,
        path: Path | str = DEFAULT_JOURNAL_PATH,
        *,
        lock_timeout_seconds: float = 5.0,
    ):
        self.path = Path(path)
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
                    raise AcceleratedEvidenceLockTimeout(str(self.lock_path))
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
        event_keys: set[tuple[object, object, object]] = set()
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AcceleratedEvidenceCorrupt(
                    f"invalid JSON line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise AcceleratedEvidenceCorrupt(
                    f"record is not an object line {line_number}"
                )
            required = (
                "event_id",
                "event_type",
                "decision_timestamp_utc",
                "cohort_offset",
                "created_at_utc",
                "contract_sha256",
                "candidate_id",
                "frozen_sha256",
                "previous_record_sha256",
                "record_sha256",
            )
            if any(field not in row for field in required):
                raise AcceleratedEvidenceCorrupt(
                    f"required field missing line {line_number}"
                )
            if row["event_type"] not in ALLOWED_EVENT_TYPES:
                raise AcceleratedEvidenceCorrupt(
                    f"event type invalid line {line_number}"
                )
            if row["contract_sha256"] != EXPECTED_CONTRACT_SHA256:
                raise AcceleratedEvidenceCorrupt(
                    f"contract identity changed line {line_number}"
                )
            if row["candidate_id"] != EXPECTED_CANDIDATE_ID:
                raise AcceleratedEvidenceCorrupt(
                    f"candidate identity changed line {line_number}"
                )
            if row["frozen_sha256"] != EXPECTED_FROZEN_SHA256:
                raise AcceleratedEvidenceCorrupt(
                    f"frozen identity changed line {line_number}"
                )
            if row.get("paper_trading_only") is not True:
                raise AcceleratedEvidenceCorrupt(
                    f"paper-only marker missing line {line_number}"
                )
            if row.get("brokerage_orders") is not False:
                raise AcceleratedEvidenceCorrupt(
                    f"brokerage authority present line {line_number}"
                )
            if row.get("v8_modified") is not False:
                raise AcceleratedEvidenceCorrupt(
                    f"V8 modification marker invalid line {line_number}"
                )
            if row.get("january_confirmation_modified") is not False:
                raise AcceleratedEvidenceCorrupt(
                    f"January modification marker invalid line {line_number}"
                )
            if row["previous_record_sha256"] != previous_hash:
                raise AcceleratedEvidenceCorrupt(
                    f"hash chain broken line {line_number}"
                )
            unsigned = dict(row)
            recorded_hash = unsigned.pop("record_sha256")
            calculated_hash = canonical_sha256(unsigned)
            if recorded_hash != calculated_hash:
                raise AcceleratedEvidenceCorrupt(
                    f"record digest mismatch line {line_number}"
                )
            expected_event_id = deterministic_event_id(row)
            if row["event_id"] != expected_event_id:
                raise AcceleratedEvidenceCorrupt(
                    f"event identity mismatch line {line_number}"
                )
            event_id = str(row["event_id"])
            event_key = (
                row["event_type"],
                row["decision_timestamp_utc"],
                row["cohort_offset"],
            )
            if event_id in event_ids or event_key in event_keys:
                raise AcceleratedEvidenceCorrupt(
                    f"duplicate evidence event line {line_number}"
                )
            event_ids.add(event_id)
            event_keys.add(event_key)
            rows.append(row)
            previous_hash = str(recorded_hash)
        return rows

    def append(self, event: Mapping[str, object]) -> bool:
        load_contract()
        required = (
            "event_type",
            "decision_timestamp_utc",
            "cohort_offset",
            "created_at_utc",
            "contract_sha256",
            "candidate_id",
            "frozen_sha256",
            "paper_trading_only",
            "brokerage_orders",
            "v8_modified",
            "january_confirmation_modified",
        )
        if any(field not in event for field in required):
            raise ValueError("ACCELERATED_EVENT_REQUIRED_FIELD_MISSING")
        if event["event_type"] not in ALLOWED_EVENT_TYPES:
            raise ValueError("ACCELERATED_EVENT_TYPE_INVALID")
        if event["contract_sha256"] != EXPECTED_CONTRACT_SHA256:
            raise ValueError("ACCELERATED_EVENT_CONTRACT_SHA_MISMATCH")
        if event["candidate_id"] != EXPECTED_CANDIDATE_ID:
            raise ValueError("ACCELERATED_EVENT_CANDIDATE_MISMATCH")
        if event["frozen_sha256"] != EXPECTED_FROZEN_SHA256:
            raise ValueError("ACCELERATED_EVENT_FROZEN_SHA_MISMATCH")
        if event["paper_trading_only"] is not True:
            raise ValueError("ACCELERATED_EVENT_NOT_PAPER_ONLY")
        if event["brokerage_orders"] is not False:
            raise ValueError("ACCELERATED_EVENT_BROKERAGE_PROHIBITED")
        if event["v8_modified"] is not False:
            raise ValueError("ACCELERATED_EVENT_V8_MODIFICATION_PROHIBITED")
        if event["january_confirmation_modified"] is not False:
            raise ValueError("ACCELERATED_EVENT_JANUARY_MODIFICATION_PROHIBITED")

        decision = _parse_aware(
            event["decision_timestamp_utc"], "DECISION_TIMESTAMP_UTC"
        )
        start = _parse_aware(
            FIRST_DECISION_SESSION_UTC, "FIRST_DECISION_SESSION_UTC"
        )
        end = _parse_aware(
            LAST_DECISION_SESSION_UTC, "LAST_DECISION_SESSION_UTC"
        )
        if not start <= decision <= end:
            raise ValueError("ACCELERATED_EVENT_OUTSIDE_DECISION_WINDOW")
        created = _parse_aware(event["created_at_utc"], "CREATED_AT_UTC")
        if event["event_type"] == "DECISION":
            closed = _parse_aware(
                event.get("decision_session_close_utc"),
                "DECISION_SESSION_CLOSE_UTC",
            )
            next_open = _parse_aware(
                event.get("next_session_open_utc"),
                "NEXT_SESSION_OPEN_UTC",
            )
            if not closed <= created < next_open:
                raise ValueError("DECISION_NOT_LOCKED_PROSPECTIVELY")
            if event.get("decision_locked_before_entry") is not True:
                raise ValueError("DECISION_LOCK_MARKER_MISSING")

        expected_event_id = deterministic_event_id(event)
        supplied_event_id = event.get("event_id")
        if supplied_event_id is not None and supplied_event_id != expected_event_id:
            raise ValueError("ACCELERATED_EVENT_ID_MISMATCH")

        with self._lock():
            rows = self.read()
            key = (
                event["event_type"],
                event["decision_timestamp_utc"],
                event["cohort_offset"],
            )
            if any(
                (
                    row["event_type"],
                    row["decision_timestamp_utc"],
                    row["cohort_offset"],
                )
                == key
                for row in rows
            ):
                return False
            previous_hash = (
                str(rows[-1]["record_sha256"]) if rows else GENESIS_HASH
            )
            record = dict(event)
            record["event_id"] = expected_event_id
            record["previous_record_sha256"] = previous_hash
            record["record_sha256"] = canonical_sha256(record)
            encoded = (
                json.dumps(record, separators=(",", ":"), sort_keys=True)
                + "\n"
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
