"""Fast, local-only market history for initial dashboard rendering.

This deliberately avoids Tiingo REST calls so /dashboard can render immediately.
The Live Stock Viewer refresh layer can then hydrate newer completed sessions and
live IEX data asynchronously after the page is interactive.
"""

from pathlib import Path

import pandas as pd


def get_recent_prices_local(symbol: str, limit: int = 60) -> list:
    path = Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")
    if not path.exists():
        return []

    df = pd.read_parquet(path).copy()
    if "timestamp_utc" in df.columns:
        ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(df.get("timestamp"), unit="ms", utc=True, errors="coerce")
    df["_ts"] = ts
    df = df.dropna(subset=["_ts"]).sort_values("_ts").tail(limit).copy()

    close = pd.to_numeric(df.get("close"), errors="coerce")
    volume = pd.to_numeric(df.get("volume"), errors="coerce")
    df["daily_change_pct"] = close.pct_change()
    df["sma_20"] = close.rolling(20, min_periods=1).mean()
    df["sma_50"] = close.rolling(50, min_periods=1).mean()
    df["sma_200"] = close.rolling(200, min_periods=1).mean()
    volume_sma = volume.rolling(20, min_periods=1).mean()
    df["volume_ratio"] = volume / volume_sma
    df["volatility_20d"] = df["daily_change_pct"].rolling(20, min_periods=2).std()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi_14"] = 100 - (100 / (1 + rs))

    records = []
    for _, row in df.sort_values("_ts", ascending=False).iterrows():
        def num(name):
            value = row.get(name)
            return float(value) if value is not None and pd.notna(value) else None

        records.append({
            "timestamp": row["_ts"].isoformat(),
            "session_date": row["_ts"].date().isoformat(),
            "open": num("open"),
            "high": num("high"),
            "low": num("low"),
            "close": num("close"),
            "daily_change_pct": num("daily_change_pct"),
            "sma_20": num("sma_20"),
            "sma_50": num("sma_50"),
            "sma_200": num("sma_200"),
            "volume": num("volume"),
            "rsi_14": num("rsi_14"),
            "volatility_20d": num("volatility_20d"),
            "volume_ratio": num("volume_ratio"),
            "completed_session": True,
            "source": "LOCAL_GOLD_INITIAL_RENDER",
        })
    return records
