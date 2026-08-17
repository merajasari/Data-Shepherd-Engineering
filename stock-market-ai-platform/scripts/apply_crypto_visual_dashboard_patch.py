"""Apply the third Crypto Visual dashboard tab to the existing Flask UI.

The patch is presentation-only. It reuses existing crypto payloads and live APIs
and does not alter frozen research, forward journals, or brokerage behavior.
"""
from __future__ import annotations

from pathlib import Path

APP = Path("webapp/app.py")
CRYPTO_TEMPLATE = Path("webapp/templates/crypto.html")
SIGNUP_JS = Path("webapp/static/js/signup_button.js")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"[SKIP] {label}")
        return
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[APPLY] {label}")


def main() -> None:
    replace_once(
        APP,
        '''@app.route("/crypto")\n@login_required\ndef crypto_dashboard():\n    return render_template("crypto.html", crypto=get_crypto_dashboard_payload())\n''',
        '''@app.route("/crypto")\n@login_required\ndef crypto_dashboard():\n    return render_template("crypto.html", crypto=get_crypto_dashboard_payload())\n\n\n@app.route("/crypto-visual")\n@login_required\ndef crypto_visual_dashboard():\n    return render_template("crypto_visual.html", crypto=get_crypto_dashboard_payload())\n''',
        "crypto visual Flask route",
    )

    replace_once(
        CRYPTO_TEMPLATE,
        '''<nav class="tabs"><a class="tab" href="{{ url_for('dashboard') }}">STOCKS</a><a class="tab active" href="{{ url_for('crypto_dashboard') }}">CRYPTO</a></nav>''',
        '''<nav class="tabs"><a class="tab" href="{{ url_for('dashboard') }}">STOCKS</a><a class="tab active" href="{{ url_for('crypto_dashboard') }}">CRYPTO</a><a class="tab" href="{{ url_for('crypto_visual_dashboard') }}">CRYPTO VISUAL</a></nav>''',
        "third tab on detailed crypto page",
    )

    replace_once(
        SIGNUP_JS,
        '''if (shell && header && !existingTabs && ['/dashboard', '/crypto'].includes(window.location.pathname)) {''',
        '''if (shell && header && !existingTabs && ['/dashboard', '/crypto', '/crypto-visual'].includes(window.location.pathname)) {''',
        "third-tab route support",
    )

    replace_once(
        SIGNUP_JS,
        '''      <a class="ds-dashboard-tab ${window.location.pathname === '/dashboard' ? 'active' : ''}" href="/dashboard">STOCKS</a>\n      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto' ? 'active' : ''}" href="/crypto">CRYPTO</a>''',
        '''      <a class="ds-dashboard-tab ${window.location.pathname === '/dashboard' ? 'active' : ''}" href="/dashboard">STOCKS</a>\n      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto' ? 'active' : ''}" href="/crypto">CRYPTO</a>\n      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto-visual' ? 'active' : ''}" href="/crypto-visual">CRYPTO VISUAL</a>''',
        "third tab on stock dashboard",
    )

    print("Crypto Visual third-tab patch complete.")
    print("Presentation only; frozen crypto research and brokerage settings unchanged.")


if __name__ == "__main__":
    main()
