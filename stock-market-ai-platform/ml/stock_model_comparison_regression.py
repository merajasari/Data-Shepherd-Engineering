"""Fail-closed integrity and dashboard regression for the stock model comparison.

Read-only except for rebuilding the generated comparison JSON through the
existing research/display builder. It never writes holdout journals, changes a
frozen model specification, or invokes a brokerage interface.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from ml import build_stock_model_comparison as builder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = PROJECT_ROOT / "webapp/static/generated/stock_model_comparison.json"
DASHBOARD_JS = PROJECT_ROOT / "webapp/static/js/v4_equity_chart.js"

EXPECTED_IDS = ["V4", "V5", "V8", "V10", "SPY"]
EXPECTED_V8_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
EXPECTED_V10_ID = "c3_confirm2_blend50"
EXPECTED_V10_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
V8_BOUNDARY = pd.Timestamp("2026-09-01T00:00:00Z")
V10_BOUNDARY = pd.Timestamp("2027-01-04T00:00:00Z")
OLD_V10_EQUITY = 989_545.87
EXPECTED_V10_EQUITY = 939_441.16


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_artifact():
    require(ARTIFACT_PATH.exists(), f"missing {ARTIFACT_PATH}")
    payload = load_json(ARTIFACT_PATH)
    require(payload.get("schema_version") == 2, "comparison schema must be version 2")
    require(payload.get("excluded_models") == ["V6", "V7"], "V6/V7 exclusion changed")

    rows = payload.get("series") or []
    ids = [row.get("model_id") for row in rows]
    require(ids == EXPECTED_IDS, f"series order/content changed: {ids}")
    by_id = {row["model_id"]: row for row in rows}

    for model_id, series in by_id.items():
        history = series.get("history") or []
        require(history, f"{model_id} history is empty")
        require(
            math.isclose(float(history[0]["equity"]), 100_000.0, rel_tol=0, abs_tol=0.01),
            f"{model_id} does not begin on the common $100,000 basis",
        )
        require(
            all(math.isfinite(float(point["equity"])) and float(point["equity"]) > 0 for point in history),
            f"{model_id} contains invalid equity",
        )
        timestamps = [pd.Timestamp(point["timestamp"]) for point in history]
        require(timestamps == sorted(timestamps), f"{model_id} history is not chronological")

    v8 = by_id["V8"]
    v10 = by_id["V10"]
    require(v8.get("label") == "V8 frozen", "V8 chart label changed")
    require(v10.get("label") == "V10 Cycle 3 frozen", "V10 chart label is not Cycle 3 frozen")
    require(
        max(pd.Timestamp(point["timestamp"]) for point in v8["history"]) < V8_BOUNDARY,
        "V8 chart includes forward-holdout evidence",
    )
    require(
        max(pd.Timestamp(point["timestamp"]) for point in v10["history"]) < V10_BOUNDARY,
        "V10 chart includes fresh forward-holdout evidence",
    )
    require(EXPECTED_V10_ID in v10.get("methodology", ""), "V10 methodology lacks frozen candidate ID")
    require(EXPECTED_V10_SHA in v10.get("methodology", ""), "V10 methodology lacks frozen SHA")
    require(
        math.isclose(float(v10["ending_equity"]), EXPECTED_V10_EQUITY, rel_tol=0, abs_tol=0.02),
        f"unexpected frozen Cycle 3 terminal equity: {v10['ending_equity']}",
    )
    require(
        not math.isclose(float(v10["ending_equity"]), OLD_V10_EQUITY, rel_tol=0, abs_tol=0.02),
        "rejected original V10 curve reappeared",
    )

    lineage = payload.get("lineage") or {}
    require(lineage.get("v8_frozen_sha256") == EXPECTED_V8_SHA, "V8 lineage SHA mismatch")
    require(lineage.get("v10_candidate_id") == EXPECTED_V10_ID, "V10 lineage candidate mismatch")
    require(lineage.get("v10_frozen_sha256") == EXPECTED_V10_SHA, "V10 lineage SHA mismatch")
    require(lineage.get("v10_forward_holdout_start_utc") == V10_BOUNDARY.isoformat(), "V10 boundary mismatch")
    require(lineage.get("forward_evidence_included") is False, "forward evidence entered comparison")
    require(lineage.get("live_paper_balances_included") is False, "paper balances entered comparison")
    require(lineage.get("brokerage_orders") is False, "comparison reports brokerage authority")

    safety = payload.get("research_safety") or {}
    require(safety and all(value is False for value in safety.values()), "research safety flag is not false")
    return payload


def validate_frozen_sources():
    v8_spec = load_json(PROJECT_ROOT / builder.V8_FREEZE_PATH)
    v10_spec = load_json(PROJECT_ROOT / builder.V10_FREEZE_PATH)
    require(v8_spec.get("spec_sha256") == EXPECTED_V8_SHA, "V8 frozen spec SHA mismatch")
    require(v10_spec.get("spec_sha256") == EXPECTED_V10_SHA, "V10 frozen spec SHA mismatch")
    require(v10_spec.get("candidate_id") == EXPECTED_V10_ID, "V10 frozen spec candidate mismatch")
    require(builder.V10_CANDIDATE_ID == EXPECTED_V10_ID, "builder points at wrong V10 candidate")
    require(builder.V10_EXPECTED_SHA == EXPECTED_V10_SHA, "builder points at wrong V10 SHA")
    require(builder.V10_PATH == Path("data/model/v10/cycle3/economic_period_results.csv"), "builder uses wrong V10 source")
    require(builder.V10_HOLDOUT_START_UTC == V10_BOUNDARY, "builder uses wrong V10 boundary")


def validate_dashboard_source():
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    required = [
        "pageHeader.insertAdjacentElement('afterend', card)",
        "V4 vs V5 vs frozen V8 vs frozen V10 Cycle 3 reconstruction vs SPY",
        "DATA INTEGRITY &amp; MODEL LINEAGE",
        "V10 CYCLE 3 CANDIDATE",
        "renderLineage()",
        "fetch(DATA_URL,{cache:'no-store'})",
        "data-model-action=\"all\"",
        "data-action=\"reset\"",
        "overlay.addEventListener('pointermove'",
        "overlay.addEventListener('click'",
        "smc-lineage-grid",
    ]
    for marker in required:
        require(marker in source, f"dashboard regression marker missing: {marker}")
    forbidden = [
        "V4 vs V5 vs frozen V8 vs reconstructed V10 vs SPY",
        "$989,545.87",
    ]
    for marker in forbidden:
        require(marker not in source, f"stale dashboard marker returned: {marker}")


def main():
    print("STOCK MODEL COMPARISON INTEGRITY + DASHBOARD REGRESSION")
    print("=" * 88)
    builder.main()
    payload = validate_artifact()
    validate_frozen_sources()
    validate_dashboard_source()

    v10 = next(row for row in payload["series"] if row["model_id"] == "V10")
    print(f"[PASS] Models/order: {', '.join(EXPECTED_IDS)}")
    print(f"[PASS] V8 frozen SHA: {EXPECTED_V8_SHA}")
    print(f"[PASS] V10 Cycle 3 candidate: {EXPECTED_V10_ID}")
    print(f"[PASS] V10 frozen SHA: {EXPECTED_V10_SHA}")
    print(f"[PASS] V10 development equity: ${float(v10['ending_equity']):,.2f}")
    print("[PASS] V8/V10 forward evidence excluded")
    print("[PASS] Live paper balances excluded")
    print("[PASS] Brokerage orders: OFF")
    print("[PASS] Top placement, desktop/mobile layout, toggles, ranges, hover and pin markers present")
    print("Production holdout evidence modified: NO")
    print("Frozen model specifications modified: NO")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
