(() => {
  const STATUS_URL = '/static/generated/v10_confirmation_status.json';
  const CONTRACT_URL = '/static/generated/v10_confirmation_contract.json';
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

  async function render() {
    const card = ensureCard();
    if (!card) return false;
    try {
      const [sr, cr] = await Promise.all([
        fetch(STATUS_URL,{cache:'no-store'}),
        fetch(CONTRACT_URL,{cache:'no-store'})
      ]);
      if (!sr.ok || !cr.ok) throw new Error(`status ${sr.status}, contract ${cr.status}`);
      const s = await sr.json();
      const c = await cr.json();
      const state = s.status || 'UNKNOWN';
      const pending = (s.decision || 'PENDING') === 'PENDING';
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
