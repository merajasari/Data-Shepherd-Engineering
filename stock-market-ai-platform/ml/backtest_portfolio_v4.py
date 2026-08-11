"""
V4 cross-sectional portfolio walk-forward backtest.

Research only.
No brokerage or paper-trading orders are placed.
"""

import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
import pyarrow.parquet as pq

sys.path.append("data-ingestion")

from symbols import SYMBOLS

from train_model_v4 import (
    DATA_PATH,
    FEATURE_COLUMNS,
    LogisticRegression,
    PURGE_GAP,
    INITIAL_TRAIN_FRACTION,
    FOLD_FRACTION,
    TOP_COUNT,
    standardize,
)


STARTING_CASH = 100_000.0

POSITION_FRACTION = 0.20

MAX_OPEN_POSITIONS = 5

ENTRY_COST_RATE = 0.001
EXIT_COST_RATE = 0.001


def load_v4_data():
    columns = [
        "symbol",
        "timestamp_utc",
        "open",
        "target_top5_5d",
        "forward_return_5d",
        *FEATURE_COLUMNS,
    ]

    table = pq.read_table(
        DATA_PATH,
        columns=columns,
    )

    data = {
        name:
            table.column(name).to_pylist()
        for name in columns
    }

    symbols = np.asarray(
        data["symbol"],
        dtype=object,
    )

    timestamps = np.asarray(
        data["timestamp_utc"],
        dtype=object,
    )

    open_prices = np.asarray(
        data["open"],
        dtype=float,
    )

    y = np.asarray(
        data["target_top5_5d"],
        dtype=int,
    )

    X = np.column_stack(
        [
            np.asarray(
                data[column],
                dtype=float,
            )
            for column in FEATURE_COLUMNS
        ]
    )

    return (
        X,
        y,
        symbols,
        timestamps,
        open_prices,
    )


def build_price_lookup(
    symbols,
    timestamps,
    open_prices,
):
    lookup = {}

    for symbol, timestamp, price in zip(
        symbols,
        timestamps,
        open_prices,
    ):
        lookup[
            (
                symbol,
                timestamp,
            )
        ] = float(
            price
        )

    return lookup


def generate_walk_forward_signals(
    X,
    y,
    symbols,
    timestamps,
):
    unique_dates = sorted(
        set(
            timestamps.tolist()
        )
    )

    date_count = len(
        unique_dates
    )

    initial_train_end = int(
        date_count
        * INITIAL_TRAIN_FRACTION
    )

    fold_size = max(
        20,
        int(
            date_count
            * FOLD_FRACTION
        ),
    )

    signals = []

    train_end = (
        initial_train_end
    )

    fold_number = 0

    while True:

        test_start = (
            train_end
            + PURGE_GAP
        )

        test_end = min(
            date_count,
            test_start
            + fold_size,
        )

        if (
            test_start >= date_count
            or test_end - test_start < 10
        ):
            break

        fold_number += 1

        train_dates = set(
            unique_dates[
                :train_end
            ]
        )

        test_dates = (
            unique_dates[
                test_start:test_end
            ]
        )

        train_mask = np.asarray(
            [
                timestamp
                in train_dates
                for timestamp
                in timestamps
            ],
            dtype=bool,
        )

        X_train = X[
            train_mask
        ]

        y_train = y[
            train_mask
        ]

        (
            X_train_scaled,
            _,
            mean,
            std,
        ) = standardize(
            X_train,
            X_train,
        )

        model = (
            LogisticRegression()
        )

        model.fit(
            X_train_scaled,
            y_train,
        )

        for signal_date in test_dates:

            date_indices = np.where(
                timestamps
                == signal_date
            )[0]

            X_day = X[
                date_indices
            ]

            X_day_scaled = (
                X_day - mean
            ) / std

            probabilities = (
                model.predict_probability(
                    X_day_scaled
                )
            )

            ranked = sorted(
                zip(
                    date_indices,
                    probabilities,
                ),
                key=lambda item:
                    item[1],
                reverse=True,
            )

            selected = ranked[
                :TOP_COUNT
            ]

            for index, probability in selected:

                signals.append(
                    {
                        "fold":
                            fold_number,

                        "signal_timestamp":
                            timestamps[
                                index
                            ],

                        "symbol":
                            symbols[
                                index
                            ],

                        "probability":
                            float(
                                probability
                            ),
                    }
                )

        train_end = test_end

    return (
        signals,
        unique_dates,
    )


