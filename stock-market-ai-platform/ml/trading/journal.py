"""Durable append-only order lifecycle journal with duplicate protection."""
from __future__ import annotations
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class JournalCorrupt(RuntimeError):pass
class JournalLockTimeout(RuntimeError):pass


class OrderJournal:
    def __init__(self,path:Path|str,lock_timeout_seconds:float=5.0):
        self.path=Path(path)
        self.lock_path=self.path.with_suffix(self.path.suffix+".lockdir")
        self.lock_timeout_seconds=lock_timeout_seconds

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        deadline=time.monotonic()+self.lock_timeout_seconds
        while True:
            try:
                self.lock_path.mkdir()
                break
            except FileExistsError:
                if time.monotonic()>=deadline:raise JournalLockTimeout(str(self.lock_path))
                time.sleep(.01)
        try:yield
        finally:
            try:self.lock_path.rmdir()
            except OSError:pass

    def read(self)->list[dict[str,Any]]:
        if not self.path.exists():return []
        rows=[]
        for number,line in enumerate(self.path.read_text(encoding="utf-8").splitlines(),1):
            if not line.strip():continue
            try:row=json.loads(line)
            except json.JSONDecodeError as exc:raise JournalCorrupt(f"invalid JSON line {number}") from exc
            if not isinstance(row,dict) or not row.get("event_id") or not row.get("intent_id") or not row.get("state"):
                raise JournalCorrupt(f"malformed lifecycle record line {number}")
            rows.append(row)
        ids=[row["event_id"] for row in rows]
        if len(ids)!=len(set(ids)):raise JournalCorrupt("duplicate event_id")
        return rows

    def append(self,event:dict[str,Any])->bool:
        required=("event_id","intent_id","state","timestamp_utc")
        if any(not event.get(key) for key in required):raise ValueError("lifecycle event missing required fields")
        with self._lock():
            rows=self.read()
            if any(row["event_id"]==event["event_id"] for row in rows):return False
            encoded=(json.dumps(event,sort_keys=True,separators=(",",":"))+"\n").encode()
            fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            try:
                os.write(fd,encoded)
                os.fsync(fd)
            finally:os.close(fd)
            return True

    def events_for(self,intent_id:str)->list[dict[str,Any]]:
        return [row for row in self.read() if row["intent_id"]==intent_id]
