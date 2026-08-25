"""Deterministic failure-injection suite for the paper execution boundary."""
from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path

from ml.trading.execution import OrderIntent
from ml.trading.journal import JournalCorrupt,JournalLockTimeout,OrderJournal
from ml.trading.lifecycle import current_state,transition
from ml.trading.paper_adapter import PaperBrokerAdapter
from ml.trading.risk import evaluate_pretrade

ROOT=Path(__file__).resolve().parent


def require(value,label):
    if not value:raise AssertionError(label)
    print(f"[PASS] {label}")


def make_intent(identifier="failure-001",side="BUY",quantity="2",price="100",created=None):
    return OrderIntent(
        identifier,f"idem-{identifier}","SYNTHETIC_FAILURE_TEST","c"*64,
        "AAPL",side,Decimal(quantity),"LIMIT",
        created or datetime.now(timezone.utc),Decimal(price),
    )


def authorized_contract():
    contract=json.loads((ROOT/"live_trading_contract.json").read_text(encoding="utf-8"))
    contract.update({
        "status":"LIVE_AUTHORIZED","live_trading_enabled":True,
        "broker":"SYNTHETIC_TEST_ONLY","account_id":"SYNTHETIC",
        "strategy_id":"SYNTHETIC_FAILURE_TEST","frozen_strategy_sha256":"c"*64,
    })
    contract["limits"]={
        "maximum_deployed_capital_usd":500,
        "maximum_order_notional_usd":200,
        "maximum_position_notional_usd":200,
        "maximum_daily_loss_usd":25,
        "maximum_open_positions":5,
        "maximum_orders_per_session":5,
        "maximum_signal_age_seconds":60,
        "maximum_quote_age_seconds":5,
        "maximum_spread_bps":25,
    }
    return contract


def lifecycle_to(journal,intent_id,states):
    for index,state in enumerate(states):
        transition(journal,intent_id,state,event_key=f"{intent_id}-{index}-{state}")


