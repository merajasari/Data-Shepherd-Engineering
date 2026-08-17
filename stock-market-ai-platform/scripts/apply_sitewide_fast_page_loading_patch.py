from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text()
    if new in text:
        print(f"[SKIP] {label}")
        return
    if old not in text:
        print(f"[INFO] {label}: expected text not found; leaving current implementation unchanged")
        return
    path.write_text(text.replace(old, new, 1))
    print(f"[APPLY] {label}")


def add_before(path: Path, marker: str, block: str, label: str):
    text = path.read_text()
    if block.strip() in text:
        print(f"[SKIP] {label}")
        return
    if marker not in text:
        print(f"[INFO] {label}: insertion point not found; leaving current implementation unchanged")
        return
    path.write_text(text.replace(marker, block + "\n" + marker, 1))
    print(f"[APPLY] {label}")


app = ROOT / "webapp/app.py"
realtime = ROOT / "webapp/static/js/realtime_market_refresh.js"
v4 = ROOT / "webapp/static/js/v4_equity_chart.js"
market_history = ROOT / "webapp/static/js/market_history_chart.js"
index = ROOT / "webapp/templates/index.html"
crypto = ROOT / "webapp/templates/crypto.html"
crypto_visual = ROOT / "webapp/templates/crypto_visual.html"

# Let the browser parse and paint before optional dashboard modules execute.
for script in [
    "/static/js/signup_button.js",
    "/static/js/realtime_market_refresh.js",
    "/static/js/dashboard_layout.js",
    "/static/js/v4_equity_chart.js",
    "/static/js/market_history_chart.js",
    "/static/js/primary_stock_spotlight.js",
]:
    replace_once(
        app,
        f'<script src="{script}"></script>',
        f'<script src="{script}" defer></script>',
        f"defer {Path(script).name}",
    )

# Keep live data fast, but let the first browser paint happen before the initial poll.
replace_once(
    realtime,
    "  document.addEventListener('DOMContentLoaded', start);",
    "  document.addEventListener('DOMContentLoaded', () => requestAnimationFrame(() => requestAnimationFrame(start)));",
    "start realtime polling after first paint",
)

# Heavy stock charts should not compete with the initial dashboard paint.
replace_once(
    v4,
    "slider.addEventListener('input',()=>show(slider.value,null,null,true));slider.addEventListener('change',()=>setTimeout(()=>tip.style.display='none',900));load().catch(e=>console.error('V4 interactive equity chart:',e));",
    "slider.addEventListener('input',()=>show(slider.value,null,null,true));slider.addEventListener('change',()=>setTimeout(()=>tip.style.display='none',900));const startLoad=()=>load().catch(e=>console.error('V4 interactive equity chart:',e));if('requestIdleCallback' in window)requestIdleCallback(startLoad,{timeout:900});else setTimeout(startLoad,120);",
    "defer V4 equity chart data load",
)

replace_once(
    market_history,
    "  load();\n})();",
    "  const startHistoryLoad=()=>load();\n  if ('requestIdleCallback' in window) requestIdleCallback(startHistoryLoad,{timeout:1000});\n  else setTimeout(startHistoryLoad,140);\n})();",
    "defer stock market-history chart data load",
)

# Ask the browser not to lay out/render long below-the-fold cards until needed.
# content-visibility is progressive enhancement; browsers without support ignore it.
PERF_CSS = """<style id=\"ds-sitewide-fast-load\">\n/* Site-wide progressive rendering: off-screen dashboard cards are skipped until near the viewport. */\nmain > .card, .container > .card, body > .card{content-visibility:auto;contain-intrinsic-size:auto 520px}\n@media(max-width:760px){main > .card, .container > .card, body > .card{contain-intrinsic-size:auto 620px}}\n</style>"""

for template, label in [
    (index, "stock dashboard progressive rendering"),
    (crypto, "crypto dashboard progressive rendering"),
    (crypto_visual, "crypto visual progressive rendering"),
]:
    add_before(template, "</head>", PERF_CSS, label)

print("Site-wide fast page-loading patch complete.")
print("Stocks, Crypto, and Crypto Visual now stage noncritical rendering after first paint.")
print("Authentication/account pages remain unchanged because they do not carry heavy market-data visualizations.")
print("No model, policy, journal, market-data collection, or brokerage behavior is changed.")
