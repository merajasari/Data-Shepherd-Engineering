(() => {
  const STATUS_URL = '/static/generated/v10_confirmation_status.json';
  const CONTRACT_URL = '/static/generated/v10_confirmation_contract.json';
  const HISTORY_URL = '/static/generated/v10_confirmation_history.json';
  const esc = v => String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const fmt = v => Number.isFinite(Number(v)) ? (Number(v) >= 0 ? '+' : '') + (Number(v) * 100).toFixed(3) + '%' : '—';
  const shortSha = v => v ? String(v).slice(0,12) + '…' : '—';
  const utcDate = v => {
    if (!v) return '—';
    const d = new Date(v);
    return Number.isFinite(d.getTime()) ? d.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}) : String(v);
  };

  function anchor() {
    return document.getElementById('v8-launch-readiness-card') ||
      [...document.querySelectorAll('section,article,div')].find(el => /V8 FORWARD \/ HOLDOUT OPERATIONS/i.test(el.textContent || '')) ||
      [...document.querySelectorAll('section,article,div')].find(el => /Frozen Strategy Readiness/i.test(el.textContent || ''));
  }

  function ensureCard() {
    let card = document.getElementById('v10-confirmation-card');
    if (card) return card;
    const a = anchor();
    if (!a) return null;
    card = document.createElement('section');
    card.id = 'v10-confirmation-card';
    card.className = 'v4-card';
    card.style.marginTop = '18px';
    card.innerHTML = '<div style="padding:22px"><div class="label">V10 PROSPECTIVE CONFIRMATION</div><h2 style="margin:6px 0 8px">Locked Challenger vs V8</h2><p style="margin:0;opacity:.74">Loading confirmation contract and status…</p></div>';
    a.insertAdjacentElement('afterend', card);
    return card;
  }

  function historyMarkup(payload) {
    const rows = Array.isArray(payload?.history) ? payload.history : [];
    if (!rows.length) {
      return `<div style="margin-top:18px;padding:16px;border:1px solid rgba(255,255,255,.09);border-radius:12px;background:rgba(255,255,255,.02)">
        <div style="font-size:12px;letter-spacing:.08em;font-weight:800;opacity:.72">CONFIRMATION PROGRESS HISTORY</div>
        <div style="margin-top:8px;opacity:.65">No completed confirmation exits yet. The history will begin automatically after Aug 24 decisions complete their 5-session holding periods.</div>
      </div>`;
    }

    const series = [
      ['overall_mean_delta_net_relative_return_vs_v8','Overall Δ'],
      ['negative_spy_mean_delta_net_relative_return_vs_v8','Negative-SPY Δ'],
      ['positive_spy_mean_delta_net_relative_return_vs_v8','Positive-SPY Δ']
    ];
    const values = rows.flatMap(r => series.map(([k]) => Number(r[k])).filter(Number.isFinite));
    const min = Math.min(0, ...values);
    const max = Math.max(0, ...values);
    const span = Math.max(max - min, 0.0001);
    const W = 640, H = 170, L = 42, R = 12, T = 12, B = 30;
    const x = i => L + (rows.length === 1 ? (W-L-R)/2 : i * (W-L-R)/(rows.length-1));
    const y = v => T + (max - v) * (H-T-B) / span;
    const pathFor = key => rows.map((r,i) => {
      const v = Number(r[key]);
      return Number.isFinite(v) ? `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}` : '';
    }).filter(Boolean).join(' ');
    const zeroY = y(0).toFixed(1);
    const firstDate = utcDate(rows[0].as_of_exit_timestamp_utc);
    const lastDate = utcDate(rows[rows.length-1].as_of_exit_timestamp_utc);
    const latest = rows[rows.length-1];
    const colors = ['#69e7aa','#efc56b','#7db7ff'];

    return `<div style="margin-top:18px;padding:16px;border:1px solid rgba(255,255,255,.09);border-radius:12px;background:rgba(255,255,255,.02)">
      <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:end">
        <div><div style="font-size:12px;letter-spacing:.08em;font-weight:800;opacity:.72">CONFIRMATION PROGRESS HISTORY</div><div style="font-size:13px;opacity:.62;margin-top:4px">Cumulative matched completed periods only; development data and the Nov 2 formal holdout are excluded.</div></div>
        <div style="font-size:12px;opacity:.72">${rows.length} history point${rows.length === 1 ? '' : 's'} · ${Number(latest.matched_periods || 0)} matched periods</div>
      </div>
      <div style="overflow-x:auto;margin-top:12px">
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:520px;height:190px;display:block" role="img" aria-label="V10 confirmation cumulative delta history">
          <line x1="${L}" y1="${zeroY}" x2="${W-R}" y2="${zeroY}" stroke="rgba(255,255,255,.22)" stroke-dasharray="4 4" />
          ${series.map(([key],idx) => { const p = pathFor(key); return p ? `<path d="${p}" fill="none" stroke="${colors[idx]}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />` : ''; }).join('')}
          <text x="${L}" y="${H-8}" fill="currentColor" opacity=".55" font-size="11">${esc(firstDate)}</text>
          <text x="${W-R}" y="${H-8}" text-anchor="end" fill="currentColor" opacity=".55" font-size="11">${esc(lastDate)}</text>
          <text x="${L-6}" y="${Number(zeroY)-4}" text-anchor="end" fill="currentColor" opacity=".5" font-size="10">0%</text>
        </svg>
      </div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px;margin-top:-6px">
        ${series.map(([,label],idx) => `<span><span style="display:inline-block;width:18px;border-top:2px solid ${colors[idx]};vertical-align:middle;margin-right:6px"></span>${label}</span>`).join('')}
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:14px;font-size:12px">
        <div>Latest overall <strong>${fmt(latest.overall_mean_delta_net_relative_return_vs_v8)}</strong></div>
        <div>Latest negative <strong>${fmt(latest.negative_spy_mean_delta_net_relative_return_vs_v8)}</strong></div>
        <div>Latest positive <strong>${fmt(latest.positive_spy_mean_delta_net_relative_return_vs_v8)}</strong></div>
      </div>
    </div>`;
  }

  async function render() {
    const card = ensureCard();
    if (!card) return false;
    try {
      const [sr, cr, hr] = await Promise.all([
        fetch(STATUS_URL,{cache:'no-store'}),
        fetch(CONTRACT_URL,{cache:'no-store'}),
        fetch(HISTORY_URL,{cache:'no-store'}).catch(() => null)
      ]);
      if (!sr.ok || !cr.ok) throw new Error(`status ${sr.status}, contract ${cr.status}`);
      const s = await sr.json();
      const c = await cr.json();
      const h = hr && hr.ok ? await hr.json() : {history:[]};
      const state = s.status || 'UNKNOWN';
      const color = state === 'COMPLETE' && s.decision === 'PASS' ? '#69e7aa' : (state === 'COMPLETE' && s.decision === 'FAIL' ? '#ff8d8d' : '#efc56b');
      const matched = s.matched_periods ?? s.completed_candidate_periods ?? 0;
      const neg = s.negative_regime_periods ?? 0;
      const pos = s.positive_regime_periods ?? 0;
      card.innerHTML = `
        <div style="padding:22px">
          <div class="label">V10 PROSPECTIVE CONFIRMATION</div>
          <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:6px">
            <div><h2 style="margin:0 0 7px">Locked Challenger vs Frozen V8</h2><p style="margin:0;opacity:.74">Prospective evidence only. The Nov 2 formal V10 holdout remains untouched.</p></div>
            <div style="font-size:22px;font-weight:850;color:${color}">${esc(state.replaceAll('_',' '))}</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:18px">
            <div class="metric"><span>DECISION</span><strong>${esc(s.decision || 'PENDING')}</strong></div>
            <div class="metric"><span>MATCHED PERIODS</span><strong>${matched}</strong></div>
            <div class="metric"><span>NEGATIVE PERIODS</span><strong>${neg}</strong></div>
            <div class="metric"><span>POSITIVE PERIODS</span><strong>${pos}</strong></div>
            <div class="metric"><span>OVERALL Δ VS V8</span><strong>${fmt(s.overall_mean_delta_net_relative_return_vs_v8)}</strong></div>
            <div class="metric"><span>NEGATIVE-SPY Δ</span><strong>${fmt(s.negative_spy_mean_delta_net_relative_return_vs_v8)}</strong></div>
            <div class="metric"><span>POSITIVE-SPY Δ</span><strong>${fmt(s.positive_spy_mean_delta_net_relative_return_vs_v8)}</strong></div>
          </div>
          ${historyMarkup(h)}
          <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:16px;font-size:13px;opacity:.8">
            <span>Confirmation start <strong>${utcDate(c.confirmation_start_utc)}</strong></span>
            <span>Formal holdout <strong>${utcDate(c.formal_holdout_start_utc)}</strong></span>
            <span>Contract <strong>${shortSha(c.contract_sha256)}</strong></span>
            <span>Orders <strong>NO</strong></span>
          </div>
          <div style="margin-top:12px;font-size:13px;opacity:.72">Rule locked: ${esc(c.switch_rule || '')}</div>
        </div>`;
      return true;
    } catch (err) {
      card.innerHTML = '<div style="padding:22px"><div class="label">V10 PROSPECTIVE CONFIRMATION</div><h2 style="margin:6px 0 8px">Locked Challenger vs V8</h2><p style="margin:0;color:#ffb36b">Confirmation artifact unavailable. The scheduler will publish it after the next confirmation cycle.</p></div>';
      console.warn('V10 confirmation dashboard:', err);
      return true;
    }
  }

  let tries = 0;
  const boot = () => render().then(ok => { if (!ok && tries++ < 20) setTimeout(boot,400); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true}); else boot();
  setInterval(render, 60000);
})();
