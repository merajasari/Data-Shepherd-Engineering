"""Disabled, preregistered V8 ranking-to-shadow-signal bridge."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from ml.trading.signal_provenance import FrozenSignalSnapshot,seal_signal

CONTRACT_PATH=Path(__file__).with_name("paper_shadow_bridge_contract.json")


class ShadowBridgeRejected(RuntimeError):
    pass


def load_contract()->dict[str,Any]:
    contract=json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("contract")!="DATA_SHEPHERD_V8_TO_PAPER_SHADOW_SIGNAL_BRIDGE":
        raise ShadowBridgeRejected("paper-shadow bridge contract identity mismatch")
    if contract.get("brokerage_orders") is not False:
        raise ShadowBridgeRejected("bridge contract grants brokerage authority")
    if contract.get("holdout_outcomes_read") is not False:
        raise ShadowBridgeRejected("bridge contract permits holdout outcome access")
    return contract


def contract_sha256()->str:
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def _canonical_rankings(rows:list[dict[str,Any]])->bytes:
    normalized=[
        {
            "rank":int(row["rank"]),
            "symbol":str(row["symbol"]).upper(),
            "score":str(row["score"]),
        }
        for row in rows
    ]
    return json.dumps(
        sorted(normalized,key=lambda row:row["rank"]),
        sort_keys=True,separators=(",",":"),ensure_ascii=True,
    ).encode("utf-8")


def _validate_rankings(rows:list[dict[str,Any]],universe_size:int)->list[dict[str,Any]]:
    if len(rows)!=universe_size:
        raise ShadowBridgeRejected(f"ranking universe must contain exactly {universe_size} names")
    normalized=json.loads(_canonical_rankings(rows))
    symbols=[row["symbol"] for row in normalized]
    ranks=[row["rank"] for row in normalized]
    if len(set(symbols))!=universe_size:
        raise ShadowBridgeRejected("ranking universe contains duplicate symbols")
    if ranks!=list(range(1,universe_size+1)):
        raise ShadowBridgeRejected("ranking universe must contain contiguous unique ranks")
    return normalized


def build_shadow_signals(
    rankings:list[dict[str,Any]],
    quotes:dict[str,dict[str,Any]],
    *,
    decision_timestamp_utc:datetime,
    rehearsal:bool=False,
)->dict[str,Any]:
    contract=load_contract()
    if decision_timestamp_utc.tzinfo is None:
        raise ShadowBridgeRejected("decision timestamp must be timezone aware")
    decision=decision_timestamp_utc.astimezone(timezone.utc)
    boundary=datetime.fromisoformat(contract["activation_not_before_utc"])
    if decision<boundary:
        raise ShadowBridgeRejected("no paper-shadow signal may exist before the V8 boundary")
    if contract.get("status")!="ACTIVE" and not rehearsal:
        raise ShadowBridgeRejected("paper-shadow bridge is preregistered but not activated")

    normalized=_validate_rankings(rankings,int(contract["source_universe_size"]))
    ranking_sha=hashlib.sha256(_canonical_rankings(normalized)).hexdigest()
    universe_sha=hashlib.sha256(
        json.dumps(sorted(row["symbol"] for row in normalized),separators=(",",":")).encode()
    ).hexdigest()
    selected=normalized[:int(contract["selected_names"])]
    signals=[]
    for row in selected:
        symbol=row["symbol"]
        quote=quotes.get(symbol)
        if not isinstance(quote,dict):
            raise ShadowBridgeRejected(f"missing quote for selected symbol {symbol}")
        price=Decimal(str(quote.get("reference_price")))
        spread=Decimal(str(quote.get("spread_bps")))
        if price<=0 or spread<0:
            raise ShadowBridgeRejected(f"invalid quote for selected symbol {symbol}")
        signals.append(seal_signal(FrozenSignalSnapshot(
            strategy_id=str(contract["source_strategy_id"]),
            frozen_strategy_sha256=str(contract["source_frozen_sha256"]),
            decision_timestamp_utc=decision,
            symbol=symbol,
            reference_price=price,
            spread_bps=spread,
            rank=int(row["rank"]),
            target_weight=Decimal(str(contract["target_weight_each"])),
            universe_sha256=universe_sha,
            ranking_artifact_sha256=ranking_sha,
        )))
    return {
        "status":"REHEARSAL_ONLY" if rehearsal else "READY_FOR_PAPER_SHADOW",
        "contract_sha256":contract_sha256(),
        "decision_timestamp_utc":decision.isoformat(),
        "ranking_artifact_sha256":ranking_sha,
        "universe_sha256":universe_sha,
        "signals":signals,
        "signal_count":len(signals),
        "production_holdout_evidence_modified":False,
        "holdout_outcomes_read":False,
        "brokerage_orders":False,
    }
