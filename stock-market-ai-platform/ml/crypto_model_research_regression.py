"""Non-mutating regression for the restored Crypto Model Research UI."""
from datetime import datetime, timezone
import os
from pathlib import Path

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

    crypto = client.get("/crypto")
    require(crypto.status_code == 200, "Combined Crypto Model Research page renders")
    require(b"COINBASE REAL-TIME MARKET" in crypto.data, "Complete legacy Crypto Overview content remains present")
    require(b"MODEL COMPARISON" in crypto.data and b"CRYPTO V5" in crypto.data,
            "Comparison and latest complete crypto model tabs are present")
    for label in (b"OVERVIEW", b"CRYPTO V1", b"CRYPTO V2", b"CRYPTO V3", b"CRYPTO V4",
                  b"SHARED CRYPTO V2", b"XRP V1", b"SHARED CRYPTO V3", b"XRP V2", b"XRP V3"):
        require(label in crypto.data, f"Crypto research tab is present: {label.decode()}")
    require(b"HISTORICAL RECONSTRUCTION" in crypto.data and b"$100,000" in crypto.data,
            "Ten-year comparison disclosure is present")

    api = client.get("/api/crypto-model-comparison")
    require(api.status_code in (200, 503), "Comparison API is read-only and actionable")
    payload = api.get_json()
    require(payload.get("research_safety", {}).get("brokerage_orders") is False
            if api.status_code == 200 else payload.get("available") is False,
            "Comparison has no brokerage authority")

    root = Path(__file__).resolve().parents[1]
    source = (root / "webapp/static/js/crypto_model_research.js").read_text()
    require(all(label in source for label in ("STARTING VALUE", "ENDING VALUE", "TOTAL RETURN",
                                               "CAGR", "MAX DRAWDOWN", "SHARPE")),
            "Model tabs expose the complete supporting metric set")
    print("Status: PASSED")


if __name__ == "__main__":
    main()
