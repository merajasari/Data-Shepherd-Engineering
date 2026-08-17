from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "webapp/app.py"
TEMPLATE = ROOT / "webapp/templates/index.html"
SERVICE = ROOT / "webapp/services/v5_shadow_portfolio_service.py"
JS = ROOT / "webapp/static/js/v5_shadow_comparison.js"

SERVICE_TEXT = r'''"""Read-only pre-holdout V5 shadow portfolio diagnostics.

This service creates an isolated hypothetical V5 portfolio for visual comparison
with the existing V4 paper portfolio. It does not modify V4 state, the frozen V5
model, the Sep 1+ official V5 forward journal, or any brokerage setting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.paper_trading_service import get_execution_price, get_portfolio_summary
from webapp.services.v5_forward_service import score_latest_snapshot

STATE_ROOT = Path("data/paper_trading/v5_shadow")
STATE_PATH = STATE_ROOT / "portfolio.json"
STARTING_EQUITY = 100_000.0
ENTRY_COST_RATE = 0.001


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_state(state):
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)


def initialize_v5_shadow(force=False):
    if STATE_PATH.exists() and not force:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))

    scored = score_latest_snapshot()
    v4 = get_portfolio_summary()
    positions = {}

    for symbol, weight in scored["portfolio"].items():
        quote = get_execution_price(symbol)
        price = quote.get("price")
        if price is None or float(price) <= 0:
            raise RuntimeError(f"No shadow initialization price for {symbol}")
        price = float(price)
        target_cash = STARTING_EQUITY * float(weight)
        effective_price = price * (1.0 + ENTRY_COST_RATE)
        shares = target_cash / effective_price
        entry_cost = target_cash - shares * price
        positions[symbol] = {
            "symbol": symbol,
            "weight": float(weight),
            "shares": shares,
            "market_entry_price": price,
            "average_cost": effective_price,
            "entry_cost": entry_cost,
            "price_source": quote.get("source"),
            "quote_timestamp": quote.get("timestamp"),
        }

    spy_quote = get_execution_price("SPY")
    state = {
        "created_at_utc": _utc_now(),
        "research_mode": "PRE_HOLDOUT_DIAGNOSTIC_SHADOW",
        "starting_equity": STARTING_EQUITY,
        "decision_timestamp_utc": str(scored["decision_timestamp"]),
        "holdout_start_utc": str(scored["holdout_start_utc"]),
        "model_sha256": scored["model_sha256"],
        "entry_cost_rate": ENTRY_COST_RATE,
        "positions": positions,
        "top_five": scored["top_five"],
        "comparison_baselines": {
            "v4_equity": float(v4["equity"]),
            "spy_price": float(spy_quote["price"]) if spy_quote.get("price") is not None else None,
            "captured_at_utc": _utc_now(),
        },
        "official_holdout_journal_written": False,
        "brokerage_orders": False,
    }
    _write_state(state)
    return state


def _load_state():
    if not STATE_PATH.exists():
        return initialize_v5_shadow()
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def get_v5_shadow_comparison():
    state = _load_state()
    positions = []
    equity = 0.0
    total_entry_friction = 0.0

    for symbol, pos in state["positions"].items():
        quote = get_execution_price(symbol)
        current = quote.get("price")
        if current is None:
            current = pos["market_entry_price"]
        current = float(current)
        shares = float(pos["shares"])
        market_value = shares * current
        net_pnl = (current - float(pos["average_cost"])) * shares
        market_move = (current - float(pos["market_entry_price"])) * shares
        entry_cost = float(pos.get("entry_cost", 0.0))
        equity += market_value
        total_entry_friction += entry_cost
        positions.append({
            "symbol": symbol,
            "weight": float(pos["weight"]),
            "shares": shares,
            "entry_price": float(pos["market_entry_price"]),
            "current_price": current,
            "market_value": round(market_value, 2),
            "market_move": round(market_move, 2),
            "net_pnl": round(net_pnl, 2),
            "price_source": quote.get("source"),
            "quote_timestamp": quote.get("timestamp"),
        })

    positions.sort(key=lambda row: (row["symbol"] != "SPY", -row["weight"], row["symbol"]))
    v5_return = equity / STARTING_EQUITY - 1.0

    v4 = get_portfolio_summary()
    base_v4 = float(state["comparison_baselines"]["v4_equity"])
    current_v4 = float(v4["equity"])
    v4_since_shadow = current_v4 / base_v4 - 1.0 if base_v4 else 0.0
    v4_normalized_equity = STARTING_EQUITY * (1.0 + v4_since_shadow)

    spy_quote = get_execution_price("SPY")
    base_spy = state["comparison_baselines"].get("spy_price")
    current_spy = spy_quote.get("price")
    if base_spy and current_spy:
        spy_return = float(current_spy) / float(base_spy) - 1.0
    else:
        spy_return = 0.0
    spy_normalized_equity = STARTING_EQUITY * (1.0 + spy_return)

    return {
        "status": "PRE_HOLDOUT_DIAGNOSTIC_SHADOW",
        "created_at_utc": state["created_at_utc"],
        "decision_timestamp_utc": state["decision_timestamp_utc"],
        "holdout_start_utc": state["holdout_start_utc"],
        "starting_equity": STARTING_EQUITY,
        "v5_shadow_equity": round(equity, 2),
        "v5_shadow_pnl": round(equity - STARTING_EQUITY, 2),
        "v5_shadow_return_pct": round(v5_return * 100.0, 4),
        "v4_baseline_equity": round(base_v4, 2),
        "v4_current_equity": round(current_v4, 2),
        "v4_normalized_equity": round(v4_normalized_equity, 2),
        "v4_since_shadow_return_pct": round(v4_since_shadow * 100.0, 4),
        "spy_normalized_equity": round(spy_normalized_equity, 2),
        "spy_since_shadow_return_pct": round(spy_return * 100.0, 4),
        "v5_vs_v4_pct_points": round((v5_return - v4_since_shadow) * 100.0, 4),
        "v5_vs_spy_pct_points": round((v5_return - spy_return) * 100.0, 4),
        "entry_friction": round(total_entry_friction, 2),
        "top_five": state["top_five"],
        "positions": positions,
        "official_holdout_journal_written": False,
        "brokerage_orders": False,
        "note": "Pre-Sep-1 diagnostic shadow only. These observations are excluded from the official frozen V5 future holdout.",
    }
'''

