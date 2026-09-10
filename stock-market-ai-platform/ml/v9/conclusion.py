"""Persist the final V9 research disposition from the Phase 4 gate.

This module is documentation-only. It does not score holdout data, freeze a V9
candidate, modify production state, or place brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

PHASE4_DECISION = Path("data/model/v9/phase4/decision.json")
OUTPUT = Path("data/model/v9/final_manifest.json")


def main():
    if not PHASE4_DECISION.exists():
        raise FileNotFoundError("Run V9 Phase 4 before recording the conclusion")
    decision = json.loads(PHASE4_DECISION.read_text())
    if decision.get("v9_promotion") != "REJECTED":
        raise RuntimeError("V9 conclusion writer is intended only for the rejected Phase-4 disposition")

    manifest = {
        "research_version": "stock_v9",
        "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "CLOSED_REJECTED",
        "champion": decision.get("champion"),
        "best_v9_challenger": decision.get("best_v9_challenger"),
        "promotion_result": decision.get("v9_promotion"),
        "metrics_won": decision.get("metrics_won_by_best_v9"),
        "metrics_total": decision.get("metrics_total"),
        "reason": "Best V9 challenger failed the predeclared full-cycle champion/challenger gate against frozen V8.",
        "v8_modified": False,
        "v9_candidate_frozen": False,
        "v9_holdout_opened": False,
        "production_modified": False,
        "brokerage_orders": False,
        "research_lessons": [
            "The fixed V9 rank blend contained useful standalone information but did not improve frozen V8 across the full economic contract.",
            "The strongest V9 behavior was conditional/defensive rather than a superior always-on replacement for V8.",
            "V9 is closed without tuning the rejected challenger or consuming its reserved future holdout.",
        ],
        "next_research_track": "stock_v10_regime_conditioned_ranking",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n")

    print("V9 FINAL RESEARCH DISPOSITION")
    print("=" * 80)
    print("Status: CLOSED_REJECTED")
    print(f"Champion: {manifest['champion']}")
    print(f"Best V9 challenger: {manifest['best_v9_challenger']}")
    print(f"Gate: {manifest['metrics_won']}/{manifest['metrics_total']} metrics won")
    print("V9 holdout opened: False")
    print("Production modified: False")
    print("Brokerage orders: False")


if __name__ == "__main__":
    main()
