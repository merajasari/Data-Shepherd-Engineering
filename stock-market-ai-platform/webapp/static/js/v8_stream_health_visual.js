(() => {
  const card = document.getElementById('stock-stream-health-card');
  if (!card) return;

  const original = {
    status: document.getElementById('stock-stream-health-status'), agent: document.getElementById('stock-stream-agent'),
    live: document.getElementById('stock-stream-live-count'), configured: document.getElementById('stock-stream-configured-count'),
    age: document.getElementById('stock-stream-cache-age'), session: document.getElementById('stock-stream-session'),
    detail: document.getElementById('stock-stream-health-detail')
  };
  const text = el => el?.textContent?.trim() || '—';
  let lastUiRefresh = null;
  let refreshCount = 0;

  const style = document.createElement('style');
  style.textContent = `
    #stock-stream-health-card{overflow:hidden;position:relative;border-color:rgba(54,216,255,.28);background:radial-gradient(circle at 92% 8%,rgba(54,216,255,.11),transparent 28%),linear-gradient(145deg,rgba(14,32,54,.98),rgba(7,18,33,.99))}#stock-stream-health-card:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,#36d8ff,#39e3a1,#9b65ff)}
    .v8-stream-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;flex-wrap:wrap}.v8-stream-title{display:flex;gap:14px;align-items:center}.v8-stream-pulse{width:13px;height:13px;border-radius:50%;background:#39e3a1;box-shadow:0 0 0 0 rgba(57,227,161,.55);animation:v8Pulse 2s infinite}.v8-stream-pulse.closed{background:#efc56b;box-shadow:none;animation:none}.v8-stream-pulse.bad{background:#ff6680;box-shadow:none;animation:none}@keyframes v8Pulse{70%{box-shadow:0 0 0 12px rgba(57,227,161,0)}100%{box-shadow:0 0 0 0 rgba(57,227,161,0)}}
    .v8-stream-state{padding:9px 13px;border-radius:999px;border:1px solid rgba(57,227,161,.32);background:rgba(57,227,161,.08);font-size:.72rem;font-weight:950;letter-spacing:.08em;color:#39e3a1}.v8-stream-state.closed{color:#efc56b;border-color:rgba(239,197,107,.32);background:rgba(239,197,107,.08)}.v8-stream-state.bad{color:#ff6680;border-color:rgba(255,102,128,.35);background:rgba(255,102,128,.08)}
    .v8-stream-grid{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:14px;margin-top:20px}.v8-stream-panel{padding:18px;border:1px solid rgba(120,155,205,.15);border-radius:18px;background:rgba(8,20,36,.55)}.v8-stream-panel .k,.v8-stream-mini span{color:#91a6c2;font-size:.66rem;font-weight:900;letter-spacing:.09em}.v8-stream-panel .v{font-size:1.5rem;font-weight:950;margin-top:6px}.v8-stream-progress{height:8px;border-radius:99px;background:#172943;overflow:hidden;margin-top:12px}.v8-stream-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#36d8ff,#39e3a1);transition:width .4s ease}
    .v8-stream-foot{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.v8-stream-mini{padding:12px 14px;border-radius:14px;border:1px solid rgba(120,155,205,.13);background:rgba(7,18,33,.55)}.v8-stream-mini strong{display:block;margin-top:5px;font-size:.98rem}.v8-stream-liveclock{font-variant-numeric:tabular-nums}.v8-stream-note{margin-top:14px;padding:12px 14px;border-radius:14px;background:rgba(54,216,255,.045);border:1px solid rgba(54,216,255,.12);color:#91a6c2;font-size:.78rem;line-height:1.5}
    @media(max-width:900px){.v8-stream-grid{grid-template-columns:1fr}.v8-stream-foot{grid-template-columns:1fr 1fr}}@media(max-width:560px){.v8-stream-foot{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);

  card.innerHTML = `
    <div class="v8-stream-head"><div><div class="label">V8 LIVE DATA MONITOR</div><div class="v8-stream-title"><span id="v8-stream-pulse" class="v8-stream-pulse"></span><h2 style="margin:6px 0">Market Data Heartbeat</h2></div><div class="muted">Is the V8 market-data pipeline alive, current, and ready to supply the frozen model universe?</div></div><div id="v8-stream-state" class="v8-stream-state">CHECKING</div></div>
    <div class="v8-stream-grid">
      <div class="v8-stream-panel"><div class="k">LAST DATA UPDATE</div><div id="v8-stream-last-data" class="v v8-stream-liveclock">—</div><div id="v8-stream-data-ago" class="muted" style="margin-top:6px;font-size:.76rem">Waiting for freshness telemetry…</div></div>
      <div class="v8-stream-panel"><div class="k">LIVE REFRESH CHECKER</div><div id="v8-stream-last-refresh" class="v v8-stream-liveclock">—</div><div class="muted" style="margin-top:6px;font-size:.76rem"><span id="v8-stream-refresh-ago">Waiting…</span> · <span id="v8-stream-refresh-count">0</span> checks observed</div></div>
      <div class="v8-stream-panel"><div class="k">CURRENT MARKET TIME</div><div id="v8-stream-clock" class="v v8-stream-liveclock">—</div><div class="muted" style="margin-top:6px;font-size:.76rem"><span id="v8-stream-date">—</span> · Pacific Time · Session: <strong id="v8-stream-session" style="color:#f2f6ff">—</strong></div></div>
    </div>
    <div class="v8-stream-foot">
      <div class="v8-stream-mini"><span>V8 + SPY COVERAGE</span><strong><span id="v8-stream-live">—</span> / <span id="v8-stream-configured">—</span></strong><div class="v8-stream-progress"><i id="v8-stream-fill"></i></div></div>
      <div class="v8-stream-mini"><span>QUOTE CACHE AGE</span><strong id="v8-stream-age">—</strong></div>
      <div class="v8-stream-mini"><span>STREAM SERVICE</span><strong id="v8-stream-agent">—</strong></div>
      <div class="v8-stream-mini"><span>REAL ORDERS</span><strong class="positive">NO</strong></div>
    </div>
    <div id="v8-stream-detail" class="v8-stream-note">Checking Tiingo IEX stream health…</div>`;

  const parseAgeSeconds = value => {
    const m = String(value).match(/([\d.]+)\s*s/i); if (m) return Number(m[1]);
    const mm = String(value).match(/([\d.]+)\s*m/i); if (mm) return Number(mm[1]) * 60;
    return NaN;
  };
  const fmtTime = d => d.toLocaleTimeString([], {hour:'numeric',minute:'2-digit',second:'2-digit',timeZone:'America/Los_Angeles'});
  const fmtAgo = seconds => !Number.isFinite(seconds) ? 'Age unavailable' : seconds < 60 ? `${Math.max(0,Math.round(seconds))} sec ago` : seconds < 3600 ? `${Math.round(seconds/60)} min ago` : `${(seconds/3600).toFixed(1)} hr ago`;

  const updateClock = () => {
    const now = new Date();
    card.querySelector('#v8-stream-clock').textContent = fmtTime(now);
    card.querySelector('#v8-stream-date').textContent = now.toLocaleDateString([], {weekday:'short',month:'short',day:'numeric',year:'numeric',timeZone:'America/Los_Angeles'});
    if (lastUiRefresh) card.querySelector('#v8-stream-refresh-ago').textContent = `${Math.floor((Date.now()-lastUiRefresh.getTime())/1000)} sec since observed refresh`;
  };

  const render = (countRefresh=false) => {
    const status=text(original.status), agent=text(original.agent), liveText=text(original.live), configuredText=text(original.configured), age=text(original.age), session=text(original.session), detail=text(original.detail);
    const live=Number(liveText), configured=Number(configuredText), pct=Number.isFinite(live)&&Number.isFinite(configured)&&configured>0?Math.max(0,Math.min(100,live/configured*100)):0;
    const closed=/CLOSED|AFTER_HOURS/i.test(`${status} ${session}`), bad=/STALE|ERROR|DOWN|DISCONNECTED|FAILED/i.test(status)&&!closed;
    const ageSeconds=parseAgeSeconds(age), estimatedDataTime=Number.isFinite(ageSeconds)?new Date(Date.now()-ageSeconds*1000):null;
    if(countRefresh){lastUiRefresh=new Date();refreshCount++;}
    card.querySelector('#v8-stream-state').textContent=closed?'MARKET CLOSED · MONITORING':status.replaceAll('_',' ');
    card.querySelector('#v8-stream-state').className=`v8-stream-state${closed?' closed':bad?' bad':''}`; card.querySelector('#v8-stream-pulse').className=`v8-stream-pulse${closed?' closed':bad?' bad':''}`;
    card.querySelector('#v8-stream-live').textContent=liveText; card.querySelector('#v8-stream-configured').textContent=configuredText; card.querySelector('#v8-stream-fill').style.width=`${pct}%`; card.querySelector('#v8-stream-age').textContent=age; card.querySelector('#v8-stream-session').textContent=session; card.querySelector('#v8-stream-agent').textContent=agent; card.querySelector('#v8-stream-detail').textContent=detail;
    card.querySelector('#v8-stream-last-data').textContent=estimatedDataTime?fmtTime(estimatedDataTime):'—'; card.querySelector('#v8-stream-data-ago').textContent=estimatedDataTime?`${fmtAgo(ageSeconds)} · estimated from quote-cache age`:'Waiting for quote timestamp…';
    card.querySelector('#v8-stream-last-refresh').textContent=lastUiRefresh?fmtTime(lastUiRefresh):'—'; card.querySelector('#v8-stream-refresh-count').textContent=String(refreshCount); updateClock();
  };

  render(false);
  const observer=new MutationObserver(()=>render(true)); Object.values(original).filter(Boolean).forEach(node=>observer.observe(node,{childList:true,subtree:true,characterData:true}));
  setInterval(updateClock,1000);

  // Replace the legacy V4 portfolio summary with genuine frozen-V8 holdout metrics.
  const equityCard = document.querySelector('.v4-dashboard .v4-equity-card');
  const metricGrid = document.querySelector('.v4-dashboard .v4-small-metrics');
  if (equityCard && metricGrid) {
    equityCard.innerHTML = `<div class="label">V8 PORTFOLIO EQUITY</div><div class="big" id="v8-summary-equity">$100,000.00</div><div id="v8-summary-gain" class="v4-gain">WAITING FOR FORWARD EVIDENCE</div><div class="muted" id="v8-summary-starting" style="margin-top:6px">$100,000 frozen starting capital · baseline only</div>`;
    metricGrid.innerHTML = `
      <div class="metric"><span>V8 TOTAL RETURN SINCE HOLDOUT START</span><strong id="v8-summary-return">—</strong></div>
      <div class="metric"><span>V8 COMPLETED-COHORT RETURN</span><strong id="v8-summary-forward">—</strong></div>
      <div class="metric"><span>SPY HOLDOUT RETURN</span><strong id="v8-summary-spy">—</strong></div>
      <div class="metric"><span>V8 EXCESS RETURN VS SPY</span><strong id="v8-summary-excess">—</strong></div>
      <div class="metric"><span>V8 MAX DRAWDOWN</span><strong id="v8-summary-drawdown">—</strong></div>
      <div class="metric"><span>V8 OBSERVATIONS</span><strong id="v8-summary-observations">0</strong></div>`;

    const money = v => '$'+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    const pct4 = v => `${v>=0?'+':''}${(v*100).toFixed(4)}%`;
    const maxDrawdown = values => {
      let peak=-Infinity, worst=0;
      for(const x of values){ if(!Number.isFinite(x)) continue; peak=Math.max(peak,x); if(peak>0) worst=Math.min(worst,(x/peak)-1); }
      return worst;
    };
    const setSummary = (id,value) => { const n=document.getElementById(id); if(n) n.textContent=value; };

    fetch('/api/v8/holdout',{cache:'no-store'})
      .then(r=>{if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json();})
      .then(d=>{
        const curve=Array.isArray(d.curve)?d.curve:[];
        const obs=Number(d.completed_cohorts||0);
        setSummary('v8-summary-observations',String(obs));
        if(!curve.length){
          setSummary('v8-summary-gain',String(d.state||'WAITING_FOR_HOLDOUT').replaceAll('_',' '));
          return;
        }
        const latest=curve[curve.length-1];
        const equity=Number(latest.strategy_normalized);
        const spyEquity=Number(latest.spy_normalized);
        if(!Number.isFinite(equity)||!Number.isFinite(spyEquity)) return;
        const ret=equity/100000-1, spy=spyEquity/100000-1, excess=ret-spy;
        const dd=maxDrawdown(curve.map(x=>Number(x.strategy_normalized)));
        setSummary('v8-summary-equity',money(equity));
        setSummary('v8-summary-gain',`${equity>=100000?'+':''}${money(equity-100000).replace('$','')} (${pct4(ret)})`);
        setSummary('v8-summary-starting','vs frozen V8 starting equity $100,000.00');
        setSummary('v8-summary-return',pct4(ret));
        setSummary('v8-summary-forward',pct4(ret));
        setSummary('v8-summary-spy',pct4(spy));
        setSummary('v8-summary-excess',pct4(excess));
        setSummary('v8-summary-drawdown',pct4(dd));
      })
      .catch(err=>{
        setSummary('v8-summary-gain','V8 HOLDOUT DATA UNAVAILABLE');
        console.error('[V8 PORTFOLIO SUMMARY]',err);
      });
  }
})();