JS_TEXT = r'''(() => {
  const money = v => `${Number(v) < 0 ? '-' : ''}$${Math.abs(Number(v || 0)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const pct = v => `${Number(v) >= 0 ? '+' : ''}${Number(v || 0).toFixed(2)}%`;
  const tone = v => Number(v) >= 0 ? 'positive' : 'negative';
  const set = (id, text, cls) => { const el=document.getElementById(id); if(!el)return; el.textContent=text; if(cls)el.className=cls; };

  async function load(){
    const status=document.getElementById('v5-shadow-status');
    try{
      const r=await fetch('/api/v5-shadow-comparison',{credentials:'same-origin',cache:'no-store'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      const d=await r.json();
      if(status) status.textContent='PRE-HOLDOUT SHADOW';
      set('v5-shadow-equity',money(d.v5_shadow_equity),tone(d.v5_shadow_pnl));
      set('v5-shadow-return',pct(d.v5_shadow_return_pct),tone(d.v5_shadow_return_pct));
      set('v5-shadow-v4-equity',money(d.v4_normalized_equity),tone(d.v4_since_shadow_return_pct));
      set('v5-shadow-v4-return',pct(d.v4_since_shadow_return_pct),tone(d.v4_since_shadow_return_pct));
      set('v5-shadow-spy-equity',money(d.spy_normalized_equity),tone(d.spy_since_shadow_return_pct));
      set('v5-shadow-spy-return',pct(d.spy_since_shadow_return_pct),tone(d.spy_since_shadow_return_pct));
      set('v5-shadow-vs-v4',`${d.v5_vs_v4_pct_points>=0?'+':''}${Number(d.v5_vs_v4_pct_points).toFixed(3)} pts`,tone(d.v5_vs_v4_pct_points));
      set('v5-shadow-vs-spy',`${d.v5_vs_spy_pct_points>=0?'+':''}${Number(d.v5_vs_spy_pct_points).toFixed(3)} pts`,tone(d.v5_vs_spy_pct_points));
      set('v5-shadow-friction',money(-Math.abs(d.entry_friction)),'negative');
      set('v5-shadow-started',new Date(d.created_at_utc).toLocaleString());
      set('v5-shadow-decision',String(d.decision_timestamp_utc));
      const list=document.getElementById('v5-shadow-holdings');
      if(list){
        list.innerHTML=d.positions.map(p=>`<div class="v5-shadow-row"><div><strong>${p.symbol}</strong><div class="muted">${(p.weight*100).toFixed(0)}% target · ${p.price_source||'price'}</div></div><div class="${tone(p.net_pnl)}"><strong>${money(p.net_pnl)}</strong><div class="muted">${money(p.current_price)}</div></div></div>`).join('');
      }
    }catch(err){
      if(status){status.textContent='SHADOW DATA ERROR';status.className='negative';}
      console.warn('[V5 SHADOW]',err);
    }
  }
  load();
  window.setInterval(load,10000);
})();
'''

