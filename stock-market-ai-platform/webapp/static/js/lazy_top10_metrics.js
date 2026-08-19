(() => {
  const cards = Array.from(document.querySelectorAll('.card'));
  const card = cards.find(x => /Top 10 Cross-Sectional Rankings/i.test(x.textContent || ''));
  const table = card?.querySelector('table');
  if (!table) return;

  const money = v => Number.isFinite(Number(v)) ? `$${Number(v).toFixed(2)}` : '—';
  const pct = v => Number.isFinite(Number(v)) ? `${Number(v) >= 0 ? '+' : ''}${(Number(v) * 100).toFixed(2)}%` : '—';

  async function load() {
    try {
      const r = await fetch('/api/v8-top10-details', {credentials:'same-origin', cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const rows = new Map((data.rows || []).map(x => [String(x.symbol), x]));
      for (const tr of table.tBodies[0]?.rows || []) {
        const symbol = tr.cells[0]?.textContent?.trim();
        const row = rows.get(symbol);
        if (!row) continue;
        tr.cells[1].textContent = money(row.display_price);
        tr.cells[2].textContent = pct(row.eod_change_pct);
        tr.cells[2].className = Number(row.eod_change_pct) < 0 ? 'negative' : 'positive';
        tr.cells[7].textContent = Number.isFinite(Number(row.rsi_14)) ? Number(row.rsi_14).toFixed(1) : '—';
      }
    } catch (err) {
      console.warn('[V8 lazy Top10]', err);
    }
  }

  for (const tr of table.tBodies[0]?.rows || []) {
    if (tr.cells[1]) tr.cells[1].textContent = '…';
    if (tr.cells[2]) tr.cells[2].textContent = '…';
    if (tr.cells[7]) tr.cells[7].textContent = '…';
  }
  if ('requestIdleCallback' in window) requestIdleCallback(load, {timeout:800});
  else setTimeout(load, 100);
})();
