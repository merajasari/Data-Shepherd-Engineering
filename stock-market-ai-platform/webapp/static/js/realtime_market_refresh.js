(() => {
  const REFRESH_MS = 2000;
  let timer = null;
  let inFlight = false;

  const money = value => {
    const n = Number(value);
    return Number.isFinite(n) ? `$${n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:8})}` : '—';
  };

  function renderStockHealth(h) {
    const status = document.getElementById('stock-stream-health-status');
    if (!status) return;
    status.textContent = h.status || 'UNKNOWN';
    status.style.color = h.status === 'LIVE' ? 'var(--green)' : (h.status === 'ERROR' || h.status === 'STALE' ? 'var(--red)' : 'var(--gold)');
    const set = (id, value) => { const el=document.getElementById(id); if (el) el.textContent=value; };
    set('stock-stream-agent', h.launchagent_running ? 'RUNNING' : 'NOT RUNNING');
    set('stock-stream-live-count', String(h.live_symbol_count ?? 0));
    set('stock-stream-configured-count', String(h.configured_symbol_count ?? 0));
    set('stock-stream-cache-age', h.cache_age_seconds == null ? '—' : `${Math.max(0,h.cache_age_seconds).toFixed(1)}s`);
    set('stock-stream-session', h.regular_session_expected_open ? 'REGULAR OPEN' : 'CLOSED');
    set('stock-stream-health-detail', h.detail || '');
  }

  async function refreshStockHealth() {
    if (location.pathname !== '/dashboard') return;
    const health = await fetch(`/api/stock-stream-health?t=${Date.now()}`, {cache:'no-store'}).then(r => r.json());
    renderStockHealth(health);
  }

  async function refreshStocks() {
    if (location.pathname !== '/dashboard') return;
    const all = await fetch(`/api/live?t=${Date.now()}`, {cache:'no-store'}).then(r => r.json());
    const quotes = all.quotes || {};
    const selected = new URLSearchParams(location.search).get('symbol') || 'AAPL';
    const q = quotes[selected.toUpperCase()];
    const main = document.querySelector('.price-block .price');
    if (main && q && q.reference_price != null) {
      const old = main.textContent;
      const next = money(q.reference_price);
      main.textContent = next;
      if (old !== next) { main.style.transform='scale(1.025)'; setTimeout(()=>main.style.transform='scale(1)',140); }
    }
    document.querySelectorAll('[data-live-price-symbol]').forEach(cell => {
      const quote = quotes[cell.dataset.livePriceSymbol];
      if (quote && quote.reference_price != null) {
        cell.textContent = money(quote.reference_price);
        cell.title = `LIVE IEX · ${quote.received_at || ''}`;
        cell.style.color = 'var(--green)';
      }
    });
    if (typeof window.loadV4 === 'function') window.loadV4();
  }

  function renderCrypto(payload) {
    const root = document.getElementById('crypto-live-ticker-grid');
    const stamp = document.getElementById('crypto-live-ticker-stamp');
    if (!root) return;
    const quotes = Object.values(payload.quotes || {}).sort((a,b)=>a.product_id.localeCompare(b.product_id));
    if (stamp) stamp.textContent = payload.updated_at ? `LIVE CACHE · ${payload.updated_at}` : 'WAITING FOR LIVE TICKS';
    root.innerHTML = quotes.length ? quotes.map(q => {
      const p = Number(q.price_percent_chg_24_h);
      const cls = Number.isFinite(p) ? (p >= 0 ? 'positive' : 'negative') : '';
      const pct = Number.isFinite(p) ? `${p>=0?'+':''}${p.toFixed(2)}%` : '—';
      return `<div class="metric"><span>${q.product_id}</span><strong>${money(q.price)}</strong><div class="${cls}" style="margin-top:5px;font-weight:800">24H ${pct}</div></div>`;
    }).join('') : '<div class="warning">Waiting for Coinbase real-time ticker data…</div>';
  }

  async function refreshCrypto() {
    if (location.pathname !== '/crypto') return;
    const payload = await fetch(`/api/crypto-live?t=${Date.now()}`, {cache:'no-store'}).then(r => r.json());
    renderCrypto(payload);
  }

  async function tick() {
    if (inFlight || document.visibilityState !== 'visible') return;
    inFlight = true;
    try { await Promise.allSettled([refreshStocks(), refreshStockHealth(), refreshCrypto()]); }
    finally { inFlight = false; }
  }

  function start() { if (timer) clearInterval(timer); tick(); timer=setInterval(tick, REFRESH_MS); }
  document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' ? start() : clearInterval(timer));
  document.addEventListener('DOMContentLoaded', () => requestAnimationFrame(() => requestAnimationFrame(start)));
})();
