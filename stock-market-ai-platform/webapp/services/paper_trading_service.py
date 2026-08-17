"""
Paper-trading service for the Stock Market AI Platform.

This module manages simulated portfolio state only.
It does not place real brokerage orders.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.live_market_service import (
    get_live_quote,
)
from webapp.services.market_service import (
    get_market_summary,
)


STATE_DIR = Path("data/paper_trading")

STATE_PATH = (
    STATE_DIR
    / "portfolio.json"
)

STARTING_CASH = 100_000.00


def utc_now():
    return (
        datetime.now(timezone.utc)
        .isoformat()
    )


def default_state():
    return {
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "starting_cash": STARTING_CASH,
        "cash": STARTING_CASH,
        "positions": {},
        "trades": [],
        "realized_pnl": 0.0,

        "strategy": {
            "name": "spy_core_v4_overlay",
            "core_symbol": "SPY",
            "core_allocation": 0.60,
            "v4_allocation": 0.40,
            "v4_position_count": 5,
            "v4_position_allocation": 0.08,
        },
    }


def save_state(state):
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    state["updated_at"] = utc_now()

    temp_path = STATE_PATH.with_suffix(
        ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    temp_path.replace(
        STATE_PATH
    )


def load_state():
    if not STATE_PATH.exists():
        state = default_state()
        save_state(state)
        return state

    try:
        state = json.loads(
            STATE_PATH.read_text(
                encoding="utf-8"
            )
        )

        if "strategy" not in state:
            state["strategy"] = {
                "name": "spy_core_v4_overlay",
                "core_symbol": "SPY",
                "core_allocation": 0.60,
                "v4_allocation": 0.40,
                "v4_position_count": 5,
                "v4_position_allocation": 0.08,
            }

            save_state(
                state
            )

        return state

    except (
        json.JSONDecodeError,
        OSError,
    ):
        state = default_state()
        save_state(state)
        return state


def get_execution_price(symbol):
    """
    Resolve a simulated execution price.

    Priority:
        1. Live Tiingo IEX reference price
        2. Latest EOD close
        3. No price available
    """

    symbol = (
        symbol
        .upper()
        .strip()
    )

    live = get_live_quote(
        symbol
    )

    if (
        live.get("available")
        and live.get("reference_price")
        is not None
    ):
        price = float(
            live["reference_price"]
        )

        if price > 0:
            return {
                "symbol": symbol,
                "price": price,
                "source": "LIVE IEX",
                "timestamp":
                    live.get(
                        "timestamp"
                    ),
            }

    try:
        market = get_market_summary(
            symbol
        )

        price = float(
            market["close"]
        )

        if price > 0:
            return {
                "symbol": symbol,
                "price": price,
                "source": "LATEST EOD",
                "timestamp":
                    market.get(
                        "timestamp"
                    ),
            }

    except Exception:
        pass

    return {
        "symbol": symbol,
        "price": None,
        "source": "UNAVAILABLE",
        "timestamp": None,
    }


def get_portfolio_summary():
    """
    Mark all simulated positions to current market prices.
    """

    state = load_state()

    market_value = 0.0
    unrealized_pnl = 0.0

    positions = []

    for symbol, position in (
        state.get(
            "positions",
            {}
        ).items()
    ):
        quote = get_execution_price(
            symbol
        )

        shares = float(
            position.get(
                "shares",
                0.0,
            )
        )

        average_cost = float(
            position.get(
                "average_cost",
                0.0,
            )
        )

        current_price = (
            quote["price"]
            if quote["price"]
            is not None
            else average_cost
        )

        position_value = (
            shares
            * current_price
        )

        position_pnl = (
            current_price
            - average_cost
        ) * shares

        market_value += (
            position_value
        )

        unrealized_pnl += (
            position_pnl
        )

        positions.append(
            {
                "symbol": symbol,
                "shares": shares,
                "average_cost":
                    average_cost,
                "current_price":
                    current_price,
                "market_value":
                    round(
                        position_value,
                        2,
                    ),
                "unrealized_pnl":
                    round(
                        position_pnl,
                        2,
                    ),
                "price_source":
                    quote["source"],
            }
        )

    cash = float(
        state.get(
            "cash",
            STARTING_CASH,
        )
    )

    equity = (
        cash
        + market_value
    )

    total_return = (
        (
            equity
            - STARTING_CASH
        )
        / STARTING_CASH
    )

    return {
        "starting_cash":
            STARTING_CASH,

        "cash":
            round(
                cash,
                2,
            ),

        "market_value":
            round(
                market_value,
                2,
            ),

        "equity":
            round(
                equity,
                2,
            ),

        "realized_pnl":
            round(
                float(
                    state.get(
                        "realized_pnl",
                        0.0,
                    )
                ),
                2,
            ),

        "unrealized_pnl":
            round(
                unrealized_pnl,
                2,
            ),

        "total_return_pct":
            round(
                total_return
                * 100.0,
                4,
            ),

        "open_position_count":
            len(positions),

        "trade_count":
            len(
                state.get(
                    "trades",
                    []
                )
            ),

        "positions":
            positions,

        "updated_at":
            state.get(
                "updated_at"
            ),
    }



def get_pnl_attribution():
    """Return read-only dollar attribution for the simulated V4 portfolio.

    Separates current open-position market movement from modeled entry friction,
    realized paper P&L, sleeve contribution, and completed rebalance costs.
    No portfolio state is modified.
    """

    state = load_state()
    rows = []

    open_entry_friction = 0.0
    open_market_move = 0.0
    core_net_pnl = 0.0
    v4_net_pnl = 0.0

    for symbol, position in state.get("positions", {}).items():
        quote = get_execution_price(symbol)
        shares = float(position.get("shares", 0.0))
        average_cost = float(position.get("average_cost", 0.0))
        market_entry_price = float(
            position.get("market_entry_price", average_cost)
        )
        current_price = quote.get("price")
        if current_price is None:
            current_price = average_cost
        current_price = float(current_price)

        entry_cost = float(position.get("entry_cost", 0.0))
        market_move = (current_price - market_entry_price) * shares
        net_pnl = (current_price - average_cost) * shares
        sleeve = str(position.get("sleeve", "unknown"))

        open_entry_friction += entry_cost
        open_market_move += market_move
        if sleeve == "core":
            core_net_pnl += net_pnl
        elif sleeve == "v4":
            v4_net_pnl += net_pnl

        rows.append(
            {
                "symbol": symbol,
                "sleeve": sleeve,
                "shares": shares,
                "market_entry_price": market_entry_price,
                "average_cost": average_cost,
                "current_price": current_price,
                "entry_friction": round(entry_cost, 2),
                "market_move": round(market_move, 2),
                "net_pnl": round(net_pnl, 2),
                "price_source": quote.get("source"),
                "quote_timestamp": quote.get("timestamp"),
            }
        )

    rows.sort(key=lambda row: row["net_pnl"], reverse=True)

    trades = list(state.get("trades", []))
    sold_symbols = {
        str(trade.get("symbol", ""))
        for trade in trades
        if trade.get("action") == "SELL"
    }

    total_trade_friction = 0.0
    realized_rebalance_cost = 0.0
    for trade in trades:
        entry_cost = float(trade.get("entry_cost", 0.0) or 0.0)
        exit_cost = float(trade.get("exit_cost", 0.0) or 0.0)
        total_trade_friction += entry_cost + exit_cost
        if str(trade.get("symbol", "")) in sold_symbols:
            realized_rebalance_cost += entry_cost + exit_cost

    realized_pnl = float(state.get("realized_pnl", 0.0))
    total_pnl = core_net_pnl + v4_net_pnl + realized_pnl

    return {
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "core_net_pnl": round(core_net_pnl, 2),
        "v4_net_pnl": round(v4_net_pnl, 2),
        "open_position_market_move": round(open_market_move, 2),
        "open_position_entry_friction": round(open_entry_friction, 2),
        "total_friction": round(total_trade_friction, 2),
        "realized_rebalance_cost": round(realized_rebalance_cost, 2),
        "best_contributor": rows[0] if rows else None,
        "worst_contributor": rows[-1] if rows else None,
        "positions": rows,
        "brokerage_orders": False,
    }

def evaluate_trade_candidates(
    symbols,
):
    """
    Evaluate V4 cross-sectional rankings for potential
    paper-trading entries.

    This function only identifies candidates.
    It does not execute trades.
    """

    from webapp.services.ranking_service_v4 import (
        rank_latest_universe,
    )

    rankings = rank_latest_universe()

    allowed_symbols = {
        symbol.upper().strip()
        for symbol in symbols
    }

    state = load_state()

    existing_positions = set(
        state.get(
            "positions",
            {}
        ).keys()
    )

    candidates = []

    for ranking in rankings:

        symbol = ranking[
            "symbol"
        ]

        if symbol not in allowed_symbols:
            continue

        reasons = []

        if not ranking.get(
            "selected",
            False,
        ):
            reasons.append(
                "outside_v4_top5"
            )

        if symbol in existing_positions:
            reasons.append(
                "position_already_open"
            )

        quote = get_execution_price(
            symbol
        )

        if quote["price"] is None:
            reasons.append(
                "execution_price_unavailable"
            )

        eligible = (
            len(reasons) == 0
        )

        candidates.append(
            {
                "symbol":
                    symbol,

                "eligible":
                    eligible,

                "rank":
                    int(
                        ranking[
                            "rank"
                        ]
                    ),

                "probability_top5":
                    float(
                        ranking[
                            "probability_top5"
                        ]
                    ),

                "selected":
                    bool(
                        ranking[
                            "selected"
                        ]
                    ),

                "model_timestamp":
                    ranking.get(
                        "timestamp"
                    ),

                "model_close":
                    ranking.get(
                        "close"
                    ),

                "execution_price":
                    quote[
                        "price"
                    ],

                "price_source":
                    quote[
                        "source"
                    ],

                "rejection_reasons":
                    reasons,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["eligible"],
            -item["rank"],
        ),
        reverse=True,
    )

    return candidates


def build_target_portfolio_plan(symbols):
    """
    Build the frozen SPY-core + V4-overlay target portfolio.

    This function is read-only.
    It does not modify paper-trading state.
    """

    state = load_state()

    strategy = state.get(
        "strategy",
        {}
    )

    core_symbol = strategy.get(
        "core_symbol",
        "SPY",
    )

    core_allocation = float(
        strategy.get(
            "core_allocation",
            0.60,
        )
    )

    v4_position_allocation = float(
        strategy.get(
            "v4_position_allocation",
            0.08,
        )
    )

    candidates = evaluate_trade_candidates(
        symbols
    )

    selected = [
        candidate
        for candidate in candidates
        if candidate.get(
            "eligible"
        )
    ][:5]

    core_quote = get_execution_price(
        core_symbol
    )

    plan = []

    plan.append(
        {
            "symbol":
                core_symbol,

            "sleeve":
                "core",

            "target_allocation":
                core_allocation,

            "execution_price":
                core_quote.get(
                    "price"
                ),

            "price_source":
                core_quote.get(
                    "source"
                ),

            "rank":
                None,

            "probability_top5":
                None,

            "available":
                core_quote.get(
                    "price"
                ) is not None,
        }
    )

    for candidate in selected:

        plan.append(
            {
                "symbol":
                    candidate[
                        "symbol"
                    ],

                "sleeve":
                    "v4",

                "target_allocation":
                    v4_position_allocation,

                "execution_price":
                    candidate[
                        "execution_price"
                    ],

                "price_source":
                    candidate[
                        "price_source"
                    ],

                "rank":
                    candidate[
                        "rank"
                    ],

                "probability_top5":
                    candidate[
                        "probability_top5"
                    ],

                "available":
                    candidate[
                        "execution_price"
                    ] is not None,
            }
        )

    return {
        "strategy":
            strategy,

        "starting_cash":
            float(
                state.get(
                    "starting_cash",
                    STARTING_CASH,
                )
            ),

        "cash":
            float(
                state.get(
                    "cash",
                    STARTING_CASH,
                )
            ),

        "target_allocation_total":
            sum(
                item[
                    "target_allocation"
                ]
                for item in plan
            ),

        "positions":
            plan,
    }


PAPER_ENTRY_COST_RATE = 0.001


def initialize_strategy_positions(symbols):
    """
    Initialize the frozen SPY-core + V4-overlay paper portfolio.

    Simulation only.

    Safety:
      - refuses to run if positions already exist
      - refuses to run if trade history already exists
      - uses fractional shares
      - includes simulated entry friction
    """

    state = load_state()

    existing_positions = state.get(
        "positions",
        {},
    )

    existing_trades = state.get(
        "trades",
        [],
    )

    if existing_positions:
        raise RuntimeError(
            "Paper portfolio already has open positions"
        )

    if existing_trades:
        raise RuntimeError(
            "Paper portfolio already has trade history"
        )

    plan = build_target_portfolio_plan(
        symbols
    )

    positions = plan[
        "positions"
    ]

    unavailable = [
        item["symbol"]
        for item in positions
        if not item.get(
            "available",
            False,
        )
    ]

    if unavailable:
        raise RuntimeError(
            "Execution price unavailable for: "
            + ", ".join(
                unavailable
            )
        )

    allocation_total = float(
        plan[
            "target_allocation_total"
        ]
    )

    if abs(
        allocation_total
        - 1.0
    ) > 1e-9:
        raise RuntimeError(
            f"Target allocations must total 1.0; "
            f"got {allocation_total}"
        )

    starting_equity = float(
        state.get(
            "starting_cash",
            STARTING_CASH,
        )
    )

    cash = float(
        state.get(
            "cash",
            STARTING_CASH,
        )
    )

    if cash < starting_equity:
        raise RuntimeError(
            "Insufficient paper cash for initialization"
        )

    opened_at = utc_now()

    new_positions = {}

    trade_records = []

    for item in positions:

        symbol = item[
            "symbol"
        ]

        market_price = float(
            item[
                "execution_price"
            ]
        )

        target_allocation = float(
            item[
                "target_allocation"
            ]
        )

        target_cash = (
            starting_equity
            * target_allocation
        )

        effective_price = (
            market_price
            * (
                1.0
                + PAPER_ENTRY_COST_RATE
            )
        )

        shares = (
            target_cash
            / effective_price
        )

        cash_used = (
            shares
            * effective_price
        )

        entry_cost = (
            shares
            * market_price
            * PAPER_ENTRY_COST_RATE
        )

        cash -= cash_used

        new_positions[
            symbol
        ] = {
            "symbol":
                symbol,

            "sleeve":
                item[
                    "sleeve"
                ],

            "shares":
                shares,

            "average_cost":
                effective_price,

            "market_entry_price":
                market_price,

            "entry_cost":
                entry_cost,

            "target_allocation":
                target_allocation,

            "opened_at":
                opened_at,

            "price_source":
                item[
                    "price_source"
                ],

            "rank":
                item.get(
                    "rank"
                ),

            "probability_top5":
                item.get(
                    "probability_top5"
                ),
        }

        trade_records.append(
            {
                "timestamp":
                    opened_at,

                "action":
                    "BUY",

                "symbol":
                    symbol,

                "sleeve":
                    item[
                        "sleeve"
                    ],

                "shares":
                    shares,

                "market_price":
                    market_price,

                "effective_price":
                    effective_price,

                "entry_cost":
                    entry_cost,

                "cash_used":
                    cash_used,

                "target_allocation":
                    target_allocation,

                "price_source":
                    item[
                        "price_source"
                    ],

                "rank":
                    item.get(
                        "rank"
                    ),

                "probability_top5":
                    item.get(
                        "probability_top5"
                    ),
            }
        )

    if cash < -0.01:
        raise RuntimeError(
            f"Initialization produced negative cash: {cash}"
        )

    state[
        "positions"
    ] = new_positions

    state[
        "trades"
    ] = trade_records

    state[
        "cash"
    ] = max(
        0.0,
        cash,
    )

    state[
        "strategy_started_at"
    ] = opened_at

    save_state(
        state
    )

    return get_portfolio_summary()


def build_rebalance_plan(symbols):
    """
    Build a read-only rebalance plan for the frozen strategy.

    SPY remains the permanent core holding.
    The V4 sleeve is compared against the latest top-5 ranking.

    This function does not modify paper-trading state.
    """

    state = load_state()

    strategy = state.get(
        "strategy",
        {},
    )

    core_symbol = strategy.get(
        "core_symbol",
        "SPY",
    )

    core_allocation = float(
        strategy.get(
            "core_allocation",
            0.60,
        )
    )

    v4_position_allocation = float(
        strategy.get(
            "v4_position_allocation",
            0.08,
        )
    )

    rankings = evaluate_trade_candidates(
        symbols
    )

    target_v4 = [
        row
        for row in rankings
        if row.get(
            "selected",
            False,
        )
    ][:5]

    target_v4_symbols = {
        row["symbol"]
        for row in target_v4
    }

    positions = state.get(
        "positions",
        {},
    )

    current_v4_symbols = {
        symbol
        for symbol, position in positions.items()
        if position.get(
            "sleeve"
        ) == "v4"
    }

    summary = get_portfolio_summary()

    equity = float(
        summary[
            "equity"
        ]
    )

    actions = []

    # Core should remain in place.
    core_position = positions.get(
        core_symbol
    )

    actions.append(
        {
            "action":
                "KEEP"
                if core_position
                else "BUY",

            "symbol":
                core_symbol,

            "sleeve":
                "core",

            "target_allocation":
                core_allocation,

            "target_value":
                equity
                * core_allocation,

            "rank":
                None,

            "probability_top5":
                None,
        }
    )

    # Exit V4 names that are no longer in the top five.
    for symbol in sorted(
        current_v4_symbols
        - target_v4_symbols
    ):
        actions.append(
            {
                "action":
                    "SELL",

                "symbol":
                    symbol,

                "sleeve":
                    "v4",

                "target_allocation":
                    0.0,

                "target_value":
                    0.0,

                "rank":
                    None,

                "probability_top5":
                    None,
            }
        )

    # Keep or buy current target names.
    for row in target_v4:

        symbol = row[
            "symbol"
        ]

        actions.append(
            {
                "action":
                    (
                        "KEEP"
                        if symbol
                        in current_v4_symbols
                        else "BUY"
                    ),

                "symbol":
                    symbol,

                "sleeve":
                    "v4",

                "target_allocation":
                    v4_position_allocation,

                "target_value":
                    equity
                    * v4_position_allocation,

                "rank":
                    row[
                        "rank"
                    ],

                "probability_top5":
                    row[
                        "probability_top5"
                    ],
            }
        )

    return {
        "equity":
            equity,

        "current_v4_symbols":
            sorted(
                current_v4_symbols
            ),

        "target_v4_symbols":
            [
                row["symbol"]
                for row in target_v4
            ],

        "actions":
            actions,
    }


PAPER_EXIT_COST_RATE = 0.001


def execute_rebalance(symbols):
    """
    Execute the current V4 rebalance plan against the simulated account.

    Simulation only.
    SPY remains untouched as the permanent core holding.
    """

    state = load_state()

    plan = build_rebalance_plan(
        symbols
    )

    actions = plan[
        "actions"
    ]

    positions = state.get(
        "positions",
        {}
    )

    trades = state.get(
        "trades",
        []
    )

    cash = float(
        state.get(
            "cash",
            0.0,
        )
    )

    realized_pnl = float(
        state.get(
            "realized_pnl",
            0.0,
        )
    )

    timestamp = utc_now()

    # --------------------------------------------------
    # SELL first so replacement capital becomes available.
    # --------------------------------------------------
    for action in actions:

        if action[
            "action"
        ] != "SELL":
            continue

        symbol = action[
            "symbol"
        ]

        position = positions.get(
            symbol
        )

        if position is None:
            continue

        quote = get_execution_price(
            symbol
        )

        market_price = quote.get(
            "price"
        )

        if market_price is None:
            raise RuntimeError(
                f"Cannot sell {symbol}: "
                f"execution price unavailable"
            )

        market_price = float(
            market_price
        )

        shares = float(
            position[
                "shares"
            ]
        )

        gross_proceeds = (
            shares
            * market_price
        )

        exit_cost = (
            gross_proceeds
            * PAPER_EXIT_COST_RATE
        )

        net_proceeds = (
            gross_proceeds
            - exit_cost
        )

        cost_basis = (
            shares
            * float(
                position[
                    "average_cost"
                ]
            )
        )

        pnl = (
            net_proceeds
            - cost_basis
        )

        cash += net_proceeds
        realized_pnl += pnl

        trades.append(
            {
                "timestamp":
                    timestamp,

                "action":
                    "SELL",

                "symbol":
                    symbol,

                "sleeve":
                    "v4",

                "shares":
                    shares,

                "market_price":
                    market_price,

                "exit_cost":
                    exit_cost,

                "net_proceeds":
                    net_proceeds,

                "realized_pnl":
                    pnl,

                "price_source":
                    quote.get(
                        "source"
                    ),
            }
        )

        del positions[
            symbol
        ]

    # --------------------------------------------------
    # BUY replacements.
    # --------------------------------------------------
    summary = get_portfolio_summary()

    equity = float(
        summary[
            "equity"
        ]
    )

    for action in actions:

        if action[
            "action"
        ] != "BUY":
            continue

        symbol = action[
            "symbol"
        ]

        # SPY core initialization is handled separately.
        if action[
            "sleeve"
        ] == "core":
            continue

        if symbol in positions:
            continue

        quote = get_execution_price(
            symbol
        )

        market_price = quote.get(
            "price"
        )

        if market_price is None:
            raise RuntimeError(
                f"Cannot buy {symbol}: "
                f"execution price unavailable"
            )

        market_price = float(
            market_price
        )

        target_value = (
            equity
            * float(
                action[
                    "target_allocation"
                ]
            )
        )

        effective_price = (
            market_price
            * (
                1.0
                + PAPER_ENTRY_COST_RATE
            )
        )

        cash_to_use = min(
            target_value,
            cash,
        )

        if cash_to_use <= 0:
            continue

        shares = (
            cash_to_use
            / effective_price
        )

        cash_used = (
            shares
            * effective_price
        )

        entry_cost = (
            shares
            * market_price
            * PAPER_ENTRY_COST_RATE
        )

        cash -= cash_used

        positions[
            symbol
        ] = {
            "symbol":
                symbol,

            "sleeve":
                "v4",

            "shares":
                shares,

            "average_cost":
                effective_price,

            "market_entry_price":
                market_price,

            "entry_cost":
                entry_cost,

            "target_allocation":
                float(
                    action[
                        "target_allocation"
                    ]
                ),

            "opened_at":
                timestamp,

            "price_source":
                quote.get(
                    "source"
                ),

            "rank":
                action.get(
                    "rank"
                ),

            "probability_top5":
                action.get(
                    "probability_top5"
                ),
        }

        trades.append(
            {
                "timestamp":
                    timestamp,

                "action":
                    "BUY",

                "symbol":
                    symbol,

                "sleeve":
                    "v4",

                "shares":
                    shares,

                "market_price":
                    market_price,

                "effective_price":
                    effective_price,

                "entry_cost":
                    entry_cost,

                "cash_used":
                    cash_used,

                "target_allocation":
                    float(
                        action[
                            "target_allocation"
                        ]
                    ),

                "price_source":
                    quote.get(
                        "source"
                    ),

                "rank":
                    action.get(
                        "rank"
                    ),

                "probability_top5":
                    action.get(
                        "probability_top5"
                    ),
            }
        )

    state[
        "positions"
    ] = positions

    state[
        "trades"
    ] = trades

    state[
        "cash"
    ] = max(
        0.0,
        cash,
    )

    state[
        "realized_pnl"
    ] = realized_pnl

    state[
        "last_rebalanced_at"
    ] = timestamp

    save_state(
        state
    )

    return {
        "plan":
            plan,

        "summary":
            get_portfolio_summary(),
    }
