"""Crypto 15m V3 Phase 4: economic rejection diagnostics.

Reads corrected Phase 3 non-overlapping hourly economic results. This phase does
not fit models or tune policies. It records whether the current 15m/1h policy
family survives realistic turnover costs and compares policies consistently.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

PHASE3_ROOT = Path("data/model/crypto_15m_v3/phase3")
SUMMARY_PATH = PHASE3_ROOT / "policy_summary.csv"
OUTPUT_ROOT = Path("data/model/crypto_15m_v3/phase4")
DIAGNOSTICS_PATH = OUTPUT_ROOT / "economic_diagnostics.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
REALISTIC_COST_FLOOR_BPS = 5


def main():
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError(f"Missing corrected Phase 3 summary: {SUMMARY_PATH}")
    df = pd.read_csv(SUMMARY_PATH)
    required = {"policy_id", "cost_bps", "ending_equity", "max_drawdown", "executed_switches"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"Phase 3 summary missing columns: {sorted(missing)}")

    rows = []
    for cost, group in df.groupby("cost_bps", sort=True):
        best = group.sort_values(["ending_equity", "max_drawdown"], ascending=[False, False]).iloc[0]
        rows.append({
            "cost_bps": float(cost),
            "best_policy_id": best["policy_id"],
            "best_ending_equity": float(best["ending_equity"]),
            "best_max_drawdown": float(best["max_drawdown"]),
            "best_executed_switches": int(best["executed_switches"]),
            "above_starting_equity": bool(float(best["ending_equity"]) > 1.0),
        })

    diagnostics = pd.DataFrame(rows)
    realistic = diagnostics[diagnostics["cost_bps"] >= REALISTIC_COST_FLOOR_BPS]
    survives_realistic_costs = bool((realistic["best_ending_equity"] > 1.0).any()) if not realistic.empty else False
    status = "CONTINUE_RESEARCH" if survives_realistic_costs else "REJECT_CURRENT_POLICY_FAMILY"

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(DIAGNOSTICS_PATH, index=False)
    manifest = {
        "research_version": "crypto_15m_v3",
        "phase": 4,
        "stage": "economic_rejection_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(SUMMARY_PATH),
        "economic_accounting": "non-overlapping 1-hour realizations with 15-minute decisions",
        "realistic_cost_floor_bps": REALISTIC_COST_FLOOR_BPS,
        "status": status,
        "reason": "Current 15m/1h Shared V3 turnover-control policies must remain above starting equity under realistic switching costs to continue toward a forward candidate.",
        "no_new_tuning": True,
        "frozen_v2_modified": False,
        "brokerage_orders": False,
        "future_holdout_start_utc": "2026-09-01T00:00:00+00:00",
        "next_step": "If rejected, preserve results as evidence and design a new research version/hypothesis rather than tuning this policy family on the same OOS results.",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("CRYPTO 15M V3 PHASE 4")
    print("=" * 90)
    print(diagnostics.to_string(index=False))
    print(f"STATUS: {status}")
    print("No model fitting, policy tuning, holdout evaluation, or orders.")


if __name__ == "__main__":
    main()
