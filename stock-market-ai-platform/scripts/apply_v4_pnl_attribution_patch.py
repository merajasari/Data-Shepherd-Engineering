from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "webapp/services/paper_trading_service.py"
APP = ROOT / "webapp/app.py"
TEMPLATE = ROOT / "webapp/templates/index.html"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"[SKIP] {label} already applied")
        return
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[APPLY] {label}")


helper = r'''

def get_pnl_attribution():
    """Return read-only dollar attribution for the simulated V4 portfolio.

    Separates current open-position market movement from modeled entry friction,
    realized paper P&L, sleeve contribution, and completed rebalance costs.
    No portfolio state is modified.
    """

    state = load_state()
    rows = []

    open_entry_friction = 0.0
    open_market_move = 0.0
    core_net_pnl = 0.0
    v4_net_pnl = 0.0

    for symbol, position in state.get("positions", {}).items():
        quote = get_execution_price(symbol)
        shares = float(position.get("shares", 0.0))
        average_cost = float(position.get("average_cost", 0.0))
        market_entry_price = float(
            position.get("market_entry_price", average_cost)
        )
        current_price = quote.get("price")
        if current_price is None:
            current_price = average_cost
        current_price = float(current_price)

        entry_cost = float(position.get("entry_cost", 0.0))
        market_move = (current_price - market_entry_price) * shares
        net_pnl = (current_price - average_cost) * shares
        sleeve = str(position.get("sleeve", "unknown"))

        open_entry_friction += entry_cost
        open_market_move += market_move
        if sleeve == "core":
            core_net_pnl += net_pnl
        elif sleeve == "v4":
            v4_net_pnl += net_pnl

        rows.append(
            {
                "symbol": symbol,
                "sleeve": sleeve,
                "shares": shares,
                "market_entry_price": market_entry_price,
                "average_cost": average_cost,
                "current_price": current_price,
                "entry_friction": round(entry_cost, 2),
                "market_move": round(market_move, 2),
                "net_pnl": round(net_pnl, 2),
                "price_source": quote.get("source"),
                "quote_timestamp": quote.get("timestamp"),
            }
        )

    rows.sort(key=lambda row: row["net_pnl"], reverse=True)

    trades = list(state.get("trades", []))
    sold_symbols = {
        str(trade.get("symbol", ""))
        for trade in trades
        if trade.get("action") == "SELL"
    }

    total_trade_friction = 0.0
    realized_rebalance_cost = 0.0
    for trade in trades:
        entry_cost = float(trade.get("entry_cost", 0.0) or 0.0)
        exit_cost = float(trade.get("exit_cost", 0.0) or 0.0)
        total_trade_friction += entry_cost + exit_cost
        if str(trade.get("symbol", "")) in sold_symbols:
            realized_rebalance_cost += entry_cost + exit_cost

    realized_pnl = float(state.get("realized_pnl", 0.0))
    total_pnl = core_net_pnl + v4_net_pnl + realized_pnl

    return {
        "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(realized_pnl, 2),
        "core_net_pnl": round(core_net_pnl, 2),
        "v4_net_pnl": round(v4_net_pnl, 2),
        "open_position_market_move": round(open_market_move, 2),
        "open_position_entry_friction": round(open_entry_friction, 2),
        "total_friction": round(total_trade_friction, 2),
        "realized_rebalance_cost": round(realized_rebalance_cost, 2),
        "best_contributor": rows[0] if rows else None,
        "worst_contributor": rows[-1] if rows else None,
        "positions": rows,
        "brokerage_orders": False,
    }
'''

service_text = SERVICE.read_text(encoding="utf-8")
if "def get_pnl_attribution():" not in service_text:
    anchor = "\ndef evaluate_trade_candidates(\n"
    if anchor not in service_text:
        raise SystemExit("Cannot apply P&L attribution helper: service anchor not found")
    SERVICE.write_text(service_text.replace(anchor, helper + anchor, 1), encoding="utf-8")
    print("[APPLY] V4 P&L attribution service")
else:
    print("[SKIP] V4 P&L attribution service already applied")

