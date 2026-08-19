"""Market data service for the presentation layer.

Dashboard reads are cached by source-file modification time so repeated page
loads do not deserialize the same Parquet files for every card and Top-10 row.
The cache invalidates automatically whenever the underlying feature/gold file
is replaced or updated.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd


def get_gold_file(symbol: str) -> Path:
    return Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")


def get_feature_file(symbol: str) -> Path:
    return Path(f"data/features/stocks/{symbol}/{symbol}_features.parquet")


def _mtime(path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return path.stat().st_mtime_ns


@lru_cache(maxsize=256)
def _load_gold_cached(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns  # key-only invalidation token
    return pd.read_parquet(path_text)


@lru_cache(maxsize=256)
def _load_feature_cached(path_text: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns  # key-only invalidation token
    return pd.read_parquet(path_text)


def load_gold_data(symbol: str) -> pd.DataFrame:
    """Load Gold data for one symbol, cached until the file changes."""
    path = get_gold_file(symbol)
    return _load_gold_cached(str(path), _mtime(path)).copy(deep=False)


def load_feature_data(symbol: str) -> pd.DataFrame:
    """Load feature data for one symbol, cached until the file changes."""
    path = get_feature_file(symbol)
    return _load_feature_cached(str(path), _mtime(path)).copy(deep=False)


@lru_cache(maxsize=512)
def _market_summary_cached(symbol: str, path_text: str, mtime_ns: int) -> dict:
    del path_text, mtime_ns  # cache-key components; loading uses public helper
    df = load_feature_data(symbol)
    # Feature files are normally chronological. Only sort when necessary.
    if "timestamp" in df.columns and not df["timestamp"].is_monotonic_increasing:
        df = df.sort_values("timestamp")
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else latest
    close = float(latest["close"])
    previous_close = float(previous["close"])
    price_change = close - previous_close
    price_change_pct = price_change / previous_close if previous_close else 0.0
    return {
        "symbol": symbol,
        "timestamp": str(latest["timestamp_utc"]),
        "close": close,
        "price_change": float(price_change),
        "price_change_pct": float(price_change_pct),
        "rsi_14": float(latest["rsi_14"]) if pd.notna(latest["rsi_14"]) else None,
        "sma_20": float(latest["sma_20"]) if pd.notna(latest["sma_20"]) else None,
        "sma_50": float(latest["sma_50"]) if pd.notna(latest["sma_50"]) else None,
        "sma_200": float(latest["sma_200"]) if pd.notna(latest["sma_200"]) else None,
        "volatility_20d": float(latest["volatility_20d"]) if pd.notna(latest["volatility_20d"]) else None,
        "volume": float(latest["volume"]),
        "volume_ratio": float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else None,
    }


def get_market_summary(symbol: str) -> dict:
    """Return latest market and technical values with automatic cache invalidation."""
    symbol = symbol.upper().strip()
    path = get_feature_file(symbol)
    return dict(_market_summary_cached(symbol, str(path), _mtime(path)))


@lru_cache(maxsize=512)
def _recent_prices_cached(symbol: str, limit: int, path_text: str, mtime_ns: int) -> tuple:
    del path_text, mtime_ns
    df = load_gold_data(symbol)
    if "timestamp" in df.columns and not df["timestamp"].is_monotonic_increasing:
        df = df.sort_values("timestamp")
    # Calculate only the tail needed for the display plus one prior row for the
    # first visible close-to-close return instead of copying/sorting all history.
    work = df.tail(max(2, int(limit) + 1)).copy()
    work["daily_change_pct"] = work["close"].pct_change()
    recent = work.tail(limit).iloc[::-1]
    records = []
    for _, row in recent.iterrows():
        records.append({
            "timestamp": str(row["timestamp_utc"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "daily_change_pct": float(row["daily_change_pct"]) if pd.notna(row["daily_change_pct"]) else None,
            "sma_20": float(row["sma_20"]) if "sma_20" in recent.columns and pd.notna(row["sma_20"]) else None,
            "sma_50": float(row["sma_50"]) if "sma_50" in recent.columns and pd.notna(row["sma_50"]) else None,
            "sma_200": float(row["sma_200"]) if "sma_200" in recent.columns and pd.notna(row["sma_200"]) else None,
            "volume": float(row["volume"]),
        })
    return tuple(records)


def get_recent_prices(symbol: str, limit: int = 20) -> list:
    """Return newest market sessions, cached until the source file changes."""
    symbol = symbol.upper().strip()
    limit = int(limit)
    path = get_gold_file(symbol)
    return [dict(row) for row in _recent_prices_cached(symbol, limit, str(path), _mtime(path))]
