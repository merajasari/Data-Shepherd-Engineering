"""Read-only readiness report for future live-trading preparation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CONTRACT_PATH=ROOT/"live_trading_contract.json"


def main():
    raw=CONTRACT_PATH.read_bytes()
    contract=json.loads(raw)
    limits=contract.get("limits") or {}
    blockers=[]
    if contract.get("status")!="LIVE_AUTHORIZED":blockers.append("contract is preparation-only")
    if contract.get("live_trading_enabled") is not True:blockers.append("live trading is disabled")
    if not contract.get("broker"):blockers.append("broker is not selected")
    if not contract.get("account_id"):blockers.append("account is not selected")
    if not contract.get("strategy_id") or not contract.get("frozen_strategy_sha256"):
        blockers.append("live strategy identity is not authorized")
    if any(value is None for value in limits.values()):blockers.append("risk limits require explicit approval")

    print("DATA SHEPHERD LIVE-TRADING PREPARATION")
    print("="*80)
    print(f"Status: {'NOT_AUTHORIZED' if blockers else 'READY_FOR_SEPARATE_ACTIVATION_AUDIT'}")
    print(f"Contract SHA-256: {hashlib.sha256(raw).hexdigest()}")
    print(f"Broker: {contract.get('broker') or 'UNSELECTED'}")
    print(f"Live trading enabled: {contract.get('live_trading_enabled') is True}")
    print("Credentials stored in repository: NO")
    print("Brokerage orders: OFF")
    print("BLOCKERS:")
    for blocker in blockers:print(f" - {blocker}")
    if not blockers:raise SystemExit("Activation audit is required; readiness does not grant order authority.")


if __name__=="__main__":
    main()
