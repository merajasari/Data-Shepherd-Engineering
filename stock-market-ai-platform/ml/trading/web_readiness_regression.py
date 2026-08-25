"""Read-only regression for the dedicated Trading Readiness page."""
import os
from pathlib import Path
os.environ.setdefault("FLASK_SECRET_KEY","trading-readiness-regression")
from webapp.app import app
from webapp.services.trading_readiness_service import get_trading_readiness

def require(value,label):
    if not value:raise AssertionError(label)
    print(f"[PASS] {label}")

def main():
    payload=get_trading_readiness()
    require(payload["status"]=="NOT_AUTHORIZED","Preparation remains not authorized")
    require(payload["live_trading_enabled"] is False,"Live trading disabled")
    require(payload["brokerage_orders"] is False,"Brokerage orders off")
    require(payload["credentials_in_repository"] is False,"No credentials exposed")
    require(payload["broker"]=="UNSELECTED","Broker unselected")
    require(len(payload["contract_sha256"])==64,"Contract SHA displayed")
    app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False)
    client=app.test_client()
    require(client.get("/trading-readiness").status_code in {302,401},"Page requires authentication")
    with client.session_transaction() as state:
        state["authenticated"]=True
        state["last_activity_utc"]="2026-08-25T00:00:00+00:00"
    # Use a current activity timestamp so the five-minute guard does not expire the test.
    from datetime import datetime,timezone
    with client.session_transaction() as state:state["last_activity_utc"]=datetime.now(timezone.utc).isoformat()
    response=client.get("/trading-readiness")
    require(response.status_code==200,"Authenticated page responds")
    require(b"Real Trading Readiness" in response.data,"Readiness content rendered")
    require(b"TRADING READINESS" in response.data,"Dedicated navigation tab rendered")
    require(b"type=\"password\"" not in response.data and b"API_KEY" not in response.data,"No credential controls or secrets rendered")
    source=(Path(__file__).resolve().parents[1]/"webapp/templates/trading_readiness.html").read_text()
    require("<form" not in source,"Page has no activation or order forms")
    print("\nStatus: PASSED")
    print("Page authority: READ ONLY")
    print("Brokerage orders: OFF")

if __name__=="__main__":main()