replace_once(
    APP,
    "from webapp.services.paper_trading_service import get_portfolio_summary  # noqa: E402",
    "from webapp.services.paper_trading_service import get_pnl_attribution, get_portfolio_summary  # noqa: E402",
    "P&L attribution service import",
)

replace_once(
    APP,
    '    portfolio = dict(get_portfolio_summary())\n',
    '    portfolio = dict(get_portfolio_summary())\n    portfolio["pnl_attribution"] = get_pnl_attribution()\n',
    "P&L attribution API payload",
)

replace_once(
    APP,
    "                '<script src=\"/static/js/v4_equity_chart.js\" defer></script>',\n",
    "                '<script src=\"/static/js/v4_equity_chart.js\" defer></script>',\n                '<script src=\"/static/js/v4_pnl_attribution.js\" defer></script>',\n",
    "P&L attribution dashboard script",
)

panel = '''  <div id="v4-pnl-attribution" class="v4-pnl-attribution">
    <div class="v4-pnl-attribution-head">
      <div><div class="label">P&amp;L ATTRIBUTION</div><h3>What is driving the portfolio right now?</h3><div class="muted">Separates market movement, modeled trading friction, the SPY core, V4 sleeve, and realized rebalance P&amp;L.</div></div>
      <div><div class="muted" style="font-size:.72rem;font-weight:900;letter-spacing:.08em">TOTAL P&amp;L</div><div id="v4-pnl-total" class="v4-pnl-total">—</div></div>
    </div>
    <div class="v4-pnl-metrics">
      <div class="metric"><span>SPY CORE</span><strong id="v4-pnl-core">—</strong></div>
      <div class="metric"><span>V4 OPEN SLEEVE</span><strong id="v4-pnl-sleeve">—</strong></div>
      <div class="metric"><span>REALIZED P&amp;L</span><strong id="v4-pnl-realized">—</strong></div>
      <div class="metric"><span>TOTAL TRADING FRICTION</span><strong id="v4-pnl-friction">—</strong></div>
      <div class="metric"><span>OPEN-POSITION MARKET MOVE</span><strong id="v4-pnl-market">—</strong></div>
    </div>
    <div class="v4-pnl-grid">
      <div class="v4-pnl-panel">
        <div class="label">OPEN POSITION CONTRIBUTION</div>
        <div class="v4-pnl-sub" style="display:grid;grid-template-columns:74px 1fr 110px 110px;gap:10px;margin-top:10px"><span>SYMBOL</span><span>RELATIVE SIZE</span><span style="text-align:right">MARKET MOVE</span><span style="text-align:right">NET P&amp;L</span></div>
        <div id="v4-pnl-positions" style="margin-top:4px">Loading attribution…</div>
      </div>
      <div class="v4-pnl-panel">
        <div class="label">QUICK DIAGNOSTICS</div>
        <div class="metric" style="margin-top:12px"><span>BEST CONTRIBUTOR</span><strong id="v4-pnl-best">—</strong></div>
        <div class="metric" style="margin-top:10px"><span>WORST CONTRIBUTOR</span><strong id="v4-pnl-worst">—</strong></div>
        <div class="metric" style="margin-top:10px"><span>COMPLETED REBALANCE COST</span><strong id="v4-pnl-switch-cost">—</strong></div>
        <div class="v4-pnl-note">Market move is measured from each position's quoted market-entry price. Net P&amp;L includes modeled entry friction. Completed rebalance cost reports modeled entry/exit friction associated with symbols that have been sold. Simulation only — no brokerage orders.</div>
      </div>
    </div>
  </div>
'''

template_text = TEMPLATE.read_text(encoding="utf-8")
if 'id="v4-pnl-attribution"' not in template_text:
    anchor = '  <div class="v4-lower">\n'
    if anchor not in template_text:
        raise SystemExit("Cannot apply P&L attribution panel: template anchor not found")
    TEMPLATE.write_text(template_text.replace(anchor, panel + anchor, 1), encoding="utf-8")
    print("[APPLY] V4 P&L attribution panel")
else:
    print("[SKIP] V4 P&L attribution panel already applied")

print("V4 P&L attribution patch complete.")
print("Read-only diagnostics only; frozen V4 rankings, paper portfolio state, journals, and brokerage settings are unchanged.")
