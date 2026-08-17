"""Append-only near-real-time V4 mark-to-market equity journal."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.paper_trading_service import get_pnl_attribution, get_portfolio_summary

JOURNAL_DIR = Path("data/paper_trading")
JOURNAL_PATH = JOURNAL_DIR / "realtime_equity_journal.jsonl"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(rows):
    payload = [
        {
            "symbol": r.get("symbol"),
            "current_price": r.get("current_price"),
            "quote_timestamp": r.get("quote_timestamp"),
            "price_source": r.get("price_source"),
        }
        for r in sorted(rows, key=lambda x: str(x.get("symbol")))
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_last():
    if not JOURNAL_PATH.exists():
        return None
    last = None
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def build_observation():
    summary = get_portfolio_summary()
    attribution = get_pnl_attribution()
    positions = list(attribution.get("positions") or [])
    return {
        "timestamp": _utc_now(),
        "equity": float(summary.get("equity") or 0.0),
        "cash": float(summary.get("cash") or 0.0),
        "market_value": float(summary.get("market_value") or 0.0),
        "realized_pnl": float(summary.get("realized_pnl") or 0.0),
        "unrealized_pnl": float(summary.get("unrealized_pnl") or 0.0),
        "total_return_pct": float(summary.get("total_return_pct") or 0.0),
        "quote_fingerprint": _fingerprint(positions),
        "quote_sources": sorted({str(r.get("price_source")) for r in positions}),
        "journal_type": "V4_REALTIME_MARK_TO_MARKET",
        "portfolio_state_modified": False,
        "brokerage_orders": False,
    }


def append_realtime_equity_observation(skip_duplicate_quotes=True):
    observation = build_observation()
    last = _read_last()
    if skip_duplicate_quotes and last and last.get("quote_fingerprint") == observation.get("quote_fingerprint"):
        return {"status": "skipped_duplicate_quotes", "timestamp": observation["timestamp"]}
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, sort_keys=True) + "\n")
    return {
        "status": "appended",
        "timestamp": observation["timestamp"],
        "equity": observation["equity"],
        "journal_path": str(JOURNAL_PATH),
    }


def get_v4_realtime_equity_history():
    if not JOURNAL_PATH.exists():
        return []
    rows = []
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("timestamp")
            eq = row.get("equity")
            if ts is None or eq is None:
                continue
            rows.append({"timestamp": ts, "equity": float(eq), "realtime_mark": True})
    return rows
