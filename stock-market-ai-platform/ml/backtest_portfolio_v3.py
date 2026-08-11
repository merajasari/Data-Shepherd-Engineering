"""
Portfolio-level walk-forward backtest for V3.

Research only.
Does not place brokerage or paper-trading orders.
"""

import sys
from collections import defaultdict

import numpy as np

sys.path.append("data-ingestion")

from symbols import get_symbols

from train_model_v3 import (
    FEATURE_COLUMNS,
    LogisticRegression,
    get_paths,
    load_dataset,
    standardize,
)


STARTING_CASH = 100_000.0

ENTRY_PROBABILITY = 0.55

POSITION_FRACTION = 0.05

MAX_OPEN_POSITIONS = 5

PURGE_GAP = 5

INITIAL_TRAIN_FRACTION = 0.60

FOLD_FRACTION = 0.10

ENTRY_COST_RATE = 0.001
EXIT_COST_RATE = 0.001


def generate_signals(
    symbol,
    entry_probability=ENTRY_PROBABILITY,
):
    """
    Generate strictly walk-forward V3 signals for one symbol.
    """

    feature_file, _ = get_paths(
        symbol
    )

    df = load_dataset(
        feature_file
    )

    X = df[
        FEATURE_COLUMNS
    ].to_numpy(
        dtype=float
    )

    y = df[
        "target_trade_5d"
    ].to_numpy(
        dtype=int
    )

    open_prices = df[
        "open"
    ].to_numpy(
        dtype=float
    )

    timestamps = df[
        "timestamp_utc"
    ].astype(str).to_numpy()

    row_count = len(df)

    train_end = int(
        row_count
        * INITIAL_TRAIN_FRACTION
    )

    fold_size = max(
        20,
        int(
            row_count
            * FOLD_FRACTION
        ),
    )

    signals = []

    while True:

        test_start = (
            train_end
            + PURGE_GAP
        )

        test_end = min(
            row_count,
            test_start + fold_size,
        )

        if (
            test_start >= row_count
            or test_end - test_start < 10
        ):
            break

        X_train = X[
            :train_end
        ]

        y_train = y[
            :train_end
        ]

        X_test = X[
            test_start:test_end
        ]

        (
            X_train_scaled,
            X_test_scaled,
            _,
            _,
        ) = standardize(
            X_train,
            X_test,
        )

        model = LogisticRegression()

        model.fit(
            X_train_scaled,
            y_train,
        )

        probabilities = (
            model.predict_probability(
                X_test_scaled
            )
        )

        for local_index, probability in enumerate(
            probabilities
        ):

            probability = float(
                probability
            )

            if (
                probability
                < entry_probability
            ):
                continue

            signal_index = (
                test_start
                + local_index
            )

            entry_index = (
                signal_index
                + 1
            )

            exit_index = (
                signal_index
                + 6
            )

            if exit_index >= row_count:
                continue

            entry_price = float(
                open_prices[
                    entry_index
                ]
            )

            exit_price = float(
                open_prices[
                    exit_index
                ]
            )

            if (
                entry_price <= 0
                or exit_price <= 0
            ):
                continue

            signals.append(
                {
                    "symbol":
                        symbol,

                    "probability":
                        probability,

                    "signal_timestamp":
                        timestamps[
                            signal_index
                        ],

                    "entry_timestamp":
                        timestamps[
                            entry_index
                        ],

                    "exit_timestamp":
                        timestamps[
                            exit_index
                        ],

                    "entry_price":
                        entry_price,

                    "exit_price":
                        exit_price,
                }
            )

        train_end = test_end

    price_map = {
        timestamp: float(price)
        for timestamp, price in zip(
            timestamps,
            open_prices,
        )
    }

    return (
        signals,
        price_map,
    )


def portfolio_equity(
    cash,
    positions,
    price_maps,
    timestamp,
):
    """
    Mark open positions to the current day's open.
    """

    value = float(
        cash
    )

    for symbol, position in positions.items():

        current_price = (
            price_maps
            .get(symbol, {})
            .get(timestamp)
        )

        if current_price is None:
            current_price = position[
                "entry_price"
            ]

        value += (
            position["shares"]
            * current_price
        )

    return value


