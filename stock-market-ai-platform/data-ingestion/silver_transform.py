"""
Silver layer transformation for market price data.
"""

from datetime import datetime, timezone

import pandas as pd


REQUIRED_COLUMNS = [
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
]


def _convert_timestamp(value):
    """Convert Unix timestamp in milliseconds to UTC datetime."""

    if pd.isna(value):
        return None

    return datetime.fromtimestamp(
        float(value) / 1000,
        tz=timezone.utc,
    )


def transform_to_silver(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform Bronze market data into a cleaned Silver dataset.
    """

    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required columns: {missing}"
        )

    if df.empty:
        raise ValueError(
            "Bronze market data contains no records"
        )

    silver = df.copy()

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
    ]

    for column in numeric_columns:
        silver[column] = pd.to_numeric(
            silver[column],
            errors="coerce",
        )

    timestamp_utc = []

    for value in silver["timestamp"].tolist():
        converted = _convert_timestamp(value)

        if converted is None:
            timestamp_utc.append(None)
        else:
            timestamp_utc.append(
                converted.isoformat()
            )

    silver.insert(
        2,
        "timestamp_utc",
        timestamp_utc,
    )

    silver = silver.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    silver = silver.drop_duplicates(
        subset=[
            "symbol",
            "timestamp",
        ]
    )

    silver = silver.sort_values(
        [
            "symbol",
            "timestamp",
        ]
    )

    silver = silver.reset_index(
        drop=True
    )

    return silver
