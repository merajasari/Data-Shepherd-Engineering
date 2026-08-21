"""
Build the V4 cross-sectional ranking dataset.

For every trading date, rank the 26 configured stocks by their
actual forward 5-day return.

The five highest-returning stocks receive target_top5_5d = 1.
All others receive 0.

Targets are used only during training/evaluation.
"""

import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.append("data-ingestion")

from symbols import SYMBOLS
from feature_source import require_feature_dataset


OUTPUT_PATH = Path(
    "data/model/v4_cross_section.parquet"
)

TOP_COUNT = 5


FEATURE_COLUMNS = [
    "daily_return",
    "return_2d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_centered",
]


def load_symbol(symbol):
    path = require_feature_dataset(symbol)

    columns = [
        "timestamp_utc",
        "forward_return_5d",
        "open",
        *FEATURE_COLUMNS,
    ]

    table = pq.read_table(
        path,
        columns=columns,
    )

    return {
        name: table.column(name).to_pylist()
        for name in columns
    }


def finite(value):
    try:
        return bool(
            np.isfinite(
                float(value)
            )
        )
    except (TypeError, ValueError):
        return False


def main():
    datasets = {
        symbol: load_symbol(symbol)
        for symbol in SYMBOLS
    }

    row_count = len(
        datasets[
            SYMBOLS[0]
        ]["timestamp_utc"]
    )

    output = []

    for index in range(row_count):

        day_rows = []

        for symbol in SYMBOLS:
            data = datasets[symbol]

            forward_return = data[
                "forward_return_5d"
            ][index]

            feature_values = [
                data[column][index]
                for column in FEATURE_COLUMNS
            ]

            if not finite(forward_return):
                continue

            if not all(
                finite(value)
                for value in feature_values
            ):
                continue

            day_rows.append(
                {
                    "symbol":
                        symbol,

                    "timestamp_utc":
                        data[
                            "timestamp_utc"
                        ][index],

                    "open":
                        float(
                            data["open"][index]
                        ),

                    "forward_return_5d":
                        float(
                            forward_return
                        ),

                    "features":
                        np.asarray(
                            feature_values,
                            dtype=float,
                        ),
                }
            )

        # Require the full universe for a proper
        # cross-sectional ranking.
        if len(day_rows) != len(SYMBOLS):
            continue

        ranked = sorted(
            day_rows,
            key=lambda row:
                row["forward_return_5d"],
            reverse=True,
        )

        top_symbols = {
            row["symbol"]
            for row in ranked[
                :TOP_COUNT
            ]
        }

        matrix = np.vstack(
            [
                row["features"]
                for row in day_rows
            ]
        )

        means = matrix.mean(
            axis=0
        )

        stds = matrix.std(
            axis=0
        )

        stds[
            stds == 0
        ] = 1.0

        normalized = (
            matrix - means
        ) / stds

        for row, features in zip(
            day_rows,
            normalized,
        ):
            record = {
                "symbol":
                    row["symbol"],

                "timestamp_utc":
                    row[
                        "timestamp_utc"
                    ],

                "open":
                    row["open"],

                "forward_return_5d":
                    row[
                        "forward_return_5d"
                    ],

                "target_top5_5d":
                    int(
                        row["symbol"]
                        in top_symbols
                    ),
            }

            for column, value in zip(
                FEATURE_COLUMNS,
                features,
            ):
                record[
                    f"xs_{column}"
                ] = float(
                    value
                )

            output.append(
                record
            )

    if not output:
        raise RuntimeError(
            "No V4 rows were generated"
        )

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    table = pa.Table.from_pylist(
        output
    )

    pq.write_table(
        table,
        OUTPUT_PATH,
    )

    unique_dates = len(
        {
            row["timestamp_utc"]
            for row in output
        }
    )

    positives = sum(
        row["target_top5_5d"]
        for row in output
    )

    print(
        f"V4 dataset written: "
        f"{OUTPUT_PATH}"
    )

    print(
        f"Trading dates: "
        f"{unique_dates:,}"
    )

    print(
        f"Rows: "
        f"{len(output):,}"
    )

    print(
        f"Positive targets: "
        f"{positives:,}"
    )

    print(
        f"Positive rate: "
        f"{positives / len(output):.2%}"
    )


if __name__ == "__main__":
    main()