PANEL = r'''
<section class="card" id="v5-shadow-comparison" style="margin-top:22px">
  <div class="label">V4 VS V5 SHADOW COMPARISON</div>
  <h2>Frozen V5 Hypothetical Portfolio</h2>
  <p class="muted">A separate $100,000 diagnostic shadow using the frozen V5 60% SPY + 40% Top-5 contract. The existing V4 portfolio remains unchanged. Pre-Sep-1 observations are never written into the official V5 future holdout.</p>
  <div id="v5-shadow-status" class="mode">LOADING SHADOW</div>
  <div class="grid grid-3" style="margin-top:18px">
    <div class="metric"><span>V5 SHADOW EQUITY</span><strong id="v5-shadow-equity">—</strong><div id="v5-shadow-return" class="muted">—</div></div>
    <div class="metric"><span>V4 NORMALIZED SINCE SHADOW START</span><strong id="v5-shadow-v4-equity">—</strong><div id="v5-shadow-v4-return" class="muted">—</div></div>
    <div class="metric"><span>SPY NORMALIZED SINCE SHADOW START</span><strong id="v5-shadow-spy-equity">—</strong><div id="v5-shadow-spy-return" class="muted">—</div></div>
  </div>
  <div class="grid metrics" style="margin-top:14px">
    <div class="metric"><span>V5 VS V4</span><strong id="v5-shadow-vs-v4">—</strong></div>
    <div class="metric"><span>V5 VS SPY</span><strong id="v5-shadow-vs-spy">—</strong></div>
    <div class="metric"><span>MODELED ENTRY FRICTION</span><strong id="v5-shadow-friction">—</strong></div>
    <div class="metric"><span>REAL ORDERS</span><strong class="positive">NO</strong></div>
    <div class="metric"><span>SHADOW STARTED</span><strong id="v5-shadow-started" style="font-size:.9rem">—</strong></div>
    <div class="metric"><span>V5 DECISION</span><strong id="v5-shadow-decision" style="font-size:.9rem">—</strong></div>
  </div>
  <div class="grid grid-2" style="margin-top:18px">
    <div>
      <div class="label">V5 SHADOW HOLDINGS</div>
      <div id="v5-shadow-holdings" class="v5-shadow-holdings"></div>
    </div>
    <div class="warning">
      <strong>Research boundary preserved.</strong><br><br>
      This panel is descriptive pre-holdout monitoring only. It does not replace V4, does not rebalance the V4 account, does not alter the frozen V5 model, and does not count toward the Sep 1+ untouched V5 evaluation.
    </div>
  </div>
</section>
'''

