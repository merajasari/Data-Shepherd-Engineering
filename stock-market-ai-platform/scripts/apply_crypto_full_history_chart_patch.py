"""Idempotently wire the Crypto Visual full-history comparison chart into the web app."""
from pathlib import Path

APP = Path("webapp/app.py")
TEMPLATE = Path("webapp/templates/crypto_visual.html")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[SKIP] {label}")
        return text
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    old = "from webapp.services.crypto_live_market_service import get_all_crypto_live_tickers  # noqa: E402\n"
    new = old + "from webapp.services.crypto_history_service import get_crypto_history_payload  # noqa: E402\n"
    text = replace_once(text, old, new, "crypto history service import")

    old = '''@app.route("/api/crypto-live")\n@login_required\ndef api_crypto_live_quotes():\n    return jsonify(get_all_crypto_live_tickers())\n'''
    new = old + '''\n\n@app.route("/api/crypto-history")\n@login_required\ndef api_crypto_history():\n    return jsonify(get_crypto_history_payload())\n'''
    text = replace_once(text, old, new, "crypto history API route")
    APP.write_text(text, encoding="utf-8")


def patch_template() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    css_anchor = "footer{padding:38px;text-align:center;color:var(--muted)}"
    css = css_anchor + '''\n.history-card{margin-top:20px;border-color:rgba(155,101,255,.42)}.history-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0}.history-btn{padding:9px 13px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}.history-btn:hover,.history-btn.active{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}.history-search-wrap{position:relative;min-width:290px;flex:1}.history-search{width:100%;padding:10px 14px;border-radius:12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:800}.history-search-results{position:absolute;z-index:35;left:0;right:0;top:calc(100% + 6px);max-height:280px;overflow:auto;display:none;background:#081526;border:1px solid var(--border);border-radius:14px;box-shadow:0 18px 40px rgba(0,0,0,.35)}.history-search-results.open{display:block}.history-search-results button{display:grid;grid-template-columns:100px 1fr auto;gap:12px;width:100%;padding:11px 13px;border:0;border-bottom:1px solid rgba(120,155,205,.11);background:transparent;color:var(--text);text-align:left;cursor:pointer}.history-search-results button:hover{background:rgba(54,216,255,.08)}.history-search-results span,.history-search-results small{color:var(--muted)}.history-svg{width:100%;height:520px;display:block}.history-legend{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.history-legend-chip{display:flex;gap:7px;align-items:center;padding:7px 9px;border:1px solid var(--border);border-radius:999px;background:rgba(8,20,36,.45);color:var(--text);cursor:pointer}.history-legend-chip i{width:9px;height:9px;border-radius:50%;display:block}.history-legend-chip small{color:var(--muted)}.history-metrics{grid-template-columns:repeat(4,1fr);margin:16px 0}'''
    text = replace_once(text, css_anchor, css, "full-history chart styles")

    anchor = "{% set live=crypto.live_v2 %}{% set xrp=crypto.xrp_live %}{% set ready=crypto.forward_evaluation_readiness %}"
    section = '''<section class="card history-card"><div class="label">FULL CRYPTO MARKET HISTORY</div><h2>From our first archived observation to right now</h2><p class="muted">Compare the complete date span available in Data Shepherd's authoritative 15-minute crypto archive. The ALL view uses the final observed 15-minute close of each UTC day for browser-scale visualization, then appends the current Coinbase ticker as the live endpoint. No research files are modified.</p><div class="grid history-metrics"><div class="metric"><span>VISIBLE ASSETS</span><strong id="history-series-count">—</strong></div><div class="metric"><span>EARLIEST DATA</span><strong id="history-start">—</strong></div><div class="metric"><span>HISTORICAL POINTS</span><strong id="history-points">—</strong></div><div class="metric"><span>CHART RESOLUTION</span><strong id="history-resolution">—</strong></div></div><div class="history-toolbar"><div class="history-search-wrap"><input id="history-search" class="history-search" type="search" autocomplete="off" placeholder="Add Bitcoin, ETH, XRP, Solana…" aria-label="Add crypto series to history chart"><div id="history-search-results" class="history-search-results"></div></div><button id="history-show-all" class="history-btn" type="button">SHOW ALL 25</button><span id="history-load-status" class="mode">LOADING HISTORY</span></div><div class="history-toolbar"><strong class="muted">RANGE</strong><button class="history-btn active" type="button" data-history-range="ALL">ALL</button><button class="history-btn" type="button" data-history-range="5Y">5Y</button><button class="history-btn" type="button" data-history-range="3Y">3Y</button><button class="history-btn" type="button" data-history-range="1Y">1Y</button><button class="history-btn" type="button" data-history-range="90D">90D</button><button class="history-btn" type="button" data-history-range="30D">30D</button><strong class="muted" style="margin-left:10px">VIEW</strong><button class="history-btn active" type="button" data-history-mode="normalized">NORMALIZED GROWTH</button><button class="history-btn" type="button" data-history-mode="raw">RAW USD PRICE</button></div><div id="history-legend" class="history-legend"></div><div class="chart-panel"><svg id="crypto-history-chart" class="history-svg" viewBox="0 0 1200 520" preserveAspectRatio="none" aria-label="Interactive full-history crypto comparison chart"></svg><div class="muted" id="history-scale-note">Growth index: each asset starts at 100 on its own first available historical observation.</div></div><div class="warning" style="margin-top:14px">Historical backbone: authoritative reconciled Coinbase 15-minute archive. ALL-history visualization: one final close per UTC day. Live endpoint: current public Coinbase ticker, refreshed every two seconds. Display-only; no model inputs, frozen policies, journals, or brokerage settings are changed.</div></section>\n\n''' + anchor
    text = replace_once(text, anchor, section, "full-history chart section")

    script_anchor = "</body>"
    script = '<script src="/static/js/crypto_history_chart.js"></script>\n</body>'
    text = replace_once(text, script_anchor, script, "full-history chart script")
    TEMPLATE.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_app()
    patch_template()
    print("Crypto Visual full-history comparison chart patch complete.")
    print("Historical archive is read-only; live ticker is appended for display only.")
