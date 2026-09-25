(() => {
  const panelId = 'v10-cycle3-accelerated-monitor';
  if (document.getElementById(panelId)) return;

  const anchor = document.getElementById('v10-confirmation-card') ||
    document.getElementById('v8-launch-readiness-card') ||
    document.getElementById('v8-holdout-monitor') ||
    document.querySelector('footer');
  if (!anchor) return;

  const section = document.createElement('section');
  section.id = panelId;
  section.className = 'panel';
  section.style.marginTop = '18px';
  section.innerHTML = `
    <style>
      #${panelId}{overflow:hidden}
      #${panelId} .a10-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
      #${panelId} .a10-head h2{margin-bottom:7px}
      #${panelId} .a10-badge{border:1px solid rgba(54,216,255,.42);border-radius:999px;padding:8px 12px;color:#36d8ff;font-size:12px;font-weight:900;text-align:center;overflow-wrap:anywhere;max-width:100%}
      #${panelId} .a10-badge.alert{border-color:rgba(255,109,109,.5);color:#ff8d8d}
      #${panelId} .a10-live{margin-top:16px;padding:18px;border:1px solid rgba(54,216,255,.3);border-radius:16px;background:linear-gradient(145deg,rgba(8,34,47,.76),rgba(7,16,31,.74))}
      #${panelId} .a10-live-grid{display:grid;grid-template-columns:minmax(300px,.62fr) minmax(0,1.38fr);gap:18px;align-items:stretch}
      #${panelId} .a10-live-summary{min-width:0;padding:18px;border:1px solid rgba(57,227,161,.3);border-radius:14px;background:rgba(7,16,31,.42)}
      #${panelId} .a10-live-equity{margin-top:8px;font-size:clamp(1.85rem,3vw,3.25rem);font-weight:950;line-height:1.05;letter-spacing:-.035em;white-space:nowrap;font-variant-numeric:tabular-nums}
      #${panelId} .a10-live-change{margin-top:4px;font-size:1.05rem;font-weight:900}
      #${panelId} .a10-live-sub{margin-top:8px;color:#91a6c2;font-size:11px;line-height:1.5}
      #${panelId} .a10-live-metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}
      #${panelId} .a10-live-metric{padding:10px;border:1px solid rgba(145,166,194,.14);border-radius:10px;background:rgba(7,16,31,.35)}
      #${panelId} .a10-live-metric span{display:block;color:#91a6c2;font-size:9px;font-weight:800;letter-spacing:.07em;text-transform:uppercase}
      #${panelId} .a10-live-metric strong{display:block;margin-top:4px;font-size:13px}
      #${panelId} .a10-live-chart{min-width:0;padding:14px;border:1px solid rgba(145,166,194,.14);border-radius:14px;background:rgba(7,16,31,.38)}
      #${panelId} .a10-live-chart-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
      #${panelId} .a10-live-legend{display:flex;gap:12px;flex-wrap:wrap;color:#91a6c2;font-size:11px}
      #${panelId} .a10-live-legend span{display:flex;align-items:center;gap:5px}
      #${panelId} .a10-live-legend i{width:15px;height:3px;border-radius:3px}
      #${panelId} .a10-live-stage{position:relative;height:330px;margin-top:8px}
      #${panelId} .a10-live-host,#${panelId} .a10-live-host svg{display:block;width:100%;height:100%}
      #${panelId} .a10-live-tooltip{position:absolute;display:none;pointer-events:none;min-width:210px;padding:10px 12px;border:1px solid rgba(54,216,255,.32);border-radius:10px;background:#071525;box-shadow:0 12px 30px rgba(0,0,0,.38);font-size:11px;z-index:4;transform:translate(-50%,-100%)}
      #${panelId} .a10-live-tooltip.show{display:block}
      #${panelId} .a10-live-tooltip strong{display:block;margin-bottom:6px}
      #${panelId} .a10-live-tooltip div{display:flex;justify-content:space-between;gap:16px;margin-top:4px}
      #${panelId} .a10-live-foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:7px;color:#91a6c2;font-size:10px}
      #${panelId} .positive{color:#39e3a1}#${panelId} .negative{color:#ff6680}
      #${panelId} .a10-boundaries{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:16px}
      #${panelId} .a10-boundary,#${panelId} .a10-metric,#${panelId} .a10-progress-card,#${panelId} .a10-chart-card,#${panelId} .a10-gates{padding:13px;border:1px solid rgba(145,166,194,.17);border-radius:12px;background:rgba(7,16,31,.42)}
      #${panelId} .a10-boundary span,#${panelId} .a10-metric span,#${panelId} .a10-progress-card span{display:block;color:#91a6c2;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      #${panelId} .a10-boundary strong,#${panelId} .a10-metric strong,#${panelId} .a10-progress-card strong{display:block;margin-top:6px;font-size:16px;overflow-wrap:anywhere}
      #${panelId} .a10-progress-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
      #${panelId} .a10-progress{height:8px;margin-top:10px;border-radius:999px;background:rgba(145,166,194,.15);overflow:hidden}
      #${panelId} .a10-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#36d8ff,#39e3a1);border-radius:inherit;transition:width .3s ease}
      #${panelId} .a10-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-top:14px}
      #${panelId} .a10-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
      #${panelId} .a10-chart-title{font-size:13px;font-weight:900;letter-spacing:.04em;text-transform:uppercase}
      #${panelId} .a10-chart-subtitle{color:#91a6c2;font-size:11px;line-height:1.45;margin-top:5px}
      #${panelId} .a10-chart-host{min-height:240px;margin-top:8px;display:flex;align-items:center;justify-content:center}
      #${panelId} .a10-chart-host svg{display:block;width:100%;height:auto;overflow:visible}
      #${panelId} .a10-placeholder{color:#91a6c2;text-align:center;font-size:12px;line-height:1.55;padding:28px}
      #${panelId} .a10-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:6px;color:#91a6c2;font-size:11px}
      #${panelId} .a10-legend span{display:flex;align-items:center;gap:6px}
      #${panelId} .a10-swatch{width:18px;height:3px;border-radius:3px}
      #${panelId} .a10-gates{margin-top:14px}
      #${panelId} .a10-gates h3{font-size:14px;margin:0 0 10px}
      #${panelId} .a10-gate-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;list-style:none;padding:0;margin:0}
      #${panelId} .a10-gate{display:grid;grid-template-columns:1fr auto;gap:6px 12px;padding:10px;border-radius:9px;background:rgba(145,166,194,.06)}
      #${panelId} .a10-gate span{font-size:12px;font-weight:700}
      #${panelId} .a10-gate small{color:#91a6c2;font-size:10px}
      #${panelId} .a10-gate strong{grid-row:1/3;grid-column:2;font-size:11px;align-self:center;color:#91a6c2}
      #${panelId} .a10-gate.pass strong{color:#39e3a1}
      #${panelId} .a10-gate.fail strong{color:#ff8d8d}
      #${panelId} .a10-ops{margin-top:14px;color:#91a6c2;font-size:12px;line-height:1.6;word-break:break-word}
      #${panelId} .a10-integrity{margin-top:12px;border:1px solid rgba(145,166,194,.17);border-radius:10px;background:rgba(7,16,31,.28)}
      #${panelId} .a10-integrity summary{cursor:pointer;padding:10px 12px;color:#c5d4e8;font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
      #${panelId} .a10-integrity-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:0 12px 12px}
      #${panelId} .a10-integrity-grid div{min-width:0}
      #${panelId} .a10-integrity-grid span{display:block;color:#91a6c2;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
      #${panelId} .a10-integrity-grid strong{display:block;margin-top:4px;font-size:11px;overflow-wrap:anywhere}
      #${panelId} .a10-alerts{margin-top:8px;color:#ff8d8d}
      @media(max-width:1050px){#${panelId} .a10-live-grid{grid-template-columns:1fr}#${panelId} .a10-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}#${panelId} .a10-charts{grid-template-columns:1fr}}
      @media(max-width:700px){#${panelId} .a10-head,#${panelId} .a10-live-chart-head{flex-direction:column}#${panelId} .a10-live-metrics,#${panelId} .a10-boundaries,#${panelId} .a10-progress-grid,#${panelId} .a10-gate-list,#${panelId} .a10-integrity-grid{grid-template-columns:1fr}#${panelId} .a10-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}#${panelId} .a10-live-stage{height:290px}}
    </style>
    <div class="a10-head">
      <div>
        <div class="label">AUTHORIZED PROSPECTIVE PAPER-FORWARD · SEPARATE EVIDENCE LANE</div>
        <h2>V10 Cycle 3 Accelerated Evidence</h2>
        <p class="muted">Frozen <strong>c3_confirm2_blend50</strong> decisions are collected prospectively before January. This panel is read-only and never invokes either V10 runner.</p>
      </div>
      <div class="a10-badge" data-a10-state>LOADING</div>
    </div>
    <div class="a10-live">
      <div class="a10-live-grid">
        <div class="a10-live-summary">
          <div class="label">V10 CURRENT PAPER EQUITY</div>
          <div class="a10-live-equity" data-a10-live-equity>$100,000.00</div>
          <div class="a10-live-change" data-a10-live-change>READING OPEN V10 SLEEVES</div>
          <div class="a10-live-sub" data-a10-live-sub>$100,000 start · waiting for current marks</div>
          <div class="a10-live-metrics">
            <div class="a10-live-metric"><span>V10 return</span><strong data-a10-live-return>—</strong></div>
            <div class="a10-live-metric"><span>Official V8 return</span><strong data-a10-live-v8>—</strong></div>
            <div class="a10-live-metric"><span>SPY return</span><strong data-a10-live-spy>—</strong></div>
            <div class="a10-live-metric"><span>Excess vs SPY</span><strong data-a10-live-excess-spy>—</strong></div>
            <div class="a10-live-metric"><span>Current return gap vs official V8</span><strong data-a10-live-excess-v8>—</strong></div>
          </div>
        </div>
        <div class="a10-live-chart">
          <div class="a10-live-chart-head"><div><div class="a10-chart-title">Interactive live paper performance</div><div class="a10-chart-subtitle">V10 and SPY use the accelerated Sep 10 evidence lane. V8 uses the official frozen-V8 holdout shown on the V8 page, with its own Sep 1 boundary. Hover for exact values.</div></div><div class="a10-live-legend"><span><i style="background:#36d8ff"></i>V10</span><span><i style="background:#efc56b"></i>V8 official</span><span><i style="background:#a78bfa"></i>SPY</span></div></div>
          <div class="a10-live-stage"><div class="a10-live-host" data-a10-live-chart></div><div class="a10-live-tooltip" data-a10-live-tooltip></div></div>
          <div class="a10-live-foot"><span data-a10-live-range>Official forward marks loading…</span><span>Refreshes every 15 seconds · official V8 is read from /api/v8/holdout · current marks are not completed evidence</span></div>
        </div>
      </div>
    </div>
    <div class="a10-boundaries">
      <div class="a10-boundary"><span>First eligible decision</span><strong data-a10-first>—</strong></div>
      <div class="a10-boundary"><span>Last eligible decision</span><strong data-a10-last>—</strong></div>
      <div class="a10-boundary"><span>Independent confirmation</span><strong data-a10-january>—</strong></div>
    </div>
    <div class="a10-progress-grid">
      <div class="a10-progress-card">
        <span>Provisional paper-champion review</span>
        <strong data-a10-provisional>0 / 8 complete blocks</strong>
        <div class="a10-progress" data-a10-provisional-progress role="progressbar" aria-label="Provisional review progress" aria-valuemin="0" aria-valuemax="8" aria-valuenow="0"><i></i></div>
      </div>
      <div class="a10-progress-card">
        <span>Stronger human-review checkpoint</span>
        <strong data-a10-stronger>0 / 12 complete blocks</strong>
        <div class="a10-progress" data-a10-stronger-progress role="progressbar" aria-label="Stronger review progress" aria-valuemin="0" aria-valuemax="12" aria-valuenow="0"><i></i></div>
      </div>
    </div>
    <div class="a10-metrics">
      <div class="a10-metric"><span>Decisions</span><strong data-a10-decisions>—</strong></div>
      <div class="a10-metric"><span>Entries</span><strong data-a10-entries>—</strong></div>
      <div class="a10-metric"><span>Completed exits</span><strong data-a10-exits>—</strong></div>
      <div class="a10-metric"><span>Promotion-scored exits</span><strong data-a10-scored>—</strong></div>
      <div class="a10-metric"><span>Complete five-sleeve blocks</span><strong data-a10-blocks>—</strong></div>
      <div class="a10-metric"><span>Mean complete-block V10 return after modeled cost</span><strong data-a10-return>—</strong></div>
      <div class="a10-metric"><span>Mean paired V10 − V8 edge</span><strong data-a10-v8-edge>—</strong></div>
      <div class="a10-metric"><span>Mean paired V10 − SPY edge</span><strong data-a10-spy-edge>—</strong></div>
      <div class="a10-metric"><span>Max cohort drawdown · V10 / V8</span><strong data-a10-drawdown>—</strong></div>
      <div class="a10-metric"><span>Completed defensive-regime exits</span><strong data-a10-defensive-exits>—</strong></div>
      <div class="a10-metric"><span>Mean defensive V10 − V8 edge</span><strong data-a10-defensive-edge>—</strong></div>
    </div>
    <div class="a10-charts">
      <figure class="a10-chart-card">
        <figcaption><div class="a10-chart-title">Complete-block normalized comparison</div><div class="a10-chart-subtitle">Diagnostic hypothetical $100,000 starting basis for V10, the same-date frozen V8 control, and SPY. Partial sleeves never enter this chart.</div></figcaption>
        <div class="a10-legend"><span><i class="a10-swatch" style="background:#36d8ff"></i>V10 accelerated</span><span><i class="a10-swatch" style="background:#efc56b"></i>V8 control</span><span><i class="a10-swatch" style="background:#a78bfa"></i>SPY</span></div>
        <div class="a10-chart-host" data-a10-equity-chart></div>
      </figure>
      <figure class="a10-chart-card">
        <figcaption><div class="a10-chart-title">Paired edge by complete block</div><div class="a10-chart-subtitle">Percentage-point return difference. The zero line separates positive and negative paired evidence.</div></figcaption>
        <div class="a10-legend"><span><i class="a10-swatch" style="background:#39e3a1"></i>V10 − V8</span><span><i class="a10-swatch" style="background:#ff7ad9"></i>V10 − SPY</span></div>
        <div class="a10-chart-host" data-a10-edge-chart></div>
      </figure>
    </div>
    <div class="a10-gates">
      <h3>Preregistered promotion gates</h3>
      <ul class="a10-gate-list" data-a10-gates><li class="a10-placeholder">Loading gate status…</li></ul>
    </div>
    <div class="a10-ops"><strong>V2 clean evidence boundary</strong> · Only prospective evidence beginning September 10, 2026 is displayed.</div><div class="a10-ops" data-a10-method>Loading accelerated evidence integrity…</div>
    <details class="a10-integrity">
      <summary>Data integrity &amp; authority</summary>
      <div class="a10-integrity-grid">
        <div><span>Frozen SHA-256</span><strong data-a10-frozen-sha>—</strong></div>
        <div><span>Contract SHA-256</span><strong data-a10-contract-sha>—</strong></div>
        <div><span>Paper only</span><strong data-a10-paper>YES</strong></div>
        <div><span>Automatic promotion</span><strong data-a10-auto-promotion>NO</strong></div>
        <div><span>Human review</span><strong data-a10-human-review>YES</strong></div>
        <div><span>Brokerage orders</span><strong data-a10-brokerage>OFF</strong></div>
        <div><span>Runner invoked by dashboard</span><strong data-a10-runner>NO</strong></div>
        <div><span>January evidence modified</span><strong data-a10-january-modified>NO</strong></div>
        <div><span>Current run health</span><strong data-a10-current-health>—</strong></div>
        <div><span>Study integrity</span><strong data-a10-study-integrity>—</strong></div>
        <div><span>Feature backend</span><strong data-a10-feature-backend>—</strong></div>
        <div><span>Latest source session</span><strong data-a10-source-session>—</strong></div>
        <div><span>Expected source session</span><strong data-a10-expected-source>—</strong></div>
        <div><span>Source price coverage</span><strong data-a10-source-coverage>—</strong></div>
        <div><span>Next lifecycle event</span><strong data-a10-next-event>—</strong></div>
        <div><span>Pending entry / exit</span><strong data-a10-pending>—</strong></div>
        <div><span>Sep 10 diagnostic</span><strong data-a10-diagnostic>—</strong></div>
      </div>
    </details>
    <div class="a10-alerts" data-a10-alerts hidden></div>
  `;

  const original = document.getElementById('v10-confirmation-card');
  if (original) original.insertAdjacentElement('beforebegin', section);
  else anchor.insertAdjacentElement('afterend', section);

  const set = (selector, value) => {
    const node = section.querySelector(selector);
    if (node) node.textContent = value;
  };
  const statusText = value => String(value || 'UNKNOWN').replaceAll('_', ' ');
  const pct = value => value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`;
  const unsignedPct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
  const dateOnly = value => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'UTC'});
  };
  const progress = (selector, value, goal) => {
    const node = section.querySelector(selector);
    if (!node) return;
    const completed = Math.max(0, Number(value) || 0);
    node.setAttribute('aria-valuenow', String(Math.min(completed, goal)));
    const bar = node.querySelector('i');
    if (bar) bar.style.width = `${Math.min(100, completed / goal * 100)}%`;
  };
  const svgLine = (points, color, width=3) => `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linejoin="round" stroke-linecap="round"/>`;
  const money = value => Number(value).toLocaleString(undefined,{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2});
  const pct4 = value => value == null || !Number.isFinite(Number(value)) ? '—' : `${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(4)}%`;
  const dateTime = value => {
    if(value==null||value==='')return '—';
    const parsed=new Date(value);
    return Number.isNaN(parsed.getTime())?'—':parsed.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/Los_Angeles',timeZoneName:'short'});
  };
  const tone = (selector, value) => {
    const node=section.querySelector(selector);
    if(!node)return;
    node.classList.remove('positive','negative');
    if(value!=null&&Number.isFinite(Number(value)))node.classList.add(Number(value)<0?'negative':'positive');
  };
  let livePayload=null,officialV8Payload=null,liveHits=[],liveRenderedSeries=[],liveWidth=900;

  const finiteNumber = value => Number.isFinite(Number(value));
  const stamp = value => {
    const parsed=new Date(value).getTime();
    return Number.isFinite(parsed)?parsed:null;
  };
  const uniqueSeriesPoints = rows => {
    const sorted=rows
      .filter(row=>Number.isFinite(row.time)&&Number.isFinite(row.value))
      .sort((left,right)=>left.time-right.time);
    return sorted.filter((row,index)=>!index||row.time!==sorted[index-1].time);
  };
  const appendCurrentPoint = (rows,timeValue,value,label) => {
    let time=stamp(timeValue);
    if(time==null||!finiteNumber(value))return rows;
    if(rows.length&&time<=rows.at(-1).time)time=rows.at(-1).time+1;
    rows.push({time,value:Number(value),label});
    return rows;
  };
  const nearestSeriesPoint = (points,time) => points.reduce(
    (left,right)=>Math.abs(right.time-time)<Math.abs(left.time-time)?right:left
  );

  function acceleratedLiveSeries(data) {
    const start=Number(data.starting_equity)||NORMALIZED_BASE;
    const boundary=stamp(data.first_decision_session_utc||'2026-09-10T00:00:00Z');
    const build=(key,currentKey,id,label,color,width)=>{
      const rows=boundary==null?[]:[{time:boundary,value:start,label:'Accelerated boundary'}];
      (Array.isArray(data.operational_curve)?data.operational_curve:[]).forEach(row=>{
        const time=stamp(row.timestamp_utc);
        if(time!=null&&finiteNumber(row[key])){
          rows.push({time,value:Number(row[key]),label:'Completed accelerated exit'});
        }
      });
      if(data.equity_basis==='LIVE_MARK_TO_MARKET'){
        appendCurrentPoint(
          rows,
          data.valuation_timestamp_utc||data.operational_checked_at_utc,
          data[currentKey],
          'Current accelerated mark'
        );
      }
      return {id,label,color,width,points:uniqueSeriesPoints(rows)};
    };
    return [
      build('v10_normalized','current_equity','v10','V10','#36d8ff',3.8),
      build('spy_normalized','current_spy_equity','spy','SPY','#a78bfa',2.8),
    ];
  }

  function officialV8LiveSeries(v8) {
    if(!v8)return null;
    const start=finiteNumber(v8.starting_equity)?Number(v8.starting_equity):NORMALIZED_BASE;
    const boundary=stamp(v8.holdout_start_utc);
    const rows=boundary==null?[]:[{time:boundary,value:start,label:'Official V8 boundary'}];
    (Array.isArray(v8.curve)?v8.curve:[]).forEach(row=>{
      const time=stamp(row.timestamp_utc);
      if(time!=null&&finiteNumber(row.strategy_normalized)){
        rows.push({time,value:Number(row.strategy_normalized),label:'Completed V8 cohort'});
      }
    });
    if(v8.equity_basis==='LIVE_MARK_TO_MARKET'){
      appendCurrentPoint(
        rows,
        v8.valuation_timestamp_utc,
        v8.current_equity,
        'Current official V8 mark'
      );
    } else if(finiteNumber(v8.current_equity)&&rows.length){
      appendCurrentPoint(
        rows,
        v8.valuation_timestamp_utc||rows.at(-1).time+1,
        v8.current_equity,
        'Latest official V8 value'
      );
    }
    return {
      id:'v8',
      label:'V8 official',
      color:'#efc56b',
      width:2.8,
      points:uniqueSeriesPoints(rows),
    };
  }

  function renderLiveChart(data,v8) {
    livePayload=data;
    officialV8Payload=v8||null;
    const host=section.querySelector('[data-a10-live-chart]');
    if(!host)return;

    const series=acceleratedLiveSeries(data);
    const official=officialV8LiveSeries(v8);
    if(official&&official.points.length)series.splice(1,0,official);
    liveRenderedSeries=series.filter(item=>item.points.length);

    const allPoints=liveRenderedSeries.flatMap(item=>item.points);
    if(!allPoints.length){
      host.innerHTML='<div class="a10-placeholder">Waiting for forward paper values.</div>';
      return;
    }

    const H=330,p={l:72,r:158,t:24,b:42};
    liveWidth=Math.max(650,Math.round(host.clientWidth||900));
    const minX=Math.min(...allPoints.map(row=>row.time));
    const rawMaxX=Math.max(...allPoints.map(row=>row.time));
    const maxX=Math.max(rawMaxX,minX+86400000);
    const values=[...allPoints.map(row=>row.value),NORMALIZED_BASE];
    const raw=Math.max(...values)-Math.min(...values),pad=Math.max(raw*.18,45);
    const lo=Math.min(...values)-pad,hi=Math.max(...values)+pad;
    const x=value=>p.l+(value-minX)/(maxX-minX)*(liveWidth-p.l-p.r);
    const y=value=>p.t+(hi-value)/(hi-lo)*(H-p.t-p.b);
    const grid=Array.from({length:5},(_,index)=>{
      const value=hi-(hi-lo)*index/4,yy=y(value);
      return `<line x1="${p.l}" y1="${yy}" x2="${liveWidth-p.r}" y2="${yy}" stroke="rgba(145,166,194,.15)"/><text x="${p.l-9}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value).toLocaleString()}</text>`;
    }).join('');
    const paths=liveRenderedSeries.map(item=>{
      const path=item.points.map((row,index)=>`${index?'L':'M'} ${x(row.time).toFixed(1)} ${y(row.value).toFixed(1)}`).join(' ');
      const dots=item.points.map((row,index)=>`<circle cx="${x(row.time)}" cy="${y(row.value)}" r="${index===item.points.length-1?4.5:3}" fill="${item.color}"/>`).join('');
      return `<path d="${path}" fill="none" stroke="${item.color}" stroke-width="${item.width}" stroke-linejoin="round" stroke-linecap="round"/>${dots}`;
    }).join('');

    const ends=liveRenderedSeries.map(item=>{
      const last=item.points.at(-1);
      return {item,last,rawY:y(last.value),labelY:y(last.value)};
    }).sort((a,b)=>a.rawY-b.rawY);
    ends.forEach((row,index)=>{
      row.labelY=Math.max(p.t+11,Math.min(H-p.b-7,row.rawY));
      if(index&&row.labelY-ends[index-1].labelY<17)row.labelY=ends[index-1].labelY+17;
    });
    for(let index=ends.length-2;index>=0;index--){
      if(ends[index+1].labelY>H-p.b-7)ends[index+1].labelY=H-p.b-7;
      if(ends[index+1].labelY-ends[index].labelY<17)ends[index].labelY=ends[index+1].labelY-17;
    }
    const endLabels=ends.map(row=>`<text x="${Math.min(liveWidth-p.r+8,x(row.last.time)+9)}" y="${row.labelY}" fill="${row.item.color}" font-size="11" font-weight="900">${row.item.label} ${money(row.last.value)}</text>`).join('');

    const hitTimes=[...new Set(allPoints.map(row=>row.time))].sort((a,b)=>a-b);
    liveHits=hitTimes.map(time=>{
      const nearest=liveRenderedSeries.map(item=>({
        item,
        point:nearestSeriesPoint(item.points,time),
      }));
      return {
        time,
        x:x(time),
        top:Math.min(...nearest.map(row=>y(row.point.value))),
      };
    });

    const firstLabel=dateOnly(minX),lastLabel=dateTime(rawMaxX);
    host.innerHTML=`<svg viewBox="0 0 ${liveWidth} ${H}" role="img" aria-label="Live V10 accelerated paper equity, official frozen V8 holdout equity, and SPY"><line x1="${p.l}" y1="${y(NORMALIZED_BASE)}" x2="${liveWidth-p.r}" y2="${y(NORMALIZED_BASE)}" stroke="rgba(242,246,255,.34)" stroke-dasharray="5 6"/>${grid}${paths}${endLabels}<line data-a10-hover-line x1="0" y1="${p.t}" x2="0" y2="${H-p.b}" stroke="rgba(242,246,255,.52)" stroke-dasharray="3 4" opacity="0"/><text x="${p.l}" y="${H-10}" fill="#91a6c2" font-size="10">${firstLabel}</text><text x="${liveWidth-p.r}" y="${H-10}" text-anchor="end" fill="#91a6c2" font-size="10">${lastLabel}</text></svg>`;
    const officialStatus=official&&official.points.length?'official V8 holdout + accelerated V10/SPY':'accelerated V10/SPY · official V8 unavailable';
    set('[data-a10-live-range]',`${firstLabel} → ${lastLabel} · ${officialStatus}`);
  }

  const liveStage=section.querySelector('.a10-live-stage');
  liveStage?.addEventListener('pointermove',event=>{
    if(!liveHits.length||!liveRenderedSeries.length)return;
    const host=section.querySelector('[data-a10-live-chart]'),tip=section.querySelector('[data-a10-live-tooltip]');
    const rect=host.getBoundingClientRect(),px=(event.clientX-rect.left)*liveWidth/rect.width;
    const hit=liveHits.reduce((left,right)=>Math.abs(right.x-px)<Math.abs(left.x-px)?right:left);
    const guide=host.querySelector('[data-a10-hover-line]');
    guide?.setAttribute('x1',hit.x);guide?.setAttribute('x2',hit.x);guide?.setAttribute('opacity','1');
    const rows=liveRenderedSeries.map(item=>({
      item,
      point:nearestSeriesPoint(item.points,hit.time),
    }));
    tip.innerHTML=`<strong>Nearest forward values · ${dateTime(hit.time)}</strong>${rows.map(row=>{
      const start=NORMALIZED_BASE;
      return `<div><span>${row.item.label}</span><b>${money(row.point.value)} (${pct4(row.point.value/start-1)})</b></div>`;
    }).join('')}`;
    tip.style.left=`${Math.max(115,Math.min(rect.width-115,hit.x/liveWidth*rect.width))}px`;
    tip.style.top=`${Math.max(118,hit.top/H*rect.height)}px`;
    tip.classList.add('show');
  });
  liveStage?.addEventListener('pointerleave',()=>{
    section.querySelector('[data-a10-live-tooltip]')?.classList.remove('show');
    section.querySelector('[data-a10-hover-line]')?.setAttribute('opacity','0');
  });
  if(window.ResizeObserver)new ResizeObserver(()=>{
    if(livePayload)renderLiveChart(livePayload,officialV8Payload);
  }).observe(section.querySelector('[data-a10-live-chart]'));

  function renderEquity(curve) {
    const host = section.querySelector('[data-a10-equity-chart]');
    if (!host) return;
    const rows = Array.isArray(curve) ? curve.filter(row => Number.isFinite(Number(row.v10_normalized)) && Number.isFinite(Number(row.v8_normalized)) && Number.isFinite(Number(row.spy_normalized))) : [];
    if (rows.length < 2) {
      host.innerHTML = '<div class="a10-placeholder">The first point appears after one exit from each of the five cohort sleeves forms a complete block.</div>';
      return;
    }
    const W=920,H=260,p={l:66,r:24,t:18,b:38};
    const values=rows.flatMap(row=>[Number(row.v10_normalized),Number(row.v8_normalized),Number(row.spy_normalized)]);
    let lo=Math.min(...values,NORMALIZED_BASE),hi=Math.max(...values,NORMALIZED_BASE);
    const span=Math.max(hi-lo,200);lo-=span*.14;hi+=span*.14;
    const x=index=>p.l+(W-p.l-p.r)*index/(rows.length-1);
    const y=value=>p.t+(H-p.t-p.b)*(1-(value-lo)/(hi-lo));
    const points=key=>rows.map((row,index)=>`${x(index)},${y(Number(row[key]))}`).join(' ');
    const grid=[0,.25,.5,.75,1].map(ratio=>{
      const value=lo+(hi-lo)*(1-ratio),yy=p.t+(H-p.t-p.b)*ratio;
      return `<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="#60708a" opacity=".2"/><text x="${p.l-8}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value/1000)}k</text>`;
    }).join('');
    const labels=rows.map((row,index)=>`<text x="${x(index)}" y="${H-12}" fill="#91a6c2" font-size="10" text-anchor="middle">${row.block}</text>`).join('');
    const dots=[
      ['v10_normalized','#36d8ff','V10 accelerated'],
      ['v8_normalized','#efc56b','V8 control'],
      ['spy_normalized','#a78bfa','SPY'],
    ];
    const dotMarkup=dots.map(([key,color,label])=>rows.slice(1).map((row,offset)=>`<circle cx="${x(offset+1)}" cy="${y(Number(row[key]))}" r="3.5" fill="${color}"><title>${label} · Block ${row.block}: $${Math.round(Number(row[key])).toLocaleString()}</title></circle>`).join('')).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Complete-block V10, V8 control and SPY normalized comparison">${grid}<line x1="${p.l}" y1="${y(NORMALIZED_BASE)}" x2="${W-p.r}" y2="${y(NORMALIZED_BASE)}" stroke="#91a6c2" stroke-dasharray="5 5" opacity=".55"/>${svgLine(points('v10_normalized'),'#36d8ff',3.2)}${svgLine(points('v8_normalized'),'#efc56b',2.7)}${svgLine(points('spy_normalized'),'#a78bfa',2.7)}${dotMarkup}${labels}<text x="${(p.l+W-p.r)/2}" y="${H-1}" fill="#91a6c2" font-size="10" text-anchor="middle">Complete five-sleeve block</text></svg>`;
  }

  function renderEdges(edges) {
    const host = section.querySelector('[data-a10-edge-chart]');
    if (!host) return;
    const rows = Array.isArray(edges) ? edges.filter(row => Number.isFinite(Number(row.v10_minus_v8)) && Number.isFinite(Number(row.v10_minus_spy))) : [];
    if (!rows.length) {
      host.innerHTML = '<div class="a10-placeholder">Paired V10−V8 and V10−SPY bars appear when the first complete block closes.</div>';
      return;
    }
    const W=920,H=260,p={l:64,r:22,t:18,b:40};
    const maxAbs=Math.max(.001,...rows.flatMap(row=>[Math.abs(Number(row.v10_minus_v8)),Math.abs(Number(row.v10_minus_spy))]));
    const y=value=>p.t+(H-p.t-p.b)*(maxAbs-value)/(2*maxAbs);
    const zero=y(0),group=(W-p.l-p.r)/rows.length,barWidth=Math.min(24,group*.28);
    const ticks=[maxAbs,maxAbs/2,0,-maxAbs/2,-maxAbs].map(value=>`<line x1="${p.l}" y1="${y(value)}" x2="${W-p.r}" y2="${y(value)}" stroke="#60708a" opacity="${value === 0 ? .65 : .2}" ${value===0?'stroke-width="1.5"':''}/><text x="${p.l-8}" y="${y(value)+4}" fill="#91a6c2" font-size="10" text-anchor="end">${(value*100).toFixed(1)}%</text>`).join('');
    const bars=rows.map((row,index)=>{
      const center=p.l+group*(index+.5),values=[[Number(row.v10_minus_v8),'#39e3a1','V10 − V8'],[Number(row.v10_minus_spy),'#ff7ad9','V10 − SPY']];
      const rects=values.map(([value,color,label],seriesIndex)=>{
        const top=Math.min(zero,y(value)),height=Math.max(1,Math.abs(zero-y(value))),x=center+(seriesIndex===0?-barWidth-2:2);
        return `<rect x="${x}" y="${top}" width="${barWidth}" height="${height}" rx="2" fill="${color}"><title>${label} · Block ${row.block}: ${(value*100).toFixed(2)} percentage points</title></rect>`;
      }).join('');
      return `${rects}<text x="${center}" y="${H-14}" fill="#91a6c2" font-size="10" text-anchor="middle">${row.block}</text>`;
    }).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Paired V10 edge versus V8 and SPY by complete block">${ticks}${bars}<text x="${(p.l+W-p.r)/2}" y="${H-1}" fill="#91a6c2" font-size="10" text-anchor="middle">Complete five-sleeve block</text></svg>`;
  }

  function renderGates(gates) {
    const list = section.querySelector('[data-a10-gates]');
    if (!list) return;
    list.replaceChildren();
    (Array.isArray(gates) ? gates : []).forEach(gate => {
      const item=document.createElement('li');
      item.className=`a10-gate ${gate.passed===true?'pass':gate.passed===false?'fail':'waiting'}`;
      const label=document.createElement('span');label.textContent=gate.label || gate.id;
      const detail=document.createElement('small');
      let observed='Awaiting eligible evidence';
      if (gate.id==='operations') observed=gate.observed===true?'PASS':'ALERT';
      else if (gate.id==='defensive_count') observed=`${Number(gate.observed)||0} observed`;
      else if (gate.observed!=null) observed=pct(gate.observed);
      detail.textContent=`${gate.requirement} · ${observed} · target ${gate.target}`;
      const state=document.createElement('strong');state.textContent=gate.passed===true?'PASS':gate.passed===false?'BLOCKED':'WAITING';
      item.append(label,detail,state);list.appendChild(item);
    });
    if (!list.children.length) list.innerHTML='<li class="a10-placeholder">Gate status unavailable.</li>';
  }

  const NORMALIZED_BASE=100000;
  function renderDashboard(data,officialV8) {
      const current=Number.isFinite(Number(data.current_equity))?Number(data.current_equity):NORMALIZED_BASE;
      const currentReturn=Number.isFinite(Number(data.current_return))?Number(data.current_return):current/NORMALIZED_BASE-1;
      const officialV8Equity=officialV8&&finiteNumber(officialV8.current_equity)?Number(officialV8.current_equity):null;
      const officialV8Return=officialV8&&finiteNumber(officialV8.current_return)
        ? Number(officialV8.current_return)
        : (officialV8Equity==null?null:officialV8Equity/NORMALIZED_BASE-1);
      const currentExcessVsOfficialV8=officialV8Return==null?null:currentReturn-officialV8Return;
      const change=current-NORMALIZED_BASE;
      const signedMoney=`${change>=0?'+':'-'}${money(Math.abs(change))}`;
      const open=Number(data.open_cohorts)||0,priced=Number(data.priced_open_cohorts)||0;
      const valuation=dateTime(data.valuation_oldest_timestamp_utc||data.valuation_timestamp_utc);
      set('[data-a10-live-equity]',money(current));
      set('[data-a10-live-change]',data.equity_basis==='LIVE_MARK_TO_MARKET'?`CURRENT MARK · ${signedMoney} (${pct4(currentReturn)})`:statusText(data.equity_basis));
      set('[data-a10-live-sub]',`${money(NORMALIZED_BASE)} start · ${priced}/${open} open cohorts priced${valuation!=='—'?` · marks as of ${valuation}`:''}`);
      set('[data-a10-live-return]',pct4(currentReturn));
      set('[data-a10-live-v8]',pct4(officialV8Return));
      set('[data-a10-live-spy]',pct4(data.current_spy_return));
      set('[data-a10-live-excess-v8]',pct4(currentExcessVsOfficialV8));
      set('[data-a10-live-excess-spy]',pct4(data.current_excess_vs_spy));
      tone('[data-a10-live-change]',currentReturn);
      tone('[data-a10-live-return]',currentReturn);
      tone('[data-a10-live-v8]',officialV8Return);
      tone('[data-a10-live-spy]',data.current_spy_return);
      tone('[data-a10-live-excess-v8]',currentExcessVsOfficialV8);
      tone('[data-a10-live-excess-spy]',data.current_excess_vs_spy);
      renderLiveChart(data,officialV8);
      const blocks=Number(data.complete_five_sleeve_blocks)||0;
      const provisional=Number(data.minimum_blocks_for_provisional_review)||8;
      const stronger=Number(data.minimum_blocks_for_stronger_review)||12;
      const badge=section.querySelector('[data-a10-state]');
      if (badge) {
        badge.textContent=statusText(data.status);
        badge.classList.toggle('alert',data.current_run_health!==true);
      }
      set('[data-a10-first]',dateOnly(data.first_decision_session_utc));
      set('[data-a10-last]',dateOnly(data.last_decision_session_utc));
      set('[data-a10-january]',`${dateOnly(data.independent_confirmation_start_utc)} · unchanged`);
      set('[data-a10-provisional]',`${blocks} / ${provisional} complete blocks${data.provisional_review_eligible?' · REVIEW ELIGIBLE':''}`);
      set('[data-a10-stronger]',`${blocks} / ${stronger} complete blocks${data.stronger_review_eligible?' · REVIEW ELIGIBLE':''}`);
      progress('[data-a10-provisional-progress]',blocks,provisional);
      progress('[data-a10-stronger-progress]',blocks,stronger);
      set('[data-a10-decisions]',data.decisions ?? 0);
      set('[data-a10-entries]',data.entries ?? 0);
      set('[data-a10-exits]',data.completed_exits ?? 0);
      set('[data-a10-scored]',data.promotion_scored_exits ?? 0);
      set('[data-a10-blocks]',blocks);
      set('[data-a10-return]',pct(data.mean_net_return_after_cost));
      set('[data-a10-v8-edge]',pct(data.mean_v10_minus_v8_net_return));
      set('[data-a10-spy-edge]',pct(data.mean_v10_minus_spy_return));
      set('[data-a10-drawdown]',data.v10_max_cohort_drawdown==null?'—':`${unsignedPct(data.v10_max_cohort_drawdown)} / ${unsignedPct(data.v8_max_cohort_drawdown)}`);
      set('[data-a10-defensive-exits]',data.completed_defensive_exits ?? 0);
      set('[data-a10-defensive-edge]',pct(data.mean_defensive_v10_minus_v8_net_return));
      renderEquity(data.block_curve);
      renderEdges(data.block_edges);
      renderGates(data.promotion_gates);
      const checked=data.operational_checked_at_utc?new Date(data.operational_checked_at_utc).toLocaleString():'not yet published';
      set('[data-a10-method]',`${data.method_note} Evidence: ${statusText(data.evidence_status)}. Current run: ${statusText(data.current_run_status)}. Study integrity: ${statusText(data.study_integrity_status)} · checked ${checked} · scheduler every ${Math.round((Number(data.scheduler_interval_seconds)||300)/60)} minutes.`);
      set('[data-a10-frozen-sha]',data.frozen_sha256 || '—');
      set('[data-a10-contract-sha]',data.contract_sha256 || '—');
      set('[data-a10-paper]',data.paper_trading_only === true ? 'YES' : 'NO');
      set('[data-a10-auto-promotion]',data.automatic_promotion === true ? 'YES' : 'NO');
      set('[data-a10-human-review]',data.human_review_required === true ? 'YES' : 'NO');
      set('[data-a10-brokerage]',data.brokerage_orders === true ? 'ON' : 'OFF');
      set('[data-a10-runner]',data.runner_invoked === true ? 'YES' : 'NO');
      set('[data-a10-january-modified]',data.january_confirmation_modified === true ? 'YES' : 'NO');
      set('[data-a10-current-health]',statusText(data.current_run_status));
      set('[data-a10-study-integrity]',statusText(data.study_integrity_status));
      set('[data-a10-feature-backend]',statusText(data.feature_backend));
      set('[data-a10-source-session]',data.latest_source_session || '—');
      set('[data-a10-expected-source]',data.expected_latest_completed_session || '—');
      set('[data-a10-source-coverage]',`${data.source_price_symbols_available ?? '—'} / ${data.source_price_symbols_required ?? '—'}`);
      set('[data-a10-next-event]',statusText(data.next_expected_lifecycle_event));
      set('[data-a10-pending]',`${data.pending_entry_count ?? 0} / ${data.pending_exit_count ?? 0}`);
      const alerts=section.querySelector('[data-a10-alerts]');
      const currentFailures=Array.isArray(data.current_run_operational_failures)?data.current_run_operational_failures:[];
      const historicalFailures=Array.isArray(data.historical_integrity_failures)?data.historical_integrity_failures:[];
      if (alerts) {
        const messages=[];
        currentFailures.forEach(failure=>messages.push(`Current-run alert: ${statusText(failure)}.`));
        historicalFailures.forEach(failure=>{
          messages.push(`V2 study-integrity alert: ${statusText(failure)}.`);
        });
        alerts.hidden=!messages.length;
        alerts.textContent=messages.join(' ');
      }
  }

  function renderError(error) {
      set('[data-a10-state]','STATUS UNAVAILABLE');
      const badge=section.querySelector('[data-a10-state]');if(badge)badge.classList.add('alert');
      set('[data-a10-method]',`The accelerated read-only endpoint could not be reached. No runner was invoked. ${error.message}`);
  }

  const fetchOfficialV8 = () => {
    if(window.DataShepherdV8Snapshot?.get){
      return window.DataShepherdV8Snapshot.get({force:true}).catch(()=>null);
    }
    return fetch('/api/v8/holdout',{credentials:'same-origin',cache:'no-store'})
      .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();})
      .catch(()=>null);
  };

  function refresh() {
    Promise.all([
      fetch('/api/v10/cycle3/accelerated-v2',{credentials:'same-origin',cache:'no-store'})
        .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();}),
      fetchOfficialV8(),
    ])
      .then(([data,officialV8])=>renderDashboard(data,officialV8))
      .catch(renderError);
  }
  refresh();
  setInterval(refresh,15000);
})();
