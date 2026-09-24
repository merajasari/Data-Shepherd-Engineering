"""Read-only health assessment for the Tiingo IEX stock stream."""
from __future__ import annotations

from datetime import datetime, time, timezone
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

from webapp.services.live_market_service import load_live_cache


LABEL = "com.datashepherd.iexstream"
MARKET_TZ = ZoneInfo("America/New_York")
FRESH_SECONDS = 90.0
CACHE_PATH = Path("data/live/latest_quotes.json")


def _parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _regular_session_clock(now_utc):
    local = now_utc.astimezone(MARKET_TZ)
    weekday = local.weekday() < 5
    in_hours = time(9, 30) <= local.time().replace(tzinfo=None) < time(16, 0)
    return {
        "expected_open": bool(weekday and in_hours),
        "market_time": local.isoformat(),
        "market_timezone": "America/New_York",
        "note": "Regular-session clock only; exchange holidays may still be closed.",
    }


def _launchagent_state():
    domain = f"gui/{os.getuid()}/{LABEL}"
    try:
        result = subprocess.run(
            ["launchctl", "print", domain],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"loaded": False, "running": False, "detail": "launchctl unavailable"}

    text = (result.stdout or "") + (result.stderr or "")
    loaded = result.returncode == 0
    running = loaded and "state = running" in text
    detail = "running" if running else ("loaded, not running" if loaded else "not loaded")
    return {"loaded": loaded, "running": running, "detail": detail}


def get_stock_stream_health(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    cache = load_live_cache()
    quotes = cache.get("quotes", {}) or {}
    configured = cache.get("configured_symbols", []) or []
    updated = _parse_timestamp(cache.get("updated_at"))
    age_seconds = (now_utc - updated).total_seconds() if updated else None
    session = _regular_session_clock(now_utc)
    agent = _launchagent_state()

    if not agent["running"]:
        status = "ERROR"
        detail = f"Tiingo IEX LaunchAgent is {agent['detail']}."
    elif session["expected_open"]:
        if not updated:
            status = "ERROR"
            detail = "Regular session expected but the live quote cache has no heartbeat timestamp."
        elif age_seconds <= FRESH_SECONDS and quotes:
            status = "LIVE"
            detail = "Tiingo IEX stream is running and live quotes are fresh during the regular session."
        elif age_seconds <= FRESH_SECONDS:
            status = "STARTING"
            detail = "Stream is running and cache heartbeat is fresh; waiting for the first live trade messages."
        else:
            status = "STALE"
            detail = "Regular session expected but the live quote cache has stopped advancing."
    else:
        status = "AFTER_HOURS_CONNECTED"
        detail = "Tiingo IEX WebSocket is running. No new trade messages are required while the regular session is closed."

    return {
        "status": status,
        "detail": detail,
        "launchagent_loaded": agent["loaded"],
        "launchagent_running": agent["running"],
        "cache_exists": CACHE_PATH.exists(),
        "cache_updated_at": cache.get("updated_at"),
        "cache_age_seconds": age_seconds,
        "configured_symbol_count": len(configured),
        "live_symbol_count": len(quotes),
        "regular_session_expected_open": session["expected_open"],
        "market_time": session["market_time"],
        "market_timezone": session["market_timezone"],
        "session_note": session["note"],
        "fresh_after_seconds": FRESH_SECONDS,
        "real_orders": False,
    }
