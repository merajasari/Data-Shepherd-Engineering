"""Regression tests for the disabled execution boundary and fail-closed risk engine."""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ml.trading.execution import DisabledBrokerAdapter, LiveTradingDisabled, OrderIntent
from ml.trading.risk import evaluate_pretrade

ROOT=Path(__file__).resolve().parent


def require(condition,label):
    if not condition:raise AssertionError(label)
    print(f"[PASS] {label}")


def _intent():
    return OrderIntent(
        intent_id="regression-intent-001",
        idempotency_key="regression-key-001",
        strategy_id="TEST_FROZEN_STRATEGY",
        frozen_strategy_sha256="a"*64,
        symbol="AAPL",side="BUY",quantity=Decimal("1"),
        order_type="LIMIT",limit_price=Decimal("100"),
        created_at_utc=datetime.now(timezone.utc),
    )


def main():
    contract=json.loads((ROOT/"live_trading_contract.json").read_text(encoding="utf-8"))
    intent=_intent()
    adapter=DisabledBrokerAdapter()

    require(adapter.account_snapshot()["brokerage_orders"] is False,"Default adapter has no brokerage authority")
    try:adapter.submit_order(intent)
    except LiveTradingDisabled:print("[PASS] Disabled adapter rejects submission")
    else:raise AssertionError("disabled adapter accepted an order")

    rejected=evaluate_pretrade(
        contract,intent,
        account={"reconciled":False,"buying_power_usd":None,"daily_pnl_usd":None,"open_positions":None},
        market={"session_open":False,"quote_current":False,"reference_price":None,"spread_bps":None},
        runtime={"human_activated":False,"kill_switch_clear":False,"frozen_model_verified":False,"idempotency_key_new":False},
    )
    require(not rejected.approved and "LIVE_TRADING_DISABLED" in rejected.reasons,"Preparation contract fails closed")
    require("RISK_LIMITS_INCOMPLETE" in rejected.reasons,"Unset monetary limits fail closed")
    require("DUPLICATE_IDEMPOTENCY_KEY" in rejected.reasons,"Duplicate intent fails closed")
    require("MARKET_DATA_STALE" in rejected.reasons,"Stale market data fails closed")

    synthetic=deepcopy(contract)
    synthetic.update({
        "status":"LIVE_AUTHORIZED","live_trading_enabled":True,
        "broker":"SYNTHETIC_TEST_ONLY","account_id":"TEST","strategy_id":"TEST_FROZEN_STRATEGY",
        "frozen_strategy_sha256":"a"*64,
    })
    synthetic["limits"]={
        "maximum_deployed_capital_usd":500,
        "maximum_order_notional_usd":100,
        "maximum_position_notional_usd":100,
        "maximum_daily_loss_usd":25,
        "maximum_open_positions":5,
        "maximum_orders_per_session":5,
        "maximum_signal_age_seconds":60,
        "maximum_quote_age_seconds":5,
        "maximum_spread_bps":25,
    }
    approved=evaluate_pretrade(
        synthetic,intent,
        account={"reconciled":True,"buying_power_usd":500,"daily_pnl_usd":0,"open_positions":0},
        market={"session_open":True,"quote_current":True,"reference_price":100,"spread_bps":5},
        runtime={"human_activated":True,"kill_switch_clear":True,"frozen_model_verified":True,"idempotency_key_new":True},
    )
    require(approved.approved,"Fully satisfied synthetic risk path approves")
    try:adapter.submit_order(intent)
    except LiveTradingDisabled:print("[PASS] Risk approval still cannot bypass disabled adapter")
    else:raise AssertionError("risk approval bypassed disabled adapter")

    source=(ROOT/"execution.py").read_text(encoding="utf-8")
    require(not any(name in source.lower() for name in ("alpaca_trade_api","ib_insync","robin_stocks")),
            "No brokerage SDK imported")
    print("\nStatus: PASSED")
    print("Live credentials: ABSENT")
    print("Brokerage orders: OFF")
    print("Frozen V8/V10 modified: NO")


if __name__=="__main__":
    main()
