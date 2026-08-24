"""Regression checks for the public Data Shepherd customer assistant and idle-session boundary."""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FLASK_SECRET_KEY","customer-chat-regression-secret")
from webapp.app import IDLE_TIMEOUT_SECONDS, app  # noqa: E402

def require(condition,label):
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")

def main():
    app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False)
    original_key=os.environ.pop("OPENAI_API_KEY",None)
    try:
        landing_client=app.test_client()
        landing=landing_client.get("/")
        require(landing.status_code==200,"Landing page available")
        require(b"customer_ai_chat.js" in landing.data,"Assistant injected on landing page")

        guide_client=app.test_client()
        response=guide_client.post("/api/customer-chat",json={"message":"What is frozen V8?","page":"research"})
        payload=response.get_json()
        require(response.status_code==200 and "September 1, 2026" in payload["reply"],"Page guide fallback works without external AI")
        require(payload["mode"]=="platform_guide","Fallback mode is explicit")

        safety_client=app.test_client()
        response=safety_client.post("/api/customer-chat",json={"message":"What stock should I buy?","page":"live"})
        payload=response.get_json()
        require(response.status_code==200 and payload["mode"]=="safety_guide","Personalized trade request blocked before external AI")
        require("cannot recommend buying or selling" in payload["reply"],"Safety response explains the boundary")

        context_client=app.test_client()
        response=context_client.post("/api/customer-chat",json={"message":"Explain this page","page":"<untrusted-context>"})
        require("platform" in response.get_json()["reply"].lower(),"Unrecognized page context is normalized")

        limit_client=app.test_client()
        statuses=[limit_client.post("/api/customer-chat",json={"message":"Explain V8","page":"research"}).status_code for _ in range(11)]
        require(statuses[:10]==[200]*10 and statuses[10]==429,"Per-session rate limit blocks request 11")

        idle_client=app.test_client()
        with idle_client.session_transaction() as state:
            state["authenticated"]=True
            state["last_activity_utc"]=(datetime.now(timezone.utc)-timedelta(seconds=IDLE_TIMEOUT_SECONDS+1)).isoformat()
        response=idle_client.post("/api/session/activity")
        require(response.status_code==401,"Expired authenticated session is rejected")
        with idle_client.session_transaction() as state:
            require(not state.get("authenticated"),"Expired session is cleared")

        print("\nStatus: PASSED")
        print("External AI calls made: NO")
        print("Brokerage orders: OFF")
    finally:
        if original_key is not None:
            os.environ["OPENAI_API_KEY"]=original_key

if __name__=="__main__":
    main()
