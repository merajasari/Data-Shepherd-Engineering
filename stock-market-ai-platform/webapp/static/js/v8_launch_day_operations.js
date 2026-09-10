(() => {
  if (window.location.pathname !== '/dashboard' || new URLSearchParams(location.search).get('view') === 'live') return;
  if (document.getElementById('v8-launch-day-operations')) return;

  const style = document.createElement('style');
  style.id = 'v8-launch-day-operations-style';
  style.textContent = `
    #v8-launch-day-operations{margin:0 0 22px;padding:20px 22px;border:1px solid rgba(57,227,161,.34);border-radius:20px;background:linear-gradient(145deg,rgba(7,30,38,.96),rgba(8,20,36,.98));box-shadow:0 15px 38px rgba(0,0,0,.2)}
    .v8ld-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}.v8ld-state{padding:8px 12px;border:1px solid rgba(57,227,161,.4);border-radius:999px;color:var(--green);font-size:.72rem;font-weight:950;letter-spacing:.08em}
    .v8ld-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-top:16px}.v8ld-item{padding:12px 13px;border:1px solid rgba(120,155,205,.15);border-radius:13px;background:rgba(8,20,36,.62);min-width:0}.v8ld-item span{display:block;color:var(--muted);font-size:.61rem;font-weight:900;letter-spacing:.07em}.v8ld-item strong{display:block;margin-top:5px;font-size:.84rem;line-height:1.3;overflow-wrap:anywhere}.v8ld-pass{color:var(--green)}.v8ld-warn{color:var(--gold)}.v8ld-fail{color:var(--red)}
    .v8ld-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:13px;color:var(--muted);font-size:.72rem;line-height:1.45}
    @media(max-width:1050px){.v8ld-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:650px){.v8ld-grid{grid-template-columns:1fr 1fr}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('section');
  card.id = 'v8-launch-day-operations';
  card.innerHTML = `
    <div class="v8ld-head"><div><div class="label">V8 FORWARD-HOLDOUT OPERATIONS</div><h2 style="margin-bottom:4px">Operational Control Panel</h2><div class="muted">Control health and data readiness only. This status is not a performance conclusion.</div></div><div class="v8ld-state" data-v8ld-state>CHECKING</div></div>
    <div class="v8ld-grid">
      <div class="v8ld-item"><span>FROZEN SHA</span><strong data-v8ld-sha>—</strong></div>
      <div class="v8ld-item"><span>SCHEDULER</span><strong data-v8ld-scheduler>—</strong></div>
      <div class="v8ld-item"><span>MARKET DATA GATE</span><strong data-v8ld-market>—</strong></div>
      <div class="v8ld-item"><span>JOURNAL</span><strong data-v8ld-journal>—</strong></div>
      <div class="v8ld-item"><span>LAST SUCCESSFUL ORCHESTRATION</span><strong data-v8ld-last>—</strong></div>
      <div class="v8ld-item"><span>NEXT EXPECTED DECISION</span><strong data-v8ld-next>—</strong></div>
      <div class="v8ld-item"><span>DECISIONS / ENTRIES / EXITS</span><strong data-v8ld-events>—</strong></div>
      <div class="v8ld-item"><span>ACTIVE ALERT</span><strong data-v8ld-alert>—</strong></div>
      <div class="v8ld-item"><span>BROKERAGE ORDERS</span><strong data-v8ld-orders>—</strong></div>
      <div class="v8ld-item"><span>WEB DATA PATH</span><strong data-v8ld-serving>—</strong></div>
    </div>
    <div class="v8ld-foot"><span data-v8ld-detail>Waiting for synchronized operational status…</span><span>Shared snapshot · refreshes every 30 seconds</span></div>`;

  const tabs = document.querySelector('.ds-dashboard-tabs');
  if (tabs) tabs.insertAdjacentElement('afterend', card);
  else document.querySelector('.shell header')?.insertAdjacentElement('afterend', card);

  const set = (name, text, cls='') => {
    const el = card.querySelector(`[data-v8ld-${name}]`);
    if (!el) return;
    el.textContent = text;
    el.className = cls;
  };
  const fmt = raw => {
    if (!raw) return 'NOT YET RECORDED';
    const dt = new Date(raw);
    return Number.isNaN(dt.getTime()) ? String(raw).replaceAll('_',' ') : dt.toLocaleString();
  };

  async function load() {
    try {
      const d = await window.DataShepherdV8Snapshot.get();
      const o = d.launch_operations || {};
      const failures = o.monitor_failures || [];
      const healthy = o.frozen_sha_verified && o.scheduler_healthy && o.market_data_current && o.journal_writable && o.journal_duplicate_safe && !failures.length;
      set('state', healthy ? 'OPERATIONS READY' : 'ATTENTION REQUIRED', healthy ? 'v8ld-state v8ld-pass' : 'v8ld-state v8ld-warn');
      set('sha', o.frozen_sha_verified ? 'VERIFIED' : 'FAILED', o.frozen_sha_verified ? 'v8ld-pass' : 'v8ld-fail');
      set('scheduler', o.scheduler_healthy ? 'RUNNING' : o.monitor_status || 'UNKNOWN', o.scheduler_healthy ? 'v8ld-pass' : 'v8ld-warn');
      set('market', o.market_data_current ? `READY THROUGH ${String(d.gold_common_latest_utc||'—').slice(0,10)}` : 'CHECK REQUIRED', o.market_data_current ? 'v8ld-pass' : 'v8ld-warn');
      set('journal', o.journal_writable && o.journal_duplicate_safe ? 'WRITABLE · DUPLICATE-SAFE' : 'CHECK REQUIRED', o.journal_writable && o.journal_duplicate_safe ? 'v8ld-pass' : 'v8ld-fail');
      set('last', fmt(o.last_successful_orchestration_utc));
      set('next', fmt(o.next_expected_decision));
      set('events', `${d.decisions||0} / ${d.entries||0} / ${d.completed_cohorts||0}`);
      set('alert', failures.length ? failures[0] : 'NONE', failures.length ? 'v8ld-fail' : 'v8ld-pass');
      set('orders', o.brokerage_orders ? 'ON' : 'OFF', o.brokerage_orders ? 'v8ld-fail' : 'v8ld-pass');
      set('serving', o.request_time_historical_parquet_load ? 'HEAVY LOAD DETECTED' : `LIGHTWEIGHT · ${o.response_cache_ttl_seconds||10}s CACHE`, o.request_time_historical_parquet_load ? 'v8ld-fail' : 'v8ld-pass');
      const sync = window.DataShepherdV8Snapshot.info();
      set('detail', `Monitor checked ${fmt(o.monitor_checked_at_utc)} · Browser synchronized ${fmt(sync.fetchedAtUtc)} · Holdout state: ${String(d.state||'UNKNOWN').replaceAll('_',' ')}`);
    } catch (error) {
      set('state','API UNAVAILABLE','v8ld-state v8ld-fail');
      set('detail',`Unable to load launch operations: ${error.message}`,'v8ld-fail');
    }
  }
  load();
  setInterval(load, 30000);
})();
