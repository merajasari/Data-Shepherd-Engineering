"""Route Crypto Visual history requests through the persistent precomputed cache.

This patch intentionally leaves the authoritative history service in place as a
fallback. Normal dashboard requests are served by prebuilt JSON files instead of
scanning Parquet history in the Flask request path.
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path("webapp/app.py")


def apply() -> None:
    text = APP.read_text()
    original = text

    if "send_file" not in text.split("\n", 30)[0:30].__str__():
        old = "from flask import Flask, jsonify, redirect, render_template, request, session, url_for"
        new = "from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for"
        if old not in text:
            raise SystemExit("Cannot patch Flask send_file import: expected import not found")
        text = text.replace(old, new, 1)
        print("[APPLY] Flask send_file import")
    else:
        print("[SKIP] Flask send_file import")

    import_line = "from webapp.services.crypto_history_web_cache_service import get_crypto_history_cache_path, normalize_history_range  # noqa: E402\n"
    if import_line not in text:
        anchor = "from webapp.services.crypto_history_service import get_crypto_history_payload  # noqa: E402\n"
        if anchor not in text:
            raise SystemExit("Cannot patch persistent history cache import: history service import not found")
        text = text.replace(anchor, anchor + import_line, 1)
        print("[APPLY] persistent history cache service import")
    else:
        print("[SKIP] persistent history cache service import")

    new_route = '''@app.route("/api/crypto-history")
@login_required
def api_crypto_history():
    range_name = normalize_history_range(request.args.get("range"))
    cache_path = get_crypto_history_cache_path(range_name)
    if cache_path.exists():
        response = send_file(
            cache_path,
            mimetype="application/json",
            conditional=True,
            max_age=30,
        )
        response.headers["Cache-Control"] = "private, max-age=30"
        response.headers["X-Data-Shepherd-History-Source"] = "persistent-web-cache"
        return response

    # Safe fallback for first install or a missing cache file. This preserves the
    # current read-only service contract, but normal page loads should never need it.
    try:
        payload = get_crypto_history_payload(range_name=range_name)
    except TypeError:
        payload = get_crypto_history_payload()
    return jsonify(payload)
'''

    pattern = re.compile(
        r'@app\.route\("/api/crypto-history"\)\n@login_required\ndef api_crypto_history\(\):\n.*?(?=\n\n@app\.route\()',
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit("Cannot patch /api/crypto-history route: route block not found")
    current = match.group(0)
    if "persistent-web-cache" not in current:
        text = text[: match.start()] + new_route.rstrip() + text[match.end() :]
        print("[APPLY] persistent precomputed history API route")
    else:
        print("[SKIP] persistent precomputed history API route")

    if text != original:
        APP.write_text(text)

    print("Crypto Visual persistent history-cache route patch complete.")
    print("Normal history requests now serve precomputed JSON; Parquet scanning remains fallback-only.")


if __name__ == "__main__":
    apply()
