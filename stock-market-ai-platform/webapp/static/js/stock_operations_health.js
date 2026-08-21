(() => {
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
  const fmtTs = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
  };
  const stateClass = status => {
    const s = String(status || '').toUpperCase();
    if (['HEALTHY','READY','RUNNING','LIVE','PASS'].includes(s)) return 'good';
    if (['ERROR','FAILED','FAIL'].includes(s)) return 'bad';
    return 'warn';
  };

  async function render() {
    try {
      const res = await fetch('/static/generated/stock_operations_health.json', {cache:'no-store'});
      if (!res.ok) return;
      const d = await res.json();
      const anchor = document.querySelector('.v4-dashboard') || document.querySelector('main') || document.body;
      if (!anchor || document.getElementById('stock-operations-health')) return;

      const card = document.createElement('section');
      card.id = 'stock-operations-health';
      card.className = 'v4-card ops-health-card';
      card.innerHTML = `
        <style>
          #stock-operations-health{margin:18px 0;padding:20px;border:1px solid rgba(255,255,255,.12);border-radius:16px;background:rgba(15,23,42,.72)}
          #stock-operations-health .ops-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:14px}
          #stock-operations-health .ops-cell{padding:12px;border-radius:12px;background:rgba(255,255,255,.045)}
          #stock-operations-health .ops-label{font-size:11px;letter-spacing:.08em;opacity:.7;text-transform:uppercase}
          #stock-operations-health .ops-value{font-size:18px;font-weight:700;margin-top:4px}
          #stock-operations-health .good{color:#86efac}.warn{color:#fde68a}.bad{color:#fca5a5}
          #stock-operations-health .ops-note{margin-top:12px;font-size:12px;opacity:.75;line-height:1.5}
        </style>
        <div class="label">PLATFORM OPERATIONS</div>
        <h2>Scheduler & Data Pipeline Health</h2>
        <div class="ops-grid">
          <div class="ops-cell"><div class="ops-label">Scheduler</div><div class="ops-value ${stateClass(d.scheduler?.status)}">${esc(d.scheduler?.status)}</div></div>
          <div class="ops-cell"><div class="ops-label">Last Exit</div><div class="ops-value">${esc(d.scheduler?.last_exit_code ?? '—')}</div></div>
          <div class="ops-cell"><div class="ops-label">Tiingo Budget</div><div class="ops-value">${esc(d.tiingo?.rolling_requests_used)} / ${esc(d.tiingo?.rolling_request_limit)}</div></div>
          <div class="ops-cell"><div class="ops-label">Features</div><div class="ops-value">${esc(d.features?.files_found)} / ${esc(d.features?.expected_files)}</div></div>
          <div class="ops-cell"><div class="ops-label">Feature Common Latest</div><div class="ops-value" style="font-size:14px">${esc(fmtTs(d.features?.common_latest_utc))}</div></div>
          <div class="ops-cell"><div class="ops-label">V8 Gate</div><div class="ops-value ${stateClass(d.v8?.guard_status)}">${esc(d.v8?.guard_status)}</div></div>
          <div class="ops-cell"><div class="ops-label">V10 Confirmation</div><div class="ops-value ${stateClass(d.v10?.status)}" style="font-size:14px">${esc(d.v10?.status)}</div></div>
          <div class="ops-cell"><div class="ops-label">Real Orders</div><div class="ops-value good">NO</div></div>
        </div>
        <div class="ops-note">
          Health snapshot: ${esc(fmtTs(d.generated_at_utc))} · error log ${esc(d.error_log?.bytes ?? 0)} bytes ·
          V10 decision ${esc(d.v10?.decision)} · safety publisher is read-only.
        </div>`;

      const firstCard = anchor.querySelector('.v4-card');
      if (firstCard) firstCard.parentNode.insertBefore(card, firstCard);
      else anchor.prepend(card);
    } catch (err) {
      console.error('Unable to load stock operations health.', err);
    }
  }

  render();
})();
