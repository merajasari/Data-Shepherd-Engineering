"""Read-only pre-holdout V5 shadow portfolio diagnostics.

This service creates an isolated hypothetical V5 portfolio for visual comparison
with the existing V4 paper portfolio. It does not modify V4 state, the frozen V5
model, the Sep 1+ official V5 forward journal, or any brokerage setting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.paper_trading_service import get_execution_price, get_portfolio_summary
from webapp.services.v5_forward_service import score_latest_snapshot

STATE_ROOT = Path("data/paper_trading/v5_shadow")
STATE_PATH = STATE_ROOT / "portfolio.json"
STARTING_EQUITY = 100_000.0
ENTRY_COST_RATE = 0.001


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_state(state):
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)


def initialize_v5_shadow(force=False):
    if STATE_PATH.exists() and not force:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))

    scored = score_latest_snapshot()
    v4 = get_portfolio_summary()
    positions = {}

    for symbol, weight in scored["portfolio"].items():
        quote = get_execution_price(symbol)
        price = quote.get("price")
        if price is None or float(price) <= 0:
            raise RuntimeError(f"No shadow initialization price for {symbol}")
        price = float(price)
        target_cash = STARTING_EQUITY * float(weight)
        effective_price = price * (1.0 + ENTRY_COST_RATE)
        shares = target_cash / effective_price
        entry_cost = target_cash - shares * price
        positions[symbol] = {
            "symbol": symbol,
            "weight": float(weight),
            "shares": shares,
            "market_entry_price": price,
            "average_cost": effective_price,
            "entry_cost": entry_cost,
            "price_source": quote.get("source"),
            "quote_timestamp": quote.get("timestamp"),
        }

    spy_quote = get_execution_price("SPY")
    state = {
        "created_at_utc": _utc_now(),
        "research_mode": "PRE_HOLDOUT_DIAGNOSTIC_SHADOW",
        "starting_equity": STARTING_EQUITY,
        "decision_timestamp_utc": str(scored["decision_timestamp"]),
        "holdout_start_utc": str(scored["holdout_start_utc"]),
        "model_sha256": scored["model_sha256"],
        "entry_cost_rate": ENTRY_COST_RATE,
        "positions": positions,
        "top_five": scored["top_five"],
        "comparison_baselines": {
            "v4_equity": float(v4["equity"]),
            "spy_price": float(spy_quote["price"]) if spy_quote.get("price") is not None else None,
            "captured_at_utc": _utc_now(),
        },
        "official_holdout_journal_written": False,
        "brokerage_orders": False,
    }
    _write_state(state)
    return state


def _load_state():
    if not STATE_PATH.exists():
        return initialize_v5_shadow()
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def get_v5_shadow_comparison():
    state = _load_state()
    positions = []
    equity = 0.0
    total_entry_friction = 0.0

    for symbol, pos in state["positions"].items():
        quote = get_execution_price(symbol)
        current = quote.get("price")
        if current is None:
            current = pos["market_entry_price"]
        current = float(current)
        shares = float(pos["shares"])
        market_value = shares * current
        net_pnl = (current - float(pos["average_cost"])) * shares
        market_move = (current - float(pos["market_entry_price"])) * shares
        entry_cost = float(pos.get("entry_cost", 0.0))
        equity += market_value
        total_entry_friction += entry_cost
        positions.append({
            "symbol": symbol,
            "weight": float(pos["weight"]),
            "shares": shares,
            "entry_price": float(pos["market_entry_price"]),
            "current_price": current,
            "market_value": round(market_value, 2),
            "market_move": round(market_move, 2),
            "net_pnl": round(net_pnl, 2),
            "price_source": quote.get("source"),
            "quote_timestamp": quote.get("timestamp"),
        })

    positions.sort(key=lambda row: (row["symbol"] != "SPY", -row["weight"], row["symbol"]))
    v5_return = equity / STARTING_EQUITY - 1.0

    v4 = get_portfolio_summary()
    base_v4 = float(state["comparison_baselines"]["v4_equity"])
    current_v4 = float(v4["equity"])
    v4_since_shadow = current_v4 / base_v4 - 1.0 if base_v4 else 0.0
    v4_normalized_equity = STARTING_EQUITY * (1.0 + v4_since_shadow)

    spy_quote = get_execution_price("SPY")
    base_spy = state["comparison_baselines"].get("spy_price")
    current_spy = spy_quote.get("price")
    if base_spy and current_spy:
        spy_return = float(current_spy) / float(base_spy) - 1.0
    else:
        spy_return = 0.0
    spy_normalized_equity = STARTING_EQUITY * (1.0 + spy_return)

    return {
        "status": "PRE_HOLDOUT_DIAGNOSTIC_SHADOW",
        "created_at_utc": state["created_at_utc"],
        "decision_timestamp_utc": state["decision_timestamp_utc"],
        "holdout_start_utc": state["holdout_start_utc"],
        "starting_equity": STARTING_EQUITY,
        "v5_shadow_equity": round(equity, 2),
        "v5_shadow_pnl": round(equity - STARTING_EQUITY, 2),
        "v5_shadow_return_pct": round(v5_return * 100.0, 4),
        "v4_baseline_equity": round(base_v4, 2),
        "v4_current_equity": round(current_v4, 2),
        "v4_normalized_equity": round(v4_normalized_equity, 2),
        "v4_since_shadow_return_pct": round(v4_since_shadow * 100.0, 4),
        "spy_normalized_equity": round(spy_normalized_equity, 2),
        "spy_since_shadow_return_pct": round(spy_return * 100.0, 4),
        "v5_vs_v4_pct_points": round((v5_return - v4_since_shadow) * 100.0, 4),
        "v5_vs_spy_pct_points": round((v5_return - spy_return) * 100.0, 4),
        "entry_friction": round(total_entry_friction, 2),
        "top_five": state["top_five"],
        "positions": positions,
        "official_holdout_journal_written": False,
        "brokerage_orders": False,
        "note": "Pre-Sep-1 diagnostic shadow only. These observations are excluded from the official frozen V5 future holdout.",
    }
