"""Read-only V4 reconstructed equity-history service.

The full-history artifact is immutable between reconstruction runs, so cache the
parsed rows in memory and only reload when the file modification time changes.
This keeps the dashboard from reparsing thousands of JSON rows on every poll.
"""

from __future__ import annotations

import json
from pathlib import Path

FULL_HISTORY_PATH = Path("data/model/v4/full_history_equity.json")
LEGACY_90D_PATHS = (
    Path("data/model/v4/reconstructed_90d_history.json"),
    Path("data/model/v4/v4_90d_reconstructed_history.json"),
)

_CACHE_PATH: Path | None = None
_CACHE_MTIME_NS: int | None = None
_CACHE_ROWS: list[dict] = []


def _read_rows(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("history") or payload.get("equity_history") or payload.get("rows") or []
    else:
        rows = []

    clean = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("timestamp"):
            continue
        try:
            equity = float(row["equity"])
        except (KeyError, TypeError, ValueError):
            continue
        clean.append(
            {
                **row,
                "equity": equity,
                "reconstructed": True,
                "history_type": row.get("history_type") or "full_walk_forward_reconstruction",
            }
        )
    clean.sort(key=lambda row: str(row.get("timestamp") or ""))
    return clean


def _preferred_path() -> Path | None:
    if FULL_HISTORY_PATH.exists():
        return FULL_HISTORY_PATH
    for path in LEGACY_90D_PATHS:
        if path.exists():
            return path
    return None


def get_v4_reconstructed_history() -> list[dict]:
    """Return cached full-history rows, reloading only when the artifact changes."""
    global _CACHE_PATH, _CACHE_MTIME_NS, _CACHE_ROWS

    path = _preferred_path()
    if path is None:
        _CACHE_PATH = None
        _CACHE_MTIME_NS = None
        _CACHE_ROWS = []
        return []

    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return []

    if _CACHE_PATH == path and _CACHE_MTIME_NS == mtime_ns:
        return _CACHE_ROWS

    rows = _read_rows(path)
    _CACHE_PATH = path
    _CACHE_MTIME_NS = mtime_ns
    _CACHE_ROWS = rows
    return _CACHE_ROWS


def get_v4_reconstructed_90d_history() -> list[dict]:
    """Backward-compatible name used by older dashboard code."""
    return get_v4_reconstructed_history()
