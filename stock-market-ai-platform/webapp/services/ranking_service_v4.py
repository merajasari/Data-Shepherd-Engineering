"""
V4 cross-sectional ranking service.

Loads the frozen V4 universe-level model and ranks the configured
stock universe using the latest available feature row for each symbol.
"""

from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd


sys.path.append("data-ingestion")

from symbols import SYMBOLS


MODEL_PATH = Path(
    "models/cross_section_model_v4.pkl"
)


def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"V4 model not found: {MODEL_PATH}"
        )

    with MODEL_PATH.open(
        "rb"
    ) as file:
        return pickle.load(
            file
        )


def get_latest_cross_section():
    """
    Load the latest feature row for all configured symbols
    and cross-sectionally normalize each feature.
    """

    artifact = load_model()

    feature_columns = artifact[
        "feature_columns"
    ]

    rows = []

    for symbol in SYMBOLS:

        path = Path(
            f"data/features/stocks/"
            f"{symbol}/{symbol}_features.parquet"
        )

        if not path.exists():
            continue

        df = pd.read_parquet(
            path
        )

        df = df.sort_values(
            "timestamp"
        ).reset_index(
            drop=True
        )

        valid = df.dropna(
            subset=[
                column.replace(
                    "xs_",
                    "",
                )
                for column
                in feature_columns
            ]
        )

        if valid.empty:
            continue

        latest = valid.iloc[-1]

        raw_features = []

        for feature in feature_columns:
            source_column = feature.replace(
                "xs_",
                "",
            )

            raw_features.append(
                float(
                    latest[
                        source_column
                    ]
                )
            )

        rows.append(
            {
                "symbol":
                    symbol,

                "timestamp":
                    str(
                        latest[
                            "timestamp_utc"
                        ]
                    ),

                "close":
                    float(
                        latest[
                            "close"
                        ]
                    ),

                "features":
                    np.asarray(
                        raw_features,
                        dtype=float,
                    ),
            }
        )

    if len(rows) != len(SYMBOLS):
        raise RuntimeError(
            f"Expected {len(SYMBOLS)} symbols, "
            f"got {len(rows)}"
        )

    matrix = np.vstack(
        [
            row[
                "features"
            ]
            for row in rows
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

    return (
        rows,
        normalized,
    )


def rank_latest_universe():
    """
    Rank all configured symbols by V4 predicted probability
    of finishing in the future top-5 cross-section.
    """

    artifact = load_model()

    rows, X = (
        get_latest_cross_section()
    )

    model_mean = np.asarray(
        artifact[
            "feature_mean"
        ],
        dtype=float,
    )

    model_std = np.asarray(
        artifact[
            "feature_std"
        ],
        dtype=float,
    )

    model_std = model_std.copy()

    model_std[
        model_std == 0
    ] = 1.0

    X_scaled = (
        X - model_mean
    ) / model_std

    weights = np.asarray(
        artifact[
            "weights"
        ],
        dtype=float,
    )

    bias = float(
        artifact[
            "bias"
        ]
    )

    scores = (
        X_scaled @ weights
        + bias
    )

    scores = np.clip(
        scores,
        -500,
        500,
    )

    probabilities = (
        1.0
        / (
            1.0
            + np.exp(
                -scores
            )
        )
    )

    ranked = []

    for row, probability in zip(
        rows,
        probabilities,
    ):

        ranked.append(
            {
                "symbol":
                    row[
                        "symbol"
                    ],

                "timestamp":
                    row[
                        "timestamp"
                    ],

                "close":
                    row[
                        "close"
                    ],

                "probability_top5":
                    float(
                        probability
                    ),
            }
        )

    ranked.sort(
        key=lambda item:
            item[
                "probability_top5"
            ],
        reverse=True,
    )

    for index, item in enumerate(
        ranked,
        start=1,
    ):
        item[
            "rank"
        ] = index

        item[
            "selected"
        ] = (
            index <= 5
        )

    return ranked
