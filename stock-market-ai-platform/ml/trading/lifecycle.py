"""Strict order lifecycle transitions backed by the append-only journal."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime,timezone
from typing import Any
from ml.trading.journal import OrderJournal

ALLOWED={
    None:{"PROPOSED"},
    "PROPOSED":{"RISK_APPROVED","REJECTED"},
    "RISK_APPROVED":{"SUBMITTED","REJECTED"},
    "SUBMITTED":{"ACKNOWLEDGED","REJECTED","CANCELED"},
    "ACKNOWLEDGED":{"PARTIALLY_FILLED","FILLED","REJECTED","CANCELED"},
    "PARTIALLY_FILLED":{"PARTIALLY_FILLED","FILLED","CANCELED"},
    "FILLED":set(),"REJECTED":set(),"CANCELED":set(),
}
TERMINAL={"FILLED","REJECTED","CANCELED"}

class InvalidTransition(RuntimeError):pass

def current_state(journal:OrderJournal,intent_id:str)->str|None:
    events=journal.events_for(intent_id)
    return events[-1]["state"] if events else None

def transition(journal:OrderJournal,intent_id:str,state:str,payload:dict[str,Any]|None=None,event_key:str|None=None)->bool:
    prior=current_state(journal,intent_id)
    if state not in ALLOWED.get(prior,set()):
        if prior==state and event_key:return False
        raise InvalidTransition(f"{prior or 'NONE'} -> {state}")
    body=payload or {}
    stable=event_key or f"{intent_id}|{prior}|{state}|{json.dumps(body,sort_keys=True,default=str)}"
    event_id=hashlib.sha256(stable.encode()).hexdigest()
    return journal.append({
        "event_id":event_id,"intent_id":intent_id,"previous_state":prior,
        "state":state,"timestamp_utc":datetime.now(timezone.utc).isoformat(),
        "payload":body,
    })
