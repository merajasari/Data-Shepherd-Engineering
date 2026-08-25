"""Deterministic in-memory paper broker for execution engineering tests."""
from __future__ import annotations
from decimal import Decimal
from typing import Any
from ml.trading.execution import BrokerAdapter,OrderIntent


class PaperBrokerAdapter(BrokerAdapter):
    def __init__(self,starting_cash:Decimal=Decimal("5000")):
        self._starting_cash=Decimal(starting_cash)
        self._cash=Decimal(starting_cash)
        self._positions:dict[str,Decimal]={}
        self._orders:dict[str,dict[str,Any]]={}
        self._idempotency:dict[str,str]={}

    def account_snapshot(self)->dict[str,Any]:
        return {"connected":True,"mode":"PAPER","cash":str(self._cash),
                "starting_cash":str(self._starting_cash),"brokerage_orders":False}

    def positions(self)->list[dict[str,Any]]:
        return [{"symbol":symbol,"quantity":str(quantity)} for symbol,quantity in sorted(self._positions.items()) if quantity]

    def orders(self)->list[dict[str,Any]]:
        return [dict(order) for order in self._orders.values()]

    def submit_order(self,intent:OrderIntent)->dict[str,Any]:
        if intent.idempotency_key in self._idempotency:
            return dict(self._orders[self._idempotency[intent.idempotency_key]])
        order_id=f"PAPER-{len(self._orders)+1:06d}"
        order={"broker_order_id":order_id,"intent_id":intent.intent_id,
               "idempotency_key":intent.idempotency_key,"symbol":intent.symbol,
               "side":intent.side.upper(),"quantity":str(intent.quantity),
               "filled_quantity":"0","status":"ACKNOWLEDGED","mode":"PAPER",
               "brokerage_orders":False}
        self._orders[order_id]=order;self._idempotency[intent.idempotency_key]=order_id
        return dict(order)

    def simulate_fill(self,broker_order_id:str,quantity:Decimal,price:Decimal)->dict[str,Any]:
        order=self._orders[broker_order_id];fill=Decimal(quantity);px=Decimal(price)
        requested=Decimal(order["quantity"]);already=Decimal(order["filled_quantity"])
        if fill<=0 or already+fill>requested:raise ValueError("invalid fill quantity")
        signed=fill if order["side"]=="BUY" else -fill
        cash_change=-(fill*px) if order["side"]=="BUY" else fill*px
        if order["side"]=="BUY" and self._cash+cash_change<0:raise ValueError("insufficient paper cash")
        current=self._positions.get(order["symbol"],Decimal("0"))
        if current+signed<0:raise ValueError("paper short selling prohibited")
        self._cash+=cash_change;self._positions[order["symbol"]]=current+signed
        order["filled_quantity"]=str(already+fill)
        order["status"]="FILLED" if already+fill==requested else "PARTIALLY_FILLED"
        order.setdefault("fills",[]).append({"quantity":str(fill),"price":str(px)})
        return dict(order)

    def cancel_order(self,broker_order_id:str)->dict[str,Any]:
        order=self._orders[broker_order_id]
        if order["status"]=="FILLED":raise ValueError("filled paper order cannot be canceled")
        order["status"]="CANCELED";return dict(order)

    def reconcile(self,expected_cash:Decimal,expected_positions:dict[str,Decimal])->dict[str,Any]:
        actual={k:v for k,v in self._positions.items() if v}
        expected={k:Decimal(v) for k,v in expected_positions.items() if Decimal(v)}
        differences=[]
        if self._cash!=Decimal(expected_cash):differences.append({"field":"cash","expected":str(expected_cash),"actual":str(self._cash)})
        for symbol in sorted(set(actual)|set(expected)):
            if actual.get(symbol,Decimal("0"))!=expected.get(symbol,Decimal("0")):
                differences.append({"field":f"position:{symbol}","expected":str(expected.get(symbol,0)),"actual":str(actual.get(symbol,0))})
        return {"reconciled":not differences,"differences":differences,"mode":"PAPER","brokerage_orders":False}
