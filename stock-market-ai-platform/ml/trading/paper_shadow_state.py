"""Atomic durable storage for the isolated paper-shadow account."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class ShadowStateRejected(RuntimeError):
    pass


class ShadowStateStore:
    def __init__(self,path:Path,*,lock_timeout_seconds:float=2.0):
        self.path=Path(path)
        normalized=str(self.path).replace("\\","/").lower()
        if "paper_shadow" not in normalized:
            raise ShadowStateRejected("shadow state must live under an isolated paper_shadow root")
        if any(token in normalized for token in ("/ml/v8/","/ml/v10/","/data/model/v8/","/data/model/v10/")):
            raise ShadowStateRejected("shadow state cannot use a model production root")
        self.lock_path=self.path.with_suffix(self.path.suffix+".lockdir")
        self.lock_timeout_seconds=lock_timeout_seconds

    @contextmanager
    def _lock(self):
        deadline=time.monotonic()+self.lock_timeout_seconds
        self.path.parent.mkdir(parents=True,exist_ok=True)
        while True:
            try:
                self.lock_path.mkdir()
                break
            except FileExistsError:
                if time.monotonic()>=deadline:
                    raise ShadowStateRejected("paper-shadow state lock timed out")
                time.sleep(.01)
        try:
            yield
        finally:
            try:self.lock_path.rmdir()
            except FileNotFoundError:pass

    @staticmethod
    def _digest(state:dict[str,Any])->str:
        raw=json.dumps(state,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()
        return hashlib.sha256(raw).hexdigest()

    def read(self)->dict[str,Any]|None:
        if not self.path.exists():return None
        try:envelope=json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError,OSError) as exc:
            raise ShadowStateRejected("paper-shadow state is unreadable") from exc
        if not isinstance(envelope,dict) or not isinstance(envelope.get("state"),dict):
            raise ShadowStateRejected("paper-shadow state envelope is malformed")
        state=envelope["state"]
        if envelope.get("state_sha256")!=self._digest(state):
            raise ShadowStateRejected("paper-shadow state digest mismatch")
        if state.get("brokerage_orders") is not False or state.get("mode")!="PAPER_ONLY":
            raise ShadowStateRejected("paper-shadow state violates paper-only boundary")
        return state

    def write(self,state:dict[str,Any])->None:
        if state.get("brokerage_orders") is not False or state.get("mode")!="PAPER_ONLY":
            raise ShadowStateRejected("refusing to persist non-paper state")
        envelope={"state":state,"state_sha256":self._digest(state)}
        with self._lock():
            fd,temporary=tempfile.mkstemp(prefix=f".{self.path.name}.",dir=self.path.parent)
            try:
                with os.fdopen(fd,"w",encoding="utf-8") as handle:
                    json.dump(envelope,handle,indent=2,sort_keys=True)
                    handle.write("\n");handle.flush();os.fsync(handle.fileno())
                os.replace(temporary,self.path)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
