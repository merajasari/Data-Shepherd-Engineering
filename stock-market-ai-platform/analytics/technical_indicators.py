"""
Stock market analytics utilities.

Research module for calculating common indicators.
"""

import pandas as pd


def moving_average(prices: pd.Series, window: int = 20) -> pd.Series:
    """Calculate simple moving average."""
    return prices.rolling(window=window).mean()


def daily_returns(prices: pd.Series) -> pd.Series:
    """Calculate daily percentage returns."""
    return prices.pct_change()


def volatility(prices: pd.Series, window: int = 20) -> pd.Series:
    """Calculate rolling volatility."""
    return daily_returns(prices).rolling(window=window).std()
