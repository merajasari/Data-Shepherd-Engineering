from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY_JS = ROOT / "webapp/static/js/crypto_history_chart.js"
REL_JS = ROOT / "webapp/static/js/crypto_relationship_explorer.js"


def replace_once(text: str, candidates, replacement: str, label: str):
    for candidate in candidates:
        if candidate in text:
            print(f"[APPLY] {label}")
            return text.replace(candidate, replacement, 1)
    if replacement in text:
        print(f"[SKIP] {label}")
        return text
    raise SystemExit(f"Cannot apply {label}: expected text not found")


history = HISTORY_JS.read_text()
history = replace_once(
    history,
    ["let range = '1Y';", "let range = '90D';", "let range='1Y';", "let range='90D';"],
    "let range = '90D';",
    "90D initial history range",
)
history = replace_once(
    history,
    ["let showAll = true;", "let showAll=true;"],
    "let showAll = false;",
    "render five major cryptos initially",
)
history = replace_once(
    history,
    [
        "selected = new Set(['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD']);zoomLevel=1;panOffset=0;hoverSymbol=null;renderAll();",
        "selected=new Set(['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD']);zoomLevel=1;panOffset=0;hoverSymbol=null;renderAll();",
    ],
    "selected = new Set(['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD']);zoomLevel=1;panOffset=0;hoverSymbol=null;renderAll();",
    "preserve five-major reset selection",
)
HISTORY_JS.write_text(history)

rel = REL_JS.read_text()
old_tail_candidates = [
    "if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();",
    "if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();",
]
new_tail = """function scheduleInit() {
    const start = () => {
      if ('requestIdleCallback' in window) {
        window.requestIdleCallback(() => init(), {timeout: 1200});
      } else {
        window.setTimeout(init, 350);
      }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
    else start();
  }

  scheduleInit();"""
rel = replace_once(
    rel,
    old_tail_candidates,
    new_tail,
    "defer relationship explorer until initial page paint",
)
REL_JS.write_text(rel)

print("Crypto Visual fast initial-render patch complete.")
print("Initial history chart now draws BTC/ETH/XRP/SOL/ADA only; all 25 remain selectable.")
print("Relationship explorer initializes during browser idle time so it does not compete with first chart paint.")
print("Presentation only; cached history, models, journals, policies, and brokerage settings are unchanged.")
