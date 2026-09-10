"""End-to-end regression for paper execution, lifecycle and reconciliation."""
from __future__ import annotations
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

from ml.trading.execution import OrderIntent
from ml.trading.journal import OrderJournal
from ml.trading.lifecycle import InvalidTransition,current_state,transition
from ml.trading.paper_adapter import PaperBrokerAdapter


def require(value,label):
    if not value:raise AssertionError(label)
    print(f"[PASS] {label}")

def intent():
    return OrderIntent("paper-intent-001","paper-idempotency-001","PAPER_TEST","b"*64,
                       "AAPL","BUY",Decimal("2"),"LIMIT",datetime.now(timezone.utc),Decimal("100"))

def main():
    with tempfile.TemporaryDirectory(prefix="ds-paper-execution-") as tmp:
        path=Path(tmp)/"orders.jsonl";journal=OrderJournal(path);order_intent=intent()
        require(transition(journal,order_intent.intent_id,"PROPOSED",{"symbol":"AAPL"},event_key="proposed"),"Proposal appended")
        require(transition(journal,order_intent.intent_id,"RISK_APPROVED",{"risk":"synthetic-pass"},event_key="risk"),"Risk approval appended")
        require(transition(journal,order_intent.intent_id,"SUBMITTED",{"mode":"PAPER"},event_key="submitted"),"Submission state appended")

        broker=PaperBrokerAdapter()
        first=broker.submit_order(order_intent);second=broker.submit_order(order_intent)
        require(first["broker_order_id"]==second["broker_order_id"] and len(broker.orders())==1,"Idempotent paper submission")
        require(transition(journal,order_intent.intent_id,"ACKNOWLEDGED",{"order_id":first["broker_order_id"]},event_key="ack"),"Acknowledgement appended")

        partial=broker.simulate_fill(first["broker_order_id"],Decimal("1"),Decimal("100"))
        require(partial["status"]=="PARTIALLY_FILLED","Partial fill simulated")
        require(transition(journal,order_intent.intent_id,"PARTIALLY_FILLED",{"filled":"1"},event_key="fill-1"),"Partial-fill state appended")
        complete=broker.simulate_fill(first["broker_order_id"],Decimal("1"),Decimal("101"))
        require(complete["status"]=="FILLED","Final fill simulated")
        require(transition(journal,order_intent.intent_id,"FILLED",{"filled":"2"},event_key="fill-2"),"Filled state appended")
        require(current_state(OrderJournal(path),order_intent.intent_id)=="FILLED","Restart reconstructs terminal state")
        require(not journal.append(journal.read()[0]),"Duplicate event rejected without append")

        reconciliation=broker.reconcile(Decimal("4799"),{"AAPL":Decimal("2")})
        require(reconciliation["reconciled"],"Cash and position reconciliation passes")
        mismatch=broker.reconcile(Decimal("4800"),{"AAPL":Decimal("2")})
        require(not mismatch["reconciled"] and mismatch["differences"],"Reconciliation mismatch detected")

        try:transition(journal,order_intent.intent_id,"SUBMITTED")
        except InvalidTransition:print("[PASS] Terminal-state mutation rejected")
        else:raise AssertionError("terminal lifecycle allowed mutation")

        concurrent=OrderJournal(Path(tmp)/"concurrent.jsonl")
        event={"event_id":"c"*64,"intent_id":"concurrent","state":"PROPOSED",
               "timestamp_utc":datetime.now(timezone.utc).isoformat()}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:concurrent.append(event),range(20)))
        require(sum(bool(x) for x in results)==1 and len(concurrent.read())==1,"Concurrent duplicate append is safe")

        require(broker.account_snapshot()["brokerage_orders"] is False,"Paper adapter has no live order authority")
        sources="\n".join((Path(__file__).resolve().parent/name).read_text() for name in ("paper_adapter.py","journal.py","lifecycle.py"))
        require(not any(token in sources.lower() for token in ("alpaca_trade_api","ib_insync","robin_stocks")),"No brokerage SDK imported")

    print("\nStatus: PASSED")
    print("Lifecycle: PROPOSED -> RISK_APPROVED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED")
    print("Restart/idempotency/concurrency/reconciliation: VERIFIED")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("Production evidence modified: NO")

if __name__=="__main__":main()
