"""Isolated forward paper trading for the frozen V5 strategy.

Simulation only.  This service deliberately uses its own state and never
reads or writes the existing V4 paper portfolio.

V5 contract:
  * 60% SPY core
  * 40% frozen-V5 top-five sleeve
  * 8% per selected stock
  * rebalance every 5 trading sessions
  * 10 bps simulated friction on buys and sells

A ranking produced from session D is never executed at D's close.  Execution
is allowed only when a market price dated after the ranking decision date is
available, preventing same-close look-ahead in the forward test.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from webapp.services.paper_trading_service import get_execution_price

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / "data/paper_trading_v5"
STATE_PATH = STATE_DIR / "portfolio.json"
JOURNAL_PATH = STATE_DIR / "journal.jsonl"
RANKING_PATH = PROJECT_ROOT / "data/live/v5_latest_rankings.json"
SPY_FEATURE_PATH = PROJECT_ROOT / "data/features/stocks/SPY/SPY_features.parquet"

STARTING_CASH = 100_000.0
ENTRY_COST_RATE = 0.001
EXIT_COST_RATE = 0.001


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict:
    return {
        "created_at": _now(),
        "updated_at": _now(),
        "starting_cash": STARTING_CASH,
        "cash": STARTING_CASH,
        "positions": {},
        "trades": [],
        "realized_pnl": 0.0,
        "last_rebalance_decision_date_utc": None,
        "strategy": {
            "name": "spy_core_v5_top5",
            "core_symbol": "SPY",
            "core_allocation": 0.60,
            "stock_sleeve_allocation": 0.40,
            "position_count": 5,
            "position_allocation": 0.08,
            "rebalance_trading_days": 5,
            "entry_cost_rate": ENTRY_COST_RATE,
            "exit_cost_rate": EXIT_COST_RATE,
        },
    }


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return _default_state()
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(STATE_PATH)


def _load_rankings() -> dict:
    if not RANKING_PATH.exists():
        raise FileNotFoundError(f"V5 ranking artifact not found: {RANKING_PATH}")
    payload = json.loads(RANKING_PATH.read_text(encoding="utf-8"))
    if payload.get("research_version") != "v5":
        raise RuntimeError("Ranking artifact is not V5")
    rows = payload.get("rankings", [])
    selected = [row for row in rows if row.get("selected_top5")]
    if len(rows) != 100 or len(selected) != 5:
        raise RuntimeError("V5 ranking artifact must contain 100 candidates and exactly 5 selected names")
    return payload


def _date(value) -> pd.Timestamp:
    return pd.Timestamp(value).tz_convert("UTC") if pd.Timestamp(value).tzinfo else pd.Timestamp(value).tz_localize("UTC")


def _execution_quote_after_decision(symbol: str, decision_date: pd.Timestamp) -> dict:
    quote = get_execution_price(symbol)
    if quote.get("price") is None or not quote.get("timestamp"):
        raise RuntimeError(f"Execution price unavailable for {symbol}")
    quote_ts = _date(quote["timestamp"])
    if quote_ts.normalize() <= decision_date.normalize():
        raise RuntimeError(
            f"V5 forward execution for {symbol} is not open yet: ranking uses "
            f"{decision_date.date()} data and available price is dated {quote_ts.date()}. "
            "Wait for the next trading session."
        )
    return quote


def _sessions_since(previous_decision: str, current_decision: str) -> int:
    if not previous_decision:
        return 10**9
    frame = pd.read_parquet(SPY_FEATURE_PATH, columns=["timestamp_utc"])
    sessions = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna().drop_duplicates().sort_values()
    previous = _date(previous_decision).normalize()
    current = _date(current_decision).normalize()
    return int(((sessions > previous) & (sessions <= current)).sum())


def get_v5_portfolio_summary() -> dict:
    state = _load_state()
    market_value = 0.0
    unrealized = 0.0
    positions = []
    for symbol, position in state.get("positions", {}).items():
        quote = get_execution_price(symbol)
        current = float(quote["price"]) if quote.get("price") is not None else float(position["average_cost"])
        shares = float(position["shares"])
        value = shares * current
        pnl = (current - float(position["average_cost"])) * shares
        market_value += value
        unrealized += pnl
        positions.append({
            "symbol": symbol,
            "sleeve": position.get("sleeve"),
            "shares": shares,
            "average_cost": float(position["average_cost"]),
            "current_price": current,
            "market_value": round(value, 2),
            "unrealized_pnl": round(pnl, 2),
            "price_source": quote.get("source"),
        })
    cash = float(state.get("cash", STARTING_CASH))
    equity = cash + market_value
    return {
        "starting_cash": STARTING_CASH,
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "equity": round(equity, 2),
        "realized_pnl": round(float(state.get("realized_pnl", 0.0)), 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_return_pct": round((equity / STARTING_CASH - 1.0) * 100.0, 4),
        "open_position_count": len(positions),
        "trade_count": len(state.get("trades", [])),
        "positions": positions,
        "last_rebalance_decision_date_utc": state.get("last_rebalance_decision_date_utc"),
    }


def _sell(state: dict, symbol: str, timestamp: str) -> None:
    position = state["positions"][symbol]
    quote = get_execution_price(symbol)
    if quote.get("price") is None:
        raise RuntimeError(f"Cannot sell {symbol}: execution price unavailable")
    market_price = float(quote["price"])
    shares = float(position["shares"])
    gross = shares * market_price
    cost = gross * EXIT_COST_RATE
    net = gross - cost
    basis = shares * float(position["average_cost"])
    pnl = net - basis
    state["cash"] = float(state["cash"]) + net
    state["realized_pnl"] = float(state.get("realized_pnl", 0.0)) + pnl
    state["trades"].append({
        "timestamp": timestamp, "action": "SELL", "symbol": symbol,
        "sleeve": position.get("sleeve"), "shares": shares,
        "market_price": market_price, "exit_cost": cost,
        "net_proceeds": net, "realized_pnl": pnl,
        "price_source": quote.get("source"),
    })
    del state["positions"][symbol]


def _buy(state: dict, symbol: str, sleeve: str, allocation: float, rank: int | None,
         predicted_return: float | None, decision_date: pd.Timestamp, timestamp: str,
         equity: float) -> None:
    quote = _execution_quote_after_decision(symbol, decision_date)
    market_price = float(quote["price"])
    target_value = equity * allocation
    cash_to_use = min(target_value, float(state["cash"]))
    if cash_to_use <= 0:
        raise RuntimeError(f"No paper cash available to buy {symbol}")
    effective = market_price * (1.0 + ENTRY_COST_RATE)
    shares = cash_to_use / effective
    cash_used = shares * effective
    entry_cost = shares * market_price * ENTRY_COST_RATE
    state["cash"] = float(state["cash"]) - cash_used
    state["positions"][symbol] = {
        "symbol": symbol, "sleeve": sleeve, "shares": shares,
        "average_cost": effective, "market_entry_price": market_price,
        "entry_cost": entry_cost, "target_allocation": allocation,
        "opened_at": timestamp, "price_source": quote.get("source"),
        "rank": rank, "predicted_relative_return_5d": predicted_return,
        "decision_date_utc": decision_date.isoformat(),
    }
    state["trades"].append({
        "timestamp": timestamp, "action": "BUY", "symbol": symbol,
        "sleeve": sleeve, "shares": shares, "market_price": market_price,
        "effective_price": effective, "entry_cost": entry_cost,
        "cash_used": cash_used, "target_allocation": allocation,
        "price_source": quote.get("source"), "rank": rank,
        "predicted_relative_return_5d": predicted_return,
        "decision_date_utc": decision_date.isoformat(),
    })


def run_v5_paper_cycle() -> dict:
    payload = _load_rankings()
    decision = _date(payload["decision_date_utc"]).normalize()
    top5 = sorted(
        [row for row in payload["rankings"] if row.get("selected_top5")],
        key=lambda row: row["rank"],
    )
    target_symbols = [row["symbol"] for row in top5]
    state = _load_state()
    previous = state.get("last_rebalance_decision_date_utc")
    sessions = _sessions_since(previous, decision.isoformat())

    if previous and sessions < int(payload.get("rebalance_trading_days", 5)):
        summary = get_v5_portfolio_summary()
        observation = _append_journal(summary, payload, target_symbols, [], "HOLD")
        return {"status": "HOLD", "sessions_since_rebalance": sessions,
                "target_symbols": target_symbols, "summary": summary, "journal": observation}

    # Fail closed before mutating anything: all required new buys must have a
    # next-session price.  This is especially important for initial launch.
    required = ["SPY"] if not state.get("positions") else []
    current_v5 = {s for s, p in state.get("positions", {}).items() if p.get("sleeve") == "v5"}
    required.extend([s for s in target_symbols if s not in current_v5])
    for symbol in required:
        _execution_quote_after_decision(symbol, decision)

    timestamp = _now()
    actions = []
    if not state.get("positions"):
        state = _default_state()
        _buy(state, "SPY", "core", float(payload.get("benchmark_weight", 0.60)), None, None,
             decision, timestamp, STARTING_CASH)
        actions.append({"action": "BUY", "symbol": "SPY", "sleeve": "core"})
    else:
        for symbol in sorted(current_v5 - set(target_symbols)):
            _sell(state, symbol, timestamp)
            actions.append({"action": "SELL", "symbol": symbol, "sleeve": "v5"})

    # Mark equity after exits, then fund each new V5 name to the frozen 8% target.
    _save_state(state)
    equity = float(get_v5_portfolio_summary()["equity"])
    for row in top5:
        symbol = row["symbol"]
        if symbol in state["positions"]:
            continue
        _buy(state, symbol, "v5", float(payload.get("weight_per_selected_stock", 0.08)),
             int(row["rank"]), float(row["predicted_relative_return_5d"]),
             decision, timestamp, equity)
        actions.append({"action": "BUY", "symbol": symbol, "sleeve": "v5", "rank": int(row["rank"])})

    state["last_rebalance_decision_date_utc"] = decision.isoformat()
    _save_state(state)
    summary = get_v5_portfolio_summary()
    observation = _append_journal(summary, payload, target_symbols, actions, "REBALANCE")
    return {"status": "REBALANCE", "sessions_since_rebalance": sessions,
            "target_symbols": target_symbols, "actions": actions,
            "summary": summary, "journal": observation}


def _append_journal(summary: dict, payload: dict, top5: list[str], actions: list[dict], status: str) -> dict:
    observation = {
        "timestamp": _now(), "status": status,
        "decision_date_utc": payload["decision_date_utc"],
        "model_id": payload.get("model_id"), "top_five_symbols": top5,
        "equity": summary["equity"], "cash": summary["cash"],
        "market_value": summary["market_value"],
        "realized_pnl": summary["realized_pnl"],
        "unrealized_pnl": summary["unrealized_pnl"],
        "total_return_pct": summary["total_return_pct"],
        "trade_count": summary["trade_count"], "trade_actions": actions,
        "benchmark_symbol": "SPY",
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, sort_keys=True) + "\n")
    return observation
