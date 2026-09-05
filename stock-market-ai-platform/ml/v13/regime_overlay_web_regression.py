"""Regression checks for the read-only V13 Model Research status panel."""
from __future__ import annotations

from pathlib import Path

from webapp.services.v13_regime_overlay_service import (
    get_v13_regime_overlay_dashboard,
)


ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    payload = get_v13_regime_overlay_dashboard()
    tabs = (ROOT / "webapp/static/js/model_research_tabs.js").read_text(
        encoding="utf-8"
    )
    renderer = (ROOT / "webapp/static/js/v13_regime_overlay_status.js").read_text(
        encoding="utf-8"
    )
    app_source = (ROOT / "webapp/app.py").read_text(encoding="utf-8")

    require(
        payload["classification"]
        == "PREREGISTERED_DEVELOPMENT_CANDIDATE_NOT_FROZEN",
        "V13 candidate is explicitly not frozen",
    )
    require(
        payload["status_scope"] == "CONTROL_HEALTH_SEPARATE_FROM_EVIDENCE",
        "Control readiness remains separate from evidence maturity",
    )
    require(
        payload["contract_sha_verified"] is True,
        "V13 contract identity is verified",
    )
    activated = payload["activation"] == "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
    require(
        activated
        or payload["activation"]
        == "DISABLED_PENDING_FRESH_EVIDENCE_PREFLIGHT",
        "Fresh evidence activation is disabled or validly paper-only",
    )
    require(
        payload["minimum_completed_sessions"] == 60
        and payload["minimum_regime_eligible_sessions"] == 15,
        "Fresh evidence thresholds are exposed exactly",
    )
    require(
        payload["retrospective_reconstruction_read"] is False
        and payload["request_time_historical_data_load"] is False,
        "Endpoint performs no historical reconstruction load",
    )
    require(
        payload["scheduler_installation_expected"] is False
        and payload["collection_expected"] is False
        and payload["market_data_requests"] == 0,
        "Disabled collection state is explicit",
    )
    require(
        (
            activated
            and payload["manual_approval_status"]
            in {"VALID_FOR_SEPARATE_ACTIVATION_STEP", "VALID_FOR_ACTIVE_RENEWAL"}
            and payload["manual_approval_present"] is True
            and payload["manual_approval_valid"] is True
        )
        or (
            not activated
            and payload["manual_approval_status"]
            in {"WAITING_FOR_BOUNDARY", "NOT_PRESENT"}
            and payload["manual_approval_present"] is False
            and payload["manual_approval_valid"] is False
        ),
        "Manual approval state is consistent with effective activation",
    )
    require(
        payload["transition_application_present"] is True
        and (
            (
                activated
                and payload["transition_status"] == "APPLIED_PAPER_ONLY"
                and payload["transition_eligible"] is True
                and payload["transition_applied"] is True
            )
            or (
                not activated
                and payload["transition_status"]
                in {"WAITING_FOR_BOUNDARY", "WAITING_FOR_MANUAL_APPROVAL"}
                and payload["transition_eligible"] is False
                and payload["transition_applied"] is False
            )
        ),
        "Transition state is consistent with effective activation",
    )
    require(
        payload["planned_activation_state"]
        == "ENABLED_FRESH_EVIDENCE_PAPER_ONLY"
        and (
            (
                activated
                and payload["activation_lease_present"] is True
                and payload["activation_lease_valid"] is True
            )
            or (
                not activated
                and payload["activation_lease_present"] is False
                and payload["activation_lease_valid"] is False
            )
        ),
        "Activation lease state is valid and remains paper only",
    )
    require(
        payload["paper_trading_only"] is True
        and payload["live_trading_enabled"] is False
        and payload["brokerage_orders"] is False,
        "V13 web payload has no trading authority",
    )
    require(
        payload["holdout_outcomes_read"] is False
        and all(
            payload[field] is False
            for field in ("v8_modified", "v10_modified", "v11_modified", "v12_modified")
        ),
        "V8 through V12 and holdout outcomes remain isolated",
    )
    require(
        all(
            key in payload
            for key in (
                "context_status",
                "context_target_session",
                "context_source_decision_session",
                "context_ranking_sha256",
                "context_control_context_sha256",
                "activation_lease_expires_at_utc",
                "activation_lease_operator",
                "activation_lease_sequence",
                "next_decision_window_utc",
                "candidate_id",
                "control_id",
                "fresh_evidence_boundary_utc",
            )
        ),
        "V13 API exposes signed-context and lease timing metadata",
    )
    require(
        "v13-regime-overlay-status" in tabs
        and "COMPLETED FRESH PAIRED SESSIONS" in tabs
        and "COMPLETED REGIME-ELIGIBLE SESSIONS" in tabs,
        "V13 tab exposes fresh evidence progress separately",
    )
    require(
        "retrospective development reconstruction" in tabs
        and "Only completed post-boundary paired observations" in tabs,
        "Retrospective and fresh evidence labels cannot be conflated",
    )
    require(
        "ACTIVATION GOVERNANCE · FAIL-CLOSED" in tabs
        and "MANUAL APPROVAL STATUS" in tabs
        and "ACTIVATION LEASE" in tabs
        and "APPLY IMPLEMENTATION" in tabs
        and "read-only panel cannot create approval, write a lease, apply activation" in tabs,
        "V13 tab exposes governance without an activation surface",
    )
    require(
        "Signed context inbox" in tabs
        and "Effective paper lease" in tabs
        and "SIGNED CONTEXT IDENTITIES" in tabs
        and "Next decision window" in tabs,
        "V13 tab exposes current context publication and lease timing",
    )
    require(
        "fetch('/api/v13/regime-overlay'" in renderer
        and "data-v13-failures" in renderer,
        "V13 panel loads only its read-only status endpoint",
    )
    require(
        "+${(returnDelta * 100).toFixed(1)} percentage points"
        in renderer
        and "versus V10 control" in renderer,
        "V13 return gate is expressed as a percentage-point comparison",
    )
    require(
        "textContent" in renderer and "document.createElement('li')" in renderer,
        "V13 diagnostics render as text rather than executable markup",
    )
    require(
        "data-v13-approval" in renderer
        and "data-v13-transition" in renderer
        and "data-v13-lease" in renderer,
        "V13 renderer publishes approval, transition and lease state",
    )
    require(
        "data-v13-context-status" in renderer
        and "data-v13-context-target" in renderer
        and "data-v13-context-source" in renderer
        and "data-v13-lease-expires" in renderer
        and "data-v13-next-window" in renderer
        and "data-v13-candidate" in renderer
        and "data-v13-control-id" in renderer
        and "data-v13-boundary" in renderer,
        "V13 renderer publishes signed-context and lease timing metadata",
    )
    require(
        '@app.get("/api/v13/regime-overlay")' in app_source
        and "no-historical-reconstruction-load" in app_source,
        "V13 lightweight API route is registered",
    )
    require(
        "activation form" not in tabs.lower()
        and "brokerage credential" not in tabs.lower(),
        "V13 panel exposes no activation or credential form",
    )

    print("Status: PASSED")
    print("V13 Model Research panel: VERIFIED READ ONLY")
    print("Historical reconstruction load: DISABLED")
    print(
        "Fresh evidence activation: "
        + ("ENABLED PAPER ONLY" if activated else "DISABLED")
    )
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production evidence modified: NO")


if __name__ == "__main__":
    main()
