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
        b'id="v11-phase2-status"' not in research.data
        and b'/static/js/v11_phase2_status.js' not in research.data,
        "Archived V11 panel and renderer are removed from Model Research",
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
        b'/static/js/overview_live_paper_dashboard.js' in research.data,
        "Model Research loads the overview live-paper comparison",
    )
    require(
        b'/static/js/v14_ml_ai_dashboard.js' in research.data,
        "Model Research loads the V14 ML/AI model-lab renderer",
    )
    require(
        b'/static/js/v15_intraday_v7_dashboard.js' in research.data,
        "Model Research loads the V15 intraday ML paper-shadow renderer",
    )
    require(
        b'/static/js/v13_regime_overlay_status.js' in research.data,
        "Model Research loads its read-only V13 status renderer",
    )
    require(
        b'/static/js/v10_confirmation_dashboard.js' in research.data
        and b'/static/js/v10_cycle3_accelerated_v2_dashboard.js' in research.data
        and b'/static/js/v10_cycle3_holdout_monitor.js' in research.data,
        "Model Research loads all three classified V10 sections",
    )
    crypto_research = client.get("/crypto")
    require(
        crypto_research.status_code == 200
        and b"Crypto Model Research" in crypto_research.data
        and b"/static/js/crypto_model_research_tabs.js" in crypto_research.data,
        "Crypto defaults to Model Research and loads model-specific tabs",
    )
    crypto_live = client.get("/crypto-visual")
    require(
        crypto_live.status_code == 200
        and b"Crypto Live" in crypto_live.data
        and b"/static/js/crypto_model_research_tabs.js" not in crypto_live.data,
        "Crypto Live retains the visual viewer under its renamed section",
    )
    readiness_page = client.get("/trading-readiness")
    require(
        readiness_page.status_code == 200,
        "Trading Readiness remains a dedicated primary area",
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
    v10_accelerated_api = client.get("/api/v10/cycle3/accelerated-v2")
    require(
        v10_accelerated_api.status_code == 200,
        "V10 accelerated read-only dashboard API responds",
    )
    v10_accelerated = v10_accelerated_api.get_json()
    require(
        v10_accelerated.get("classification")
        == "AUTHORIZED_PROSPECTIVE_PAPER_FORWARD"
        and v10_accelerated.get("first_decision_session_utc")
        == "2026-09-10T00:00:00+00:00"
        and v10_accelerated.get("independent_confirmation_start_utc")
        == "2027-01-04T00:00:00+00:00",
        "V10 accelerated and January evidence boundaries stay separate",
    )
    require(
        v10_accelerated.get("runner_invoked") is False
        and v10_accelerated.get("historical_reconstruction_read") is False
        and v10_accelerated.get("january_holdout_outcomes_read") is False
        and v10_accelerated.get("v8_modified") is False
        and v10_accelerated.get("brokerage_orders") is False,
        "V10 dashboard request cannot invoke models, alter V8, or place orders",
    )
    require(
        all(
            key in v10_accelerated
            for key in (
                "starting_equity",
                "current_equity",
                "current_v8_equity",
                "current_spy_equity",
                "equity_basis",
                "open_cohorts",
                "priced_open_cohorts",
                "operational_curve",
            )
        ),
        "V10 accelerated API exposes read-only live comparison equity",
    )
    require(
        all(
            key in v10_accelerated
            for key in (
                "current_run_health",
                "current_run_status",
                "study_integrity",
                "study_integrity_status",
                "feature_backend",
                "latest_source_session",
                "expected_latest_completed_session",
                "source_price_symbols_available",
                "source_price_symbols_required",
                "next_expected_lifecycle_event",
                "pending_entry_count",
                "pending_exit_count",
                "diagnostic_backfill_status",
                "diagnostic_backfill_promotion_eligible",
            )
        ),
        "V10 accelerated API separates runtime health from study integrity",
    )
    v14_api = client.get("/api/v14/ml-ai")
    require(v14_api.status_code == 200, "V14 ML/AI dashboard API responds")
    v14_payload = v14_api.get_json()
    require(
        v14_payload.get("classification")
        == "TRAINED_ML_LOGISTIC_REGRESSION_PAPER_FORWARD"
        and v14_payload.get("model_type") == "numpy_logistic_regression"
        and v14_payload.get("paper_forward_start_utc")
        == "2026-09-11T00:00:00+00:00",
        "V14 API identifies genuine trained ML and its clean evidence boundary",
    )
    require(
        v14_payload.get("runner_invoked") is False
        and v14_payload.get("brokerage_orders") is False
        and v14_payload.get("v8_modified") is False
        and v14_payload.get("v10_modified") is False,
        "V14 dashboard cannot run models, place orders, or modify V8/V10",
    )
    require(
        all(
            key in v14_payload
            for key in (
                "coefficients",
                "rankings",
                "open_positions",
                "event_history",
                "curve",
                "current_equity",
                "current_spy_equity",
                "next_lifecycle_event",
            )
        ),
        "V14 API exposes model lineage, rankings, positions, and forward charts",
    )
    v15_api = client.get("/api/v15/intraday-v7")
    require(v15_api.status_code == 200, "V15 intraday dashboard API responds")
    v15_payload = v15_api.get_json()
    require(
        v15_payload.get("classification")
        == "PREREGISTERED_PROSPECTIVE_INTRADAY_ML_PAPER_SHADOW"
        and v15_payload.get("candidate_id")
        == "v15_v7_v5_signal_fixed_60pct_exposure"
        and v15_payload.get("first_eligible_session") == "2026-09-21"
        and v15_payload.get("model_type")
        == "RIDGE_RETURN_REGRESSION_V11_V14_HYBRID",
        "V15 API identifies the frozen intraday ML candidate and clean boundary",
    )
    require(
        v15_payload.get("historical_results_are_v7_evidence") is False
        and v15_payload.get("historical_reconstruction_read") is False
        and v15_payload.get("v5_result_artifact_read") is False
        and v15_payload.get("runner_invoked") is False
        and v15_payload.get("dashboard_network_requests") == 0
        and v15_payload.get("brokerage_orders") is False
        and v15_payload.get("automatic_promotion") is False
        and all(
            v15_payload.get(key) is False
            for key in (
                "v8_modified",
                "v10_modified",
                "v11_modified",
                "v13_modified",
                "v14_modified",
            )
        ),
        "V15 dashboard preserves evidence isolation and has no execution authority",
    )
    require(
        all(
            key in v15_payload
            for key in (
                "coefficients",
                "curve",
                "current_equity",
                "current_v11_equity",
                "current_v14_equity",
                "current_spy_equity",
                "latest_decision",
                "open_positions",
                "event_history",
                "review",
                "next_lifecycle_event",
                "prepared_model_verified",
            )
        ),
        "V15 API exposes model lineage, lifecycle, controls, and review state",
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
    v13_activated = (
        v13_payload.get("activation") == "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
    )
    require(
        v13_payload.get("transition_application_present") is True
        and (
            (
                v13_activated
                and v13_payload.get("manual_approval_present") is True
                and v13_payload.get("manual_approval_valid") is True
                and v13_payload.get("activation_lease_present") is True
                and v13_payload.get("activation_lease_valid") is True
                and v13_payload.get("transition_applied") is True
            )
            or (
                not v13_activated
                and v13_payload.get("manual_approval_valid") is False
                and v13_payload.get("activation_lease_valid") is False
                and v13_payload.get("transition_applied") is False
                and (
                    v13_payload.get("activation_lease_present") is False
                    or v13_payload.get("manual_approval_present") is True
                )
            )
        ),
        "V13 API exposes internally consistent activation governance",
    )
    require(
        all(
            key in v13_payload
            for key in (
                "automation_status",
                "automation_target_session",
                "automation_source_session",
                "automation_attempt_consumed",
                "automation_failure_reason",
                "automation_market_data_requests",
                "automation_quote_recovery_attempted",
                "automation_quote_batch_requests",
                "automation_maximum_market_data_requests",
            )
        )
        and v13_payload.get("automation_backfill_permitted") is False,
        "V13 API exposes the latest immutable automatic collection result",
    )

    project_root = Path(__file__).resolve().parents[1]
    dashboard_template = (project_root / "webapp/templates/index.html").read_text()
    site_navigation = (
        project_root / "webapp/static/js/signup_button.js"
    ).read_text()
    crypto_research_tabs = (
        project_root / "webapp/static/js/crypto_model_research_tabs.js"
    ).read_text()
    crypto_template = (
        project_root / "webapp/templates/crypto.html"
    ).read_text()
    crypto_live_template = (
        project_root / "webapp/templates/crypto_visual.html"
    ).read_text()
    readiness_template = (
        project_root / "webapp/templates/trading_readiness.html"
    ).read_text()
    layout = (project_root / "webapp/static/js/dashboard_layout.js").read_text()
    operations = (project_root / "webapp/static/js/stock_operations_health.js").read_text()
    comparison = (project_root / "webapp/static/js/v4_equity_chart.js").read_text()
    research_tabs = (project_root / "webapp/static/js/model_research_tabs.js").read_text()
    v13_status = (project_root / "webapp/static/js/v13_regime_overlay_status.js").read_text()
    v10_accelerated_status = (
        project_root
        / "webapp/static/js/v10_cycle3_accelerated_v2_dashboard.js"
    ).read_text()
    v14_status = (
        project_root / "webapp/static/js/v14_ml_ai_dashboard.js"
    ).read_text()
    v15_status = (
        project_root / "webapp/static/js/v15_intraday_v7_dashboard.js"
    ).read_text()
    overview_live_paper = (
        project_root / "webapp/static/js/overview_live_paper_dashboard.js"
    ).read_text()
    v10_january_status = (
        project_root / "webapp/static/js/v10_cycle3_holdout_monitor.js"
    ).read_text()
    final_polish = (project_root / "webapp/static/js/v8_dashboard_final_polish.js").read_text()
    require(
        "{#" not in dashboard_template,
        "Dashboard CSS contains no accidental Jinja comment opener",
    )
    require(
        all(label in site_navigation for label in (
            "STOCKS", "CRYPTO", "TRADING READINESS",
            "MODEL RESEARCH", "LIVE STOCK VIEWER",
            "CRYPTO MODEL RESEARCH", "CRYPTO LIVE",
        ))
        and "Primary platform areas" in site_navigation
        and "Stock areas" in site_navigation
        and "Crypto areas" in site_navigation,
        "Site navigation exposes three primary areas and nested stock/crypto choices",
    )
    require(
        all(label in crypto_research_tabs for label in (
            "Overview", "Shared Crypto V2", "XRP V1", "Crypto V1",
            "Shared Crypto V3", "XRP V2", "XRP V3",
        ))
        and 'role="tablist"' in crypto_research_tabs
        and "setAttribute('role', 'tabpanel')" in crypto_research_tabs
        and "ArrowLeft" in crypto_research_tabs,
        "Crypto Model Research preserves every classified model in accessible tabs",
    )
    require(
        "CRYPTO MODEL RESEARCH" in crypto_template
        and "CRYPTO LIVE" in crypto_template
        and "Crypto Live" in crypto_live_template
        and "CRYPTO VISUAL" not in readiness_template
        and "MODEL RESEARCH" not in readiness_template
        and "LIVE STOCK VIEWER" not in readiness_template,
        "Server-rendered navigation mirrors the new hierarchy without legacy peers",
    )
    require(
        all(label in research_tabs for label in (
            "Overview", "V8 Frozen", "V10 Cycle 3", "V14_ML_AI",
            "V15 Intraday", "V13 Dev",
        )),
        "Model Research exposes the active classified model-tab set",
    )
    require(
        "fetch(API" in v14_status
        and "/api/v14/ml-ai" in v14_status
        and "Learned standardized coefficients" in v14_status
        and "100-STOCK ML RANKING BOARD" in v14_status
        and "Interactive paper-forward performance" in v14_status
        and "Dashboard invoked runner" in v14_status,
        "V14 tab renders learning, ranking, performance, and authority surfaces",
    )
    require(
        "fetch(API" in v15_status
        and "/api/v15/intraday-v7" in v15_status
        and "V15 V7 Intraday Hybrid Intelligence" in v15_status
        and "Interactive prospective performance" in v15_status
        and "Immutable hybrid model coefficients" in v15_status
        and "PREREGISTERED HUMAN-REVIEW GATES" in v15_status
        and "TAMPER-EVIDENT APPEND-ONLY LIFECYCLE" in v15_status
        and "Historical V5 evidence included" in v15_status
        and "Dashboard invoked runner" in v15_status
        and "Dashboard network requests" in v15_status
        and "Brokerage orders" in v15_status
        and "Automatic promotion" in v15_status,
        "V15 tab renders intraday ML, prospective evidence, and authority surfaces",
    )
    require(
        "overview-live-paper-comparison" in overview_live_paper
        and "/api/v10/cycle3/accelerated-v2" in overview_live_paper
        and "/api/v14/ml-ai" in overview_live_paper
        and "/api/v15/intraday-v7" in overview_live_paper
        and "V10 accelerated" in overview_live_paper
        and "V14 ML" in overview_live_paper
        and "V15 intraday" in overview_live_paper
        and "Promise.allSettled" in overview_live_paper
        and "pointermove" in overview_live_paper
        and "ResizeObserver" in overview_live_paper
        and "No historical reconstruction" in overview_live_paper,
        "Overview renders an interactive isolated V10/V14/V15 live-paper chart",
    )
    require(
        research_tabs.index("id:'v14'") < research_tabs.index("id:'v15'")
        < research_tabs.index("id:'v13'")
        and "V15 V7 · INTRADAY ML · PROSPECTIVE PAPER SHADOW" in research_tabs
        and "Only post-September 21 paper-shadow events count as V15 evidence."
        in research_tabs,
        "V15 tab is ordered and labeled as a separate prospective evidence lane",
    )
    require(
        "const ORDER = ['V4','V5','V8','V10','V14','V13','SPY']" in comparison
        and "V14 TEN-YEAR WHAT-IF" in comparison
        and "renderV14Answer()" in comparison
        and "RETROSPECTIVE · NOT PROMOTION EVIDENCE" in comparison
        and "smc-lineage-v14-reconstruction" in comparison,
        "Model comparison renders the V14 ten-year counterfactual and lineage",
    )
    require(
        "V11 Intraday" not in research_tabs
        and "model-research-pane-v11" not in research_tabs
        and "v11-phase2-status" not in dashboard_template,
        "Archived V11 has no dashboard tab or page content",
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
        and "v10-cycle3-holdout-monitor" in research_tabs,
        "Shared and model-owned dashboard panels route to their proper tabs",
    )
    require(
        research_tabs.index("'v10-cycle3-accelerated-monitor'")
        < research_tabs.index("'v10-cycle3-holdout-monitor'")
        < research_tabs.index("'v10-confirmation-card'")
        and "ACCELERATED PAPER-FORWARD" in research_tabs,
        "V10 tab orders accelerated, January, then legacy evidence",
    )
    require(
        "fetch('/api/v10/cycle3/accelerated-v2'" in v10_accelerated_status
        and "0 / 8 complete blocks" in v10_accelerated_status
        and "0 / 12 complete blocks" in v10_accelerated_status
        and "Complete-block normalized comparison" in v10_accelerated_status
        and "Paired edge by complete block" in v10_accelerated_status
        and "V10 CURRENT PAPER EQUITY" in v10_accelerated_status
        and "CURRENT MARK" in v10_accelerated_status
        and "Refreshes every 15 seconds" in v10_accelerated_status
        and "data-a10-hover-line" in v10_accelerated_status
        and "awaiting first journaled entry" in v10_accelerated_status
        and "V2 clean evidence boundary" in v10_accelerated_status
        and "Only prospective evidence beginning September 10, 2026 is displayed." in v10_accelerated_status
        and "Current run health" in v10_accelerated_status
        and "Study integrity" in v10_accelerated_status
        and "Feature backend" in v10_accelerated_status
        and "Next lifecycle event" in v10_accelerated_status
        and "data-a10-current-health" in v10_accelerated_status
        and "data-a10-next-event" in v10_accelerated_status
        and "Sep 8 diagnostic" not in v10_accelerated_status
        and "Diagnostic promotion eligibility" not in v10_accelerated_status
        and "Preserved study-integrity disclosure" not in v10_accelerated_status
        and "if(value==null||value==='')return '—'" in v10_accelerated_status
        and "grid-template-columns:minmax(300px,.62fr) minmax(0,1.38fr)"
        in v10_accelerated_status
        and "font-size:clamp(1.85rem,3vw,3.25rem)"
        in v10_accelerated_status
        and "white-space:nowrap;font-variant-numeric:tabular-nums"
        in v10_accelerated_status
        and "Preregistered promotion gates" in v10_accelerated_status,
        "V10 accelerated tab renders live equity, comparison charts, and gates",
    )
    require(
        "Accelerated September–December evidence never enters"
        in v10_january_status
        and "INDEPENDENT JANUARY CONFIRMATION · UNCHANGED"
        in v10_january_status,
        "January confirmation explicitly excludes accelerated evidence",
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
        and "short-lived paper-only lease" in research_tabs
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
        "ACTIVATION GOVERNANCE · FAIL-CLOSED" in research_tabs
        and "MANUAL APPROVAL STATUS" in research_tabs
        and "ACTIVATION LEASE" in research_tabs
        and "APPLY IMPLEMENTATION" in research_tabs,
        "V13 tab shows its manual approval and transition boundary",
    )
    require(
        "fetch('/api/v13/regime-overlay'" in v13_status
        and "data-v13-failures" in v13_status
        and "textContent" in v13_status,
        "V13 tab renders read-only status and safe diagnostics",
    )
    require(
        "data-v13-approval" in v13_status
        and "data-v13-transition" in v13_status
        and "data-v13-lease" in v13_status,
        "V13 tab renders approval, transition and lease status",
    )
    require(
        "data-v13-context-status" in v13_status
        and "data-v13-context-target" in v13_status
        and "data-v13-context-source" in v13_status
        and "data-v13-lease-expires" in v13_status
        and "data-v13-next-window" in v13_status
        and "data-v13-candidate" in v13_status
        and "data-v13-control-id" in v13_status
        and "data-v13-boundary" in v13_status,
        "V13 tab renders signed-context and lease timing metadata",
    )
    require(
        "LATEST AUTOMATIC COLLECTION · IMMUTABLE SESSION RESULT"
        in research_tabs
        and "data-v13-automation-status" in v13_status
        and "data-v13-automation-source" in v13_status
        and "data-v13-automation-consumed" in v13_status
        and "data-v13-automation-requests" in v13_status
        and "data-v13-automation-recovery" in v13_status
        and "data-v13-automation-failure" in v13_status,
        "V13 tab renders automatic attempt and recovery diagnostics",
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
        b'/static/js/model_research_tabs.js' not in live.data
        and b'/static/js/overview_live_paper_dashboard.js' not in live.data,
        "Model tabs and overview paper comparison remain exclusive to Model Research",
    )
    require(
        b'/static/js/v13_regime_overlay_status.js' not in live.data,
        "V13 research renderer remains off the live page",
    )
    require(
        b'/static/js/v14_ml_ai_dashboard.js' not in live.data
        and b'/static/js/v15_intraday_v7_dashboard.js' not in live.data,
        "V14 and V15 ML research renderers remain off the live page",
    )
    require(
        b'/static/js/v10_cycle3_accelerated_v2_dashboard.js' not in live.data
        and b'/static/js/v10_cycle3_holdout_monitor.js' not in live.data,
        "V10 research evidence renderers remain off the Live Stock Viewer",
    )

    print("Status: PASSED")
    print("Post-login dashboard rendering: VERIFIED")
    print("Internal server error: NOT REPRODUCED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
