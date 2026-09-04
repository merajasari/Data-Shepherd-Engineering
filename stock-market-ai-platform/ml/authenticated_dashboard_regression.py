"""Authenticated dashboard smoke regression for post-login rendering."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

os.environ.setdefault(
    "FLASK_SECRET_KEY",
    "authenticated-dashboard-regression",
)

from webapp.app import app


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def authenticated_client():
    client = app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "dashboard-regression"
        session["legacy_member"] = True
        session["last_activity_utc"] = datetime.now(
            timezone.utc
        ).isoformat()
    return client


def main() -> None:
    app.config.update(
        TESTING=True,
        SESSION_COOKIE_SECURE=False,
        PROPAGATE_EXCEPTIONS=True,
    )
    client = authenticated_client()
    research = client.get("/dashboard")
    require(
        research.status_code == 200,
        "Authenticated Model Research dashboard renders",
    )
    require(
        b'id="v11-phase2-status"' in research.data,
        "V11 Phase 2 panel survives authenticated rendering",
    )
    require(
        b'/static/js/v8_holdout_snapshot.js' in research.data,
        "Synchronized V8 snapshot reader is loaded before dashboard panels",
    )
    require(
        b'/static/js/model_research_tabs.js' in research.data,
        "Model Research loads its page-specific model tabs",
    )
    require(
        b'/static/js/v13_regime_overlay_status.js' in research.data,
        "Model Research loads its read-only V13 status renderer",
    )
    v8_api = client.get("/api/v8/holdout")
    require(v8_api.status_code == 200, "V8 synchronized dashboard API responds")
    require(
        len(v8_api.get_json().get("latest_research_rankings") or []) == 100,
        "V8 API exposes the complete lightweight 100-stock ranking snapshot",
    )
    require(
        all(
            isinstance(event.get("symbols"), list)
            for event in (v8_api.get_json().get("event_history") or [])
        ),
        "V8 lifecycle events expose their official symbol baskets for hover details",
    )
    v13_api = client.get("/api/v13/regime-overlay")
    require(v13_api.status_code == 200, "V13 read-only dashboard API responds")
    v13_payload = v13_api.get_json()
    require(
        v13_payload.get("classification")
        == "PREREGISTERED_DEVELOPMENT_CANDIDATE_NOT_FROZEN"
        and v13_payload.get("candidate_frozen") is False,
        "V13 API cannot be mistaken for a frozen model",
    )
    require(
        v13_payload.get("minimum_completed_sessions") == 60
        and v13_payload.get("minimum_regime_eligible_sessions") == 15
        and v13_payload.get("retrospective_reconstruction_read") is False,
        "V13 API separates retrospective reconstruction from fresh thresholds",
    )

    project_root = Path(__file__).resolve().parents[1]
    dashboard_template = (project_root / "webapp/templates/index.html").read_text()
    layout = (project_root / "webapp/static/js/dashboard_layout.js").read_text()
    operations = (project_root / "webapp/static/js/stock_operations_health.js").read_text()
    comparison = (project_root / "webapp/static/js/v4_equity_chart.js").read_text()
    research_tabs = (project_root / "webapp/static/js/model_research_tabs.js").read_text()
    v11_status = (project_root / "webapp/static/js/v11_phase2_status.js").read_text()
    v13_status = (project_root / "webapp/static/js/v13_regime_overlay_status.js").read_text()
    final_polish = (project_root / "webapp/static/js/v8_dashboard_final_polish.js").read_text()
    require(
        "{#" not in dashboard_template,
        "Dashboard CSS contains no accidental Jinja comment opener",
    )
    require(
        all(label in research_tabs for label in (
            "Overview", "V8 Frozen", "V10 Cycle 3", "V11 Intraday",
            "V13 Dev",
        )),
        "Model Research exposes the complete classified model-tab set",
    )
    require(
        "label:'V4 Paper'" not in research_tabs
        and "model-research-pane-v4" not in research_tabs
        and "v4-dashboard'), 'v8'" in research_tabs,
        "Standalone V4 tab is removed and its enhanced V8 shell routes to V8",
    )
    require(
        "stock-stream-health-card', 'overview'" in research_tabs
        and "smc-full-width-card" in research_tabs
        and "v4-dashboard'), 'v8'" in research_tabs
        and "v8-holdout-monitor" in research_tabs
        and "v10-cycle3-holdout-monitor" in research_tabs
        and "v11-phase2-status', 'v11'" in research_tabs,
        "Shared and model-owned dashboard panels route to their proper tabs",
    )
    require(
        "(?:DISTANCE-ONLY|COMPLETED-EOD) RANK SIGNAL" in research_tabs
        and "moveV8ContractGrid" in research_tabs
        and "FROZEN V8 STRATEGY CONTRACT" in research_tabs
        and "(?:V8 )?PORTFOLIO CONTRACT" in research_tabs,
        "Completed-EOD rank signal and both V8 contracts route to V8",
    )
    require(
        'role="tablist"' in research_tabs
        and "setAttribute('role', 'tabpanel')" in research_tabs
        and "aria-selected" in research_tabs
        and "ArrowLeft" in research_tabs,
        "Model tabs support accessible keyboard navigation",
    )
    require(
        "PREREGISTERED DEVELOPMENT · NOT FROZEN" in research_tabs
        and "activation disabled" in research_tabs
        and "V5" not in "".join(
            line for line in research_tabs.splitlines()
            if "label:" in line
        ),
        "V13 and legacy V5 are not mislabeled as active forward models",
    )
    require(
        "v13-regime-overlay-status" in research_tabs
        and "COMPLETED FRESH PAIRED SESSIONS" in research_tabs
        and "COMPLETED REGIME-ELIGIBLE SESSIONS" in research_tabs
        and "Only completed post-boundary paired observations" in research_tabs,
        "V13 tab separates retrospective development from fresh evidence",
    )
    require(
        "fetch('/api/v13/regime-overlay'" in v13_status
        and "data-v13-failures" in v13_status
        and "textContent" in v13_status,
        "V13 tab renders read-only status and safe diagnostics",
    )
    require(
        "+${(returnDelta * 100).toFixed(1)} percentage points" in v13_status
        and "versus V10 control" in v13_status,
        "V13 return gate uses percentage points versus its control",
    )
    require(
        "Multi-model research, forward evidence, and operational monitoring"
        in dashboard_template
        and "Multi-model research, forward evidence, and operational monitoring"
        in final_polish,
        "Model Research header describes the complete multi-model platform",
    )
    require(
        "V11 · PREREGISTERED RESEARCH · NOT FROZEN" in research_tabs
        and "no production or brokerage authority" in research_tabs,
        "V11 is explicitly distinguished from frozen production models",
    )
    require(
        "renderAttempt(lastAttempt)" in v11_status
        and "attempt.symbol_count" in v11_status
        and "attempt.reasons" in v11_status,
        "V11 tab renders last collection coverage and rejection diagnostics",
    )
    require(
        "LATEST COMPLETED-EOD RESEARCH SNAPSHOT" in layout
        and "PRODUCTION RANKING SESSION" in layout
        and "OFFICIAL FORWARD EVIDENCE" in layout,
        "V8 research, production ranking, and evidence labels are separated",
    )
    require(
        "Latest Price" in layout and "Completed-EOD Change" in layout,
        "Live prices are labeled separately from completed-EOD fields",
    )
    require(
        "hydrateSelectedV8Signal" in layout
        and "V8 COMPLETED-EOD RANK SIGNAL" in layout,
        "Selected-stock V8 signal is repaired from the synchronized ranking snapshot",
    )
    require(
        "fmtSession" in operations
        and "first holdout market session" in operations,
        "Market-session dates cannot shift to the prior local calendar day",
    )
    require(
        "Y-axis = model lifecycle stage" in comparison
        and "this is not a money or return axis" in comparison
        and "DECISION · Top 10 selected" in comparison
        and "ENTRY · Next open" in comparison
        and "EXIT · 5 sessions complete" in comparison,
        "V8 holdout Y-axis is an explicit categorical lifecycle stage",
    )
    require(
        "data-holdout-event" in comparison
        and "data-holdout-action" in comparison
        and "holdoutPinned" in comparison
        and "smc-holdout-tooltip" in comparison,
        "V8 holdout chart supports filters, hover, pinning, zoom and navigation",
    )

    client = authenticated_client()
    live = client.get("/dashboard?view=live")
    require(
        live.status_code == 200,
        "Authenticated Live Stock Viewer renders",
    )
    require(
        b'id="v11-phase2-status"' not in live.data,
        "V11 research panel remains off the live page",
    )
    require(
        b'/static/js/model_research_tabs.js' not in live.data,
        "Model-specific tabs remain exclusive to Model Research",
    )
    require(
        b'/static/js/v13_regime_overlay_status.js' not in live.data,
        "V13 research renderer remains off the live page",
    )

    print("Status: PASSED")
    print("Post-login dashboard rendering: VERIFIED")
    print("Internal server error: NOT REPRODUCED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
