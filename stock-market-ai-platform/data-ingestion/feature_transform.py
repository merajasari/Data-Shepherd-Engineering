"""
Feature engineering for Gold market data.

Creates reusable ML-ready features from the Gold layer.
"""

import pandas as pd


def transform_to_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transform Gold market data into ML-ready features.
    """

    result = df.copy()

    # ---------------------------------------------------------
    # Price momentum
    # ---------------------------------------------------------
    result["return_5d"] = result["close"].pct_change(5)
    result["return_10d"] = result["close"].pct_change(10)
    result["return_20d"] = result["close"].pct_change(20)

    # ---------------------------------------------------------
    # Price relative to moving averages
    # ---------------------------------------------------------
    result["price_vs_sma_7"] = (
        result["close"] / result["sma_7"] - 1
    )

    result["price_vs_sma_20"] = (
        result["close"] / result["sma_20"] - 1
    )

    result["price_vs_sma_50"] = (
        result["close"] / result["sma_50"] - 1
    )

    result["price_vs_sma_200"] = (
        result["close"] / result["sma_200"] - 1
    )

    # ---------------------------------------------------------
    # Moving-average relationships
    # ---------------------------------------------------------
    result["sma_7_vs_sma_20"] = (
        result["sma_7"] / result["sma_20"] - 1
    )

    result["sma_20_vs_sma_50"] = (
        result["sma_20"] / result["sma_50"] - 1
    )

    result["sma_50_vs_sma_200"] = (
        result["sma_50"] / result["sma_200"] - 1
    )

    # ---------------------------------------------------------
    # Daily trading range
    # ---------------------------------------------------------
    result["intraday_range"] = (
        result["high"] - result["low"]
    ) / result["close"]

    result["open_close_range"] = (
        result["close"] - result["open"]
    ) / result["open"]

    # ---------------------------------------------------------
    # Volume features
    # ---------------------------------------------------------
    result["volume_ratio"] = (
        result["volume"] / result["volume_sma_20"]
    )

    result["volume_change_5d"] = (
        result["volume"].pct_change(5)
    )

    # ---------------------------------------------------------
    # Volatility features
    # ---------------------------------------------------------
    result["volatility_5d"] = (
        result["daily_return"].rolling(5).std()
    )

    result["volatility_20d"] = (
        result["daily_return"].rolling(20).std()
    )

    # ---------------------------------------------------------
    # RSI
    # ---------------------------------------------------------
    delta = result["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss

    result["rsi_14"] = 100 - (100 / (1 + rs))

    # ---------------------------------------------------------
    # Momentum
    # ---------------------------------------------------------
    result["momentum_10d"] = (
        result["close"] - result["close"].shift(10)
    )

    # ---------------------------------------------------------
    # Forward target
    #
    # Used later for supervised ML training.
    # This represents the return over the next 5 trading days.
    # ---------------------------------------------------------
    result["forward_return_5d"] = (
        result["close"].shift(-5) / result["close"] - 1
    )

    # Binary target for classification models.
    result["target_up_5d"] = (
        result["forward_return_5d"] > 0
    ).astype("int8")

    return result
