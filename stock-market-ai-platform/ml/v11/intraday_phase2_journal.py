"""Tamper-evident append-only journal for V11 Phase 2 evidence.

The journal is isolated under the V11 research root. It has no brokerage
interface and cannot read or modify V8/V10 production evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ml.v11.intraday_phase2_contract import contract_sha256, load_contract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL_PATH = (
    ROOT / "data/research/v11/intraday/phase2/evidence.jsonl"
)
GENESIS_HASH = "0" * 64
ALLOWED_EVENT_TYPES = ("DECISION", "ENTRY", "EXIT", "SESSION_OBSERVATION")


class EvidenceJournalCorrupt(RuntimeError):
    pass


class EvidenceJournalLockTimeout(RuntimeError):
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


class Phase2EvidenceJournal:
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
                    raise EvidenceJournalLockTimeout(str(self.lock_path))
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
                raise EvidenceJournalCorrupt(
                    f"invalid JSON line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise EvidenceJournalCorrupt(
                    f"record is not an object line {line_number}"
                )
            required = (
                "event_id",
                "event_type",
                "session_date",
                "timestamp_utc",
                "contract_sha256",
                "previous_record_sha256",
                "record_sha256",
            )
            if any(not row.get(field) for field in required):
                raise EvidenceJournalCorrupt(
                    f"required field missing line {line_number}"
                )
            if row["event_type"] not in ALLOWED_EVENT_TYPES:
                raise EvidenceJournalCorrupt(
                    f"event type invalid line {line_number}"
                )
            if row["previous_record_sha256"] != previous_hash:
                raise EvidenceJournalCorrupt(
                    f"hash chain broken line {line_number}"
                )
            unsigned = dict(row)
            recorded_hash = unsigned.pop("record_sha256")
            calculated_hash = canonical_sha256(unsigned)
            if recorded_hash != calculated_hash:
                raise EvidenceJournalCorrupt(
                    f"record digest mismatch line {line_number}"
                )
            event_id = str(row["event_id"])
            session_key = (str(row["session_date"]), str(row["event_type"]))
            if event_id in event_ids:
                raise EvidenceJournalCorrupt("duplicate event_id")
            if session_key in session_events:
                raise EvidenceJournalCorrupt(
                    "duplicate session event"
                )
            event_ids.add(event_id)
            session_events.add(session_key)
            rows.append(row)
            previous_hash = str(recorded_hash)
        return rows

    def append(self, event: Mapping[str, object]) -> bool:
        contract = load_contract()
        expected_contract_sha = contract_sha256(contract)
        required = (
            "event_type",
            "session_date",
            "timestamp_utc",
            "contract_sha256",
        )
        if any(not event.get(field) for field in required):
            raise ValueError("evidence event missing required fields")
        if event["event_type"] not in ALLOWED_EVENT_TYPES:
            raise ValueError("evidence event type is not allowed")
        if event["contract_sha256"] != expected_contract_sha:
            raise ValueError("evidence contract SHA mismatch")

        boundary = datetime.fromisoformat(
            str(contract["fresh_confirmation_start_utc"])
        ).astimezone(timezone.utc)
        timestamp = datetime.fromisoformat(
            str(event["timestamp_utc"]).replace("Z", "+00:00")
        )
        if timestamp.tzinfo is None:
            raise ValueError("evidence timestamp must be timezone aware")
        if timestamp.astimezone(timezone.utc) < boundary:
            raise ValueError("pre-boundary evidence is prohibited")

        expected_event_id = deterministic_event_id(
            expected_contract_sha,
            str(event["session_date"]),
            str(event["event_type"]),
        )
        supplied_event_id = event.get("event_id")
        if supplied_event_id is not None and supplied_event_id != expected_event_id:
            raise ValueError("event_id does not match deterministic identity")

        with self._lock():
            rows = self.read()
            session_key = (
                str(event["session_date"]),
                str(event["event_type"]),
            )
            if any(row["event_id"] == expected_event_id for row in rows):
                return False
            if any(
                (row["session_date"], row["event_type"]) == session_key
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


def build_rehearsal_event(
    *,
    session_date: str = "2026-09-01",
    timestamp_utc: str = "2026-09-01T14:05:00+00:00",
) -> dict[str, object]:
    contract = load_contract()
    return {
        "event_type": "DECISION",
        "session_date": session_date,
        "timestamp_utc": timestamp_utc,
        "contract_sha256": contract_sha256(contract),
        "ranking_sha256": "1" * 64,
        "selected_symbols": [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
            "META", "AVGO", "TSLA", "JPM", "XOM",
        ],
        "rehearsal": True,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
