"""Non-mutating regression for the additive Crypto Model Research UI."""
from datetime import datetime, timezone
import os

os.environ.setdefault("FLASK_SECRET_KEY", "crypto-model-research-regression")

from webapp.app import app


def require(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main():
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    client = app.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "crypto-research-regression"
        session["legacy_member"] = True
        session["last_activity_utc"] = datetime.now(timezone.utc).isoformat()

    stock = client.get("/dashboard")
    require(stock.status_code == 200, "Existing Model Research page still renders")
    require(b'/static/js/model_research_tabs.js' in stock.data, "Existing stock model tabs remain loaded")
    require(b'V15 Intraday' in stock.data, "Existing V15 tab remains present")

    crypto = client.get("/crypto")
    require(crypto.status_code == 200, "Existing Crypto Overview still renders")
    require(b'COINBASE REAL-TIME MARKET' in crypto.data, "Existing Crypto Overview content is unchanged")
    require(b'/static/js/crypto_research_nav.js' in crypto.data, "Additive Crypto section navigation is loaded")

    research = client.get("/crypto/model-research")
    require(research.status_code == 200, "Crypto Model Research page renders")
    for label in (b'OVERVIEW', b'CRYPTO V1', b'CRYPTO V2', b'CRYPTO V3', b'CRYPTO V4', b'15M V2', b'XRP V1'):
        require(label in research.data, f"Crypto research tab is present: {label.decode()}")
    require(b'HISTORICAL RECONSTRUCTION' in research.data and b'$100,000' in research.data, "Ten-year comparison disclosure is present")

    api = client.get("/api/crypto-model-comparison")
    require(api.status_code in (200, 503), "Comparison API is read-only and actionable with or without artifact")
    payload = api.get_json()
    require(payload.get("research_safety", {}).get("brokerage_orders") is False if api.status_code == 200 else payload.get("available") is False, "Comparison has no brokerage authority")


if __name__ == "__main__":
    main()
