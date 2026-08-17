"""Read-only history reader for the V4/V5/SPY diagnostic comparison journal."""

from __future__ import annotations

import json
from pathlib import Path

JOURNAL_PATH = Path("data/paper_trading/v5_shadow/comparison_journal.jsonl")


def get_v5_shadow_history():
    rows = []
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append({
                "timestamp_utc": row.get("timestamp_utc"),
                "v4_normalized_equity": row.get("v4_normalized_equity"),
                "v5_shadow_equity": row.get("v5_shadow_equity"),
                "spy_normalized_equity": row.get("spy_normalized_equity"),
                "v5_vs_v4_pct_points": row.get("v5_vs_v4_pct_points"),
                "v5_vs_spy_pct_points": row.get("v5_vs_spy_pct_points"),
            })

    return {
        "journal_type": "V4_V5_SPY_DIAGNOSTIC_COMPARISON",
        "comparison_scope": "NON_OFFICIAL_DIAGNOSTIC",
        "observation_count": len(rows),
        "rows": rows,
        "official_holdout_excluded": True,
        "brokerage_orders": False,
    }
