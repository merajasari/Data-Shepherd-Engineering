"""
Append-only forward journal for V4 paper trading.

Each successful paper-trading cycle appends one JSON object to a JSONL
runtime file. The journal is observational only and does not replace the
mutable portfolio state in portfolio.json.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


JOURNAL_DIR = Path("data/paper_trading")
JOURNAL_PATH = JOURNAL_DIR / "journal.jsonl"


def utc_now():
    return (
        datetime.now(timezone.utc)
        .isoformat()
    )


def build_cycle_observation(
    summary,
    top_five_symbols,
    trade_actions,
    benchmark_symbol=None,
    benchmark_price=None,
    benchmark_source=None,
):
    """
    Build one serializable forward-test observation.
    """

    actions = []

    for action in trade_actions:
        actions.append(
            {
                "action":
                    action.get(
                        "action"
                    ),

                "symbol":
                    action.get(
                        "symbol"
                    ),

                "sleeve":
                    action.get(
                        "sleeve"
                    ),

                "rank":
                    action.get(
                        "rank"
                    ),

                "probability_top5":
                    action.get(
                        "probability_top5"
                    ),

                "target_allocation":
                    action.get(
                        "target_allocation"
                    ),

                "target_value":
                    action.get(
                        "target_value"
                    ),
            }
        )

    return {
        "timestamp":
            utc_now(),

        "equity":
            float(
                summary[
                    "equity"
                ]
            ),

        "cash":
            float(
                summary[
                    "cash"
                ]
            ),

        "market_value":
            float(
                summary[
                    "market_value"
                ]
            ),

        "realized_pnl":
            float(
                summary[
                    "realized_pnl"
                ]
            ),

        "unrealized_pnl":
            float(
                summary[
                    "unrealized_pnl"
                ]
            ),

        "total_return_pct":
            float(
                summary[
                    "total_return_pct"
                ]
            ),

        "open_position_count":
            int(
                summary[
                    "open_position_count"
                ]
            ),

        "trade_count":
            int(
                summary[
                    "trade_count"
                ]
            ),

        "top_five_symbols":
            list(
                top_five_symbols
            ),

        "trade_actions":
            actions,

        "benchmark_symbol":
            benchmark_symbol,

        "benchmark_price":
            (
                float(benchmark_price)
                if benchmark_price is not None
                else None
            ),

        "benchmark_source":
            benchmark_source,
    }


def append_cycle_observation(
    summary,
    top_five_symbols,
    trade_actions,
    benchmark_symbol=None,
    benchmark_price=None,
    benchmark_source=None,
):
    """
    Append exactly one paper-cycle observation to the JSONL journal.
    """

    observation = build_cycle_observation(
        summary=summary,
        top_five_symbols=top_five_symbols,
        trade_actions=trade_actions,
        benchmark_symbol=benchmark_symbol,
        benchmark_price=benchmark_price,
        benchmark_source=benchmark_source,
    )

    JOURNAL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with JOURNAL_PATH.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(
            json.dumps(
                observation,
                sort_keys=True,
            )
        )
        file.write("\n")

    return observation
