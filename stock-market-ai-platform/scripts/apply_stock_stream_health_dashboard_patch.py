from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    if new in text:
        print(f"[SKIP] {label}")
        return
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found in {path}")
    p.write_text(text.replace(old, new, 1))
    print(f"[APPLY] {label}")


replace_once(
    "webapp/app.py",
    "from webapp.services.live_market_service import get_all_live_quotes, get_live_quote  # noqa: E402\n",
    "from webapp.services.live_market_service import get_all_live_quotes, get_live_quote  # noqa: E402\nfrom webapp.services.stock_stream_health_service import get_stock_stream_health  # noqa: E402\n",
    "stock stream health import",
)

replace_once(
    "webapp/app.py",
    "@app.route(\"/api/live\")\n@login_required\ndef api_live_quotes():\n    return jsonify(get_all_live_quotes())\n",
    "@app.route(\"/api/live\")\n@login_required\ndef api_live_quotes():\n    return jsonify(get_all_live_quotes())\n\n\n@app.route(\"/api/stock-stream-health\")\n@login_required\ndef api_stock_stream_health():\n    return jsonify(get_stock_stream_health())\n",
    "stock stream health API route",
)

p = Path("webapp/templates/index.html")
text = p.read_text()
card_marker = 'id="stock-stream-health-card"'
card = '''<section class="card" id="stock-stream-health-card" style="margin-bottom:22px"><div class="label">STOCK REAL-TIME STREAM HEALTH</div><h2>Tiingo IEX Live Feed</h2><p class="muted">Read-only monitoring for the full V5 universe (100 stocks + SPY). During regular U.S. trading hours this card turns stale if live quote timestamps stop advancing.</p><div class="mode" id="stock-stream-health-status">CHECKING</div><div class="grid metrics" style="margin-top:18px"><div class="metric"><span>LAUNCHAGENT</span><strong id="stock-stream-agent">—</strong></div><div class="metric"><span>LIVE SYMBOLS</span><strong id="stock-stream-live-count">—</strong></div><div class="metric"><span>CONFIGURED</span><strong id="stock-stream-configured-count">—</strong></div><div class="metric"><span>CACHE AGE</span><strong id="stock-stream-cache-age">—</strong></div><div class="metric"><span>MARKET CLOCK</span><strong id="stock-stream-session">—</strong></div><div class="metric"><span>REAL ORDERS</span><strong class="positive">NO</strong></div></div><p class="muted" id="stock-stream-health-detail" style="margin-top:16px">Checking Tiingo IEX stream health…</p></section>'''
if card_marker in text:
    print("[SKIP] stock stream health card")
else:
    anchors = [
        '<section class="card v4-dashboard">',
        '<section class="card" style="margin-top:22px"><div class="label">V5 LEADERS</div>',
    ]
    anchor = next((candidate for candidate in anchors if candidate in text), None)
    if anchor is None:
        raise SystemExit("Cannot apply stock stream health card: no safe current-template anchor found")
    text = text.replace(anchor, card + "\n\n" + anchor, 1)
    p.write_text(text)
    print("[APPLY] stock stream health card")

p = Path("webapp/static/js/realtime_market_refresh.js")
text = p.read_text()
marker = "  async function refreshStocks() {\n"
helper = '''  function renderStockHealth(h) {\n    const status = document.getElementById('stock-stream-health-status');\n    if (!status) return;\n    status.textContent = h.status || 'UNKNOWN';\n    status.style.color = h.status === 'LIVE' ? 'var(--green)' : (h.status === 'ERROR' || h.status === 'STALE' ? 'var(--red)' : 'var(--gold)');\n    const set = (id, value) => { const el=document.getElementById(id); if (el) el.textContent=value; };\n    set('stock-stream-agent', h.launchagent_running ? 'RUNNING' : 'NOT RUNNING');\n    set('stock-stream-live-count', String(h.live_symbol_count ?? 0));\n    set('stock-stream-configured-count', String(h.configured_symbol_count ?? 0));\n    set('stock-stream-cache-age', h.cache_age_seconds == null ? '—' : `${Math.max(0,h.cache_age_seconds).toFixed(1)}s`);\n    set('stock-stream-session', h.regular_session_expected_open ? 'REGULAR OPEN' : 'CLOSED');\n    set('stock-stream-health-detail', h.detail || '');\n  }\n\n  async function refreshStockHealth() {\n    if (location.pathname !== '/dashboard') return;\n    const health = await fetch(`/api/stock-stream-health?t=${Date.now()}`, {cache:'no-store'}).then(r => r.json());\n    renderStockHealth(health);\n  }\n\n'''
if "async function refreshStockHealth()" not in text:
    if marker not in text:
        raise SystemExit("Cannot apply stock stream health JS: marker not found")
    text = text.replace(marker, helper + marker, 1)
    text = text.replace(
        "try { await Promise.allSettled([refreshStocks(), refreshCrypto()]); }",
        "try { await Promise.allSettled([refreshStocks(), refreshStockHealth(), refreshCrypto()]); }",
        1,
    )
    p.write_text(text)
    print("[APPLY] stock stream health live refresh")
else:
    print("[SKIP] stock stream health live refresh")

print("Stock real-time stream health dashboard patch complete.")
