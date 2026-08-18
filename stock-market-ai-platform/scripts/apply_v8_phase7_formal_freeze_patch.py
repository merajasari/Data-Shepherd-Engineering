"""Apply Stock V8 Phase 7 formal candidate freeze."""

from pathlib import Path

PHASE7 = Path("ml/v8/phase7.py")


def main():
    PHASE7.parent.mkdir(parents=True, exist_ok=True)
    PHASE7.write_text(r'''"""Stock V8 Phase 7: formal candidate freeze.

Purpose
-------
Freeze the exact DISTANCE_ONLY candidate that passed the V8 development and
pre-freeze robustness process. This phase records an immutable canonical
specification and SHA-256 fingerprint without scoring or reading the future
2026-09-01+ holdout.

Scientific contract
-------------------
* No new signal search, weight tuning, Top-N tuning, holding-period tuning,
  cost tuning, regime filtering, or portfolio redesign.
* Candidate is exactly DISTANCE_ONLY from V8 Phases 4-6.
* Universe is the existing 100-stock V8 candidate universe; SPY is benchmark
  context only, not an investable candidate.
* Signal is distance_from_low_20d after same-day cross-sectional neutralization
  to volatility_20d and beta_60.
* Selection is fixed Top 10, equal weight, long only, fully invested.
* Decision uses completed-session information only.
* Execution enters at next trading-session open and exits five sessions later
  at the open.
* All five staggered cohort offsets 0..4 are retained; none is selected.
* Primary modeled trading cost remains 10 bps per dollar traded.
* No high-volatility filter is added post hoc.
* 2026-09-01+ holdout remains sealed and unscored.
* No paper-state mutation or brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ml.v8.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

PHASE = 7
PHASE6_MANIFEST = Path("data/model/v8/phase6/manifest.json")
OUTPUT_ROOT = Path("data/model/v8/phase7")
FREEZE_SPEC_PATH = OUTPUT_ROOT / "frozen_candidate_spec.json"
FREEZE_LOCK_PATH = OUTPUT_ROOT / "frozen_candidate.sha256"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


def _canonical_json_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _load_phase6_manifest():
    if not PHASE6_MANIFEST.exists():
        raise FileNotFoundError(f"Missing {PHASE6_MANIFEST}; run V8 Phase 6 first")
    d = json.loads(PHASE6_MANIFEST.read_text())
    required = {
        "score_id": "DISTANCE_ONLY",
        "top_n": 10,
        "holding_sessions": 5,
        "primary_cost_bps_per_dollar_traded": 10,
        "candidate_frozen": False,
        "future_holdout_scored": False,
    }
    mismatches = []
    for key, expected in required.items():
        if d.get(key) != expected:
            mismatches.append(f"{key}={d.get(key)!r} expected {expected!r}")
    if mismatches:
        raise RuntimeError("Phase-6 contract mismatch: " + "; ".join(mismatches))
    return d


def main():
    p6 = _load_phase6_manifest()

    freeze_spec = {
        "research_version": RESEARCH_VERSION,
        "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "candidate_status": "FROZEN",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "holdout_scored_at_freeze": False,
        "universe": {
            "candidate_count": 100,
            "benchmark": "SPY",
            "benchmark_investable": False,
        },
        "signal": {
            "signal_id": "DISTANCE_ONLY",
            "raw_feature": "distance_from_low_20d",
            "neutralization": {
                "type": "same_day_cross_sectional_residualization",
                "controls": ["volatility_20d", "beta_60"],
            },
            "ranking_direction": "higher residual signal ranks higher",
        },
        "portfolio_contract": {
            "selection": "Top 10",
            "top_n": 10,
            "weighting": "equal_weight",
            "long_only": True,
            "fully_invested": True,
            "leverage": False,
            "shorting": False,
        },
        "decision_execution_contract": {
            "decision_information": "completed trading session only",
            "entry": "next trading-session open",
            "holding_sessions": 5,
            "exit": "open five trading sessions after entry",
            "cohort_offsets": [0, 1, 2, 3, 4],
            "cohort_selection": False,
        },
        "cost_contract": {
            "primary_cost_bps_per_dollar_traded": 10,
            "cost_basis": "actual equal-weight transition notional",
            "first_entry_charged": True,
            "forced_final_liquidation": False,
        },
        "explicit_non_rules": {
            "high_volatility_filter": False,
            "market_regime_filter": False,
            "dynamic_top_n": False,
            "dynamic_holding_period": False,
            "dynamic_cost_assumption": False,
            "signal_weight_tuning": False,
        },
        "development_evidence_snapshot": {
            "phase6_full_mean_net_relative_return": p6.get("full_mean_net_relative_return"),
            "phase6_positive_calendar_year_fraction": p6.get("positive_calendar_year_fraction"),
            "phase6_positive_market_regime_fraction": p6.get("positive_market_regime_fraction"),
            "phase6_positive_abs_return_regime_fraction": p6.get("positive_abs_return_regime_fraction"),
            "phase6_leave_one_stock_out_all_positive": p6.get("leave_one_stock_out_all_positive"),
            "phase6_max_period_selection_fraction": p6.get("max_period_selection_fraction"),
        },
    }

    digest = hashlib.sha256(_canonical_json_bytes(freeze_spec)).hexdigest()
    freeze_spec["spec_sha256"] = digest

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    FREEZE_SPEC_PATH.write_text(json.dumps(freeze_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    FREEZE_LOCK_PATH.write_text(digest + "  frozen_candidate_spec.json\n", encoding="utf-8")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "formal_candidate_freeze",
        "objective": "Freeze the exact V8 DISTANCE_ONLY candidate before any future holdout scoring.",
        "candidate_id": freeze_spec["candidate_id"],
        "candidate_frozen": True,
        "spec_sha256": digest,
        "freeze_spec_path": str(FREEZE_SPEC_PATH),
        "freeze_lock_path": str(FREEZE_LOCK_PATH),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "development_research_closed": True,
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "v7_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "signal_search": False,
            "score_weight_tuning": False,
            "top_n_optimization": False,
            "holding_period_tuning": False,
            "cost_tuning": False,
            "regime_filter_tuning": False,
            "candidate_frozen": True,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("STOCK V8 PHASE 7")
    print("=" * 100)
    print("FORMAL CANDIDATE FREEZE")
    print(f"Candidate: {freeze_spec['candidate_id']}")
    print(f"Spec SHA-256: {digest}")
    print(f"Holdout starts: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print("Future holdout scored: False")
    print("Development research closed: True")
    print("No tuning. No holdout score. No paper-state changes. No orders.")

if __name__ == "__main__":
    main()
''', encoding="utf-8")

    print("[APPLY] ml/v8/phase7.py")
    print("Stock V8 Phase 7 formal-freeze patch complete.")
    print("The exact DISTANCE_ONLY specification will be fingerprinted and frozen without scoring the 2026-09-01+ holdout.")


if __name__ == "__main__":
    main()
