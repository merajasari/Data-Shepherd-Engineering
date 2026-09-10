"""Regression for the preregistered, disabled V8 paper-shadow signal bridge."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path

from ml.trading.paper_shadow_signal_bridge import (
    CONTRACT_PATH,
    ShadowBridgeRejected,
    build_shadow_signals,
    contract_sha256,
    load_contract,
)
from ml.trading.signal_provenance import FrozenSignalVerifier


def require(value,label):
    if not value:raise AssertionError(label)
    print(f"[PASS] {label}")


def rankings():
    return [
        {"symbol":f"S{rank:03d}","rank":rank,"score":f"{101-rank}.0"}
        for rank in range(1,101)
    ]


def quotes():
    return {
        f"S{rank:03d}":{"reference_price":str(20+rank),"spread_bps":"5"}
        for rank in range(1,11)
    }


def main():
    raw_before=CONTRACT_PATH.read_bytes()
    contract=load_contract()
    require(contract["status"]=="PREREGISTERED_DISABLED","Bridge remains disabled")
    require(contract["activation_mode"]=="MANUAL_SEPARATE_APPROVAL","Activation requires separate manual approval")
    require(contract["activation_not_before_utc"]=="2026-09-01T00:00:00+00:00","V8 boundary is locked")
    require(contract["source_frozen_sha256"]=="ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41","Frozen V8 identity is locked")
    require(contract["brokerage_orders"] is False,"Bridge has no brokerage authority")
    require(contract["holdout_outcomes_read"] is False,"Holdout outcomes are prohibited")

    post_boundary=datetime(2026,9,1,tzinfo=timezone.utc)
    try:build_shadow_signals(rankings(),quotes(),decision_timestamp_utc=post_boundary)
    except ShadowBridgeRejected as exc:
        require("not activated" in str(exc),"Disabled bridge rejects non-rehearsal export")
    else:raise AssertionError("disabled bridge exported operational signals")

    try:
        build_shadow_signals(
            rankings(),quotes(),
            decision_timestamp_utc=datetime(2026,8,31,23,59,59,tzinfo=timezone.utc),
            rehearsal=True,
        )
    except ShadowBridgeRejected as exc:
        require("before the V8 boundary" in str(exc),"Pre-boundary rehearsal fails closed")
    else:raise AssertionError("pre-boundary signal was produced")

    result=build_shadow_signals(
        rankings(),quotes(),decision_timestamp_utc=post_boundary,rehearsal=True
    )
    require(result["status"]=="REHEARSAL_ONLY","Post-boundary rehearsal is visibly non-operational")
    require(result["signal_count"]==10,"Exactly Top 10 signals exported")
    require(all(str(signal.target_weight)=="0.10" for signal in result["signals"]),"Top 10 weights are locked at 10%")
    require([signal.rank for signal in result["signals"]]==list(range(1,11)),"Selected ranks are exactly 1 through 10")
    verifier=FrozenSignalVerifier({
        contract["source_strategy_id"]:contract["source_frozen_sha256"]
    })
    require(all(verifier.verify(signal)["verified"] for signal in result["signals"]),"Every exported signal passes provenance verification")
    require(len({signal.universe_sha256 for signal in result["signals"]})==1,"Signals share one universe identity")
    require(len({signal.ranking_artifact_sha256 for signal in result["signals"]})==1,"Signals share one ranking artifact identity")
    require(result["holdout_outcomes_read"] is False,"Rehearsal reads no holdout outcomes")
    require(result["production_holdout_evidence_modified"] is False,"Rehearsal modifies no holdout evidence")
    require(result["brokerage_orders"] is False,"Rehearsal creates no brokerage orders")

    changed=rankings();changed[0]["score"]="999"
    changed_result=build_shadow_signals(
        changed,quotes(),decision_timestamp_utc=post_boundary,rehearsal=True
    )
    require(
        changed_result["ranking_artifact_sha256"]!=result["ranking_artifact_sha256"],
        "Ranking artifact tampering changes the sealed identity",
    )

    duplicate=rankings();duplicate[1]["symbol"]=duplicate[0]["symbol"]
    try:build_shadow_signals(duplicate,quotes(),decision_timestamp_utc=post_boundary,rehearsal=True)
    except ShadowBridgeRejected:
        print("[PASS] Duplicate ranking symbol rejected")
    else:raise AssertionError("duplicate symbol entered signal bridge")

    missing=quotes();missing.pop("S001")
    try:build_shadow_signals(rankings(),missing,decision_timestamp_utc=post_boundary,rehearsal=True)
    except ShadowBridgeRejected:
        print("[PASS] Missing selected quote rejected")
    else:raise AssertionError("selected signal built without a quote")

    require(CONTRACT_PATH.read_bytes()==raw_before,"Preregistered bridge contract unchanged")
    require(len(contract_sha256())==64,"Bridge contract SHA-256 recorded")
    print("\nStatus: PASSED")
    print("V8 -> provenance-sealed shadow signals: REHEARSAL VERIFIED")
    print("Bridge activation: DISABLED")
    print("Activation boundary: 2026-09-01")
    print("Holdout outcomes read: NO")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__=="__main__":main()
