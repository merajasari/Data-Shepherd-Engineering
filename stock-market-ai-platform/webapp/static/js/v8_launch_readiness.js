(() => {
  const CHECKLIST_URL = '/static/generated/v8_launch_checklist.json';

  const labels = {
    frozen_contract: 'Frozen contract',
    sha_verified: 'Frozen SHA verified',
    universe_100_plus_spy: '100-stock universe + SPY',
    ranking_generation: 'Ranking generation',
    next_open_execution: 'Next-open execution',
    five_session_lifecycle: '5-session lifecycle',
    spy_benchmark: 'SPY benchmark',
    append_only_idempotency: 'Append-only / restart idempotency',
    missing_data_fail_closed: 'Missing-data fail closed',
    production_journal_isolation: 'Production journal isolation',
    production_status_isolation: 'Production status isolation',
    brokerage_orders_off: 'Brokerage orders OFF'
  };

  const utcDate = value => {
    if (!value) return '—';
    const d = new Date(value);
    if (!Number.isFinite(d.getTime())) return String(value);
    return d.toLocaleDateString(undefined, {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'});
  };

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  function findAnchor() {
    const cards = [...document.querySelectorAll('.v4-card, .v4-chart-card, section, article, div')];
    return cards.find(el => /V8 FORWARD \/ HOLDOUT OPERATIONS/i.test(el.textContent || '')) ||
           cards.find(el => /Frozen Strategy Readiness/i.test(el.textContent || ''));
  }

  function ensureCard() {
    let card = document.getElementById('v8-launch-readiness-card');
    if (card) return card;
    const anchor = findAnchor();
    if (!anchor) return null;
    card = document.createElement('section');
    card.id = 'v8-launch-readiness-card';
    card.className = 'v4-card';
    card.style.marginTop = '18px';
    card.innerHTML = '<div style="padding:22px"><div class="label">V8 HOLDOUT LAUNCH READINESS</div><h2 style="margin:6px 0 8px">Sep 1 Operational Checklist</h2><p style="margin:0;opacity:.74">Loading isolated end-to-end rehearsal results…</p></div>';
    anchor.insertAdjacentElement('afterend', card);
    return card;
  }

  async function render() {
    const card = ensureCard();
    if (!card) return false;
    try {
      const [checklistResp, holdout] = await Promise.all([
        fetch(CHECKLIST_URL, {cache:'no-store'}),
        window.DataShepherdV8Snapshot.get()
      ]);
      if (!checklistResp.ok) throw new Error(`checklist HTTP ${checklistResp.status}`);
      const checklist = await checklistResp.json();
      const keys = Object.keys(labels);
      const passes = keys.filter(k => checklist[k] === 'PASS').length;
      const status = checklist.status === 'READY' && passes === keys.length ? 'READY' : 'NOT READY';
      const good = status === 'READY';
      const chips = keys.map(k => {
        const pass = checklist[k] === 'PASS';
        return `<div style="display:flex;align-items:center;justify-content:space-between;gap:14px;padding:9px 11px;border:1px solid rgba(255,255,255,.09);border-radius:10px;background:rgba(255,255,255,.025)"><span>${esc(labels[k])}</span><strong style="color:${pass ? '#69e7aa' : '#ff8d8d'}">${pass ? '✓ PASS' : esc(checklist[k] || '—')}</strong></div>`;
      }).join('');
      card.innerHTML = `
        <div style="padding:22px">
          <div class="label">V8 HOLDOUT LAUNCH READINESS</div>
          <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:6px">
            <div><h2 style="margin:0 0 7px">Sep 1 Operational Checklist</h2><p style="margin:0;opacity:.74">Independent rehearsal of ranking → next-open entry → 5-session exit → SPY-relative evidence. Production holdout remains isolated.</p></div>
            <div style="font-size:24px;font-weight:800;color:${good ? '#69e7aa' : '#ff8d8d'}">${status}</div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:9px;margin-top:18px">${chips}</div>
          <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:16px;font-size:13px;opacity:.78">
            <span><strong>${passes}/${keys.length}</strong> checks passing</span>
            <span>Holdout start <strong>${utcDate(checklist.holdout_start_utc || holdout.holdout_start_utc)}</strong></span>
            <span>Production journal events <strong>${holdout.journal_event_count ?? 0}</strong></span>
            <span>Real orders <strong>NO</strong></span>
          </div>
        </div>`;
      return true;
    } catch (err) {
      card.innerHTML = `<div style="padding:22px"><div class="label">V8 HOLDOUT LAUNCH READINESS</div><h2 style="margin:6px 0 8px">Sep 1 Operational Checklist</h2><p style="margin:0;color:#ffb36b">Checklist artifact unavailable. Run the V8 holdout rehearsal sync before relying on launch readiness.</p></div>`;
      console.warn('V8 launch readiness card:', err);
      return true;
    }
  }

  let tries = 0;
  const boot = () => {
    render().then(ok => {
      if (!ok && tries++ < 20) setTimeout(boot, 400);
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
  setInterval(render, 60000);
})();