def max_drawdown(
    equity_curve,
):
    peak = None
    worst = 0.0

    for _, equity in equity_curve:

        if (
            peak is None
            or equity > peak
        ):
            peak = equity

        if peak:
            drawdown = (
                equity / peak
                - 1.0
            )

            worst = min(
                worst,
                drawdown,
            )

    return worst


def run_backtest():
    (
        X,
        y,
        symbols,
        timestamps,
        open_prices,
    ) = load_v4_data()

    signals, unique_dates = (
        generate_walk_forward_signals(
            X,
            y,
            symbols,
            timestamps,
        )
    )

    price_lookup = (
        build_price_lookup(
            symbols,
            timestamps,
            open_prices,
        )
    )

    date_to_index = {
        timestamp: index
        for index, timestamp
        in enumerate(
            unique_dates
        )
    }

    signals_by_entry = defaultdict(
        list
    )

    for signal in signals:

        signal_index = (
            date_to_index[
                signal[
                    "signal_timestamp"
                ]
            ]
        )

        entry_index = (
            signal_index + 1
        )

        exit_index = (
            signal_index + 6
        )

        if (
            exit_index
            >= len(unique_dates)
        ):
            continue

        entry_timestamp = (
            unique_dates[
                entry_index
            ]
        )

        exit_timestamp = (
            unique_dates[
                exit_index
            ]
        )

        symbol = signal[
            "symbol"
        ]

        entry_price = (
            price_lookup.get(
                (
                    symbol,
                    entry_timestamp,
                )
            )
        )

        exit_price = (
            price_lookup.get(
                (
                    symbol,
                    exit_timestamp,
                )
            )
        )

        if (
            entry_price is None
            or exit_price is None
            or entry_price <= 0
            or exit_price <= 0
        ):
            continue

        enriched = dict(
            signal
        )

        enriched[
            "entry_timestamp"
        ] = entry_timestamp

        enriched[
            "exit_timestamp"
        ] = exit_timestamp

        enriched[
            "entry_price"
        ] = float(
            entry_price
        )

        enriched[
            "exit_price"
        ] = float(
            exit_price
        )

        signals_by_entry[
            entry_timestamp
        ].append(
            enriched
        )

    cash = STARTING_CASH

    positions = {}

    completed_trades = []

    equity_curve = []

    skipped_capacity = 0
    skipped_duplicate = 0

    open_position_counts = []

    for timestamp in unique_dates:

        symbols_to_exit = [
            symbol
            for symbol, position
            in positions.items()
            if position[
                "exit_timestamp"
            ] == timestamp
        ]

        for symbol in symbols_to_exit:

            position = (
                positions.pop(
                    symbol
                )
            )

            gross_proceeds = (
                position[
                    "shares"
                ]
                * position[
                    "exit_price"
                ]
            )

            exit_cost = (
                gross_proceeds
                * EXIT_COST_RATE
            )

            net_proceeds = (
                gross_proceeds
                - exit_cost
            )

            cash += net_proceeds

            pnl = (
                net_proceeds
                - position[
                    "entry_cash_used"
                ]
            )

            return_pct = (
                pnl
                / position[
                    "entry_cash_used"
                ]
            )

            completed_trades.append(
                {
                    "symbol":
                        symbol,

                    "entry_timestamp":
                        position[
                            "entry_timestamp"
                        ],

                    "exit_timestamp":
                        timestamp,

                    "probability":
                        position[
                            "probability"
                        ],

                    "pnl":
                        pnl,

                    "return_pct":
                        return_pct,
                }
            )

        candidates = sorted(
            signals_by_entry.get(
                timestamp,
                []
            ),
            key=lambda item:
                item[
                    "probability"
                ],
            reverse=True,
        )

        portfolio_value = cash

        for symbol, position in positions.items():

            price = (
                price_lookup.get(
                    (
                        symbol,
                        timestamp,
                    ),
                    position[
                        "entry_price"
                    ],
                )
            )

            portfolio_value += (
                position[
                    "shares"
                ]
                * price
            )

        for signal in candidates:

            symbol = signal[
                "symbol"
            ]

            if symbol in positions:
                skipped_duplicate += 1
                continue

            if (
                len(positions)
                >= MAX_OPEN_POSITIONS
            ):
                skipped_capacity += 1
                continue

            target_allocation = (
                portfolio_value
                * POSITION_FRACTION
            )

            effective_entry_price = (
                signal[
                    "entry_price"
                ]
                * (
                    1.0
                    + ENTRY_COST_RATE
                )
            )

            shares = (
                target_allocation
                / effective_entry_price
            )

            entry_cash_used = (
                shares
                * effective_entry_price
            )

            if entry_cash_used > cash:
                shares = (
                    cash
                    / effective_entry_price
                )

                entry_cash_used = (
                    shares
                    * effective_entry_price
                )

            if shares <= 0:
                continue

            cash -= (
                entry_cash_used
            )

            positions[
                symbol
            ] = {
                "symbol":
                    symbol,

                "shares":
                    shares,

                "probability":
                    signal[
                        "probability"
                    ],

                "entry_timestamp":
                    timestamp,

                "exit_timestamp":
                    signal[
                        "exit_timestamp"
                    ],

                "entry_price":
                    signal[
                        "entry_price"
                    ],

                "exit_price":
                    signal[
                        "exit_price"
                    ],

                "entry_cash_used":
                    entry_cash_used,
            }

        equity = cash

        for symbol, position in positions.items():

            current_price = (
                price_lookup.get(
                    (
                        symbol,
                        timestamp,
                    ),
                    position[
                        "entry_price"
                    ],
                )
            )

            equity += (
                position[
                    "shares"
                ]
                * current_price
            )

        equity_curve.append(
            (
                timestamp,
                equity,
            )
        )

        open_position_counts.append(
            len(
                positions
            )
        )

    final_equity = (
        equity_curve[-1][1]
        if equity_curve
        else STARTING_CASH
    )

    start = datetime.fromisoformat(
        str(
            equity_curve[0][0]
        )
    )

    end = datetime.fromisoformat(
        str(
            equity_curve[-1][0]
        )
    )

    years = (
        end - start
    ).days / 365.25

    total_return = (
        final_equity
        / STARTING_CASH
        - 1.0
    )

    cagr = (
        (
            final_equity
            / STARTING_CASH
        )
        ** (
            1.0 / years
        )
        - 1.0
    )

    trade_count = len(
        completed_trades
    )

    wins = sum(
        1
        for trade
        in completed_trades
        if trade[
            "pnl"
        ] > 0
    )

    win_rate = (
        wins / trade_count
        if trade_count
        else 0.0
    )

    average_trade_return = (
        float(
            np.mean(
                [
                    trade[
                        "return_pct"
                    ]
                    for trade
                    in completed_trades
                ]
            )
        )
        if completed_trades
        else 0.0
    )

    average_positions = (
        float(
            np.mean(
                open_position_counts
            )
        )
        if open_position_counts
        else 0.0
    )

    capital_utilization = (
        average_positions
        * POSITION_FRACTION
    )

    return {
        "start_timestamp":
            equity_curve[0][0],

        "end_timestamp":
            equity_curve[-1][0],

        "equity_curve":
            equity_curve,

        "starting_cash":
            STARTING_CASH,

        "final_equity":
            final_equity,

        "total_return":
            total_return,

        "cagr":
            cagr,

        "max_drawdown":
            max_drawdown(
                equity_curve
            ),

        "trade_count":
            trade_count,

        "win_rate":
            win_rate,

        "average_trade_return":
            average_trade_return,

        "average_positions":
            average_positions,

        "capital_utilization":
            capital_utilization,

        "skipped_capacity":
            skipped_capacity,

        "skipped_duplicate":
            skipped_duplicate,
    }


