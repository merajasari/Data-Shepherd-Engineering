"""Persistent, restart-safe paper-shadow signal runner."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from ml.trading.journal import OrderJournal
from ml.trading.paper_adapter import PaperBrokerAdapter
from ml.trading.paper_shadow_state import ShadowStateRejected,ShadowStateStore
from ml.trading.sandbox_orchestrator import (
    PaperSignalOrchestrator,
    SandboxLimits,
)
from ml.trading.signal_provenance import FrozenSignalSnapshot


class ShadowReconciliationFailed(RuntimeError):
    pass


class PersistentPaperShadowRunner:
    def __init__(
        self,
        root:Path,
        *,
        approved_model_identities:dict[str,str],
        limits:SandboxLimits|None=None,
    ):
        self.root=Path(root)
        normalized=str(self.root).replace("\\","/").lower()
        if "paper_shadow" not in normalized:
            raise ShadowStateRejected("runner requires an isolated paper_shadow root")
        self.limits=limits or SandboxLimits()
        self.state_store=ShadowStateStore(self.root/"account_state.json")
        self.journal=OrderJournal(self.root/"orders.jsonl")
        restored=self.state_store.read()
        self.adapter=PaperBrokerAdapter(
            self.limits.starting_cash_usd,
            restored_state=restored,
        )
        self.orchestrator=PaperSignalOrchestrator(
            self.journal,
            adapter=self.adapter,
            limits=self.limits,
            approved_model_identities=approved_model_identities,
        )
        self._verify_journal_account_consistency()

    def _verify_journal_account_consistency(self)->None:
        journal_filled={
            event["intent_id"]
            for event in self.journal.read()
            if event.get("state")=="FILLED"
        }
        account_filled={
            str(order["intent_id"])
            for order in self.adapter.orders()
            if order.get("status")=="FILLED"
        }
        if journal_filled!=account_filled:
            raise ShadowReconciliationFailed(
                "paper-shadow journal and account state disagree; manual review required"
            )

    def run(self,signal:FrozenSignalSnapshot)->dict[str,Any]:
        self._verify_journal_account_consistency()
        result=self.orchestrator.run(signal)
        self._verify_journal_account_consistency()
        self.state_store.write(self.adapter.export_state())
        return {**result,"persistent":True,"brokerage_orders":False}

    def summary(self)->dict[str,Any]:
        self._verify_journal_account_consistency()
        account=self.adapter.account_snapshot()
        orders=self.adapter.orders()
        return {
            "mode":"PAPER_ONLY",
            "starting_cash":account["starting_cash"],
            "cash":account["cash"],
            "positions":self.adapter.positions(),
            "orders":len(orders),
            "filled_orders":sum(order.get("status")=="FILLED" for order in orders),
            "journal_events":len(self.journal.read()),
            "reconciled":True,
            "persistent":True,
            "brokerage_orders":False,
        }
