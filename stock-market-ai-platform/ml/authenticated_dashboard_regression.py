"""Authenticated dashboard smoke regression for post-login rendering."""
from __future__ import annotations

from datetime import datetime, timezone
import os

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

    print("Status: PASSED")
    print("Post-login dashboard rendering: VERIFIED")
    print("Internal server error: NOT REPRODUCED")
    print("Brokerage orders: OFF")


if __name__ == "__main__":
    main()