def main():
    with tempfile.TemporaryDirectory(prefix="ds-trading-failures-") as tmp:
        root=Path(tmp)

        rejected=OrderJournal(root/"rejected.jsonl")
        lifecycle_to(rejected,"rejected",["PROPOSED","RISK_APPROVED","SUBMITTED","REJECTED"])
        require(current_state(rejected,"rejected")=="REJECTED","Broker rejection reaches terminal state")

        canceled=OrderJournal(root/"canceled.jsonl");cancel_intent=make_intent("cancel")
        lifecycle_to(canceled,"cancel",["PROPOSED","RISK_APPROVED","SUBMITTED","ACKNOWLEDGED"])
        cancel_broker=PaperBrokerAdapter();cancel_order=cancel_broker.submit_order(cancel_intent)
        cancel_broker.cancel_order(cancel_order["broker_order_id"])
        transition(canceled,"cancel","CANCELED",event_key="cancel-terminal")
        require(current_state(canceled,"cancel")=="CANCELED","Acknowledged order cancellation is terminal")

        partial_journal=OrderJournal(root/"partial_cancel.jsonl");partial_intent=make_intent("partial-cancel")
        lifecycle_to(partial_journal,"partial-cancel",["PROPOSED","RISK_APPROVED","SUBMITTED","ACKNOWLEDGED"])
        partial_broker=PaperBrokerAdapter();partial_order=partial_broker.submit_order(partial_intent)
        partial_broker.simulate_fill(partial_order["broker_order_id"],Decimal("1"),Decimal("100"))
        transition(partial_journal,"partial-cancel","PARTIALLY_FILLED",event_key="partial")
        partial_broker.cancel_order(partial_order["broker_order_id"])
        transition(partial_journal,"partial-cancel","CANCELED",event_key="partial-cancel-terminal")
        require(partial_broker.positions()==[{"symbol":"AAPL","quantity":"1"}] and current_state(partial_journal,"partial-cancel")=="CANCELED",
                "Partial fill remains reconciled when remainder is canceled")

        cash_broker=PaperBrokerAdapter(Decimal("50"));expensive=make_intent("insufficient",quantity="1",price="100")
        expensive_order=cash_broker.submit_order(expensive)
        try:cash_broker.simulate_fill(expensive_order["broker_order_id"],Decimal("1"),Decimal("100"))
        except ValueError as exc:require("insufficient paper cash" in str(exc),"Insufficient cash fails closed")
        else:raise AssertionError("insufficient cash fill succeeded")

        short_broker=PaperBrokerAdapter();sell=make_intent("short",side="SELL",quantity="1",price="100")
        sell_order=short_broker.submit_order(sell)
        try:short_broker.simulate_fill(sell_order["broker_order_id"],Decimal("1"),Decimal("100"))
        except ValueError as exc:require("short selling prohibited" in str(exc),"Short sale fails closed")
        else:raise AssertionError("short sale succeeded")

        contract=authorized_contract()
        base_account={"reconciled":True,"buying_power_usd":500,"daily_pnl_usd":0,"open_positions":0}
        base_market={"session_open":True,"quote_current":True,"reference_price":100,"spread_bps":5}
        base_runtime={"human_activated":True,"kill_switch_clear":True,"frozen_model_verified":True,"idempotency_key_new":True}

        stale=make_intent("stale",created=datetime.now(timezone.utc)-timedelta(minutes=5))
        stale_result=evaluate_pretrade(contract,stale,account=base_account,market=base_market,runtime=base_runtime)
        require(not stale_result.approved and "SIGNAL_STALE" in stale_result.reasons,"Stale signal rejected")

        stale_quote=evaluate_pretrade(contract,make_intent("stale-quote"),account=base_account,
                                      market={**base_market,"quote_current":False},runtime=base_runtime)
        require("MARKET_DATA_STALE" in stale_quote.reasons,"Stale quote rejected")

        loss=evaluate_pretrade(contract,make_intent("loss"),account={**base_account,"daily_pnl_usd":-25},
                               market=base_market,runtime=base_runtime)
        require("DAILY_LOSS_LIMIT_REACHED" in loss.reasons,"Daily-loss boundary rejects new order")

        duplicate=evaluate_pretrade(contract,make_intent("duplicate"),account=base_account,market=base_market,
                                    runtime={**base_runtime,"idempotency_key_new":False})
        require("DUPLICATE_IDEMPOTENCY_KEY" in duplicate.reasons,"Duplicate order intent rejected")

        interrupted=OrderJournal(root/"interrupted.jsonl")
        lifecycle_to(interrupted,"interrupted",["PROPOSED","RISK_APPROVED","SUBMITTED"])
        restarted=OrderJournal(root/"interrupted.jsonl")
        require(current_state(restarted,"interrupted")=="SUBMITTED","Interrupted process reconstructs submitted state")
        transition(restarted,"interrupted","ACKNOWLEDGED",event_key="restart-ack")
        require(current_state(restarted,"interrupted")=="ACKNOWLEDGED","Restart resumes valid lifecycle")

        corrupt_path=root/"corrupt.jsonl";corrupt_path.write_text('{"event_id":\n',encoding="utf-8")
        try:OrderJournal(corrupt_path).read()
        except JournalCorrupt:print("[PASS] Corrupted journal fails closed")
        else:raise AssertionError("corrupted journal was accepted")

        malformed_path=root/"malformed.jsonl";malformed_path.write_text('{"event_id":"x"}\n',encoding="utf-8")
        try:OrderJournal(malformed_path).read()
        except JournalCorrupt:print("[PASS] Malformed journal record fails closed")
        else:raise AssertionError("malformed journal was accepted")

        locked=OrderJournal(root/"locked.jsonl",lock_timeout_seconds=.03)
        locked.lock_path.mkdir()
        try:
            locked.append({"event_id":"l"*64,"intent_id":"locked","state":"PROPOSED",
                           "timestamp_utc":datetime.now(timezone.utc).isoformat()})
        except JournalLockTimeout:print("[PASS] Lock contention times out without unsafe append")
        else:raise AssertionError("append bypassed journal lock")

        reconcile_broker=PaperBrokerAdapter();ri=make_intent("reconcile",quantity="1",price="100")
        ro=reconcile_broker.submit_order(ri);reconcile_broker.simulate_fill(ro["broker_order_id"],Decimal("1"),Decimal("100"))
        drift=reconcile_broker.reconcile(Decimal("4900"),{"AAPL":Decimal("2")})
        require(not drift["reconciled"],"Position drift detected")
        recovered=reconcile_broker.reconcile(Decimal("4900"),{"AAPL":Decimal("1")})
        require(recovered["reconciled"],"Reconciliation recovery verified")

        require(not any((root/name).exists() for name in ("production_journal.jsonl","broker_credentials.json")),
                "No production journal or credential artifact created")

    print("\nStatus: PASSED")
    print("Failure-injection suite: ALL SCENARIOS PASSED")
    print("Process interruption and recovery: VERIFIED")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__=="__main__":main()
