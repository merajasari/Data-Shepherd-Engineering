"""Fail-closed V11 five-minute intraday research foundation.

This module performs no network I/O, imports no brokerage SDK, and cannot place
orders. It validates completed regular-session bars and derives research-only
features without reading V8/V10 production evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from math import log, sqrt
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
REQUIRED_FIELDS = ("symbol", "timestamp_utc", "open", "high", "low", "close", "volume")
BAR_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True)
class IntradayValidation:
    accepted: bool
    reasons: tuple[str, ...]
    completed_bar_count: int

    @property
    def status(self) -> str:
        return "ACCEPTED_FOR_RESEARCH" if self.accepted else "REJECTED_FAIL_CLOSED"


@dataclass(frozen=True)
class IntradayFeatures:
    symbol: str
    timestamp_utc: datetime
    return_5m: float
    return_15m: float
    vwap_distance: float
    volume_acceleration: float
    realized_volatility_30m: float
    opening_gap: float


def _utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def validate_completed_bars(
    bars: Sequence[Mapping[str, object]],
    *,
    now_utc: datetime,
    expected_symbol: str,
    minimum_bars: int = 6,
    maximum_age_seconds: int = 420,
) -> IntradayValidation:
    reasons: list[str] = []
    if now_utc.tzinfo is None:
        reasons.append("NOW_MUST_BE_TIMEZONE_AWARE")
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    if len(bars) < minimum_bars:
        reasons.append("INSUFFICIENT_COMPLETED_BARS")

    timestamps: list[datetime] = []
    for bar in bars:
        missing = [field for field in REQUIRED_FIELDS if field not in bar]
        if missing:
            reasons.append("REQUIRED_FIELD_MISSING")
            continue
        if str(bar.get("symbol", "")).upper() != expected_symbol.upper():
            reasons.append("SYMBOL_MISMATCH")

        timestamp = _utc(bar.get("timestamp_utc"))
        if timestamp is None:
            reasons.append("TIMESTAMP_INVALID")
            continue
        timestamps.append(timestamp)

        local = timestamp.astimezone(NEW_YORK)
        if local.weekday() >= 5 or not (time(9, 30) <= local.time() < time(16, 0)):
            reasons.append("OUTSIDE_REGULAR_SESSION")

        values = [_number(bar.get(name)) for name in ("open", "high", "low", "close")]
        volume = _number(bar.get("volume"))
        if any(value is None or value <= 0 for value in values):
            reasons.append("PRICE_INVALID")
        elif values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
            reasons.append("OHLC_INCONSISTENT")
        if volume is None or volume < 0:
            reasons.append("VOLUME_INVALID")

        if timestamp + BAR_INTERVAL > now_utc:
            reasons.append("INCOMPLETE_BAR")

    if timestamps:
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            reasons.append("TIMESTAMPS_NOT_STRICTLY_INCREASING")
        for left, right in zip(timestamps, timestamps[1:]):
            if right - left != BAR_INTERVAL:
                reasons.append("FIVE_MINUTE_SEQUENCE_GAP")
                break
        age = (now_utc - (timestamps[-1] + BAR_INTERVAL)).total_seconds()
        if age < 0:
            reasons.append("INCOMPLETE_BAR")
        elif age > maximum_age_seconds:
            reasons.append("LATEST_BAR_STALE")

    unique = tuple(dict.fromkeys(reasons))
    return IntradayValidation(not unique, unique, len(timestamps))


def derive_features(
    bars: Sequence[Mapping[str, object]],
    *,
    previous_close: float,
) -> IntradayFeatures:
    """Derive a small auditable feature vector after validation succeeds."""
    if len(bars) < 6:
        raise ValueError("At least six completed bars are required")
    closes = [float(bar["close"]) for bar in bars]
    opens = [float(bar["open"]) for bar in bars]
    highs = [float(bar["high"]) for bar in bars]
    lows = [float(bar["low"]) for bar in bars]
    volumes = [float(bar["volume"]) for bar in bars]
    if previous_close <= 0 or any(value <= 0 for value in closes + opens + highs + lows):
        raise ValueError("Prices must be positive")

    typical = [(high + low + close) / 3.0 for high, low, close in zip(highs, lows, closes)]
    cumulative_volume = sum(volumes)
    if cumulative_volume <= 0:
        raise ValueError("Cumulative volume must be positive")
    vwap = sum(price * volume for price, volume in zip(typical, volumes)) / cumulative_volume

    log_returns = [log(right / left) for left, right in zip(closes, closes[1:])]
    recent = log_returns[-6:]
    mean = sum(recent) / len(recent)
    variance = sum((value - mean) ** 2 for value in recent) / max(len(recent) - 1, 1)
    prior_volume = sum(volumes[-6:-3]) / 3.0
    recent_volume = sum(volumes[-3:]) / 3.0

    timestamp = _utc(bars[-1]["timestamp_utc"])
    if timestamp is None:
        raise ValueError("Latest timestamp is invalid")
    return IntradayFeatures(
        symbol=str(bars[-1]["symbol"]).upper(),
        timestamp_utc=timestamp,
        return_5m=closes[-1] / closes[-2] - 1.0,
        return_15m=closes[-1] / closes[-4] - 1.0,
        vwap_distance=closes[-1] / vwap - 1.0,
        volume_acceleration=(recent_volume / prior_volume - 1.0) if prior_volume > 0 else 0.0,
        realized_volatility_30m=sqrt(variance),
        opening_gap=opens[0] / previous_close - 1.0,
    )


def validate_cross_section(
    symbol_results: Iterable[IntradayValidation],
    *,
    required_symbols: int = 101,
) -> IntradayValidation:
    results = tuple(symbol_results)
    reasons: list[str] = []
    if len(results) != required_symbols:
        reasons.append("UNIVERSE_INCOMPLETE")
    if any(not result.accepted for result in results):
        reasons.append("SYMBOL_VALIDATION_FAILED")
    counts = {result.completed_bar_count for result in results}
    if len(counts) > 1:
        reasons.append("CROSS_SECTION_BAR_COUNT_MISMATCH")
    unique = tuple(dict.fromkeys(reasons))
    return IntradayValidation(not unique, unique, min(counts) if counts else 0)
