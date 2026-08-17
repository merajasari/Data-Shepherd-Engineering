"""Append-only V4 vs V5 vs SPY diagnostic comparison journal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.v5_shadow_portfolio_service import get_v5_shadow_comparison

JOURNAL_DIR = Path("data/paper_trading/v5_shadow")
JOURNAL_PATH = JOURNAL_DIR / "comparison_journal.jsonl"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _quote_fingerprint(positions):
    payload = [
        {
            "symbol": row.get("symbol"),
            "current_price": row.get("current_price"),
            "quote_timestamp": row.get("quote_timestamp"),
            "price_source": row.get("price_source"),
        }
        for row in sorted(positions, key=lambda x: str(x.get("symbol")))
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_last_observation():
    if not JOURNAL_PATH.exists():
        return None
    last = None
    for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last


def build_comparison_observation():
    c = get_v5_shadow_comparison()
    positions = list(c.get("positions") or [])
    top_five = c.get("top_five") or []
    if top_five and isinstance(top_five[0], dict):
        top_five_symbols = [str(row.get("symbol")) for row in top_five]
    else:
        top_five_symbols = [str(symbol) for symbol in top_five]

    return {
        "timestamp_utc": _utc_now(),
        "journal_type": "V4_V5_SPY_DIAGNOSTIC_COMPARISON",
        "comparison_scope": "NON_OFFICIAL_DIAGNOSTIC",
        "shadow_started_at_utc": c.get("created_at_utc"),
        "v5_decision_timestamp_utc": c.get("decision_timestamp_utc"),
        "official_v5_holdout_start_utc": c.get("holdout_start_utc"),
        "v5_shadow_equity": c.get("v5_shadow_equity"),
        "v5_shadow_pnl": c.get("v5_shadow_pnl"),
        "v5_shadow_return_pct": c.get("v5_shadow_return_pct"),
        "v4_current_equity": c.get("v4_current_equity"),
        "v4_baseline_equity": c.get("v4_baseline_equity"),
        "v4_normalized_equity": c.get("v4_normalized_equity"),
        "v4_since_shadow_return_pct": c.get("v4_since_shadow_return_pct"),
        "spy_normalized_equity": c.get("spy_normalized_equity"),
        "spy_since_shadow_return_pct": c.get("spy_since_shadow_return_pct"),
        "v5_vs_v4_pct_points": c.get("v5_vs_v4_pct_points"),
        "v5_vs_spy_pct_points": c.get("v5_vs_spy_pct_points"),
        "modeled_v5_entry_friction": c.get("entry_friction"),
        "v5_top_five": top_five_symbols,
        "positions": [
            {
                "symbol": row.get("symbol"),
                "current_price": row.get("current_price"),
                "market_value": row.get("market_value"),
                "net_pnl": row.get("net_pnl"),
                "price_source": row.get("price_source"),
                "quote_timestamp": row.get("quote_timestamp"),
            }
            for row in positions
        ],
        "quote_fingerprint": _quote_fingerprint(positions),
        "official_holdout_journal_written": False,
        "official_holdout_excluded": True,
        "brokerage_orders": False,
    }


def append_comparison_observation(skip_duplicate_quotes=True):
    observation = build_comparison_observation()
    last = _read_last_observation()
    if skip_duplicate_quotes and last and last.get("quote_fingerprint") == observation.get("quote_fingerprint"):
        return {
            "status": "skipped_duplicate_quotes",
            "journal_path": str(JOURNAL_PATH),
            "timestamp_utc": observation["timestamp_utc"],
        }

    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, sort_keys=True) + "\n")

    return {
        "status": "appended",
        "journal_path": str(JOURNAL_PATH),
        "timestamp_utc": observation["timestamp_utc"],
        "v5_shadow_equity": observation["v5_shadow_equity"],
        "v4_normalized_equity": observation["v4_normalized_equity"],
        "spy_normalized_equity": observation["spy_normalized_equity"],
        "v5_vs_v4_pct_points": observation["v5_vs_v4_pct_points"],
        "v5_vs_spy_pct_points": observation["v5_vs_spy_pct_points"],
    }
