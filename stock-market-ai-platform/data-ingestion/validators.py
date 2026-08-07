"""Data quality checks for ingested market data."""


def validate_prices(df):
    """Validate required market fields."""
    required = ["open", "high", "low", "close", "volume"]

    missing = [column for column in required if column not in df.columns]

    if missing:
        raise ValueError(f"Missing columns: {missing}")

    if df.empty:
        raise ValueError("Market data contains no records")

    return True
