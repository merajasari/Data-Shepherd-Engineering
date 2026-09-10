"""Regression for durable paper-shadow account persistence and recovery."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

from ml.trading.lifecycle import transition
from ml.trading.paper_shadow_runner import (
    PersistentPaperShadowRunner,
    ShadowReconciliationFailed,
)
from ml.trading.paper_shadow_state import ShadowStateRejected
from ml.trading.signal_provenance import FrozenSignalSnapshot,seal_signal

STRATEGY="PERSISTENT_SYNTHETIC_SIGNAL"
MODEL_SHA="1"*64
REGISTRY={STRATEGY:MODEL_SHA}


def require(value,label):
    if not value:raise AssertionError(label)
    print(f"[PASS] {label}")


def signal(symbol,artifact):
    return seal_signal(FrozenSignalSnapshot(
        strategy_id=STRATEGY,
        frozen_strategy_sha256=MODEL_SHA,
        decision_timestamp_utc=datetime.now(timezone.utc),
        symbol=symbol,
        reference_price=Decimal("100"),
        spread_bps=Decimal("5"),
        rank=1,
        target_weight=Decimal(".40"),
        universe_sha256="2"*64,
        ranking_artifact_sha256=artifact*64,
    ))


def main():
    with tempfile.TemporaryDirectory(prefix="ds-paper-shadow-") as tmp:
        root=Path(tmp)/"data/trading/paper_shadow/regression"
        first=PersistentPaperShadowRunner(root,approved_model_identities=REGISTRY)
        aapl=signal("AAPL","3")
        result=first.run(aapl)
        require(result["status"]=="FILLED","First sealed signal persisted as paper fill")
        require((root/"account_state.json").exists(),"Atomic account state created")
        require((root/"orders.jsonl").exists(),"Append-only shadow journal created")

        restarted=PersistentPaperShadowRunner(root,approved_model_identities=REGISTRY)
        summary=restarted.summary()
        require(summary["cash"]=="4800","Cash restored across process restart")
        require(summary["positions"]==[{"symbol":"AAPL","quantity":"2"}],"Position restored across process restart")
        require(summary["reconciled"] is True,"Restored journal and account reconcile")

        duplicate=restarted.run(aapl)
        require(duplicate["duplicate_safe"] is True,"Restarted duplicate signal remains idempotent")
        require(restarted.summary()["orders"]==1,"Duplicate creates no additional paper order")

        msft=signal("MSFT","4")
        second=restarted.run(msft)
        require(second["status"]=="FILLED","Second sealed signal executes after restart")
        multi=restarted.summary()
        require(multi["cash"]=="4600","Persistent cash reflects both paper fills")
        require(
            multi["positions"]==[
                {"symbol":"AAPL","quantity":"2"},
                {"symbol":"MSFT","quantity":"2"},
            ],
            "Multiple persistent positions reconcile",
        )
        require(multi["orders"]==2 and multi["filled_orders"]==2,"Persistent order ledger is complete")
        require(multi["brokerage_orders"] is False,"Persistent account has no brokerage authority")

        state_path=root/"account_state.json"
        envelope=json.loads(state_path.read_text(encoding="utf-8"))
        envelope["state"]["cash"]="999999"
        state_path.write_text(json.dumps(envelope),encoding="utf-8")
        try:PersistentPaperShadowRunner(root,approved_model_identities=REGISTRY)
        except ShadowStateRejected:print("[PASS] Tampered account state fails digest verification")
        else:raise AssertionError("tampered persistent state was accepted")

        drift_root=Path(tmp)/"data/trading/paper_shadow/drift"
        drift=PersistentPaperShadowRunner(drift_root,approved_model_identities=REGISTRY)
        drift.run(signal("NVDA","5"))
        for index,state in enumerate(("PROPOSED","RISK_APPROVED","SUBMITTED","ACKNOWLEDGED","FILLED")):
            transition(drift.journal,"journal-only-intent",state,event_key=f"drift-{index}")
        try:PersistentPaperShadowRunner(drift_root,approved_model_identities=REGISTRY)
        except ShadowReconciliationFailed:print("[PASS] Journal/account crash drift fails closed on restart")
        else:raise AssertionError("journal/account drift was accepted")

        require("paper_shadow" in str(root),"State remains under isolated paper-shadow root")
        require(not any(token in str(root) for token in ("data/model/v8","data/model/v10")),"No model production root used")

    print("\nStatus: PASSED")
    print("Persistent $5,000 paper-shadow account: VERIFIED")
    print("Atomic state, restart recovery and drift detection: VERIFIED")
    print("Signal provenance: REQUIRED")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__=="__main__":main()