def calculate_max_drawdown(
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


def run_portfolio_backtest(
    position_fraction=POSITION_FRACTION,
    entry_probability=ENTRY_PROBABILITY,
):
    symbols = get_symbols()

    signals_by_entry = defaultdict(
        list
    )

    price_maps = {}

    all_dates = set()

    print(
        f"Generating V3 signals for "
        f"{len(symbols)} symbols..."
    )

    for symbol in symbols:

        signals, price_map = (
            generate_signals(
                symbol,
                entry_probability=entry_probability,
            )
        )

        price_maps[
            symbol
        ] = price_map

        all_dates.update(
            price_map.keys()
        )

        for signal in signals:
            signals_by_entry[
                signal[
                    "entry_timestamp"
                ]
            ].append(
                signal
            )

    dates = sorted(
        all_dates
    )

    cash = STARTING_CASH

    positions = {}

    completed_trades = []

    equity_curve = []

    skipped_capacity = 0
    skipped_duplicate = 0

    for timestamp in dates:

        # --------------------------------------------------
        # Exit positions first.
        # --------------------------------------------------
        symbols_to_exit = [
            symbol
            for symbol, position
            in positions.items()
            if position[
                "exit_timestamp"
            ] == timestamp
        ]

        for symbol in symbols_to_exit:

            position = positions.pop(
                symbol
            )

            exit_price = position[
                "exit_price"
            ]

            gross_proceeds = (
                position["shares"]
                * exit_price
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

            total_cost = (
                position[
                    "entry_cash_used"
                ]
            )

            pnl = (
                net_proceeds
                - total_cost
            )

            return_pct = (
                pnl / total_cost
                if total_cost
                else 0.0
            )

            completed_trades.append(
                {
                    "symbol":
                        symbol,

                    "probability":
                        position[
                            "probability"
                        ],

                    "entry_timestamp":
                        position[
                            "entry_timestamp"
                        ],

                    "exit_timestamp":
                        timestamp,

                    "entry_price":
                        position[
                            "entry_price"
                        ],

                    "exit_price":
                        exit_price,

                    "capital":
                        total_cost,

                    "pnl":
                        pnl,

                    "return_pct":
                        return_pct,
                }
            )

        # --------------------------------------------------
        # Rank today's new entries by model probability.
        # --------------------------------------------------
        candidates = sorted(
            signals_by_entry.get(
                timestamp,
                []
            ),
            key=lambda item:
                item["probability"],
            reverse=True,
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

            equity = portfolio_equity(
                cash,
                positions,
                price_maps,
                timestamp,
            )

            target_allocation = (
                equity
                * position_fraction
            )

            if (
                target_allocation <= 0
                or cash <= 0
            ):
                continue

            entry_price = signal[
                "entry_price"
            ]

            # Include estimated entry friction
            # inside the position's cash usage.
            effective_entry_price = (
                entry_price
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

                "probability":
                    signal[
                        "probability"
                    ],

                "shares":
                    shares,

                "entry_timestamp":
                    timestamp,

                "exit_timestamp":
                    signal[
                        "exit_timestamp"
                    ],

                "entry_price":
                    entry_price,

                "exit_price":
                    signal[
                        "exit_price"
                    ],

                "entry_cash_used":
                    entry_cash_used,
            }

        equity = portfolio_equity(
            cash,
            positions,
            price_maps,
            timestamp,
        )

        equity_curve.append(
            (
                timestamp,
                equity,
            )
        )

    # Any remaining positions should normally be absent because
    # generated signals require a valid exit date.
    final_equity = (
        equity_curve[-1][1]
        if equity_curve
        else STARTING_CASH
    )

    total_return = (
        final_equity
        / STARTING_CASH
        - 1.0
    )

    wins = sum(
        1
        for trade in completed_trades
        if trade[
            "pnl"
        ] > 0
    )

    trade_count = len(
        completed_trades
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

    max_drawdown = (
        calculate_max_drawdown(
            equity_curve
        )
    )

    return {
        "starting_cash":
            STARTING_CASH,

        "final_equity":
            final_equity,

        "total_return":
            total_return,

        "max_drawdown":
            max_drawdown,

        "trade_count":
            trade_count,

        "win_rate":
            win_rate,

        "average_trade_return":
            average_trade_return,

        "skipped_capacity":
            skipped_capacity,

        "skipped_duplicate":
            skipped_duplicate,

        "trades":
            completed_trades,

        "equity_curve":
            equity_curve,
    }


def main():

    result = run_portfolio_backtest()

    print()
    print(
        "V3 PORTFOLIO WALK-FORWARD BACKTEST"
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
        f"Capacity skips:     "
        f"{result['skipped_capacity']}"
    )

    print(
        f"Duplicate skips:    "
        f"{result['skipped_duplicate']}"
    )


if __name__ == "__main__":
    main()
