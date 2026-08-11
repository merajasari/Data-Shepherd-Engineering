"""
Run one V4 paper-trading cycle.

Workflow:
  1. Load latest V4 rankings
  2. Build rebalance plan
  3. Execute simulated rebalance if needed
  4. Print portfolio summary

Simulation only.
No real brokerage orders are placed.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(PROJECT_ROOT),
)

sys.path.insert(
    0,
    str(PROJECT_ROOT / "data-ingestion"),
)

from symbols import SYMBOLS

from webapp.services.paper_trading_service import (
    build_rebalance_plan,
    execute_rebalance,
    get_portfolio_summary,
)


def main():

    print()
    print("V4 PAPER TRADING CYCLE")
    print("=" * 52)

    plan = build_rebalance_plan(
        SYMBOLS
    )

    trade_actions = [
        action
        for action in plan["actions"]
        if action["action"]
        in {
            "BUY",
            "SELL",
        }
    ]

    print()
    print("Latest target V4:")
    print(
        ", ".join(
            plan[
                "target_v4_symbols"
            ]
        )
    )

    print()

    if trade_actions:

        print(
            f"Rebalance required: "
            f"{len(trade_actions)} action(s)"
        )

        for action in trade_actions:
            probability = action.get(
                "probability_top5"
            )

            probability_text = (
                f"{probability:.4f}"
                if probability is not None
                else "-"
            )

            print(
                f"  {action['action']:<4} "
                f"{action['symbol']:<6} "
                f"rank={str(action['rank']):>4} "
                f"p_top5={probability_text}"
            )

        result = execute_rebalance(
            SYMBOLS
        )

        summary = result[
            "summary"
        ]

        print()
        print(
            "Simulated rebalance executed."
        )

    else:

        print(
            "No rebalance required."
        )

        summary = (
            get_portfolio_summary()
        )

    print()
    print("PORTFOLIO")
    print("-" * 52)

    print(
        f"Equity:          "
        f"${summary['equity']:,.2f}"
    )

    print(
        f"Cash:            "
        f"${summary['cash']:,.2f}"
    )

    print(
        f"Market value:    "
        f"${summary['market_value']:,.2f}"
    )

    print(
        f"Realized P&L:    "
        f"${summary['realized_pnl']:,.2f}"
    )

    print(
        f"Unrealized P&L:  "
        f"${summary['unrealized_pnl']:,.2f}"
    )

    print(
        f"Total return:    "
        f"{summary['total_return_pct']:.4f}%"
    )

    print(
        f"Open positions:  "
        f"{summary['open_position_count']}"
    )

    print(
        f"Trade records:   "
        f"{summary['trade_count']}"
    )

    print()
    print("POSITIONS")
    print("-" * 52)

    positions = sorted(
        summary[
            "positions"
        ],
        key=lambda item:
            (
                item[
                    "symbol"
                ]
                != "SPY",
                item[
                    "symbol"
                ],
            ),
    )

    for position in positions:

        print(
            f"{position['symbol']:<6} "
            f"value="
            f"${position['market_value']:>10,.2f} "
            f"pnl="
            f"${position['unrealized_pnl']:>9,.2f} "
            f"price="
            f"${position['current_price']:>9,.2f}"
        )


if __name__ == "__main__":
    main()
