(() => {
  const card = document.getElementById('stock-stream-health-card');
  if (!card) return;

  const original = {
    status: document.getElementById('stock-stream-health-status'),
    agent: document.getElementById('stock-stream-agent'),
    live: document.getElementById('stock-stream-live-count'),
    configured: document.getElementById('stock-stream-configured-count'),
    age: document.getElementById('stock-stream-cache-age'),
    session: document.getElementById('stock-stream-session'),
    detail: document.getElementById('stock-stream-health-detail')
  };

  const style = document.createElement('style');
  style.textContent = `
    #stock-stream-health-card{overflow:hidden;position:relative;border-color:rgba(54,216,255,.28);background:radial-gradient(circle at 92% 8%,rgba(54,216,255,.11),transparent 28%),linear-gradient(145deg,rgba(14,32,54,.98),rgba(7,18,33,.99))}
    #stock-stream-health-card:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#36d8ff,#39e3a1,#9b65ff);opacity:.9}
    .v8-stream-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;flex-wrap:wrap}.v8-stream-title{display:flex;gap:14px;align-items:center}.v8-stream-pulse{width:13px;height:13px;border-radius:50%;background:#39e3a1;box-shadow:0 0 0 0 rgba(57,227,161,.55);animation:v8Pulse 2s infinite}.v8-stream-pulse.closed{background:#efc56b;box-shadow:none;animation:none}.v8-stream-pulse.bad{background:#ff6680;box-shadow:none;animation:none}@keyframes v8Pulse{70%{box-shadow:0 0 0 12px rgba(57,227,161,0)}100%{box-shadow:0 0 0 0 rgba(57,227,161,0)}}
    .v8-stream-state{padding:9px 13px;border-radius:999px;border:1px solid rgba(57,227,161,.32);background:rgba(57,227,161,.08);font-size:.72rem;font-weight:950;letter-spacing:.08em;color:#39e3a1}.v8-stream-state.closed{color:#efc56b;border-color:rgba(239,197,107,.32);background:rgba(239,197,107,.08)}.v8-stream-state.bad{color:#ff6680;border-color:rgba(255,102,128,.35);background:rgba(255,102,128,.08)}
    .v8-stream-grid{display:grid;grid-template-columns:1.15fr 1fr 1fr;gap:14px;margin-top:20px}.v8-stream-panel{padding:18px;border:1px solid rgba(120,155,205,.15);border-radius:18px;background:rgba(8,20,36,.55)}.v8-stream-panel .k{color:#91a6c2;font-size:.66rem;font-weight:900;letter-spacing:.09em}.v8-stream-panel .v{font-size:1.5rem;font-weight:950;margin-top:6px}.v8-stream-progress{height:8px;border-radius:99px;background:#172943;overflow:hidden;margin-top:12px}.v8-stream-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#36d8ff,#39e3a1);transition:width .4s ease}.v8-stream-foot{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.v8-stream-mini{padding:12px 14px;border-radius:14px;border:1px solid rgba(120,155,205,.13);background:rgba(7,18,33,.55)}.v8-stream-mini span{display:block;color:#91a6c2;font-size:.62rem;font-weight:900;letter-spacing:.08em}.v8-stream-mini strong{display:block;margin-top:5px;font-size:.92rem}.v8-stream-note{margin-top:14px;padding:12px 14px;border-radius:14px;background:rgba(54,216,255,.045);border:1px solid rgba(54,216,255,.12);color:#91a6c2;font-size:.78rem;line-height:1.5}@media(max-width:900px){.v8-stream-grid{grid-template-columns:1fr}.v8-stream-foot{grid-template-columns:1fr 1fr}}@media(max-width:560px){.v8-stream-foot{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);

  card.innerHTML = `
    <div class="v8-stream-head">
      <div>
        <div class="label">V8 MARKET DATA PIPELINE</div>
        <div class="v8-stream-title"><span id="v8-stream-pulse" class="v8-stream-pulse"></span><h2 style="margin:6px 0">Real-Time Universe Health</h2></div>
        <div class="muted">Tiingo IEX read-only market-data coverage for the frozen V8 stock universe plus SPY benchmark. This is data-pipeline health, not an order-routing system.</div>
      </div>
      <div id="v8-stream-state" class="v8-stream-state">CHECKING</div>
    </div>
    <div class="v8-stream-grid">
      <div class="v8-stream-panel"><div class="k">UNIVERSE COVERAGE</div><div class="v"><span id="v8-stream-live">—</span> <span class="muted" style="font-size:.9rem">/ <span id="v8-stream-configured">—</span> symbols live</span></div><div class="v8-stream-progress"><i id="v8-stream-fill"></i></div><div class="muted" id="v8-stream-coverage-copy" style="margin-top:9px;font-size:.76rem">Checking symbol coverage…</div></div>
      <div class="v8-stream-panel"><div class="k">DATA FRESHNESS</div><div id="v8-stream-age" class="v">—</div><div class="muted" style="margin-top:6px;font-size:.76rem">Age of the latest quote cache. Freshness is judged in context of the U.S. market session.</div></div>
      <div class="v8-stream-panel"><div class="k">MARKET SESSION</div><div id="v8-stream-session" class="v">—</div><div class="muted" style="margin-top:6px;font-size:.76rem">When the market is closed, zero advancing live symbols is expected and should not look like a failure.</div></div>
    </div>
    <div class="v8-stream-foot">
      <div class="v8-stream-mini"><span>STREAM SERVICE</span><strong id="v8-stream-agent">—</strong></div>
      <div class="v8-stream-mini"><span>DATA PROVIDER</span><strong>TIINGO IEX</strong></div>
      <div class="v8-stream-mini"><span>SPY ROLE</span><strong>BENCHMARK</strong></div>
      <div class="v8-stream-mini"><span>REAL ORDERS</span><strong class="positive">NO</strong></div>
    </div>
    <div id="v8-stream-detail" class="v8-stream-note">Checking V8 market-data pipeline…</div>`;

  const text = el => el?.textContent?.trim() || '—';
  const render = () => {
    const status = text(original.status);
    const agent = text(original.agent);
    const liveText = text(original.live);
    const configuredText = text(original.configured);
    const age = text(original.age);
    const session = text(original.session);
    const detail = text(original.detail);
    const live = Number(liveText);
    const configured = Number(configuredText);
    const pct = Number.isFinite(live) && Number.isFinite(configured) && configured > 0 ? Math.max(0,Math.min(100,live/configured*100)) : 0;
    const closed = /CLOSED|AFTER_HOURS/i.test(`${status} ${session}`);
    const bad = /STALE|ERROR|DOWN|DISCONNECTED|FAILED/i.test(status) && !closed;

    card.querySelector('#v8-stream-state').textContent = closed ? 'MARKET CLOSED · FEED CONNECTED' : status.replaceAll('_',' ');
    card.querySelector('#v8-stream-state').className = `v8-stream-state${closed?' closed':bad?' bad':''}`;
    card.querySelector('#v8-stream-pulse').className = `v8-stream-pulse${closed?' closed':bad?' bad':''}`;
    card.querySelector('#v8-stream-live').textContent = liveText;
    card.querySelector('#v8-stream-configured').textContent = configuredText;
    card.querySelector('#v8-stream-fill').style.width = `${pct}%`;
    card.querySelector('#v8-stream-age').textContent = age;
    card.querySelector('#v8-stream-session').textContent = session;
    card.querySelector('#v8-stream-agent').textContent = agent;
    card.querySelector('#v8-stream-detail').textContent = detail;
    card.querySelector('#v8-stream-coverage-copy').textContent = closed ? `Market closed — ${configuredText} symbols remain configured; live quote advancement resumes with the regular session.` : `${pct.toFixed(1)}% of configured V8 + SPY symbols currently represented by the live feed.`;
  };

  // Existing stream-health code continues updating the detached original nodes.
  // Mirror those values into the redesigned V8 presentation without changing the API.
  render();
  const observer = new MutationObserver(render);
  Object.values(original).filter(Boolean).forEach(node => observer.observe(node,{childList:true,subtree:true,characterData:true}));
  setInterval(render,5000);
})();