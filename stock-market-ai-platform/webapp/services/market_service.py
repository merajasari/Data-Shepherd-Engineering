"""Market data service for dashboard presentation.

Persisted Gold/Feature files remain the research source of record.  For display,
recent completed Tiingo EOD sessions are merged in memory so the Live Stock
Viewer does not stop at the last persisted Gold refresh.  Nothing here writes
back to research data or V8 artifacts.
"""

import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests


LIVE_EOD_CACHE_TTL_SECONDS = 300
_live_eod_cache = {}


def get_gold_file(symbol: str) -> Path:
    return Path(f"data/gold/stocks/{symbol}/{symbol}_prices.parquet")


def get_feature_file(symbol: str) -> Path:
    return Path(f"data/features/stocks/{symbol}/{symbol}_features.parquet")


def load_gold_data(symbol: str) -> pd.DataFrame:
    path = get_gold_file(symbol)
    if not path.exists():
        raise FileNotFoundError(f"Gold dataset not found: {path}")
    return pd.read_parquet(path)


def load_feature_data(symbol: str) -> pd.DataFrame:
    path = get_feature_file(symbol)
    if not path.exists():
        raise FileNotFoundError(f"Feature dataset not found: {path}")
    return pd.read_parquet(path)


def get_market_summary(symbol: str) -> dict:
    """Return persisted feature values used by the research/model page."""
    df = load_feature_data(symbol).sort_values("timestamp").reset_index(drop=True)
    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else latest
    close = float(latest["close"])
    previous_close = float(previous["close"])
    change = close - previous_close
    return {
        "symbol": symbol,
        "timestamp": str(latest["timestamp_utc"]),
        "close": close,
        "price_change": change,
        "price_change_pct": change / previous_close if previous_close else 0.0,
        "rsi_14": float(latest["rsi_14"]) if pd.notna(latest["rsi_14"]) else None,
        "sma_20": float(latest["sma_20"]) if pd.notna(latest["sma_20"]) else None,
        "sma_50": float(latest["sma_50"]) if pd.notna(latest["sma_50"]) else None,
        "sma_200": float(latest["sma_200"]) if pd.notna(latest["sma_200"]) else None,
        "volatility_20d": float(latest["volatility_20d"]) if pd.notna(latest["volatility_20d"]) else None,
        "volume": float(latest["volume"]),
        "volume_ratio": float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else None,
    }


def _local_gold_frame(symbol: str) -> pd.DataFrame:
    df = load_gold_data(symbol).copy()
    if "timestamp_utc" in df.columns:
        df["session_date"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dt.date
    else:
        df["session_date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce").dt.date
    return df.dropna(subset=["session_date"]).sort_values("session_date").reset_index(drop=True)


def _fetch_recent_tiingo_eod(symbol: str) -> pd.DataFrame:
    """Fetch recent completed EOD bars; cache each selected symbol for 5 minutes."""
    now = time.monotonic()
    cached = _live_eod_cache.get(symbol)
    if cached and now - cached["fetched"] < LIVE_EOD_CACHE_TTL_SECONDS:
        return cached["frame"].copy()

    token = os.getenv("TIINGO_API_KEY")
    if not token:
        return cached["frame"].copy() if cached else pd.DataFrame()

    try:
        response = requests.get(
            f"https://api.tiingo.com/tiingo/daily/{symbol}/prices",
            params={
                "startDate": (date.today() - timedelta(days=45)).isoformat(),
                "endDate": date.today().isoformat(),
                "format": "json",
                "token": token,
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"[LIVE STOCK EOD ERROR] {symbol}: {exc}")
        return cached["frame"].copy() if cached else pd.DataFrame()

    rows = []
    for item in payload:
        try:
            rows.append({
                "session_date": pd.to_datetime(item["date"], utc=True).date(),
                "timestamp_utc": str(item["date"]),
                "open": float(item.get("adjOpen", item.get("open"))),
                "high": float(item.get("adjHigh", item.get("high"))),
                "low": float(item.get("adjLow", item.get("low"))),
                "close": float(item.get("adjClose", item.get("close"))),
                "volume": float(item.get("adjVolume", item.get("volume"))),
            })
        except (KeyError, TypeError, ValueError):
            continue

    frame = pd.DataFrame(rows)
    _live_eod_cache[symbol] = {"fetched": now, "frame": frame.copy()}
    return frame


def _current_display_frame(symbol: str) -> pd.DataFrame:
    """Merge local Gold with recent Tiingo EOD, then calculate display indicators."""
    local = _local_gold_frame(symbol)
    remote = _fetch_recent_tiingo_eod(symbol)
    if not remote.empty:
        cols = ["session_date", "timestamp_utc", "open", "high", "low", "close", "volume"]
        local = local[[c for c in cols if c in local.columns]]
        df = pd.concat([local, remote[cols]], ignore_index=True, sort=False)
        df = df.sort_values("session_date").drop_duplicates("session_date", keep="last").reset_index(drop=True)
    else:
        df = local.copy()

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    df["daily_change_pct"] = df["close"].pct_change()
    df["sma_20"] = df["close"].rolling(20, min_periods=1).mean()
    df["sma_50"] = df["close"].rolling(50, min_periods=1).mean()
    df["sma_200"] = df["close"].rolling(200, min_periods=1).mean()
    df["volume_sma_20"] = df["volume"].rolling(20, min_periods=1).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma_20"]
    df["volatility_20d"] = df["daily_change_pct"].rolling(20, min_periods=2).std()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi_14"] = 100 - (100 / (1 + rs))
    return df


def get_live_display_technicals(symbol: str) -> dict:
    """Latest completed-session technicals from the current display frame."""
    df = _current_display_frame(symbol)
    row = df.iloc[-1]
    return {
        "session_date": row["session_date"].isoformat(),
        "rsi_14": float(row["rsi_14"]) if pd.notna(row["rsi_14"]) else None,
        "sma_20": float(row["sma_20"]),
        "sma_50": float(row["sma_50"]),
        "sma_200": float(row["sma_200"]),
        "volatility_20d": float(row["volatility_20d"]) if pd.notna(row["volatility_20d"]) else None,
        "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
    }


def get_recent_prices(symbol: str, limit: int = 20) -> list:
    """Return newest completed sessions, including EOD rows newer than local Gold."""
    df = _current_display_frame(symbol)
    recent = df.tail(limit).sort_values("session_date", ascending=False)
    records = []
    for _, row in recent.iterrows():
        timestamp = row.get("timestamp_utc")
        if not timestamp or str(timestamp) == "nan":
            timestamp = f"{row['session_date'].isoformat()}T00:00:00+00:00"
        records.append({
            "timestamp": str(timestamp),
            "session_date": row["session_date"].isoformat(),
            "open": float(row["open"]) if pd.notna(row.get("open")) else None,
            "high": float(row["high"]) if pd.notna(row.get("high")) else None,
            "low": float(row["low"]) if pd.notna(row.get("low")) else None,
            "close": float(row["close"]),
            "daily_change_pct": float(row["daily_change_pct"]) if pd.notna(row["daily_change_pct"]) else None,
            "sma_20": float(row["sma_20"]),
            "sma_50": float(row["sma_50"]),
            "sma_200": float(row["sma_200"]),
            "volume": float(row["volume"]) if pd.notna(row["volume"]) else None,
            "rsi_14": float(row["rsi_14"]) if pd.notna(row["rsi_14"]) else None,
            "volatility_20d": float(row["volatility_20d"]) if pd.notna(row["volatility_20d"]) else None,
            "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else None,
            "completed_session": True,
        })
    return records
