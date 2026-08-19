"""Read-only V4 reconstructed equity-history service."""

from __future__ import annotations

import json
from pathlib import Path

FULL_HISTORY_PATH = Path("data/model/v4/full_history_equity.json")
LEGACY_90D_PATHS = (
    Path("data/model/v4/reconstructed_90d_history.json"),
    Path("data/model/v4/v4_90d_reconstructed_history.json"),
)


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


def get_v4_reconstructed_history() -> list[dict]:
    """Prefer the full-history artifact; retain legacy fallback during migration."""
    if FULL_HISTORY_PATH.exists():
        return _read_rows(FULL_HISTORY_PATH)
    for path in LEGACY_90D_PATHS:
        if path.exists():
            return _read_rows(path)
    return []


def get_v4_reconstructed_90d_history() -> list[dict]:
    """Backward-compatible name used by older dashboard code."""
    return get_v4_reconstructed_history()
