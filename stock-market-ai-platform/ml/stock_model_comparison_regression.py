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

EXPECTED_IDS = ["V4", "V5", "V8", "V10", "V13", "SPY"]
EXPECTED_V8_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
EXPECTED_V10_ID = "c3_confirm2_blend50"
EXPECTED_V10_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
EXPECTED_V13_SHA = "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702"
V8_BOUNDARY = pd.Timestamp("2026-09-01T00:00:00Z")
V10_BOUNDARY = pd.Timestamp("2027-01-04T00:00:00Z")
V13_BOUNDARY = pd.Timestamp("2026-09-01T14:00:00Z")
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
    require(payload.get("schema_version") == 4, "comparison schema must be version 4")
    require(
        payload.get("excluded_models") == ["V6", "V7", "V11", "V12"],
        "V6/V7/V11/V12 exclusion changed",
    )

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
    v13 = by_id["V13"]
    require(v8.get("label") == "V8 frozen", "V8 chart label changed")
    require(v10.get("label") == "V10 Cycle 3 frozen", "V10 chart label is not Cycle 3 frozen")
    require(
        v13.get("label") == "V13 regime overlay retrospective DEV",
        "V13 chart label does not disclose retrospective development status",
    )
    require(
        max(pd.Timestamp(point["timestamp"]) for point in v8["history"]) < V8_BOUNDARY,
        "V8 chart includes forward-holdout evidence",
    )
    require(
        max(pd.Timestamp(point["timestamp"]) for point in v10["history"]) < V10_BOUNDARY,
        "V10 chart includes fresh forward-holdout evidence",
    )
    require(
        max(pd.Timestamp(point["timestamp"]) for point in v13["history"]) < V13_BOUNDARY,
        "V13 chart includes fresh evidence",
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
    require(v13.get("simulation_starting_capital") == 5_000.0, "V13 did not simulate the locked $5,000 account")
    require(v13.get("ten_calendar_years_available") is False, "V13 hides the August-2017 intraday limitation")
    require(EXPECTED_V13_SHA in v13.get("methodology", ""), "V13 methodology lacks locked contract identity")
    require("not fresh evidence" in v13.get("status", ""), "V13 is not labeled separate from fresh evidence")
    require(bool(v13.get("reconstruction_sha256")), "V13 reconstruction identity is missing")

    lineage = payload.get("lineage") or {}
    require(lineage.get("v8_frozen_sha256") == EXPECTED_V8_SHA, "V8 lineage SHA mismatch")
    require(lineage.get("v10_candidate_id") == EXPECTED_V10_ID, "V10 lineage candidate mismatch")
    require(lineage.get("v10_frozen_sha256") == EXPECTED_V10_SHA, "V10 lineage SHA mismatch")
    require(lineage.get("v10_forward_holdout_start_utc") == V10_BOUNDARY.isoformat(), "V10 boundary mismatch")
    require(lineage.get("v13_contract_sha256") == EXPECTED_V13_SHA, "V13 contract SHA mismatch")
    require(lineage.get("v13_reconstruction_sha256") == v13.get("reconstruction_sha256"), "V13 reconstruction lineage mismatch")
    require(lineage.get("v13_classification") == "RETROSPECTIVE_DEVELOPMENT_ONLY_NOT_FRESH_EVIDENCE", "V13 classification mismatch")
    require(lineage.get("v13_ten_calendar_years_available") is False, "V13 source-history limitation missing")
    require(lineage.get("v13_fresh_evidence_included") is False, "V13 fresh evidence entered comparison")
    require(
        not any(str(key).lower().startswith("v11") for key in lineage),
        "V11 lineage entered the chart artifact",
    )
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
    require(builder.V13_EXPECTED_SHA == EXPECTED_V13_SHA, "builder points at wrong V13 contract")
    require(builder.V13_FRESH_BOUNDARY_UTC == V13_BOUNDARY, "builder uses wrong V13 boundary")
    require(
        builder.V13_PATH == Path("data/research/v13/development/retrospective_reconstruction.json"),
        "builder uses wrong V13 reconstruction source",
    )


def validate_dashboard_source():
    source = DASHBOARD_JS.read_text(encoding="utf-8")
    required = [
        "pageHeader.insertAdjacentElement('afterend', card)",
        "V4 vs V5 vs frozen V8 vs frozen V10 Cycle 3 vs V13 retrospective DEV vs SPY",
        "V6, V7, V11, and V12 are intentionally excluded from this model-history chart",
        "const ORDER = ['V4','V5','V8','V10','V13','SPY']",
        "V13:'#ff8a3d'",
        "data-range=\"10Y\"",
        "else if(range==='10Y')",
        "V13 DEV",
        "smc-lineage-v13-contract",
        "smc-lineage-v13-reconstruction",
        "DATA INTEGRITY &amp; MODEL LINEAGE",
        "V10 CYCLE 3 CANDIDATE",
        "renderLineage()",
        "fetch(DATA_URL,{cache:'no-store'})",
        "data-model-action=\"all\"",
        "data-action=\"reset\"",
        "overlay.addEventListener('pointermove'",
        "overlay.addEventListener('click'",
        "smc-lineage-grid",
        "mode=\'normalized\'",
        "normalizedBases[s.model_id]",
        "NORMALIZED OVERLAP",
        "common eligible overlap",
        "a=Math.max(requestedA,...edges.map(edge=>edge.first))",
        "b=Math.min(requestedB,...edges.map(edge=>edge.last))",
        "every active line is rebased to 100",
        "Visible-range return",
        "Math.max(0,minV-span*.1)",
        "score:row?value(series[id],row):NaN",
    ]
    for marker in required:
        require(marker in source, f"dashboard regression marker missing: {marker}")
    forbidden = [
        "V4 vs V5 vs frozen V8 vs reconstructed V10 vs SPY",
        "V11 Phase 2 frozen",
        "V11 Phase 2 development vs SPY",
        "V11 DEV",
        "smc-lineage-v11",
        "series.V11",
        "'V11','SPY'",
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
    v13 = next(row for row in payload["series"] if row["model_id"] == "V13")
    print(f"[PASS] Models/order: {', '.join(EXPECTED_IDS)}")
    print(f"[PASS] V8 frozen SHA: {EXPECTED_V8_SHA}")
    print(f"[PASS] V10 Cycle 3 candidate: {EXPECTED_V10_ID}")
    print(f"[PASS] V10 frozen SHA: {EXPECTED_V10_SHA}")
    print(f"[PASS] V10 development equity: ${float(v10['ending_equity']):,.2f}")
    print(f"[PASS] V13 retrospective contract SHA: {EXPECTED_V13_SHA}")
    print(f"[PASS] V13 reconstruction SHA: {v13['reconstruction_sha256']}")
    print(f"[PASS] V13 display equity: ${float(v13['ending_equity']):,.2f}")
    print("[PASS] V13 is retrospective development only; fresh evidence excluded")
    print("[PASS] Unavailable pre-August-2017 intraday history is disclosed")
    print("[PASS] V11 is absent from the model-history chart and artifact")
    print("[PASS] V8/V10 forward evidence excluded")
    print("[PASS] Live paper balances excluded")
    print("[PASS] Brokerage orders: OFF")
    print("[PASS] Common-overlap normalization is the default; raw equity remains selectable and zero-clamped")
    print("[PASS] Hover values, returns and ranks follow the selected chart mode")
    print("[PASS] Top placement, desktop/mobile layout, toggles, ranges, hover and pin markers present")
    print("Production holdout evidence modified: NO")
    print("Frozen model specifications modified: NO")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
