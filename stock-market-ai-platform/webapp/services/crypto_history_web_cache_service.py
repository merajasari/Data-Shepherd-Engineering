"""Fast reader for persistent Crypto Visual history payloads."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = PROJECT_ROOT / "data/live/crypto_rt/history_web"
ALLOWED_RANGES = {"30D", "90D", "1Y", "3Y", "5Y", "ALL"}


def normalize_history_range(value: str | None) -> str:
    key = (value or "90D").upper().strip()
    return key if key in ALLOWED_RANGES else "90D"


def get_crypto_history_cache_path(value: str | None) -> Path:
    key = normalize_history_range(value)
    return CACHE_ROOT / f"{key}.json"