def main():

    result = run_backtest()

    print()
    print(
        "V4 PORTFOLIO WALK-FORWARD BACKTEST"
    )
    print(
        "=" * 52
    )

    print(
        f"Starting capital:   "
        f"${result['starting_cash']:,.2f}"
    )

    print(
        f"Final equity:       "
        f"${result['final_equity']:,.2f}"
    )

    print(
        f"Total return:       "
        f"{result['total_return']:.2%}"
    )

    print(
        f"CAGR:               "
        f"{result['cagr']:.2%}"
    )

    print(
        f"Maximum drawdown:   "
        f"{result['max_drawdown']:.2%}"
    )

    print(
        f"Completed trades:   "
        f"{result['trade_count']}"
    )

    print(
        f"Win rate:           "
        f"{result['win_rate']:.2%}"
    )

    print(
        f"Avg trade return:   "
        f"{result['average_trade_return']:.2%}"
    )

    print(
        f"Average positions:  "
        f"{result['average_positions']:.2f}"
    )

    print(
        f"Capital utilization:"
        f" {result['capital_utilization']:.2%}"
    )

    print(
        f"Capacity skips:     "
        f"{result['skipped_capacity']}"
    )

    print(
        f"Duplicate skips:    "
        f"{result['skipped_duplicate']}"
    )


if __name__ == "__main__":
    main()
