"""
Market data service for the presentation layer.
"""

from pathlib import Path

import pandas as pd


def get_gold_file(symbol: str) -> Path:
    return Path(
        f"data/gold/stocks/{symbol}/{symbol}_prices.parquet"
    )


def get_feature_file(symbol: str) -> Path:
    return Path(
        f"data/features/stocks/{symbol}/{symbol}_features.parquet"
    )


def load_gold_data(symbol: str) -> pd.DataFrame:
    """Load Gold data for one symbol."""

    file_path = get_gold_file(symbol)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Gold dataset not found: {file_path}"
        )

    return pd.read_parquet(file_path)


def load_feature_data(symbol: str) -> pd.DataFrame:
    """Load feature data for one symbol."""

    file_path = get_feature_file(symbol)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Feature dataset not found: {file_path}"
        )

    return pd.read_parquet(file_path)


def get_market_summary(symbol: str) -> dict:
    """Return latest market and technical values."""

    df = load_feature_data(symbol)

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    latest = df.iloc[-1]

    previous = (
        df.iloc[-2]
        if len(df) > 1
        else latest
    )

    close = float(latest["close"])
    previous_close = float(previous["close"])

    price_change = (
        close - previous_close
    )

    price_change_pct = (
        price_change / previous_close
        if previous_close
        else 0.0
    )

    return {
        "symbol": symbol,

        "timestamp":
            str(latest["timestamp_utc"]),

        "close":
            close,

        "price_change":
            float(price_change),

        "price_change_pct":
            float(price_change_pct),

        "rsi_14":
            float(latest["rsi_14"])
            if pd.notna(latest["rsi_14"])
            else None,

        "sma_20":
            float(latest["sma_20"])
            if pd.notna(latest["sma_20"])
            else None,

        "sma_50":
            float(latest["sma_50"])
            if pd.notna(latest["sma_50"])
            else None,

        "sma_200":
            float(latest["sma_200"])
            if pd.notna(latest["sma_200"])
            else None,

        "volatility_20d":
            float(latest["volatility_20d"])
            if pd.notna(latest["volatility_20d"])
            else None,

        "volume":
            float(latest["volume"]),

        "volume_ratio":
            float(latest["volume_ratio"])
            if pd.notna(latest["volume_ratio"])
            else None,
    }


def get_recent_prices(
    symbol: str,
    limit: int = 20,
) -> list:
    """Return the most recent market sessions, newest first."""

    df = load_gold_data(symbol)

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    # Compute close-to-close daily performance while the rows are still in
    # chronological order. This keeps the percentage tied to the prior
    # completed trading session, including across weekends and holidays.
    df["daily_change_pct"] = (
        df["close"].pct_change()
    )

    # Select the latest N rows, then reverse them for presentation so callers
    # that display the first rows see the newest completed trading sessions.
    recent = df.tail(limit).sort_values(
        "timestamp",
        ascending=False,
    )

    records = []

    for _, row in recent.iterrows():

        records.append(
            {
                "timestamp":
                    str(row["timestamp_utc"]),

                "open":
                    float(row["open"]),

                "high":
                    float(row["high"]),

                "low":
                    float(row["low"]),

                "close":
                    float(row["close"]),

                "daily_change_pct":
                    float(row["daily_change_pct"])
                    if pd.notna(row["daily_change_pct"])
                    else None,

                "volume":
                    float(row["volume"]),
            }
        )

    return records
