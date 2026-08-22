"""V9 automatic-tuning candidate registry.

This module defines a bounded, deterministic development-only search space.
It does not evaluate the V9 future holdout, change frozen V8, promote a
candidate, mutate production state, or place brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path

from ml.v9.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION

OUTPUT_ROOT = Path("data/model/v9/tuning")
REGISTRY_PATH = OUTPUT_ROOT / "candidate_registry.jsonl"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

SCORE_IDS = (
    "downside_vol_ratio_20",
    "volume_trend_5_20",
    "equal_weight_rank_blend",
)
TOP_N_VALUES = (5, 10, 15)
HOLD_SESSION_VALUES = (3, 5, 10)
PRIMARY_COST_BPS = 10
ENTRY_RULE = "next_trading_session_open"
WEIGHTING = "equal_weight"
OBJECTIVE_ID = "risk_adjusted_relative_return_v1"


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _candidate_id(config: dict) -> str:
    digest = hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()
    return f"V9TUNE_{digest[:16].upper()}"


def build_candidate_registry() -> list[dict]:
    """Return the complete immutable candidate grid in stable order."""
    rows = []
    for score_id, top_n, hold_sessions in product(
        SCORE_IDS,
        TOP_N_VALUES,
        HOLD_SESSION_VALUES,
    ):
        config = {
            "research_version": RESEARCH_VERSION,
            "score_id": score_id,
            "top_n": top_n,
            "holding_sessions": hold_sessions,
            "weighting": WEIGHTING,
            "entry": ENTRY_RULE,
            "cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
            "objective_id": OBJECTIVE_ID,
            "development_data_end_exclusive_utc": (
                FUTURE_HOLDOUT_START_UTC.isoformat()
            ),
        }
        rows.append(
            {
                "candidate_id": _candidate_id(config),
                "config": config,
                "status": "REGISTERED_UNEVALUATED",
            }
        )

    rows.sort(key=lambda row: row["candidate_id"])
    ids = [row["candidate_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Candidate hash collision detected")
    return rows


def _registry_text(rows: list[dict]) -> str:
    return "".join(_canonical_json(row) + "\n" for row in rows)


def write_registry(
    rows: list[dict],
    registry_path: Path = REGISTRY_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> dict:
    """Write once, or verify an identical existing registry; never overwrite drift."""
    expected = _registry_text(rows)
    if registry_path.exists() and registry_path.read_text() != expected:
        raise RuntimeError(
            f"Existing tuning registry differs from the declared search space: "
            f"{registry_path}"
        )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temp = registry_path.with_suffix(registry_path.suffix + ".tmp")
    temp.write_text(expected)
    temp.replace(registry_path)

    registry_sha = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    manifest = {
        "research_version": RESEARCH_VERSION,
        "stage": "development_only_automatic_tuning_registry",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "registry_sha256": registry_sha,
        "search_space": {
            "score_ids": list(SCORE_IDS),
            "top_n_values": list(TOP_N_VALUES),
            "holding_session_values": list(HOLD_SESSION_VALUES),
            "cost_bps_per_dollar_traded": PRIMARY_COST_BPS,
            "cost_tuned": False,
        },
        "objective_id": OBJECTIVE_ID,
        "v9_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v9_future_holdout_scored": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "candidate_evaluated": False,
        "candidate_promoted": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    manifest_temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest_temp.replace(manifest_path)
    return manifest


def main():
    rows = build_candidate_registry()
    manifest = write_registry(rows)
    print("STOCK V9 AUTOMATIC TUNING REGISTRY")
    print("=" * 88)
    print(f"Candidates registered: {manifest['candidate_count']}")
    print(f"Registry SHA: {manifest['registry_sha256']}")
    print(
        "Search: "
        f"{len(SCORE_IDS)} signals x {len(TOP_N_VALUES)} Top-N values x "
        f"{len(HOLD_SESSION_VALUES)} holding periods"
    )
    print(f"Primary transaction cost fixed at {PRIMARY_COST_BPS} bps.")
    print(
        "Development-only registry. No evaluation, holdout access, promotion, "
        "production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
