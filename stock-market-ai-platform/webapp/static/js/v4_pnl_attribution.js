(() => {
  const root = document.getElementById('v4-pnl-attribution');
  if (!root) return;

  const style = document.createElement('style');
  style.textContent = `
    .v4-pnl-attribution{margin-top:20px;border:1px solid var(--border);border-radius:18px;background:rgba(8,20,36,.58);padding:20px}
    .v4-pnl-attribution-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;flex-wrap:wrap}
    .v4-pnl-attribution-head h3{margin:5px 0 0}.v4-pnl-total{font-size:1.45rem;font-weight:950}
    .v4-pnl-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-top:16px}
    .v4-pnl-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);gap:18px;margin-top:18px}
    .v4-pnl-panel{border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.5);padding:15px}
    .v4-pnl-row{display:grid;grid-template-columns:74px 1fr 110px 110px;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid rgba(120,155,205,.10)}
    .v4-pnl-row:last-child{border-bottom:0}.v4-pnl-symbol{font-weight:950}.v4-pnl-bar{height:8px;background:#172943;border-radius:99px;overflow:hidden;position:relative}
    .v4-pnl-bar > span{position:absolute;inset:0 auto 0 50%;width:0;border-radius:99px}.v4-pnl-bar > span.pos{background:var(--green)}.v4-pnl-bar > span.neg{background:var(--red)}
    .v4-pnl-number{text-align:right;font-weight:900}.v4-pnl-sub{font-size:.75rem;color:var(--muted);margin-top:3px}.v4-pnl-note{margin-top:12px;font-size:.78rem;color:var(--muted);line-height:1.45}
    @media(max-width:1000px){.v4-pnl-metrics{grid-template-columns:repeat(2,1fr)}.v4-pnl-grid{grid-template-columns:1fr}}
    @media(max-width:650px){.v4-pnl-metrics{grid-template-columns:1fr}.v4-pnl-row{grid-template-columns:64px 1fr 92px}.v4-pnl-row .v4-pnl-market{display:none}}
  `;
  document.head.appendChild(style);

  const money = v => {
    const n = Number(v || 0);
    return `${n >= 0 ? '+' : '-'}$${Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  };
  const cls = v => Number(v) >= 0 ? 'positive' : 'negative';
  const set = (id, value, valueClass) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    if (valueClass) el.className = valueClass;
  };

  function render(payload) {
    const p = payload?.portfolio?.pnl_attribution;
    if (!p) return;

    set('v4-pnl-total', money(p.total_pnl), cls(p.total_pnl));
    set('v4-pnl-core', money(p.core_net_pnl), cls(p.core_net_pnl));
    set('v4-pnl-sleeve', money(p.v4_net_pnl), cls(p.v4_net_pnl));
    set('v4-pnl-realized', money(p.realized_pnl), cls(p.realized_pnl));
    set('v4-pnl-friction', money(-Math.abs(Number(p.total_friction || 0))), 'negative');
    set('v4-pnl-market', money(p.open_position_market_move), cls(p.open_position_market_move));

    const rows = Array.isArray(p.positions) ? p.positions : [];
    const maxAbs = Math.max(1, ...rows.map(r => Math.abs(Number(r.net_pnl || 0))));
    const list = document.getElementById('v4-pnl-positions');
    if (list) {
      list.innerHTML = rows.map(r => {
        const net = Number(r.net_pnl || 0);
        const pct = Math.min(50, 50 * Math.abs(net) / maxAbs);
        const left = net >= 0 ? 50 : 50 - pct;
        return `<div class="v4-pnl-row">
          <div><div class="v4-pnl-symbol">${r.symbol}</div><div class="v4-pnl-sub">${String(r.sleeve || '').toUpperCase()}</div></div>
          <div class="v4-pnl-bar"><span class="${net >= 0 ? 'pos' : 'neg'}" style="left:${left}%;width:${pct}%"></span></div>
          <div class="v4-pnl-number v4-pnl-market ${cls(r.market_move)}">${money(r.market_move)}</div>
          <div class="v4-pnl-number ${cls(net)}">${money(net)}</div>
        </div>`;
      }).join('') || '<div class="muted">No open positions.</div>';
    }

    const best = p.best_contributor;
    const worst = p.worst_contributor;
    set('v4-pnl-best', best ? `${best.symbol} ${money(best.net_pnl)}` : '—', best ? cls(best.net_pnl) : '');
    set('v4-pnl-worst', worst ? `${worst.symbol} ${money(worst.net_pnl)}` : '—', worst ? cls(worst.net_pnl) : '');
    set('v4-pnl-switch-cost', money(-Math.abs(Number(p.realized_rebalance_cost || 0))), Number(p.realized_rebalance_cost || 0) ? 'negative' : '');
  }

  async function load() {
    const r = await fetch(`/api/v4-forward?t=${Date.now()}`, {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    render(await r.json());
  }

  window.renderV4PnlAttribution = render;
  const start = () => load().catch(e => console.error('V4 P&L attribution:', e));
  if ('requestIdleCallback' in window) requestIdleCallback(start, {timeout:1000}); else setTimeout(start, 150);
})();
