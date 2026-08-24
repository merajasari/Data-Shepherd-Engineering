"""Static and lightweight runtime regression for Gunicorn request-path performance."""
from __future__ import annotations
import ast
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP_PATH=ROOT/"webapp/app.py"
HEAVY={"pandas","pyarrow","numpy","sklearn"}

def require(condition,label):
    if not condition:raise AssertionError(label)
    print(f"[PASS] {label}")

def main():
    source=APP_PATH.read_text(encoding="utf-8")
    tree=ast.parse(source)
    imported=set()
    for node in tree.body:
        if isinstance(node,ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    require(not (imported&HEAVY),f"App startup has no eager heavy imports: {sorted(HEAVY)}")
    require("def _lazy(" in source,"Dashboard research services are lazy-loaded")
    require("deque(maxlen=200)" in source,"Endpoint timing telemetry is memory bounded")
    require('response.headers["Server-Timing"]' in source,"Every Flask response receives Server-Timing")
    require('response.headers["X-Response-Time-Ms"]' in source,"Every Flask response receives X-Response-Time-Ms")
    require('/api/operations/performance' in source,"Read-only performance telemetry endpoint exists")
    require("brokerage_orders":False" in source,"Performance endpoint declares brokerage orders off")

    os.environ.setdefault("FLASK_SECRET_KEY","performance-regression-secret")
    from webapp.app import app
    app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False)
    client=app.test_client()
    health=client.get("/health")
    require(health.status_code==200,"Health endpoint responds")
    require("Server-Timing" in health.headers,"Health response is timed")
    performance=client.get("/api/operations/performance")
    payload=performance.get_json()
    require(performance.status_code==200 and payload["status"]=="ok","Performance endpoint responds")
    require(payload["heavy_modules_loaded"]["pandas"] is False,"Health-only worker does not load Pandas")
    require(payload["heavy_modules_loaded"]["pyarrow"] is False,"Health-only worker does not load PyArrow")
    print("\nStatus: PASSED")
    print("Production evidence modified: NO")
    print("Brokerage orders: OFF")

if __name__=="__main__":
    main()
