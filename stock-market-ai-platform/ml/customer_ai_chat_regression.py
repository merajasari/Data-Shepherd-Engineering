"""Regression checks for the public Data Shepherd customer assistant and idle-session boundary."""
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

os.environ.setdefault("FLASK_SECRET_KEY","customer-chat-regression-secret")
from webapp.app import IDLE_TIMEOUT_SECONDS, app  # noqa: E402

def require(condition,label):
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")

def main():
    app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False)
    project_root=Path(__file__).resolve().parents[1]
    chat_source=(project_root/"webapp/static/js/customer_ai_chat.js").read_text(encoding="utf-8")
    original_key=os.environ.pop("OPENAI_API_KEY",None)
    try:
        landing_client=app.test_client()
        landing=landing_client.get("/")
        require(landing.status_code==200,"Landing page available")
        require(b"customer_ai_chat.js" in landing.data,"Assistant injected while logged out on landing page")
        require("ds-chat-suggestions" in chat_source and "ds-chat-suggestion" in chat_source,
                "Visible example-question controls are present")

        page_prompts={
            "landing":("Platform introduction",("What is Data Shepherd?","How are results validated?","What is a frozen holdout?")),
            "research":("Model Research guide",("Explain the model comparison","What is frozen V8?","What is V10 Cycle 3?")),
            "live":("Live Stock Viewer guide",("How do I read this chart?","What does a V8 rank mean?","Why is live data provisional?")),
            "crypto":("Crypto dashboard guide",("Explain this crypto dashboard","What does data freshness mean?","Are these live trading signals?")),
            "crypto_visual":("Crypto Visual guide",("How do I read this visual?","What do the ranges change?","What evidence is forward-only?")),
        }
        for page,(label,prompts) in page_prompts.items():
            require(label in chat_source and all(prompt in chat_source for prompt in prompts),
                    f"{page} page has its own visible suggested questions")

        guide_client=app.test_client()
        response=guide_client.post("/api/customer-chat",json={"message":"What is frozen V8?","page":"research"})
        payload=response.get_json()
        require(response.status_code==200 and "September 1, 2026" in payload["reply"],"Page guide fallback works without external AI")
        require(payload["mode"]=="platform_guide","Fallback mode is explicit")

        for page,expected in {
            "landing":"landing page",
            "research":"model research",
            "live":"live stock viewer",
            "crypto":"crypto dashboard",
            "crypto_visual":"crypto visual",
        }.items():
            page_client=app.test_client()
            page_reply=page_client.post("/api/customer-chat",json={"message":"Explain this page","page":page}).get_json()["reply"].lower()
            require(expected in page_reply,f"Server recognizes {page} assistant context")

        safety_client=app.test_client()
        response=safety_client.post("/api/customer-chat",json={"message":"What stock should I buy?","page":"live"})
        payload=response.get_json()
        require(response.status_code==200 and payload["mode"]=="safety_guide","Personalized trade request blocked before external AI")
        require("cannot recommend buying or selling" in payload["reply"],"Safety response explains the boundary")
        for unsafe_prompt in ("Should I sell AAPL?","Recommend a stock","Give me a price target"):
            advice_client=app.test_client()
            blocked=advice_client.post("/api/customer-chat",json={"message":unsafe_prompt,"page":"live"}).get_json()
            require(blocked["mode"]=="safety_guide",f"Advice guard blocks: {unsafe_prompt}")

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
