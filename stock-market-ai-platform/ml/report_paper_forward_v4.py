"""
Report forward V4 paper-trading performance.

Read-only.
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(PROJECT_ROOT),
)

from webapp.services.paper_journal_reader import (
    summarize_journal,
)


def main():
    summary = summarize_journal()

    print()
    print("V4 FORWARD PAPER-TRADING REPORT")
    print("=" * 56)

    if summary["observation_count"] == 0:
        print("No journal observations available.")
        return

    print(
        f"Observations:       "
        f"{summary['observation_count']}"
    )

    print(
        f"Start:              "
        f"{summary['start_timestamp']}"
    )

    print(
        f"End:                "
        f"{summary['end_timestamp']}"
    )

    print()

    print(
        f"Starting equity:    "
        f"${summary['starting_equity']:,.2f}"
    )

    print(
        f"Ending equity:      "
        f"${summary['ending_equity']:,.2f}"
    )

    print(
        f"Forward return:     "
        f"{summary['forward_return']:.4%}"
    )

    print(
        f"Maximum drawdown:   "
        f"{summary['max_drawdown']:.4%}"
    )

    print()

    print("BENCHMARK")
    print("-" * 56)

    print(
        f"Benchmark:          "
        f"{summary['benchmark_symbol'] or '-'}"
    )

    print(
        f"Benchmark obs:      "
        f"{summary['benchmark_observation_count']}"
    )

    if summary["benchmark_start_price"] is not None:
        print(
            f"Start price:        "
            f"${summary['benchmark_start_price']:,.2f}"
        )

        print(
            f"End price:          "
            f"${summary['benchmark_end_price']:,.2f}"
        )

    print(
        f"Benchmark return:   "
        f"{summary['benchmark_return']:.4%}"
    )

    print(
        f"Excess return:      "
        f"{summary['excess_return']:.4%}"
    )

    print()

    print(
        f"Rebalance cycles:   "
        f"{summary['rebalance_cycles']}"
    )

    print(
        f"Trade actions:      "
        f"{summary['trade_action_count']}"
    )

    print(
        f"Total trades:       "
        f"{summary['latest_trade_count']}"
    )

    print()

    print(
        "Current V4 top five:"
    )

    for rank, symbol in enumerate(
        summary["latest_top_five"],
        start=1,
    ):
        print(
            f"  {rank}. {symbol}"
        )


if __name__ == "__main__":
    main()
