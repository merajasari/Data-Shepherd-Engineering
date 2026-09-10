"""Read-only presentation service for the isolated persistent paper-shadow account."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from ml.trading.journal import JournalCorrupt,OrderJournal
from ml.trading.paper_shadow_state import ShadowStateRejected,ShadowStateStore

ROOT=Path("data/trading/paper_shadow")
STATE_PATH=ROOT/"account_state.json"
JOURNAL_PATH=ROOT/"orders.jsonl"
STARTING_CASH=Decimal("5000")


def _empty()->dict[str,Any]:
    return {
        "status":"EMPTY_READY",
        "starting_cash":str(STARTING_CASH),
        "cash":str(STARTING_CASH),
        "deployed_capital":"0",
        "positions":[],
        "position_count":0,
        "orders":0,
        "filled_orders":0,
        "journal_events":0,
        "reconciled":True,
        "persistent":True,
        "signal_provenance_required":True,
        "brokerage_orders":False,
        "alert":None,
    }


def get_paper_shadow_status()->dict[str,Any]:
    state_exists=STATE_PATH.exists()
    journal_exists=JOURNAL_PATH.exists()
    if not state_exists and not journal_exists:
        return _empty()
    if state_exists!=journal_exists:
        return {**_empty(),"status":"FAIL_CLOSED","reconciled":False,
                "alert":"Account state and execution journal are incomplete."}
    try:
        state=ShadowStateStore(STATE_PATH).read()
        events=OrderJournal(JOURNAL_PATH).read()
        if state is None:
            raise ShadowStateRejected("account state disappeared during read")
    except (ShadowStateRejected,JournalCorrupt,OSError,KeyError,ValueError) as exc:
        return {**_empty(),"status":"FAIL_CLOSED","reconciled":False,
                "alert":f"{type(exc).__name__}: paper-shadow data requires review."}

    orders=state.get("orders") or {}
    positions=[
        {"symbol":str(symbol),"quantity":str(quantity)}
        for symbol,quantity in sorted((state.get("positions") or {}).items())
        if Decimal(str(quantity))!=0
    ]
    journal_filled={
        str(event["intent_id"]) for event in events if event.get("state")=="FILLED"
    }
    account_filled={
        str(order["intent_id"]) for order in orders.values()
        if order.get("status")=="FILLED"
    }
    reconciled=journal_filled==account_filled
    starting=Decimal(str(state.get("starting_cash",STARTING_CASH)))
    cash=Decimal(str(state.get("cash",starting)))
    return {
        "status":"HEALTHY" if reconciled else "FAIL_CLOSED",
        "starting_cash":str(starting),
        "cash":str(cash),
        "deployed_capital":str(starting-cash),
        "positions":positions,
        "position_count":len(positions),
        "orders":len(orders),
        "filled_orders":len(account_filled),
        "journal_events":len(events),
        "reconciled":reconciled,
        "persistent":True,
        "signal_provenance_required":True,
        "brokerage_orders":False,
        "alert":None if reconciled else "Journal and account state disagree; execution is blocked.",
    }
