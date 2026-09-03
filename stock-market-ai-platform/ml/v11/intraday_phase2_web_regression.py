"""Read-only web regression for the V11 Phase 2 status panel."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("FLASK_SECRET_KEY", "v11-phase2-web-regression")

from webapp.app import app
from webapp.services.v11_phase2_service import get_v11_phase2_dashboard


def require(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    payload = get_v11_phase2_dashboard()
    require(
        payload["classification"]
        == "PREREGISTERED_FRESH_PAPER_CONFIRMATION",
        "V11 classification is explicit",
    )
    require(
        payload["status_scope"]
        == "CONTROL_HEALTH_SEPARATE_FROM_EVIDENCE",
        "Control readiness is explicitly separate from evidence",
    )
    require(
        payload["display_status"]
        in {"AWAITING_FRESH_SESSION", "FRESH_EVIDENCE_ACTIVE", "ALERT"},
        "Evidence-aware display status is exposed",
    )
    require(
        payload["contract_sha_verified"] is True,
        "V11 contract identity is verified",
    )
    require(
        payload["maximum_tiingo_requests_per_session"] == 404,
        "Bounded request ceiling is exposed",
    )
    require(
        payload["request_time_historical_data_load"] is False,
        "Endpoint performs no historical request-time load",
    )
    require(
        payload["paper_trading_only"] is True
        and payload["live_trading_enabled"] is False
        and payload["brokerage_orders"] is False,
        "Web payload remains paper only",
    )
    require(
        payload["holdout_outcomes_read"] is False,
        "Web payload reads no holdout outcomes",
    )
    require(
        payload["v8_modified"] is False
        and payload["v10_modified"] is False,
        "V8 and V10 remain isolated",
    )

    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    compiled_template = app.jinja_env.get_template("index.html")
    require(
        compiled_template is not None,
        "Model Research template compiles under Jinja",
    )
    response = app.test_client().get("/api/v11/phase2")
    require(response.status_code == 200, "V11 status API responds")
    api_payload = response.get_json()
    require(
        api_payload["brokerage_orders"] is False,
        "V11 status API has no brokerage authority",
    )
    require(
        response.headers.get("X-Data-Serving-Path")
        == "lightweight-files; no-historical-intraday-load",
        "V11 endpoint declares its lightweight serving path",
    )

    project_root = Path(__file__).resolve().parents[2]
    template = (project_root / "webapp/templates/index.html").read_text()
    app_source = (project_root / "webapp/app.py").read_text()
    script = (
        project_root / "webapp/static/js/v11_phase2_status.js"
    ).read_text()
    require(
        'id="v11-phase2-status"' in template,
        "V11 status panel is rendered",
    )
    require(
        "{% if not live_view %}" in template,
        "V11 panel is limited to Model Research",
    )
    require(
        "{#" not in template,
        "Dashboard CSS cannot accidentally open a Jinja comment",
    )
    require(
        "FIVE-MINUTE FRESH CONFIRMATION" in template,
        "Intraday paper-confirmation identity is visible",
    )
    require(
        "BROKERAGE ORDERS" in template and "OFF" in template,
        "Brokerage orders remain visibly off",
    )
    require(
        "/api/v11/phase2" in app_source,
        "V11 read-only API route exists",
    )
    require(
        "v11_phase2_status.js" in app_source,
        "V11 panel script is injected on Model Research",
    )
    require(
        "fetch('/api/v11/phase2'" in script,
        "V11 panel loads its read-only endpoint",
    )
    require(
        "data.display_status" in script
        and "Controls are healthy, but no fresh session has been accepted" in script,
        "V11 panel does not present control health as collected evidence",
    )
    require(
        'data-v11-attempt-status' in template
        and 'data-v11-attempt-symbols' in template
        and 'data-v11-attempt-bar' in template
        and 'data-v11-attempt-reasons' in template,
        "V11 panel exposes the persisted collection diagnostic fields",
    )
    require(
        "renderAttempt(lastAttempt)" in script
        and "attempt.schedule_state" in script
        and "attempt.symbol_count" in script
        and "attempt.completed_bar_utc" in script
        and "attempt.reasons" in script,
        "V11 collection diagnostics render from the read-only API payload",
    )
    require(
        "replaceChildren" in script
        and "item.textContent" in script
        and "No manual evidence run is required" in script,
        "V11 rejection reasons render safely without triggering collection",
    )
    require(
        "<form" not in template[template.index('id="v11-phase2-status"'):],
        "V11 panel exposes no activation form",
    )
    require(
        "API_KEY" not in template and "TIINGO_API_KEY" not in script,
        "No credentials are exposed",
    )

    print("Status: PASSED")
    print("V11 Model Research panel: VERIFIED READ ONLY")
    print("Historical request-time load: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10 production evidence modified: NO")


if __name__ == "__main__":
    main()
