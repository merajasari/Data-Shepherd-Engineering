"""Market data service for the presentation layer.

The research/model views continue to read the persisted Gold and Feature layers.
The Live Stock Viewer uses a separate read-only presentation path that merges:
- persisted Gold history,
- freshly fetched Tiingo completed EOD sessions, and
- the current Tiingo IEX reference price supplied by live_market_service.

Nothing in this module writes back to Gold, Features, model artifacts, or V8
holdout evidence.
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
    file_path = get_gold_file(symbol)
    if not file_path.exists():
        raise FileNotFoundError(f"Gold dataset not found: {file_path}")
    return pd.read_parquet(file_path)


def load_feature_data(symbol: str) -> pd.DataFrame:
    file_path = get_feature_file(symbol)
    if not file_path.exists():
        raise FileNotFoundError(f"Feature dataset not found: {file_path}")
    return pd.read_parquet(file_path)


def get_market_summary(symbol: str) -> dict:
    """Return latest persisted market and technical values."""
    df = load_feature_data(symbol).sort_values("timestamp").reset_index(drop=True)
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


def _prepare_gold_frame(symbol: str) -> pd.DataFrame:
    df = load_gold_data(symbol).copy()
    if "timestamp_utc" in df.columns:
        df["session_date"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").dt.date
    else:
        df["session_date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce").dt.date
    return df.dropna(subset=["session_date"]).sort_values("session_date").reset_index(drop=True)


def _fetch_recent_tiingo_eod(symbol: str) -> pd.DataFrame:
    """Fetch recent completed Tiingo daily bars with a short in-process cache."""
    now = time.monotonic()
    cached = _live_eod_cache.get(symbol)
    if cached and now - cached["fetched_monotonic"] < LIVE_EOD_CACHE_TTL_SECONDS:
        return cached["frame"].copy()

    token = os.getenv("TIINGO_API_KEY")
    if not token:
        return pd.DataFrame()

    start = (date.today() - timedelta(days=45)).isoformat()
    end = date.today().isoformat()
    try:
        response = requests.get(
            f"https://api.tiingo.com/tiingo/daily/{symbol}/prices",
            params={"startDate": start, "endDate": end, "format": "json", "token": token},
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
        except (TypeError, ValueError, KeyError):
            continue

    frame = pd.DataFrame(rows)
    _live_eod_cache[symbol] = {"fetched_monotonic": now, "frame": frame.copy()}
    return frame


def _build_live_daily_frame(symbol: str) -> tuple[pd.DataFrame, bool]:
    """Merge local Gold with newly available Tiingo EOD sessions in memory only."""
    local = _prepare_gold_frame(symbol)
    remote = _fetch_recent_tiingo_eod(symbol)
    remote_used = not remote.empty
    if not remote.empty:
        base_cols = ["session_date", "timestamp_utc", "open", "high", "low", "close", "volume"]
        local_simple = local[[c for c in base_cols if c in local.columns]].copy()
        merged = pd.concat([local_simple, remote[base_cols]], ignore_index=True, sort=False)
        merged = merged.sort_values("session_date").drop_duplicates("session_date", keep="last").reset_index(drop=True)
    else:
        merged = local.copy()

    merged["close"] = pd.to_numeric(merged["close"], errors="coerce")
    merged["volume"] = pd.to_numeric(merged["volume"], errors="coerce")
    merged = merged.dropna(subset=["close"]).reset_index(drop=True)
    merged["daily_change_pct"] = merged["close"].pct_change()
    merged["sma_20"] = merged["close"].rolling(20, min_periods=1).mean()
    merged["sma_50"] = merged["close"].rolling(50, min_periods=1).mean()
    merged["sma_200"] = merged["close"].rolling(200, min_periods=1).mean()
    merged["volume_sma_20"] = merged["volume"].rolling(20, min_periods=1).mean()
    merged["volume_ratio"] = merged["volume"] / merged["volume_sma_20"]
    merged["volatility_20d"] = merged["daily_change_pct"].rolling(20, min_periods=2).std()

    delta = merged["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    merged["rsi_14"] = 100 - (100 / (1 + rs))
    return merged, remote_used


def _record_from_row(row) -> dict:
    timestamp = row.get("timestamp_utc")
    if not timestamp or str(timestamp) == "nan":
        timestamp = f"{row['session_date'].isoformat()}T00:00:00+00:00"
    return {
        "timestamp": str(timestamp),
        "session_date": row["session_date"].isoformat(),
        "open": float(row["open"]) if pd.notna(row.get("open")) else None,
        "high": float(row["high"]) if pd.notna(row.get("high")) else None,
        "low": float(row["low"]) if pd.notna(row.get("low")) else None,
        "close": float(row["close"]),
        "daily_change_pct": float(row["daily_change_pct"]) if pd.notna(row.get("daily_change_pct")) else None,
        "sma_20": float(row["sma_20"]) if pd.notna(row.get("sma_20")) else None,
        "sma_50": float(row["sma_50"]) if pd.notna(row.get("sma_50")) else None,
        "sma_200": float(row["sma_200"]) if pd.notna(row.get("sma_200")) else None,
        "volume": float(row["volume"]) if pd.notna(row.get("volume")) else None,
        "completed_session": True,
        "live": False,
    }


def get_live_stock_view_payload(symbol: str, live_quote: dict | None = None, limit: int = 60) -> dict:
    """Return a current presentation-only payload for the Live Stock Viewer."""
    df, remote_used = _build_live_daily_frame(symbol)
    if df.empty:
        raise ValueError(f"No market data available for {symbol}")

    latest = df.iloc[-1]
    previous = df.iloc[-2] if len(df) > 1 else latest
    latest_close = float(latest["close"])
    completed = [_record_from_row(row) for _, row in df.tail(limit).iterrows()]

    live_quote = live_quote or {}
    live_available = bool(live_quote.get("available") and live_quote.get("reference_price") is not None)
    live_point = None
    technical = {
        "rsi_14": float(latest["rsi_14"]) if pd.notna(latest["rsi_14"]) else None,
        "sma_20": float(latest["sma_20"]),
        "sma_50": float(latest["sma_50"]),
        "sma_200": float(latest["sma_200"]),
        "volatility_20d": float(latest["volatility_20d"]) if pd.notna(latest["volatility_20d"]) else None,
        "volume_ratio": float(latest["volume_ratio"]) if pd.notna(latest["volume_ratio"]) else None,
        "mode": "COMPLETED SESSION",
    }

    if live_available:
        live_price = float(live_quote["reference_price"])
        closes = df["close"].astype(float).tolist()
        live_timestamp = live_quote.get("timestamp") or live_quote.get("received_at")
        try:
            live_date = pd.to_datetime(live_timestamp, utc=True).date() if live_timestamp else date.today()
        except Exception:
            live_date = date.today()
        if live_date == latest["session_date"]:
            provisional_closes = closes[:-1] + [live_price]
            prior_close = float(previous["close"])
        else:
            provisional_closes = closes + [live_price]
            prior_close = latest_close
        s = pd.Series(provisional_closes, dtype="float64")
        d = s.diff()
        g = d.clip(lower=0).rolling(14).mean()
        l = (-d.clip(upper=0)).rolling(14).mean()
        rs_live = g.iloc[-1] / l.iloc[-1] if pd.notna(l.iloc[-1]) and l.iloc[-1] != 0 else None
        technical.update({
            "rsi_14": (100 - (100 / (1 + rs_live))) if rs_live is not None else technical["rsi_14"],
            "sma_20": float(s.tail(20).mean()),
            "sma_50": float(s.tail(50).mean()),
            "sma_200": float(s.tail(200).mean()),
            "mode": "LIVE / PROVISIONAL",
        })
        live_point = {
            "timestamp": str(live_timestamp or date.today().isoformat()),
            "session_date": live_date.isoformat(),
            "open": None,
            "high": None,
            "low": None,
            "close": live_price,
            "daily_change_pct": (live_price / prior_close - 1.0) if prior_close else None,
            "sma_20": technical["sma_20"],
            "sma_50": technical["sma_50"],
            "sma_200": technical["sma_200"],
            "volume": None,
            "completed_session": False,
            "live": True,
            "received_at": live_quote.get("received_at"),
        }

    chart_history = list(completed)
    if live_point:
        if chart_history and live_point["session_date"] == chart_history[-1]["session_date"]:
            chart_history[-1] = live_point
        else:
            chart_history.append(live_point)

    display_price = live_point["close"] if live_point else latest_close
    prior_for_display = float(previous["close"]) if live_point and live_point["session_date"] == latest["session_date"].isoformat() else latest_close
    if not live_point:
        prior_for_display = float(previous["close"])

    return {
        "symbol": symbol,
        "display_price": display_price,
        "price_source": "LIVE IEX" if live_point else "LATEST COMPLETED EOD",
        "price_timestamp": live_point["timestamp"] if live_point else str(latest.get("timestamp_utc")),
        "price_change": display_price - prior_for_display,
        "price_change_pct": (display_price / prior_for_display - 1.0) if prior_for_display else 0.0,
        "latest_completed_session": latest["session_date"].isoformat(),
        "latest_completed_close": latest_close,
        "completed_sessions": list(reversed(completed)),
        "chart_history": chart_history,
        "technical": technical,
        "live_quote": live_point,
        "data_status": {
            "historical_source": "TIINGO EOD + LOCAL GOLD" if remote_used else "LOCAL GOLD (Tiingo refresh unavailable)",
            "live_source": "TIINGO IEX REFERENCE PRICE" if live_point else "NO CURRENT LIVE QUOTE",
            "eod_refresh_cache_seconds": LIVE_EOD_CACHE_TTL_SECONDS,
        },
    }


def get_recent_prices(symbol: str, limit: int = 20) -> list:
    """Return persisted Gold sessions for research/model presentation."""
    df = load_gold_data(symbol).sort_values("timestamp").reset_index(drop=True)
    df["daily_change_pct"] = df["close"].pct_change()
    recent = df.tail(limit).sort_values("timestamp", ascending=False)
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
    return records