STYLE = r'''
<style id="v5-shadow-comparison-style">
.v5-shadow-holdings{display:grid;gap:8px;margin-top:12px}.v5-shadow-row{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:12px 14px;border:1px solid rgba(120,155,205,.15);border-radius:12px;background:rgba(8,20,36,.45)}.v5-shadow-row>div:last-child{text-align:right}
</style>
'''


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def main():
    SERVICE.write_text(SERVICE_TEXT, encoding="utf-8")
    JS.write_text(JS_TEXT, encoding="utf-8")
    print("[APPLY] V5 shadow portfolio service")
    print("[APPLY] V5 shadow comparison browser module")

    app = APP.read_text(encoding="utf-8")
    app = replace_once(
        app,
        "from webapp.services.paper_journal_reader import summarize_journal  # noqa: E402\n",
        "from webapp.services.paper_journal_reader import summarize_journal  # noqa: E402\nfrom webapp.services.v5_shadow_portfolio_service import get_v5_shadow_comparison  # noqa: E402\n",
        "V5 shadow service import",
    )
    app = replace_once(
        app,
        "                '<script src=\"/static/js/v4_pnl_attribution.js\" defer></script>',\n",
        "                '<script src=\"/static/js/v4_pnl_attribution.js\" defer></script>',\n                '<script src=\"/static/js/v5_shadow_comparison.js\" defer></script>',\n",
        "V5 shadow comparison script",
    )
    app = replace_once(
        app,
        "@app.route(\"/api/v4-forward\")\n@login_required\ndef api_v4_forward():\n    return jsonify(build_v4_dashboard_payload())\n",
        "@app.route(\"/api/v4-forward\")\n@login_required\ndef api_v4_forward():\n    return jsonify(build_v4_dashboard_payload())\n\n\n@app.route(\"/api/v5-shadow-comparison\")\n@login_required\ndef api_v5_shadow_comparison():\n    return jsonify(get_v5_shadow_comparison())\n",
        "V5 shadow comparison API",
    )
    APP.write_text(app, encoding="utf-8")

    html = TEMPLATE.read_text(encoding="utf-8")
    if 'id="v5-shadow-comparison-style"' not in html:
        html = replace_once(html, "</head>", STYLE + "\n</head>", "V5 shadow comparison styles")
    if 'id="v5-shadow-comparison"' not in html:
        marker_text = "Frozen V4 cross-sectional strategy monitored against SPY. Simulation only — no brokerage orders are placed."
        marker_pos = html.find(marker_text)
        if marker_pos < 0:
            raise SystemExit("Cannot apply V5 shadow panel: V4 dashboard marker not found")
        close_pos = html.find("</section>", marker_pos)
        if close_pos < 0:
            raise SystemExit("Cannot apply V5 shadow panel: V4 section close not found")
        close_pos += len("</section>")
        html = html[:close_pos] + "\n\n" + PANEL + html[close_pos:]
        print("[APPLY] V4 vs V5 shadow comparison panel")
    TEMPLATE.write_text(html, encoding="utf-8")

    # Initialize the isolated shadow immediately so the first dashboard request
    # only has to mark six positions instead of scoring 100 feature files.
    from webapp.services.v5_shadow_portfolio_service import initialize_v5_shadow
    state = initialize_v5_shadow(force=False)
    print("[APPLY] isolated V5 shadow starting snapshot")
    print("V5 shadow decision:", state["decision_timestamp_utc"])
    print("V5 shadow Top-5:", ", ".join(row["symbol"] for row in state["top_five"]))
    print("V4 baseline equity:", state["comparison_baselines"]["v4_equity"])
    print("SPY baseline price:", state["comparison_baselines"]["spy_price"])
    print("V5 shadow comparison patch complete.")
    print("Pre-holdout diagnostics only; V4 state, frozen V5, official Sep 1+ journal, and brokerage settings are unchanged.")


if __name__ == "__main__":
    main()
