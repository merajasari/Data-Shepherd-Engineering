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
    .v8-live-chart{position:relative;margin:0 0 20px;padding:22px 24px 18px;border:1px solid rgba(54,216,255,.24);border-radius:22px;background:radial-gradient(circle at 92% 0,rgba(54,216,255,.09),transparent 30%),rgba(8,20,36,.72);overflow:hidden}.v8-live-chart:before{content:"";position:absolute;inset:0 0 auto;height:2px;background:linear-gradient(90deg,#36d8ff,#39e3a1)}.v8-live-chart-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}.v8-live-chart h3{margin:5px 0 4px;font-size:1.35rem}.v8-live-chart-sub{color:#91a6c2;font-size:.78rem;line-height:1.5}.v8-live-chart-badge{padding:8px 11px;border-radius:999px;border:1px solid rgba(57,227,161,.3);background:rgba(57,227,161,.08);color:#39e3a1;font-size:.68rem;font-weight:950;letter-spacing:.08em;white-space:nowrap}.v8-live-chart-legend{display:flex;gap:22px;align-items:center;flex-wrap:wrap;margin-top:17px}.v8-live-chart-key{display:flex;gap:9px;align-items:center;color:#91a6c2;font-size:.76rem;font-weight:850}.v8-live-chart-key i{display:block;width:24px;height:3px;border-radius:99px}.v8-live-chart-key strong{color:#f2f6ff;font-size:.84rem}.v8-live-chart-stage{position:relative;margin-top:12px;min-height:340px;touch-action:none}.v8-live-chart-plot{width:100%;height:340px}.v8-live-chart-plot svg{display:block;width:100%;height:100%;overflow:visible}.v8-live-chart-tooltip{position:absolute;z-index:3;min-width:205px;padding:11px 13px;border:1px solid rgba(129,162,205,.34);border-radius:12px;background:rgba(5,15,28,.96);box-shadow:0 12px 35px rgba(0,0,0,.34);pointer-events:none;opacity:0;transform:translate(-50%,-108%);transition:opacity .12s ease;color:#f2f6ff;font-size:.72rem;line-height:1.5}.v8-live-chart-tooltip.show{opacity:1}.v8-live-chart-tooltip strong{display:block;margin-bottom:3px}.v8-live-chart-tooltip .v8-tip-row{display:flex;justify-content:space-between;gap:20px}.v8-live-chart-foot{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-top:10px;color:#91a6c2;font-size:.72rem;line-height:1.45}
    @media(max-width:900px){.v8-stream-grid{grid-template-columns:1fr}.v8-stream-foot{grid-template-columns:1fr 1fr}.v8-live-chart{padding:18px 14px}.v8-live-chart-stage,.v8-live-chart-plot{min-height:300px;height:300px}}@media(max-width:560px){.v8-stream-foot{grid-template-columns:1fr}}
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
  const modelResearchView = new URLSearchParams(window.location.search).get('view') !== 'live';
  if (equityCard && metricGrid && modelResearchView) {
    equityCard.innerHTML = `<div class="label">V8 CURRENT PORTFOLIO EQUITY</div><div class="big" id="v8-summary-equity">Loading…</div><div id="v8-summary-gain" class="v4-gain">READING OPEN V8 POSITIONS</div><div class="muted" id="v8-summary-starting" style="margin-top:6px">$100,000 frozen starting capital</div>`;
    metricGrid.innerHTML = `
      <div class="metric"><span>V8 TOTAL RETURN SINCE HOLDOUT START</span><strong id="v8-summary-return">—</strong></div>
      <div class="metric"><span>V8 COMPLETED-COHORT RETURN</span><strong id="v8-summary-forward">—</strong></div>
      <div class="metric"><span>SPY CURRENT MARK RETURN</span><strong id="v8-summary-spy">—</strong></div>
      <div class="metric"><span>V8 CURRENT EXCESS VS SPY</span><strong id="v8-summary-excess">—</strong></div>
      <div class="metric"><span>V8 COMPLETED MAX DRAWDOWN</span><strong id="v8-summary-drawdown">—</strong></div>
      <div class="metric"><span>COMPLETED / OPEN COHORTS</span><strong id="v8-summary-observations">0 / 0</strong></div>`;

    const chartPanel = document.createElement('section');
    chartPanel.className = 'v8-live-chart';
    chartPanel.setAttribute('aria-label','Interactive live V8 portfolio equity compared with SPY');
    chartPanel.innerHTML = `
      <div class="v8-live-chart-head">
        <div><div class="label">V8 VS SPY · LIVE FORWARD EQUITY</div><h3>Interactive Holdout Performance</h3><div class="v8-live-chart-sub">Both lines use the same $100,000 starting value. Move across the graph to compare exact marks.</div></div>
        <div id="v8-live-chart-badge" class="v8-live-chart-badge">LOADING LIVE MARKS</div>
      </div>
      <div class="v8-live-chart-legend">
        <div class="v8-live-chart-key"><i style="background:#36d8ff"></i>V8 <strong id="v8-live-chart-v8">—</strong></div>
        <div class="v8-live-chart-key"><i style="background:#a988ff"></i>SPY <strong id="v8-live-chart-spy">—</strong></div>
        <div class="v8-live-chart-key">EXCESS <strong id="v8-live-chart-excess">—</strong></div>
      </div>
      <div class="v8-live-chart-stage">
        <div id="v8-live-chart-plot" class="v8-live-chart-plot" role="img" aria-label="V8 and SPY equity from the September 1, 2026 holdout start"></div>
        <div id="v8-live-chart-tooltip" class="v8-live-chart-tooltip"></div>
      </div>
      <div class="v8-live-chart-foot"><span id="v8-live-chart-range">Holdout start → current mark</span><span>Live marks refresh every 15 seconds · completed points remain official evidence only</span></div>`;
    equityCard.insertAdjacentElement('beforebegin',chartPanel);

    const chartPlot=chartPanel.querySelector('#v8-live-chart-plot');
    const chartStage=chartPanel.querySelector('.v8-live-chart-stage');
    const chartTooltip=chartPanel.querySelector('#v8-live-chart-tooltip');
    let lastChartPayload=null;
    let chartHitPoints=[];
    const escapeText=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    const chartDate=(timestamp,withTime=false)=>{
      const d=new Date(timestamp);
      if(Number.isNaN(d.getTime()))return '—';
      return d.toLocaleString(undefined,withTime
        ? {month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/Los_Angeles',timeZoneName:'short'}
        : {month:'short',day:'numeric',timeZone:'America/Los_Angeles'});
    };
    const chartMoney=value=>Number(value).toLocaleString(undefined,{style:'currency',currency:'USD',maximumFractionDigits:2});
    const chartPct=value=>`${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(4)}%`;
    const toneValue=(node,value)=>{
      if(!node)return;
      node.classList.remove('positive','negative');
      if(Number.isFinite(Number(value)))node.classList.add(Number(value)<0?'negative':'positive');
    };
    const chartSeries=d=>{
      const start=Number(d.starting_equity)||100000;
      const startTime=new Date(d.holdout_start_utc||'2026-09-01T00:00:00Z').getTime();
      const points=[{time:startTime,v8:start,spy:start,kind:'Holdout start'}];
      (Array.isArray(d.curve)?d.curve:[]).forEach(row=>{
        const time=new Date(row.timestamp_utc).getTime();
        const v8=Number(row.strategy_normalized),spy=Number(row.spy_normalized);
        if(Number.isFinite(time)&&Number.isFinite(v8)&&Number.isFinite(spy))points.push({time,v8,spy,kind:'Completed cohort'});
      });
      const liveTime=new Date(d.valuation_timestamp_utc||Date.now()).getTime();
      const liveV8=Number(d.current_equity),liveSpy=Number(d.current_spy_equity);
      if(Number.isFinite(liveTime)&&Number.isFinite(liveV8)&&Number.isFinite(liveSpy)){
        const time=points.length&&liveTime<=points[points.length-1].time?points[points.length-1].time+1:liveTime;
        points.push({time,v8:liveV8,spy:liveSpy,kind:d.equity_basis==='LIVE_MARK_TO_MARKET'?'Current live mark':'Latest completed value'});
      }
      return points.sort((a,b)=>a.time-b.time);
    };
    const renderV8Chart=d=>{
      lastChartPayload=d;
      const points=chartSeries(d);
      if(!points.length){chartPlot.innerHTML='<div class="muted" style="padding:120px 20px;text-align:center">Waiting for V8 and SPY values…</div>';return;}
      const width=Math.max(620,Math.round(chartPlot.clientWidth||900)),height=340;
      const margin={top:24,right:24,bottom:44,left:82};
      const plotW=width-margin.left-margin.right,plotH=height-margin.top-margin.bottom;
      let minTime=Math.min(...points.map(p=>p.time)),maxTime=Math.max(...points.map(p=>p.time));
      if(maxTime<=minTime)maxTime=minTime+86400000;
      const values=points.flatMap(p=>[p.v8,p.spy,100000]);
      let minY=Math.min(...values),maxY=Math.max(...values);
      const rawSpan=Math.max(maxY-minY,100);
      minY-=rawSpan*.18;maxY+=rawSpan*.18;
      const x=time=>margin.left+(time-minTime)/(maxTime-minTime)*plotW;
      const y=value=>margin.top+(maxY-value)/(maxY-minY)*plotH;
      const pathFor=key=>points.map((p,index)=>`${index?'L':'M'} ${x(p.time).toFixed(2)} ${y(p[key]).toFixed(2)}`).join(' ');
      const grid=Array.from({length:5},(_,index)=>{
        const value=maxY-(maxY-minY)*index/4,py=y(value);
        return `<line x1="${margin.left}" y1="${py}" x2="${width-margin.right}" y2="${py}" stroke="rgba(129,162,205,.14)" stroke-width="1"/><text x="${margin.left-12}" y="${py+4}" text-anchor="end" fill="#91a6c2" font-size="11">${escapeText('    const signedMoney = v => `${Number(v)>=0?'+':'-'}$${Math.abs(Number(v)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    const finite = v => v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
    const pct4 = v => finite(v)?`${Number(v)>=0?'+':''}${(Number(v)*100).toFixed(4)}%`:'—';
    const markTime = value => {
      const d=new Date(value); if(Number.isNaN(d.getTime()))return null;
      return d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZone:'America/Los_Angeles',timeZoneName:'short'});
    };
    const setSummary = (id,value) => { const n=document.getElementById(id); if(n) n.textContent=value; };
    const tone = (id,value) => { const n=document.getElementById(id);if(!n)return;n.classList.remove('positive','negative');if(finite(value))n.classList.add(Number(value)<0?'negative':'positive'); };
    const getSnapshot = force => window.DataShepherdV8Snapshot
      ? window.DataShepherdV8Snapshot.get({force})
      : fetch('/api/v8/holdout',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();});

    const refreshV8Equity = async (force=false) => {
      try {
        const d=await getSnapshot(force);
        const completed=Number(d.completed_cohorts||0),open=Number(d.open_cohorts||0);
        const equity=finite(d.current_equity)?Number(d.current_equity):100000;
        const ret=finite(d.current_return)?Number(d.current_return):equity/100000-1;
        const spy=finite(d.current_spy_return)?Number(d.current_spy_return):null;
        const excess=finite(d.current_excess_return)?Number(d.current_excess_return):null;
        const change=equity-100000;
        const basis=String(d.equity_basis||'BASELINE_NO_OPEN_COHORTS');
        const isMark=basis==='LIVE_MARK_TO_MARKET';
        const hasCompleted=completed>0;
        const priced=Number(d.priced_open_cohorts||0);
        const when=markTime(d.valuation_oldest_timestamp_utc||d.valuation_timestamp_utc);
        const displayedReturn=isMark||hasCompleted?ret:null;
        const displayedSpy=isMark||hasCompleted?spy:null;

        renderV8Chart(d);
        setSummary('v8-summary-equity',money(equity));
        setSummary('v8-summary-gain',isMark?`CURRENT MARK · ${signedMoney(change)} (${pct4(ret)})`:basis.replaceAll('_',' '));
        tone('v8-summary-gain',isMark||hasCompleted?change:null);
        setSummary('v8-summary-starting',isMark
          ? `$100,000 start · ${priced}/${open} open cohorts priced${when?` · marks as of ${when}`:''}`
          : `$100,000 start · ${completed} completed · ${open} open${d.missing_mark_symbols?.length?` · waiting for ${d.missing_mark_symbols.join(', ')} marks`:''}`);
        setSummary('v8-summary-return',pct4(displayedReturn));
        setSummary('v8-summary-forward',pct4(d.strategy_total_return));
        setSummary('v8-summary-spy',pct4(displayedSpy));
        setSummary('v8-summary-excess',pct4(excess));
        setSummary('v8-summary-drawdown',pct4(d.max_drawdown));
        setSummary('v8-summary-observations',`${completed} / ${open}`);
        [['v8-summary-return',displayedReturn],['v8-summary-forward',d.strategy_total_return],['v8-summary-spy',displayedSpy],['v8-summary-excess',excess],['v8-summary-drawdown',d.max_drawdown]].forEach(([id,value])=>tone(id,value));
      } catch(err) {
        setSummary('v8-summary-equity','$100,000.00');
        setSummary('v8-summary-gain','V8 HOLDOUT DATA UNAVAILABLE');
        console.error('[V8 PORTFOLIO SUMMARY]',err);
      }
    };

    refreshV8Equity(true);
    setInterval(()=>refreshV8Equity(true),15000);
  }
})();
+Math.round(value).toLocaleString())}</text>`;
      }).join('');
      const latest=points[points.length-1];
      const circles=points.map((p,index)=>`<circle cx="${x(p.time)}" cy="${y(p.v8)}" r="${index===points.length-1?5:3}" fill="#36d8ff" stroke="#081424" stroke-width="2"/><circle cx="${x(p.time)}" cy="${y(p.spy)}" r="${index===points.length-1?5:3}" fill="#a988ff" stroke="#081424" stroke-width="2"/>`).join('');
      chartHitPoints=points.map(p=>({...p,x:x(p.time),v8Y:y(p.v8),spyY:y(p.spy)}));
      chartPlot.innerHTML=`<svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
        <defs><linearGradient id="v8LiveFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#36d8ff" stop-opacity=".16"/><stop offset="1" stop-color="#36d8ff" stop-opacity="0"/></linearGradient></defs>
        ${grid}
        <line x1="${margin.left}" y1="${y(100000)}" x2="${width-margin.right}" y2="${y(100000)}" stroke="rgba(242,246,255,.3)" stroke-dasharray="5 6"/>
        <path d="${pathFor('v8')} L ${x(latest.time)} ${height-margin.bottom} L ${x(points[0].time)} ${height-margin.bottom} Z" fill="url(#v8LiveFill)"/>
        <path d="${pathFor('spy')}" fill="none" stroke="#a988ff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="${pathFor('v8')}" fill="none" stroke="#36d8ff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
        ${circles}
        <line id="v8-live-hover-line" x1="0" y1="${margin.top}" x2="0" y2="${height-margin.bottom}" stroke="rgba(242,246,255,.45)" stroke-dasharray="3 4" opacity="0"/>
        <text x="${margin.left}" y="${height-12}" fill="#91a6c2" font-size="11">${escapeText(chartDate(minTime))}</text>
        <text x="${width-margin.right}" y="${height-12}" text-anchor="end" fill="#91a6c2" font-size="11">${escapeText(chartDate(maxTime))}</text>
      </svg>`;
      const v8Return=latest.v8/(Number(d.starting_equity)||100000)-1;
      const spyReturn=latest.spy/(Number(d.starting_equity)||100000)-1;
      const v8Legend=chartPanel.querySelector('#v8-live-chart-v8'),spyLegend=chartPanel.querySelector('#v8-live-chart-spy'),excessLegend=chartPanel.querySelector('#v8-live-chart-excess');
      v8Legend.textContent=`${chartMoney(latest.v8)} (${chartPct(v8Return)})`;
      spyLegend.textContent=`${chartMoney(latest.spy)} (${chartPct(spyReturn)})`;
      excessLegend.textContent=chartPct(v8Return-spyReturn);
      toneValue(v8Legend,v8Return);toneValue(spyLegend,spyReturn);toneValue(excessLegend,v8Return-spyReturn);
      const open=Number(d.open_cohorts||0),priced=Number(d.priced_open_cohorts||0);
      chartPanel.querySelector('#v8-live-chart-badge').textContent=d.equity_basis==='LIVE_MARK_TO_MARKET'?`LIVE MARK · ${priced}/${open} COHORTS`:`${Number(d.completed_cohorts||0)} COMPLETED COHORTS`;
      chartPanel.querySelector('#v8-live-chart-range').textContent=`${chartDate(minTime)} → ${chartDate(maxTime,true)} · ${Math.max(0,points.length-2)} official exit points + current mark`;
    };
    chartStage.onpointermove=event=>{
      if(!chartHitPoints.length)return;
      const rect=chartPlot.getBoundingClientRect();
      const pointerX=(event.clientX-rect.left)*(Math.max(620,Math.round(chartPlot.clientWidth||900))/rect.width);
      const point=chartHitPoints.reduce((best,item)=>Math.abs(item.x-pointerX)<Math.abs(best.x-pointerX)?item:best);
      const screenX=point.x/Math.max(620,Math.round(chartPlot.clientWidth||900))*rect.width;
      const line=chartPlot.querySelector('#v8-live-hover-line');
      if(line){line.setAttribute('x1',point.x);line.setAttribute('x2',point.x);line.setAttribute('opacity','1');}
      const start=Number(lastChartPayload?.starting_equity)||100000;
      chartTooltip.innerHTML=`<strong>${escapeText(point.kind)} · ${escapeText(chartDate(point.time,true))}</strong><div class="v8-tip-row"><span>V8 equity</span><b>${escapeText(chartMoney(point.v8))}</b></div><div class="v8-tip-row"><span>SPY equity</span><b>${escapeText(chartMoney(point.spy))}</b></div><div class="v8-tip-row"><span>V8 return</span><b>${escapeText(chartPct(point.v8/start-1))}</b></div><div class="v8-tip-row"><span>Excess</span><b>${escapeText(chartPct((point.v8-point.spy)/start))}</b></div>`;
      chartTooltip.style.left=`${Math.max(110,Math.min(rect.width-110,screenX))}px`;
      chartTooltip.style.top=`${Math.max(105,Math.min(point.v8Y,point.spyY))}px`;
      chartTooltip.classList.add('show');
    };
    chartStage.onpointerleave=()=>{
      chartTooltip.classList.remove('show');
      const line=chartPlot.querySelector('#v8-live-hover-line');if(line)line.setAttribute('opacity','0');
    };
    if(window.ResizeObserver)new ResizeObserver(()=>{if(lastChartPayload)renderV8Chart(lastChartPayload);}).observe(chartPlot);

    const money = v => '    const signedMoney = v => `${Number(v)>=0?'+':'-'}$${Math.abs(Number(v)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    const finite = v => v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
    const pct4 = v => finite(v)?`${Number(v)>=0?'+':''}${(Number(v)*100).toFixed(4)}%`:'—';
    const markTime = value => {
      const d=new Date(value); if(Number.isNaN(d.getTime()))return null;
      return d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZone:'America/Los_Angeles',timeZoneName:'short'});
    };
    const setSummary = (id,value) => { const n=document.getElementById(id); if(n) n.textContent=value; };
    const tone = (id,value) => { const n=document.getElementById(id);if(!n)return;n.classList.remove('positive','negative');if(finite(value))n.classList.add(Number(value)<0?'negative':'positive'); };
    const getSnapshot = force => window.DataShepherdV8Snapshot
      ? window.DataShepherdV8Snapshot.get({force})
      : fetch('/api/v8/holdout',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();});

    const refreshV8Equity = async (force=false) => {
      try {
        const d=await getSnapshot(force);
        const completed=Number(d.completed_cohorts||0),open=Number(d.open_cohorts||0);
        const equity=finite(d.current_equity)?Number(d.current_equity):100000;
        const ret=finite(d.current_return)?Number(d.current_return):equity/100000-1;
        const spy=finite(d.current_spy_return)?Number(d.current_spy_return):null;
        const excess=finite(d.current_excess_return)?Number(d.current_excess_return):null;
        const change=equity-100000;
        const basis=String(d.equity_basis||'BASELINE_NO_OPEN_COHORTS');
        const isMark=basis==='LIVE_MARK_TO_MARKET';
        const hasCompleted=completed>0;
        const priced=Number(d.priced_open_cohorts||0);
        const when=markTime(d.valuation_oldest_timestamp_utc||d.valuation_timestamp_utc);
        const displayedReturn=isMark||hasCompleted?ret:null;
        const displayedSpy=isMark||hasCompleted?spy:null;

        setSummary('v8-summary-equity',money(equity));
        setSummary('v8-summary-gain',isMark?`CURRENT MARK · ${signedMoney(change)} (${pct4(ret)})`:basis.replaceAll('_',' '));
        tone('v8-summary-gain',isMark||hasCompleted?change:null);
        setSummary('v8-summary-starting',isMark
          ? `$100,000 start · ${priced}/${open} open cohorts priced${when?` · marks as of ${when}`:''}`
          : `$100,000 start · ${completed} completed · ${open} open${d.missing_mark_symbols?.length?` · waiting for ${d.missing_mark_symbols.join(', ')} marks`:''}`);
        setSummary('v8-summary-return',pct4(displayedReturn));
        setSummary('v8-summary-forward',pct4(d.strategy_total_return));
        setSummary('v8-summary-spy',pct4(displayedSpy));
        setSummary('v8-summary-excess',pct4(excess));
        setSummary('v8-summary-drawdown',pct4(d.max_drawdown));
        setSummary('v8-summary-observations',`${completed} / ${open}`);
        [['v8-summary-return',displayedReturn],['v8-summary-forward',d.strategy_total_return],['v8-summary-spy',displayedSpy],['v8-summary-excess',excess],['v8-summary-drawdown',d.max_drawdown]].forEach(([id,value])=>tone(id,value));
      } catch(err) {
        setSummary('v8-summary-equity','$100,000.00');
        setSummary('v8-summary-gain','V8 HOLDOUT DATA UNAVAILABLE');
        console.error('[V8 PORTFOLIO SUMMARY]',err);
      }
    };

    refreshV8Equity(true);
    setInterval(()=>refreshV8Equity(true),15000);
  }
})();
+Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    const signedMoney = v => `${Number(v)>=0?'+':'-'}$${Math.abs(Number(v)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    const finite = v => v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
    const pct4 = v => finite(v)?`${Number(v)>=0?'+':''}${(Number(v)*100).toFixed(4)}%`:'—';
    const markTime = value => {
      const d=new Date(value); if(Number.isNaN(d.getTime()))return null;
      return d.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit',timeZone:'America/Los_Angeles',timeZoneName:'short'});
    };
    const setSummary = (id,value) => { const n=document.getElementById(id); if(n) n.textContent=value; };
    const tone = (id,value) => { const n=document.getElementById(id);if(!n)return;n.classList.remove('positive','negative');if(finite(value))n.classList.add(Number(value)<0?'negative':'positive'); };
    const getSnapshot = force => window.DataShepherdV8Snapshot
      ? window.DataShepherdV8Snapshot.get({force})
      : fetch('/api/v8/holdout',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();});

    const refreshV8Equity = async (force=false) => {
      try {
        const d=await getSnapshot(force);
        const completed=Number(d.completed_cohorts||0),open=Number(d.open_cohorts||0);
        const equity=finite(d.current_equity)?Number(d.current_equity):100000;
        const ret=finite(d.current_return)?Number(d.current_return):equity/100000-1;
        const spy=finite(d.current_spy_return)?Number(d.current_spy_return):null;
        const excess=finite(d.current_excess_return)?Number(d.current_excess_return):null;
        const change=equity-100000;
        const basis=String(d.equity_basis||'BASELINE_NO_OPEN_COHORTS');
        const isMark=basis==='LIVE_MARK_TO_MARKET';
        const hasCompleted=completed>0;
        const priced=Number(d.priced_open_cohorts||0);
        const when=markTime(d.valuation_oldest_timestamp_utc||d.valuation_timestamp_utc);
        const displayedReturn=isMark||hasCompleted?ret:null;
        const displayedSpy=isMark||hasCompleted?spy:null;

        setSummary('v8-summary-equity',money(equity));
        setSummary('v8-summary-gain',isMark?`CURRENT MARK · ${signedMoney(change)} (${pct4(ret)})`:basis.replaceAll('_',' '));
        tone('v8-summary-gain',isMark||hasCompleted?change:null);
        setSummary('v8-summary-starting',isMark
          ? `$100,000 start · ${priced}/${open} open cohorts priced${when?` · marks as of ${when}`:''}`
          : `$100,000 start · ${completed} completed · ${open} open${d.missing_mark_symbols?.length?` · waiting for ${d.missing_mark_symbols.join(', ')} marks`:''}`);
        setSummary('v8-summary-return',pct4(displayedReturn));
        setSummary('v8-summary-forward',pct4(d.strategy_total_return));
        setSummary('v8-summary-spy',pct4(displayedSpy));
        setSummary('v8-summary-excess',pct4(excess));
        setSummary('v8-summary-drawdown',pct4(d.max_drawdown));
        setSummary('v8-summary-observations',`${completed} / ${open}`);
        [['v8-summary-return',displayedReturn],['v8-summary-forward',d.strategy_total_return],['v8-summary-spy',displayedSpy],['v8-summary-excess',excess],['v8-summary-drawdown',d.max_drawdown]].forEach(([id,value])=>tone(id,value));
      } catch(err) {
        setSummary('v8-summary-equity','$100,000.00');
        setSummary('v8-summary-gain','V8 HOLDOUT DATA UNAVAILABLE');
        console.error('[V8 PORTFOLIO SUMMARY]',err);
      }
    };

    refreshV8Equity(true);
    setInterval(()=>refreshV8Equity(true),15000);
  }
})();
