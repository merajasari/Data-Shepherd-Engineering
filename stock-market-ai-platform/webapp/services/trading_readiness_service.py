"""Read-only presentation service for the live-trading preparation contract."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from webapp.services.paper_shadow_service import get_paper_shadow_status
from webapp.services.paper_shadow_bridge_service import get_paper_shadow_bridge_status
from webapp.services.paper_shadow_scheduler_service import get_paper_shadow_scheduler_status

CONTRACT_PATH=Path("ml/trading/live_trading_contract.json")
PAPER_CHECKPOINT_PATH=Path("data/trading/readiness/paper_engineering_status.json")


def _paper_engineering_status():
    default={
        "status":"NOT_VALIDATED",
        "validated_at_utc":None,
        "mode":"PAPER_ONLY",
        "modules":[],
        "lifecycle":[],
        "restart_recovery":False,
        "idempotency":False,
        "concurrency_safety":False,
        "reconciliation":False,
        "failure_injection":False,
        "signal_provenance":False,
        "sandbox_orchestration":False,
        "persistent_paper_shadow":False,
        "atomic_shadow_state":False,
        "controlled_signal_bridge":False,
        "bridge_activation_disabled":False,
        "paper_shadow_scheduler":False,
        "scheduler_monitor_only":False,
        "operational_change_control":False,
        "protected_runtime_locked":False,
        "live_credentials":False,
        "brokerage_orders":False,
        "production_evidence_modified":False,
    }
    try:
        payload=json.loads(PAPER_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError,OSError):
        return default
    if not isinstance(payload,dict):
        return default
    safe={**default,**payload}
    # Presentation fails closed even if the generated file is malformed.
    safe["brokerage_orders"]=False
    safe["live_credentials"]=False
    return safe


def get_trading_readiness():
    raw=CONTRACT_PATH.read_bytes()
    contract=json.loads(raw)
    limits=contract.get("limits") or {}
    blockers=[]
    checks=[
        ("Contract live-authorized",contract.get("status")=="LIVE_AUTHORIZED"),
        ("Live trading enabled",contract.get("live_trading_enabled") is True),
        ("Broker selected",bool(contract.get("broker"))),
        ("Account selected",bool(contract.get("account_id"))),
        ("Strategy identity authorized",bool(contract.get("strategy_id") and contract.get("frozen_strategy_sha256"))),
        ("Risk limits configured",bool(limits) and all(value is not None for value in limits.values())),
        ("Human activation required",contract.get("human_activation_required") is True),
        ("Repository credentials prohibited",(contract.get("credentials") or {}).get("may_be_stored_in_repository") is False),
        ("Brokerage orders off",contract.get("brokerage_orders") is False),
    ]
    for label,passed in checks:
        if not passed and label not in {"Human activation required"}:blockers.append(label)
    return {
        "status":"NOT_AUTHORIZED" if blockers else "READY_FOR_SEPARATE_ACTIVATION_AUDIT",
        "contract_status":contract.get("status"),
        "contract_sha256":hashlib.sha256(raw).hexdigest(),
        "broker":contract.get("broker") or "UNSELECTED",
        "account":"NOT CONNECTED" if not contract.get("account_id") else "CONFIGURED (ID HIDDEN)",
        "strategy":"NOT AUTHORIZED" if not contract.get("strategy_id") else str(contract.get("strategy_id")),
        "live_trading_enabled":contract.get("live_trading_enabled") is True,
        "human_activation_required":contract.get("human_activation_required") is True,
        "brokerage_orders":contract.get("brokerage_orders") is True,
        "credentials_in_repository":False,
        "checks":[{"label":label,"passed":passed} for label,passed in checks],
        "blockers":blockers,
        "required_runtime_gates":contract.get("required_runtime_gates") or [],
        "prohibited":[name.replace("_"," ").upper() for name,value in (contract.get("prohibited") or {}).items() if value],
        "limits":[{"label":name.replace("_"," ").upper(),"configured":value is not None} for name,value in limits.items()],
        "paper_engineering":_paper_engineering_status(),
        "paper_shadow":get_paper_shadow_status(),
        "paper_shadow_bridge":get_paper_shadow_bridge_status(),
        "paper_shadow_scheduler":get_paper_shadow_scheduler_status(),
    }
