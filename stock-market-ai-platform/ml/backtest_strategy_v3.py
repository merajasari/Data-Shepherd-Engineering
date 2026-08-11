"""
Walk-forward V3 selective-trading backtest for the Stock Market AI Platform.

Research only.
Does not place real or paper brokerage orders.
"""

import sys

import numpy as np

from train_model_v3 import (
    FEATURE_COLUMNS,
    LogisticRegression,
    get_paths,
    load_dataset,
    standardize,
)


PURGE_GAP = 5
INITIAL_TRAIN_FRACTION = 0.60
FOLD_FRACTION = 0.10

ENTRY_PROBABILITY = 0.70

# Approximate round-trip trading friction:
# 0.10% entry + 0.10% exit.
ROUND_TRIP_COST = 0.002


def max_drawdown(equity_curve):
    peak = 1.0
    worst = 0.0

    for equity in equity_curve:
        peak = max(
            peak,
            equity,
        )

        drawdown = (
            equity / peak
            - 1.0
        )

        worst = min(
            worst,
            drawdown,
        )

    return worst


def backtest_symbol(symbol, entry_probability=ENTRY_PROBABILITY):
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

    trades = []

    fold_number = 0

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

        fold_number += 1

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

        # Evaluate every fifth test row so
        # simulated 5-day positions do not overlap.
        for local_index in range(
            0,
            len(probabilities),
            5,
        ):
            probability_up = float(
                probabilities[
                    local_index
                ]
            )

            if (
                probability_up
                < entry_probability
            ):
                continue

            absolute_index = (
                test_start
                + local_index
            )

            entry_index = (
                absolute_index
                + 1
            )

            exit_index = (
                absolute_index
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

            gross_return = (
                exit_price
                / entry_price
                - 1.0
            )

            net_return = (
                gross_return
                - ROUND_TRIP_COST
            )

            trades.append(
                {
                    "symbol":
                        symbol,

                    "fold":
                        fold_number,

                    "signal_timestamp":
                        timestamps[
                            absolute_index
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

                    "probability_up":
                        probability_up,

                    "gross_return":
                        gross_return,

                    "net_return":
                        net_return,
                }
            )

        train_end = test_end

    equity = 1.0
    equity_curve = [
        equity
    ]

    wins = 0

    for trade in trades:
        net_return = trade[
            "net_return"
        ]

        if net_return > 0:
            wins += 1

        equity *= (
            1.0
            + net_return
        )

        equity_curve.append(
            equity
        )

    trade_count = len(
        trades
    )

    if trade_count:
        avg_net_return = float(
            np.mean(
                [
                    trade["net_return"]
                    for trade in trades
                ]
            )
        )

        win_rate = (
            wins / trade_count
        )

    else:
        avg_net_return = 0.0
        win_rate = 0.0

    total_return = (
        equity - 1.0
    )

    return {
        "symbol":
            symbol,

        "trade_count":
            trade_count,

        "win_rate":
            win_rate,

        "average_net_return":
            avg_net_return,

        "total_return":
            total_return,

        "max_drawdown":
            max_drawdown(
                equity_curve
            ),

        "trades":
            trades,
    }


def main():
    symbol = (
        sys.argv[1]
        .upper()
        .strip()
        if len(sys.argv) > 1
        else "COST"
    )

    result = backtest_symbol(
        symbol
    )

    print()
    print(
        f"{symbol} V3 WALK-FORWARD TRADING BACKTEST"
    )
    print(
        "=" * 52
    )

    print(
        f"Trades:             "
        f"{result['trade_count']}"
    )

    print(
        f"Win rate:           "
        f"{result['win_rate']:.2%}"
    )

    print(
        f"Avg net 5-day ret:  "
        f"{result['average_net_return']:.2%}"
    )

    print(
        f"Compounded return:  "
        f"{result['total_return']:.2%}"
    )

    print(
        f"Maximum drawdown:   "
        f"{result['max_drawdown']:.2%}"
    )


if __name__ == "__main__":
    main()
