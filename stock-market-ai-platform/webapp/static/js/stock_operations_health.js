(() => {
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
  const fmtTs = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
  };
  const stateClass = status => {
    const s = String(status || '').toUpperCase();
    if (['HEALTHY','READY','RUNNING','LIVE','PASS','DATA_CONVERGED','END_TO_END_READY_VERIFIED'].includes(s)) return 'good';
    if (s.includes('VIOLATION') || ['ERROR','FAILED','FAIL'].includes(s)) return 'bad';
    return 'warn';
  };
  const layerCell = (name, layer) => `
    <div class="ops-cell">
      <div class="ops-label">${esc(name)}</div>
      <div class="ops-value ${layer?.complete_for_target ? 'good' : 'warn'}">${esc(layer?.symbols_at_target ?? 0)} / ${esc(layer?.symbols_expected ?? 101)}</div>
      <div class="ops-mini">at target session</div>
    </div>`;

  async function render() {
    try {
      const res = await fetch('/static/generated/stock_operations_health.json', {cache:'no-store'});
      if (!res.ok) return;
      const d = await res.json();
      const anchor = document.querySelector('.v4-dashboard') || document.querySelector('main') || document.body;
      if (!anchor || document.getElementById('stock-operations-health')) return;

      const layers = d.convergence?.layers || {};
      const gateOpen = Boolean(d.v8?.decision_gate_open);
      const decisionState = gateOpen ? 'READY TO RANK' : 'WAITING FOR COMPLETE EOD DATA';
      const decisionClass = gateOpen ? 'good' : 'warn';
      const latestConverged = d.features?.common_latest_utc || d.convergence?.common_latest_utc || null;
      const rankingTs = d.v8?.ranking_timestamp_utc || null;

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
          #stock-operations-health .ops-mini{font-size:10px;opacity:.6;margin-top:2px}
          #stock-operations-health .good{color:#86efac}.warn{color:#fde68a}.bad{color:#fca5a5}
          #stock-operations-health .ops-note{margin-top:12px;font-size:12px;opacity:.78;line-height:1.55}
          #stock-operations-health .ops-proof,#stock-operations-health .ops-decision{margin-top:16px;padding:14px;border-radius:12px;background:rgba(255,255,255,.035)}
          #stock-operations-health .ops-decision{border:1px solid rgba(255,255,255,.08)}
          #stock-operations-health .ops-state-title{font-size:15px;font-weight:800;margin-top:4px}
          #stock-operations-health .ops-separation{margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,.08);font-size:11px;line-height:1.55;opacity:.72}
        </style>
        <div class="label">PLATFORM OPERATIONS</div>
        <h2>Scheduler & Data Pipeline Health</h2>
        <div class="ops-grid">
          <div class="ops-cell"><div class="ops-label">Scheduler</div><div class="ops-value ${stateClass(d.scheduler?.status)}">${esc(d.scheduler?.status)}</div></div>
          <div class="ops-cell"><div class="ops-label">Last Exit</div><div class="ops-value">${esc(d.scheduler?.last_exit_code ?? '—')}</div></div>
          <div class="ops-cell"><div class="ops-label">Tiingo Budget</div><div class="ops-value">${esc(d.tiingo?.rolling_requests_used)} / ${esc(d.tiingo?.rolling_request_limit)}</div></div>
          <div class="ops-cell"><div class="ops-label">Target Session</div><div class="ops-value" style="font-size:14px">${esc(fmtTs(d.convergence?.target_session_utc))}</div></div>
          <div class="ops-cell"><div class="ops-label">Convergence</div><div class="ops-value ${stateClass(d.convergence?.status)}" style="font-size:14px">${esc(d.convergence?.status)}</div></div>
          <div class="ops-cell"><div class="ops-label">V8 Gate</div><div class="ops-value ${stateClass(d.v8?.guard_status)}">${esc(d.v8?.guard_status)}</div></div>
          <div class="ops-cell"><div class="ops-label">V10 Confirmation</div><div class="ops-value ${stateClass(d.v10?.status)}" style="font-size:14px">${esc(d.v10?.status)}</div></div>
          <div class="ops-cell"><div class="ops-label">Real Orders</div><div class="ops-value good">NO</div></div>
        </div>

        <div class="ops-decision">
          <div class="ops-label">CURRENT PRODUCTION DECISION STATE</div>
          <div class="ops-state-title ${decisionClass}">${esc(decisionState)}</div>
          <div class="ops-grid">
            <div class="ops-cell"><div class="ops-label">EOD Target Being Built</div><div class="ops-value" style="font-size:14px">${esc(fmtTs(d.convergence?.target_session_utc))}</div></div>
            <div class="ops-cell"><div class="ops-label">Latest Fully Converged Feature Session</div><div class="ops-value" style="font-size:14px">${esc(fmtTs(latestConverged))}</div></div>
            <div class="ops-cell"><div class="ops-label">Production Ranking Timestamp</div><div class="ops-value" style="font-size:14px">${esc(fmtTs(rankingTs))}</div><div class="ops-mini">blank while gate is closed</div></div>
            <div class="ops-cell"><div class="ops-label">Decision Gate</div><div class="ops-value ${decisionClass}">${gateOpen ? 'OPEN' : 'CLOSED'}</div></div>
          </div>
          <div class="ops-separation">
            The separate <strong>Frozen V8 development snapshot</strong> elsewhere on this dashboard is historical research/reference evidence. It is not the current production decision. This panel is the authoritative operational state for the EOD target currently being assembled.
          </div>
        </div>

        <div class="ops-proof">
          <div class="ops-label">EOD CONVERGENCE PROOF</div>
          <div class="ops-grid">
            ${layerCell('Bronze', layers.bronze)}
            ${layerCell('Silver', layers.silver)}
            ${layerCell('Gold', layers.gold)}
            ${layerCell('Features', layers.features)}
          </div>
          <div class="ops-note">
            Verification: <strong class="${stateClass(d.convergence?.verification)}">${esc(d.convergence?.verification)}</strong> ·
            V8 gate ${gateOpen ? 'OPEN' : 'CLOSED'} ·
            feature common latest ${esc(fmtTs(latestConverged))}.
          </div>
        </div>
        <div class="ops-note">
          Health snapshot: ${esc(fmtTs(d.generated_at_utc))} · error log ${esc(d.error_log?.bytes ?? 0)} bytes ·
          V10 decision ${esc(d.v10?.decision)} · monitoring is read-only.
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
