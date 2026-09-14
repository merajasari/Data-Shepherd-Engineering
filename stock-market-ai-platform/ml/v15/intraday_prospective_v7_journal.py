"""Tamper-evident append-only journal for V15 V7 prospective paper evidence."""
from __future__ import annotations

import fcntl
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from ml.v15.intraday_logistic import canonical_sha256
from ml.v15.intraday_prospective_v7_contract import (
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNAL_PATH = ROOT / "data/research/v15/prospective_v7/journal.jsonl"
ALLOWED_EVENT_TYPES = ("DECISION", "ENTRY", "EXIT")
EVENT_ORDER = {name: index for index, name in enumerate(ALLOWED_EVENT_TYPES)}


def _utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("V15_V7_EVENT_TIMESTAMP_MUST_BE_AWARE")
    return current.astimezone(timezone.utc).isoformat()


def build_event(
    *,
    event_type: str,
    session_date: str,
    payload: Mapping[str, object],
    occurred_at_utc: datetime | None = None,
) -> dict[str, object]:
    contract = load_contract()
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError("V15_V7_EVENT_TYPE_INVALID")
    parsed_session = date.fromisoformat(session_date)
    if parsed_session < date.fromisoformat(
        str(contract["evidence_boundary"]["first_eligible_session"])
    ):
        raise ValueError("V15_V7_EVENT_BEFORE_EVIDENCE_BOUNDARY")
    forbidden = {
        "sequence",
        "previous_event_sha256",
        "event_sha256",
        "brokerage_orders",
        "live_trading_enabled",
        "contract_sha256",
        "candidate_id",
    }
    if forbidden.intersection(payload):
        raise ValueError("V15_V7_EVENT_PAYLOAD_RESERVED_FIELD")
    return {
        "event_type": event_type,
        "session_date": session_date,
        "occurred_at_utc": _utc_iso(occurred_at_utc),
        "candidate_id": contract["candidate_id"],
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "paper_shadow_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "payload": dict(payload),
    }


class V7EvidenceJournal:
    def __init__(self, path: Path = DEFAULT_JOURNAL_PATH):
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    def read(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, object]] = []
        previous: str | None = None
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"V15_V7_JOURNAL_JSON_INVALID:{line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError(f"V15_V7_JOURNAL_ROW_INVALID:{line_number}")
            unsigned = dict(row)
            embedded = unsigned.pop("event_sha256", None)
            if embedded != canonical_sha256(unsigned):
                raise ValueError(f"V15_V7_JOURNAL_HASH_MISMATCH:{line_number}")
            if row.get("sequence") != line_number:
                raise ValueError(f"V15_V7_JOURNAL_SEQUENCE_INVALID:{line_number}")
            if row.get("previous_event_sha256") != previous:
                raise ValueError(f"V15_V7_JOURNAL_CHAIN_INVALID:{line_number}")
            self._validate_identity(row, line_number)
            rows.append(row)
            previous = str(embedded)
        self._validate_lifecycle(rows)
        return rows

    @staticmethod
    def _validate_identity(row: Mapping[str, object], line_number: int) -> None:
        if row.get("event_type") not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"V15_V7_JOURNAL_EVENT_INVALID:{line_number}")
        if row.get("contract_sha256") != EXPECTED_CONTRACT_SHA256:
            raise ValueError(f"V15_V7_JOURNAL_CONTRACT_INVALID:{line_number}")
        contract = load_contract()
        if row.get("candidate_id") != contract["candidate_id"]:
            raise ValueError(f"V15_V7_JOURNAL_CANDIDATE_INVALID:{line_number}")
        if row.get("paper_shadow_only") is not True:
            raise ValueError(f"V15_V7_JOURNAL_PAPER_BOUNDARY_INVALID:{line_number}")
        if row.get("live_trading_enabled") is not False:
            raise ValueError(f"V15_V7_JOURNAL_LIVE_AUTHORITY_INVALID:{line_number}")
        if row.get("brokerage_orders") is not False:
            raise ValueError(f"V15_V7_JOURNAL_ORDER_AUTHORITY_INVALID:{line_number}")
        if date.fromisoformat(str(row["session_date"])) < date(2026, 9, 21):
            raise ValueError(f"V15_V7_JOURNAL_DATE_INVALID:{line_number}")
        timestamp = datetime.fromisoformat(str(row["occurred_at_utc"]))
        if timestamp.tzinfo is None:
            raise ValueError(f"V15_V7_JOURNAL_TIMESTAMP_INVALID:{line_number}")

    @staticmethod
    def _validate_lifecycle(rows: list[dict[str, object]]) -> None:
        sessions: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            sessions.setdefault(str(row["session_date"]), []).append(row)
        for session, events in sessions.items():
            seen: set[str] = set()
            last_order = -1
            last_timestamp: datetime | None = None
            for event in events:
                event_type = str(event["event_type"])
                if event_type in seen:
                    raise ValueError(f"V15_V7_DUPLICATE_EVENT:{session}:{event_type}")
                order = EVENT_ORDER[event_type]
                if order != last_order + 1:
                    raise ValueError(f"V15_V7_LIFECYCLE_ORDER_INVALID:{session}")
                timestamp = datetime.fromisoformat(str(event["occurred_at_utc"]))
                if last_timestamp is not None and timestamp < last_timestamp:
                    raise ValueError(f"V15_V7_EVENT_TIME_ORDER_INVALID:{session}")
                seen.add(event_type)
                last_order = order
                last_timestamp = timestamp

    def append(self, event: Mapping[str, object]) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("r+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            rows = self.read()
            session = str(event.get("session_date"))
            event_type = str(event.get("event_type"))
            existing = [
                row
                for row in rows
                if row["session_date"] == session
                and row["event_type"] == event_type
            ]
            if existing:
                comparable = dict(existing[0])
                for name in ("sequence", "previous_event_sha256", "event_sha256"):
                    comparable.pop(name, None)
                if comparable != dict(event):
                    raise ValueError(
                        f"V15_V7_DUPLICATE_EVENT_CONFLICT:{session}:{event_type}"
                    )
                return False
            row = dict(event)
            row["sequence"] = len(rows) + 1
            row["previous_event_sha256"] = (
                rows[-1]["event_sha256"] if rows else None
            )
            self._validate_identity(row, int(row["sequence"]))
            candidate_rows = rows + [{**row, "event_sha256": ""}]
            self._validate_lifecycle(candidate_rows)
            row["event_sha256"] = canonical_sha256(row)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.read()
            return True
