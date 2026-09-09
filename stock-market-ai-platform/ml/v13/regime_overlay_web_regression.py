"""Regression checks for the read-only V13 Model Research status panel."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import webapp.services.v13_regime_overlay_service as v13_service
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
    service_source = (
        ROOT / "webapp/services/v13_regime_overlay_service.py"
    ).read_text(encoding="utf-8")
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
                "automation_status",
                "automation_target_session",
                "automation_source_session",
                "automation_attempted_at_utc",
                "automation_attempt_consumed",
                "automation_retry_permitted",
                "automation_backfill_permitted",
                "automation_evidence_appended",
                "automation_failure_reason",
                "automation_market_data_requests",
                "automation_request_count_status",
                "automation_quote_recovery_policy",
                "automation_quote_recovery_attempted",
                "automation_quote_batch_requests",
                "automation_maximum_market_data_requests",
                "missing_quote_policy",
            )
        ),
        "V13 API exposes signed-context and lease timing metadata",
    )
    require(
        payload["missing_quote_policy"] == "FAIL_SESSION_NO_EVIDENCE_NO_RETRY"
        and payload["automation_backfill_permitted"] is False,
        "V13 API exposes fail-closed automatic collection state",
    )
    require(
        "quote_recovery_automation" in service_source
        and "AUTOMATION_ROOTS" in service_source,
        "V13 API selects the latest legacy or quote-recovery session",
    )
    with TemporaryDirectory(prefix="v13_web_automation_") as raw:
        root = Path(raw)
        legacy = root / "automation"
        recovery = root / "quote_recovery_automation"
        (legacy / "2026-09-08").mkdir(parents=True)
        latest = recovery / "2026-09-09"
        latest.mkdir(parents=True)
        (latest / "collection_attempt.json").write_text(
            json.dumps(
                {
                    "target_session": "2026-09-09",
                    "source_session": "2026-09-08",
                    "attempted_at_utc": "2026-09-09T14:00:05+00:00",
                }
            ),
            encoding="utf-8",
        )
        (latest / "status.json").write_text(
            json.dumps(
                {
                    "status": "COLLECTION_FAILED_NO_EVIDENCE",
                    "target_session": "2026-09-09",
                    "source_session": "2026-09-08",
                    "attempt_consumed": True,
                    "retry_permitted": False,
                    "backfill_permitted": False,
                    "evidence_appended": False,
                    "failure_reason": "V13_BID_INVALID:META",
                    "market_data_requests": 103,
                    "request_count_status": "RECORDED",
                    "quote_recovery_policy": (
                        "ONE_FULL_BATCH_RETRY_THEN_FAIL_CLOSED"
                    ),
                }
            ),
            encoding="utf-8",
        )
        original_roots = v13_service.AUTOMATION_ROOTS
        try:
            v13_service.AUTOMATION_ROOTS = (legacy, recovery)
            latest_automation = v13_service._read_automation_metadata()
        finally:
            v13_service.AUTOMATION_ROOTS = original_roots
        require(
            latest_automation["status"] == "COLLECTION_FAILED_NO_EVIDENCE"
            and latest_automation["target_session"] == "2026-09-09"
            and latest_automation["source_session"] == "2026-09-08"
            and latest_automation["quote_recovery_attempted"] is True
            and latest_automation["quote_batch_requests"] == 2
            and latest_automation["maximum_market_data_requests"] == 104,
            "V13 API reports the newest exhausted quote-recovery attempt",
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
        "LATEST AUTOMATIC COLLECTION · IMMUTABLE SESSION RESULT" in tabs
        and "data-v13-automation-status" in tabs
        and "data-v13-automation-recovery" in tabs
        and "data-v13-automation-failure" in tabs,
        "V13 tab exposes the latest immutable automatic collection result",
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
        "data-v13-automation-status" in renderer
        and "data-v13-automation-source" in renderer
        and "data-v13-automation-consumed" in renderer
        and "data-v13-automation-requests" in renderer
        and "data-v13-automation-recovery" in renderer
        and "data-v13-automation-failure" in renderer,
        "V13 renderer publishes automatic attempt and recovery diagnostics",
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
