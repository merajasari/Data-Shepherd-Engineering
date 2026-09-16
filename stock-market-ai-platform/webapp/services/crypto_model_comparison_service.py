"""Read-only service for the generated crypto model comparison artifact."""
from __future__ import annotations

import json
from pathlib import Path

COMPARISON_PATH = Path("webapp/static/generated/crypto_model_comparison.json")


def get_crypto_model_comparison(path=COMPARISON_PATH):
    path = Path(path)
    if not path.exists():
        return {
            "available": False,
            "error": "Crypto comparison artifact is not available yet.",
            "build_command": "python -m ml.build_crypto_model_comparison",
            "series": [],
            "unavailable_series": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "error": f"Crypto comparison artifact is unreadable: {exc}", "series": [], "unavailable_series": []}
    required = {"schema_version", "starting_capital", "series", "research_safety"}
    missing = sorted(required - set(payload))
    if missing:
        return {"available": False, "error": "Crypto comparison artifact is missing: " + ", ".join(missing), "series": [], "unavailable_series": []}
    return {**payload, "available": True}
