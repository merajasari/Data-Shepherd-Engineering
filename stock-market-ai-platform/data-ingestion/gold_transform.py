"""
Gold layer transformations for analytics-ready market data.
"""

import pandas as pd


def transform_to_gold(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform Silver market data into analytics-ready Gold data.
    """

    gold = df.copy()

    gold = gold.sort_values(
        "timestamp_utc"
    ).reset_index(drop=True)

    # Daily percentage return based on closing price.
    gold["daily_return"] = gold["close"].pct_change()

    # Cumulative return from the beginning of the dataset.
    first_close = gold["close"].iloc[0]
    gold["cumulative_return"] = (
        gold["close"] / first_close
    ) - 1

    # Simple moving averages.
    gold["sma_7"] = (
        gold["close"]
        .rolling(window=7, min_periods=1)
        .mean()
    )

    gold["sma_20"] = (
        gold["close"]
        .rolling(window=20, min_periods=1)
        .mean()
    )

    gold["sma_50"] = (
        gold["close"]
        .rolling(window=50, min_periods=1)
        .mean()
    )

    gold["sma_200"] = (
        gold["close"]
        .rolling(window=200, min_periods=1)
        .mean()
    )

    # 20-day average trading volume.
    gold["volume_sma_20"] = (
        gold["volume"]
        .rolling(window=20, min_periods=1)
        .mean()
    )

    # Rolling 20-day volatility of daily returns.
    gold["daily_volatility"] = (
        gold["daily_return"]
        .rolling(window=20, min_periods=2)
        .std()
    )

    return gold
