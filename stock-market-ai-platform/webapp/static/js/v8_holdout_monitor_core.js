(() => {
  const root = document.getElementById('v8-holdout-monitor');
  if (!root) return;
  const style = document.createElement('style');
  style.id = 'v8-forward-performance-style';
  style.textContent = `
    #v8-holdout-monitor .panel-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}
    .v8h-evidence{padding:8px 11px;border:1px solid rgba(239,197,107,.3);border-radius:999px;background:rgba(239,197,107,.08);color:var(--gold);font-size:.69rem;font-weight:950;letter-spacing:.06em}
    .v8h-evidence.mature{border-color:rgba(57,227,161,.35);background:rgba(57,227,161,.08);color:var(--green)}
    .v8h-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
    .v8h-card{padding:12px;border:1px solid rgba(120,155,205,.16);border-radius:12px;background:rgba(7,16,31,.48)}
    .v8h-label{font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}.v8h-value{font-size:1rem;font-weight:850;margin-top:4px}
    .v8h-positive{color:var(--green)}.v8h-negative{color:#ff6680}
    .v8h-legend{display:flex;align-items:center;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:.72rem;margin:8px 0}
    .v8h-legend span{display:flex;align-items:center;gap:7px}.v8h-line{display:inline-block;width:24px;border-top:3px solid}.v8h-line-v8{border-color:var(--gold)}.v8h-line-spy{border-color:#a78bfa;border-top-style:dashed}
    .v8h-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.68rem;word-break:break-all;color:var(--muted);margin-top:9px}
    .v8h-chart{position:relative;height:390px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.45);overflow:hidden;margin-top:10px}
    .v8h-chart svg{width:100%;height:100%;display:block}.v8h-empty{padding:32px;color:var(--muted);line-height:1.55}.v8h-empty strong{display:block;color:var(--gold);margin-bottom:5px}
    .v8h-tooltip{position:absolute;display:none;pointer-events:none;z-index:5;min-width:210px;padding:10px 12px;border:1px solid #2a5277;border-radius:11px;background:rgba(7,21,39,.97);box-shadow:0 14px 32px rgba(0,0,0,.4);font-size:.73rem;color:#f2f6ff}
    .v8h-tooltip strong{display:block;margin-bottom:5px}.v8h-tip-row{display:flex;justify-content:space-between;gap:16px;margin-top:3px}.v8h-method{padding:9px 11px;margin-top:9px;border:1px solid rgba(120,155,205,.14);border-radius:10px;background:rgba(8,20,36,.42);color:var(--muted);font-size:.72rem;line-height:1.45}
    .v8h-note{font-size:.73rem;color:var(--muted);margin-top:8px;line-height:1.5}
    @media(max-width:800px){.v8h-chart{height:310px}}
  `;
  document.getElementById(style.id)?.remove();
  document.head.appendChild(style);

  const fmtPct = v => v == null ? '—' : `${v>=0?'+':''}${(100*v).toFixed(2)}%`;
  const fmtNumber = v => v == null ? '—' : Number(v).toFixed(2);
  const fmtMoney = v => '$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const set = (selector,value) => { const el=root.querySelector(selector); if(el)el.textContent=value; };
  const colorMetric = (selector,value) => {
    const el=root.querySelector(selector); if(!el)return;
    el.textContent=fmtPct(value); el.classList.remove('v8h-positive','v8h-negative');
    if(value!=null)el.classList.add(value>=0?'v8h-positive':'v8h-negative');
  };

  function evidenceLabel(status,count,minimum){
    if(status==='NO_COMPLETED_COHORTS')return 'NO COMPLETED COHORTS';
    if(status==='INSUFFICIENT_EVIDENCE')return `INSUFFICIENT EVIDENCE · ${count}/${minimum}`;
    if(status==='EARLY_EVIDENCE')return 'EARLY FORWARD EVIDENCE';
    return 'FORWARD EVIDENCE ACCUMULATING';
  }

  function draw(curve,evidenceStatus){
    const box=root.querySelector('.v8h-chart'); if(!box)return;
    box.innerHTML='';
    if(!curve.length){
      box.innerHTML=`<div class="v8h-empty"><strong>${evidenceStatus==='NO_COMPLETED_COHORTS'?'No completed forward cohorts yet':'Forward curve pending'}</strong>The chart begins only after a genuine post-September 1 cohort completes its next-open entry and five-session holding lifecycle.</div>`;
      return;
    }
    const rows=[{timestamp_utc:null,strategy_normalized:100000,spy_normalized:100000},...curve];
    const W=1200,H=390,p={l:82,r:118,t:28,b:55}; const vals=rows.flatMap(x=>[x.strategy_normalized,x.spy_normalized,100000]);
    let lo=Math.min(...vals),hi=Math.max(...vals); const span=Math.max(500,hi-lo);lo-=span*.18;hi+=span*.18;
    const x=i=>p.l+(W-p.l-p.r)*(i/Math.max(1,rows.length-1)); const y=v=>p.t+(H-p.t-p.b)*(1-(v-lo)/(hi-lo));
    const ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('preserveAspectRatio','none');box.appendChild(svg);
    const make=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));svg.appendChild(n);return n;};
    for(let i=0;i<5;i++){const val=lo+(hi-lo)*i/4,yy=y(val);make('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.15)'});const t=make('text',{x:p.l-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});t.textContent='$'+Math.round(val).toLocaleString();}
    const path=k=>rows.map((d,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(d[k]).toFixed(1)}`).join(' ');
    make('path',{d:path('strategy_normalized'),fill:'none',stroke:'#efc56b','stroke-width':3.5,'stroke-linecap':'round','stroke-linejoin':'round'});
    make('path',{d:path('spy_normalized'),fill:'none',stroke:'#a78bfa','stroke-width':2.5,'stroke-dasharray':'8 6','stroke-linecap':'round'});
    const last=rows.at(-1),lx=x(rows.length-1);
    [['V8',last.strategy_normalized,'#efc56b'],['SPY',last.spy_normalized,'#a78bfa']].forEach(([name,value,color],i)=>{const t=make('text',{x:lx+10,y:y(value)+(i?14:-7),fill:color,'font-size':12,'font-weight':900});t.textContent=`${name} ${fmtMoney(value)}`;});
    const startText=make('text',{x:p.l,y:H-18,'text-anchor':'start',fill:'#91a6c2','font-size':10});startText.textContent='Start';
    const endText=make('text',{x:W-p.r,y:H-18,'text-anchor':'end',fill:'#91a6c2','font-size':10});endText.textContent=new Date(rows.at(-1).timestamp_utc).toLocaleDateString();
    const guide=make('line',{y1:p.t,y2:H-p.b,stroke:'#dfe8f6','stroke-dasharray':'4 4',opacity:.45,visibility:'hidden'});
    const dotV8=make('circle',{r:5,fill:'#efc56b',stroke:'#07101f','stroke-width':2,visibility:'hidden'});
    const dotSpy=make('circle',{r:5,fill:'#a78bfa',stroke:'#07101f','stroke-width':2,visibility:'hidden'});
    const overlay=make('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'rgba(0,0,0,.001)','pointer-events':'all'});
    const tip=document.createElement('div');tip.className='v8h-tooltip';box.appendChild(tip);
    overlay.addEventListener('pointermove',e=>{const rect=svg.getBoundingClientRect();const mx=(e.clientX-rect.left)/rect.width*W;const idx=Math.max(0,Math.min(rows.length-1,Math.round((mx-p.l)/(W-p.l-p.r)*(rows.length-1))));const row=rows[idx],xx=x(idx);guide.setAttribute('x1',xx);guide.setAttribute('x2',xx);guide.setAttribute('visibility','visible');[[dotV8,row.strategy_normalized],[dotSpy,row.spy_normalized]].forEach(([dot,value])=>{dot.setAttribute('cx',xx);dot.setAttribute('cy',y(value));dot.setAttribute('visibility','visible');});const when=idx===0?'Normalized start':new Date(row.timestamp_utc).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});tip.innerHTML=`<strong>${when}</strong><div class="v8h-tip-row"><span>Frozen V8</span><b>${fmtMoney(row.strategy_normalized)}</b></div><div class="v8h-tip-row"><span>SPY</span><b>${fmtMoney(row.spy_normalized)}</b></div>`;tip.style.display='block';tip.style.left=Math.min(e.clientX-box.getBoundingClientRect().left+12,box.clientWidth-225)+'px';tip.style.top=Math.max(8,e.clientY-box.getBoundingClientRect().top-64)+'px';});
    overlay.addEventListener('pointerleave',()=>{tip.style.display='none';guide.setAttribute('visibility','hidden');dotV8.setAttribute('visibility','hidden');dotSpy.setAttribute('visibility','hidden');});
  }

  async function refresh(){
    try{
      const d=await window.DataShepherdV8Snapshot.get();
      set('[data-v8h-state]',String(d.state||'UNKNOWN').replaceAll('_',' '));
      set('[data-v8h-decisions]',d.decisions??0);set('[data-v8h-entries]',d.entries??0);set('[data-v8h-exits]',d.completed_cohorts??0);
      colorMetric('[data-v8h-v8-return]',d.strategy_total_return);colorMetric('[data-v8h-spy-return]',d.spy_total_return);colorMetric('[data-v8h-edge]',d.total_relative_return);
      set('[data-v8h-hit]',fmtPct(d.net_relative_hit_rate));colorMetric('[data-v8h-drawdown]',d.max_drawdown);set('[data-v8h-volatility]',fmtPct(d.cohort_return_volatility));set('[data-v8h-sharpe]',fmtNumber(d.diagnostic_annualized_sharpe));
      set('[data-v8h-sha]',d.frozen_sha256);set('[data-v8h-start]',d.holdout_start_utc.replace('T00:00:00+00:00',''));
      const evidence=root.querySelector('[data-v8h-evidence]');evidence.textContent=evidenceLabel(d.evidence_status,d.completed_cohorts,d.minimum_completed_cohorts_for_early_read);evidence.classList.toggle('mature',['EARLY_EVIDENCE','EVIDENCE_ACCUMULATING'].includes(d.evidence_status));
      set('[data-v8h-method]',d.metric_note||'Completed five-session forward cohorts after modeled costs.');
      draw(d.curve||[],d.evidence_status);
    }catch(e){set('[data-v8h-state]','MONITOR ERROR');console.error(e);}
  }
  refresh(); setInterval(refresh,30000);
})();

/* Additive V4 portfolio-equity chart. This intentionally leaves the existing model-comparison panel untouched. */
(() => {
  const metrics = document.querySelector('.v4-dashboard .v4-small-metrics');
  if (!metrics || document.getElementById('v4-compact-equity-card')) return;

  const style = document.createElement('style');
  style.id = 'v4-compact-equity-style';
  style.textContent = `
    .v4-compact-equity{margin-top:20px;padding:18px 16px 16px;border:1px solid var(--border);border-radius:18px;background:rgba(8,20,36,.72);box-shadow:0 14px 34px rgba(0,0,0,.18);min-width:0}
    .v4-compact-equity-title{color:var(--cyan);font-size:.72rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase}
    .v4-compact-equity-sub{margin-top:6px;color:var(--muted);font-size:.78rem;line-height:1.4}
    .v4-compact-equity-legend{display:flex;align-items:center;gap:8px;margin-top:12px;color:#dfe8f6;font-size:.76rem;font-weight:800}
    .v4-compact-equity-dot{width:10px;height:10px;border-radius:50%;background:var(--green);box-shadow:0 0 12px rgba(57,227,161,.28)}
    .v4-compact-equity-wrap{position:relative;height:340px;margin-top:8px}
    .v4-compact-equity-wrap svg{width:100%;height:100%;display:block;overflow:visible;cursor:crosshair}
    .v4-compact-equity-tooltip{position:absolute;display:none;pointer-events:none;z-index:20;min-width:180px;padding:11px 12px;border:1px solid #2a5277;border-radius:12px;background:rgba(7,21,39,.97);box-shadow:0 16px 36px rgba(0,0,0,.38);font-size:.75rem;line-height:1.45;color:#f2f6ff}
    .v4-compact-equity-tooltip strong{display:block;margin-bottom:5px;font-size:.8rem}.v4-compact-equity-tooltip-row{display:flex;justify-content:space-between;gap:16px}.v4-compact-equity-tooltip-name{display:flex;align-items:center;gap:7px}.v4-compact-equity-tooltip-value{font-weight:900}
    .v4-compact-equity-summary{display:grid;grid-template-columns:1fr;gap:9px;border-top:1px solid rgba(120,155,205,.16);padding-top:13px;margin-top:8px}
    .v4-compact-equity-summary-row{display:flex;justify-content:space-between;gap:12px;align-items:baseline}.v4-compact-equity-summary-row span{color:var(--muted);font-size:.66rem;font-weight:900;letter-spacing:.08em}.v4-compact-equity-summary-row strong{font-size:.9rem;text-align:right}
    @media(max-width:1000px){.v4-compact-equity-wrap{height:320px}}
  `;
  document.head.appendChild(style);

  const card = document.createElement('div');
  card.id = 'v4-compact-equity-card';
  card.className = 'v4-compact-equity';
  card.innerHTML = `
    <div class="v4-compact-equity-title">PORTFOLIO EQUITY OVER TIME</div>
    <div class="v4-compact-equity-sub">Recorded V4 journal equity plus the current read-only mark-to-market point.</div>
    <div class="v4-compact-equity-legend"><span class="v4-compact-equity-dot"></span><span>V4 Paper Portfolio</span></div>
    <div class="v4-compact-equity-wrap">
      <svg id="v4-compact-equity-chart" viewBox="0 0 420 340" preserveAspectRatio="none" aria-label="V4 portfolio equity over time"></svg>
      <div id="v4-compact-equity-tooltip" class="v4-compact-equity-tooltip"></div>
    </div>
    <div class="v4-compact-equity-summary">
      <div class="v4-compact-equity-summary-row"><span>STARTING EQUITY</span><strong id="v4-compact-start">—</strong></div>
      <div class="v4-compact-equity-summary-row"><span>CURRENT EQUITY</span><strong id="v4-compact-current">—</strong></div>
      <div class="v4-compact-equity-summary-row"><span>NET CHANGE</span><strong id="v4-compact-change">—</strong></div>
    </div>`;
  metrics.insertAdjacentElement('afterend', card);

  const svg = card.querySelector('#v4-compact-equity-chart');
  const tooltip = card.querySelector('#v4-compact-equity-tooltip');
  const ns = 'http://www.w3.org/2000/svg';
  const money = v => '$' + Number(v || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const signedMoney = v => (Number(v)>=0?'+':'-') + '$' + Math.abs(Number(v||0)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const signedPct = v => (Number(v)>=0?'+':'') + (Number(v||0)*100).toFixed(2) + '%';
  const make = (tag,attrs={}) => { const n=document.createElementNS(ns,tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v))); svg.appendChild(n); return n; };

  function render(history, startingEquity) {
    svg.innerHTML = '';
    tooltip.style.display = 'none';
    if (!history || history.length < 2) {
      const t=make('text',{x:210,y:170,'text-anchor':'middle',fill:'#91a6c2','font-size':12});
      t.textContent='More observations are needed.';
      return;
    }

    const W=420,H=340,p={l:62,r:18,t:22,b:42};
    const rows=history.map(r=>({...r,equity:Number(r.equity)})).filter(r=>Number.isFinite(r.equity));
    const values=rows.map(r=>r.equity);
    let min=Math.min(...values,startingEquity),max=Math.max(...values,startingEquity);
    const span=Math.max(max-min,Math.max(100,startingEquity*.002));
    min-=span*.18; max+=span*.18;
    const x=i=>p.l+(W-p.l-p.r)*(i/Math.max(1,rows.length-1));
    const y=v=>p.t+(H-p.t-p.b)*(1-(v-min)/Math.max(.000001,max-min));

    for(let i=0;i<5;i++){
      const val=min+(max-min)*i/4, yy=y(val);
      make('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.15)','stroke-width':1});
      const t=make('text',{x:p.l-8,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':10});
      t.textContent='$'+Math.round(val).toLocaleString();
    }

    const baselineY=y(startingEquity);
    make('line',{x1:p.l,y1:baselineY,x2:W-p.r,y2:baselineY,stroke:'#91a6c2','stroke-width':1.2,'stroke-dasharray':'5 5',opacity:.75});

    const pts=rows.map((r,i)=>[x(i),y(r.equity)]);
    make('polyline',{points:pts.map(q=>q.join(',')).join(' '),fill:'none',stroke:'#39e3a1','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'});

    const guide=make('line',{y1:p.t,y2:H-p.b,stroke:'#dfe8f6','stroke-width':1,'stroke-dasharray':'4 4',opacity:.45,visibility:'hidden'});
    const marker=make('circle',{r:5.5,fill:'#39e3a1',stroke:'#07101f','stroke-width':2,visibility:'hidden'});
    const overlay=make('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'rgba(0,0,0,.001)','pointer-events':'all'});

    const labels=[0,Math.floor((rows.length-1)/2),rows.length-1];
    labels.forEach((idx,pos)=>{
      const row=rows[idx], t=make('text',{x:x(idx),y:H-16,'text-anchor':pos===0?'start':pos===2?'end':'middle',fill:'#91a6c2','font-size':9.5});
      t.textContent=row.label || (row.timestamp ? new Date(row.timestamp).toLocaleDateString(undefined,{month:'numeric',day:'numeric'}) : (pos===0?'Start':pos===2?'Current':''));
    });

    function inspect(e){
      const rect=svg.getBoundingClientRect();
      const mx=(e.clientX-rect.left)/rect.width*W;
      const raw=(mx-p.l)/(W-p.l-p.r)*Math.max(1,rows.length-1);
      const idx=Math.max(0,Math.min(rows.length-1,Math.round(raw)));
      const row=rows[idx], xx=x(idx), yy=y(row.equity);
      guide.setAttribute('x1',xx); guide.setAttribute('x2',xx); guide.setAttribute('visibility','visible');
      marker.setAttribute('cx',xx); marker.setAttribute('cy',yy); marker.setAttribute('visibility','visible');
      const when=row.label || (row.timestamp ? new Date(row.timestamp).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'}) : 'Portfolio observation');
      tooltip.innerHTML=`<strong>${when}</strong><div class="v4-compact-equity-tooltip-row"><span class="v4-compact-equity-tooltip-name"><span class="v4-compact-equity-dot"></span>V4</span><span class="v4-compact-equity-tooltip-value">${money(row.equity)}</span></div>`;
      tooltip.style.display='block';
      const host=card.querySelector('.v4-compact-equity-wrap').getBoundingClientRect();
      tooltip.style.left=Math.min(e.clientX-host.left+10,host.width-195)+'px';
      tooltip.style.top=Math.max(6,e.clientY-host.top-58)+'px';
    }
    overlay.addEventListener('pointermove',inspect);
    overlay.addEventListener('pointerleave',()=>{tooltip.style.display='none';guide.setAttribute('visibility','hidden');marker.setAttribute('visibility','hidden');});
  }

  async function load(){
    try{
      const r=await fetch('/api/v4-forward',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const d=await r.json(), f=d.forward||{}, p=d.portfolio||{};
      const start=Number(p.starting_cash||f.starting_equity||100000);
      const current=Number(p.equity||f.ending_equity||start);
      const gain=current-start, gainPct=start?gain/start:0;
      let history=Array.isArray(f.equity_history)?f.equity_history.slice():[];
      history=history.filter(row=>Number.isFinite(Number(row.equity)));
      if(!history.length || Math.abs(Number(history[0].equity)-start)>.0001) history.unshift({label:'Start',equity:start});
      else history[0]={...history[0],label:history[0].label||'Start'};
      if(!history.length || Math.abs(Number(history.at(-1).equity)-current)>.0001) history.push({label:'Current',equity:current,timestamp:new Date().toISOString()});
      else history[history.length-1]={...history.at(-1),label:'Current'};
      card.querySelector('#v4-compact-start').textContent=money(start);
      card.querySelector('#v4-compact-current').textContent=money(current);
      const change=card.querySelector('#v4-compact-change');
      change.textContent=`${signedMoney(gain)} (${signedPct(gainPct)})`;
      change.className=gain<0?'negative':'positive';
      render(history,start);
    }catch(e){
      console.error('Compact V4 equity chart failed:',e);
      svg.innerHTML=''; const t=make('text',{x:210,y:170,'text-anchor':'middle',fill:'#91a6c2','font-size':12}); t.textContent='Portfolio equity history unavailable.';
    }
  }

  load();
  setInterval(load,30000);
})();

/* The standalone latest-model equity chart is superseded by the full-width model comparison. */
(() => {
  document.getElementById('v8-compact-equity-card')?.remove();
  return;

  const metrics = document.querySelector('.v4-dashboard .v4-small-metrics');
  if (!metrics || document.getElementById('v8-compact-equity-card')) return;

  const style = document.createElement('style');
  style.id = 'v8-compact-equity-style';
  style.textContent = `
    .v8-compact-equity{margin-top:20px;padding:18px 16px 16px;border:1px solid var(--border);border-radius:18px;background:rgba(8,20,36,.72);box-shadow:0 14px 34px rgba(0,0,0,.18);min-width:0}
    .v8-compact-equity-title{color:var(--cyan);font-size:.72rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase}
    .v8-compact-equity-sub{margin-top:6px;color:var(--muted);font-size:.78rem;line-height:1.4}
    .v8-compact-equity-legend{display:flex;align-items:center;gap:8px;margin-top:12px;color:#dfe8f6;font-size:.76rem;font-weight:800}
    .v8-compact-equity-dot{width:10px;height:10px;border-radius:50%;background:var(--gold);box-shadow:0 0 12px rgba(239,197,107,.28)}
    .v8-compact-equity-wrap{position:relative;height:340px;margin-top:8px}
    .v8-compact-equity-wrap svg{width:100%;height:100%;display:block;overflow:visible;cursor:crosshair}
    .v8-compact-equity-tooltip{position:absolute;display:none;pointer-events:none;z-index:20;min-width:190px;padding:11px 12px;border:1px solid #2a5277;border-radius:12px;background:rgba(7,21,39,.97);box-shadow:0 16px 36px rgba(0,0,0,.38);font-size:.75rem;line-height:1.45;color:#f2f6ff}
    .v8-compact-equity-tooltip strong{display:block;margin-bottom:5px;font-size:.8rem}.v8-compact-equity-tooltip-row{display:flex;justify-content:space-between;gap:16px}.v8-compact-equity-tooltip-name{display:flex;align-items:center;gap:7px}.v8-compact-equity-tooltip-value{font-weight:900}
    .v8-compact-equity-summary{display:grid;grid-template-columns:1fr;gap:9px;border-top:1px solid rgba(120,155,205,.16);padding-top:13px;margin-top:8px}
    .v8-compact-equity-summary-row{display:flex;justify-content:space-between;gap:12px;align-items:baseline}.v8-compact-equity-summary-row span{color:var(--muted);font-size:.66rem;font-weight:900;letter-spacing:.08em}.v8-compact-equity-summary-row strong{font-size:.9rem;text-align:right}
  `;
  document.head.appendChild(style);

  const card = document.createElement('div');
  card.id = 'v8-compact-equity-card';
  card.className = 'v8-compact-equity';
  card.innerHTML = `
    <div class="v8-compact-equity-title">PORTFOLIO EQUITY OVER TIME — LATEST MODEL</div>
    <div class="v8-compact-equity-sub">Frozen V8 historical strategy equity on the same $100,000 research basis used by Model Performance Comparison.</div>
    <div class="v8-compact-equity-legend"><span class="v8-compact-equity-dot"></span><span>V8 Frozen</span></div>
    <div class="v8-compact-equity-wrap">
      <svg id="v8-compact-equity-chart" viewBox="0 0 420 340" preserveAspectRatio="none" aria-label="V8 frozen portfolio equity over time"></svg>
      <div id="v8-compact-equity-tooltip" class="v8-compact-equity-tooltip"></div>
    </div>
    <div class="v8-compact-equity-summary">
      <div class="v8-compact-equity-summary-row"><span>STARTING EQUITY</span><strong id="v8-compact-start">—</strong></div>
      <div class="v8-compact-equity-summary-row"><span>LATEST EQUITY</span><strong id="v8-compact-current">—</strong></div>
      <div class="v8-compact-equity-summary-row"><span>TOTAL RETURN</span><strong id="v8-compact-change">—</strong></div>
    </div>`;

  const existingV4 = document.getElementById('v4-compact-equity-card');
  if (existingV4) existingV4.insertAdjacentElement('beforebegin', card);
  else metrics.insertAdjacentElement('afterend', card);

  const svg = card.querySelector('#v8-compact-equity-chart');
  const tooltip = card.querySelector('#v8-compact-equity-tooltip');
  const ns='http://www.w3.org/2000/svg';
  const money=v=>'$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const pct=v=>(Number(v)>=0?'+':'')+Number(v||0).toFixed(2)+'%';
  const make=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));svg.appendChild(n);return n;};

  function render(rows){
    svg.innerHTML=''; tooltip.style.display='none';
    if(!rows || rows.length<2){const t=make('text',{x:210,y:170,'text-anchor':'middle',fill:'#91a6c2','font-size':12});t.textContent='V8 history unavailable.';return;}
    const W=420,H=340,p={l:64,r:18,t:22,b:42};
    const values=rows.map(r=>r.equity); let min=Math.min(...values),max=Math.max(...values); const span=Math.max(max-min,1000); min-=span*.08; max+=span*.08;
    const x=i=>p.l+(W-p.l-p.r)*(i/Math.max(1,rows.length-1)); const y=v=>p.t+(H-p.t-p.b)*(1-(v-min)/Math.max(.000001,max-min));
    for(let i=0;i<5;i++){const val=min+(max-min)*i/4,yy=y(val);make('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.15)','stroke-width':1});const t=make('text',{x:p.l-8,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':10});t.textContent='$'+Math.round(val).toLocaleString();}
    const pts=rows.map((r,i)=>[x(i),y(r.equity)]);make('polyline',{points:pts.map(q=>q.join(',')).join(' '),fill:'none',stroke:'#efc56b','stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'});
    const guide=make('line',{y1:p.t,y2:H-p.b,stroke:'#dfe8f6','stroke-width':1,'stroke-dasharray':'4 4',opacity:.45,visibility:'hidden'});const marker=make('circle',{r:5.5,fill:'#efc56b',stroke:'#07101f','stroke-width':2,visibility:'hidden'});const overlay=make('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'rgba(0,0,0,.001)','pointer-events':'all'});
    [0,Math.floor((rows.length-1)/2),rows.length-1].forEach((idx,pos)=>{const row=rows[idx],t=make('text',{x:x(idx),y:H-16,'text-anchor':pos===0?'start':pos===2?'end':'middle',fill:'#91a6c2','font-size':9.5});t.textContent=new Date(row.timestamp).toLocaleDateString(undefined,{month:'numeric',day:'numeric',year:'2-digit'});});
    overlay.addEventListener('pointermove',e=>{const rect=svg.getBoundingClientRect();const mx=(e.clientX-rect.left)/rect.width*W;const idx=Math.max(0,Math.min(rows.length-1,Math.round((mx-p.l)/(W-p.l-p.r)*Math.max(1,rows.length-1))));const row=rows[idx],xx=x(idx),yy=y(row.equity);guide.setAttribute('x1',xx);guide.setAttribute('x2',xx);guide.setAttribute('visibility','visible');marker.setAttribute('cx',xx);marker.setAttribute('cy',yy);marker.setAttribute('visibility','visible');tooltip.innerHTML=`<strong>${new Date(row.timestamp).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'})}</strong><div class="v8-compact-equity-tooltip-row"><span class="v8-compact-equity-tooltip-name"><span class="v8-compact-equity-dot"></span>V8</span><span class="v8-compact-equity-tooltip-value">${money(row.equity)}</span></div>`;tooltip.style.display='block';const host=card.querySelector('.v8-compact-equity-wrap').getBoundingClientRect();tooltip.style.left=Math.min(e.clientX-host.left+10,host.width-205)+'px';tooltip.style.top=Math.max(6,e.clientY-host.top-58)+'px';});
    overlay.addEventListener('pointerleave',()=>{tooltip.style.display='none';guide.setAttribute('visibility','hidden');marker.setAttribute('visibility','hidden');});
  }

  async function load(){
    try{
      const r=await fetch('/static/generated/stock_model_comparison.json',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`); const d=await r.json();
      const s=(d.series||[]).find(x=>x.model_id==='V8'); if(!s)throw new Error('V8 series missing');
      const rows=(s.history||[]).map(x=>({timestamp:x.timestamp,equity:Number(x.equity)})).filter(x=>x.timestamp&&Number.isFinite(x.equity)).sort((a,b)=>Date.parse(a.timestamp)-Date.parse(b.timestamp));
      if(rows.length<2)throw new Error('V8 history unavailable');
      const start=Number(s.starting_capital||rows[0].equity||100000), current=rows.at(-1).equity, totalReturn=Number(s.total_return_pct ?? ((current/start-1)*100));
      card.querySelector('#v8-compact-start').textContent=money(start);
      card.querySelector('#v8-compact-current').textContent=money(current);
      const change=card.querySelector('#v8-compact-change'); change.textContent=pct(totalReturn); change.className=totalReturn<0?'negative':'positive';
      render(rows);
    }catch(e){console.error('Compact V8 equity chart failed:',e);svg.innerHTML='';const t=make('text',{x:210,y:170,'text-anchor':'middle',fill:'#91a6c2','font-size':12});t.textContent='V8 portfolio history unavailable.';}
  }
  load();
})();

/* Interactive controls for the frozen V8 model-structure card. */
(() => {
  let attempts = 0;
  const boot = () => {
    const card = document.getElementById('v8-portfolio-structure');
    if (!card) {
      attempts += 1;
      if (attempts < 150) setTimeout(boot, 100);
      return;
    }
    if (document.getElementById('v8-structure-interactive')) return;

    const style = document.createElement('style');
    style.id = 'v8-structure-interactive-style';
    style.textContent = `
      #v8-portfolio-structure .v4-donut{cursor:pointer;transition:transform .18s ease,filter .18s ease}
      #v8-portfolio-structure .v4-donut:hover{transform:scale(1.035);filter:brightness(1.08)}
      .v8si-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0 12px}.v8si-tab{border:1px solid var(--border);background:rgba(8,20,36,.62);color:var(--muted);border-radius:999px;padding:8px 11px;font-weight:850;cursor:pointer}.v8si-tab.active,.v8si-tab:hover{color:#07101f;background:linear-gradient(90deg,var(--gold),var(--cyan));border-color:transparent}
      .v8si-panel{padding:13px 14px;border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(7,16,31,.42);min-height:118px}.v8si-title{font-weight:900;margin-bottom:6px}.v8si-copy{color:var(--muted);font-size:.8rem;line-height:1.5}
      .v8si-positions{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;margin-top:11px}.v8si-position{padding:8px 5px;border:1px solid rgba(239,197,107,.24);border-radius:10px;background:rgba(239,197,107,.07);text-align:center;cursor:pointer;color:var(--text);font-weight:850}.v8si-position:hover,.v8si-position.active{background:rgba(239,197,107,.18);border-color:rgba(239,197,107,.65)}
      .v8si-cohorts{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:10px}.v8si-cohort{height:10px;border-radius:999px;background:rgba(54,216,255,.22);overflow:hidden}.v8si-cohort span{display:block;height:100%;background:var(--cyan)}
      .v8si-live{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:10px}.v8si-live div{padding:9px;border:1px solid rgba(120,155,205,.14);border-radius:10px;background:rgba(8,20,36,.5)}.v8si-live span{display:block;color:var(--muted);font-size:.62rem;font-weight:900;letter-spacing:.07em}.v8si-live strong{display:block;margin-top:3px;font-size:.9rem}
      @media(max-width:650px){.v8si-positions{grid-template-columns:repeat(2,1fr)}.v8si-live{grid-template-columns:1fr}}
    `;
    document.getElementById(style.id)?.remove();
    document.head.appendChild(style);

    const host = document.createElement('div');
    host.id = 'v8-structure-interactive';
    host.innerHTML = `
      <div class="v8si-tabs" role="tablist" aria-label="V8 model structure views">
        <button type="button" class="v8si-tab active" data-view="allocation">Allocation</button>
        <button type="button" class="v8si-tab" data-view="execution">Execution</button>
        <button type="button" class="v8si-tab" data-view="cohorts">Cohorts</button>
        <button type="button" class="v8si-tab" data-view="holdout">Holdout</button>
      </div>
      <div class="v8si-panel" aria-live="polite"></div>`;
    card.appendChild(host);

    let holdout = null;
    let selectedPosition = null;
    const panel = host.querySelector('.v8si-panel');
    const tabs = Array.from(host.querySelectorAll('.v8si-tab'));

    const views = {
      allocation: () => `
        <div class="v8si-title">10 equal-weight positions · 100% invested</div>
        <div class="v8si-copy">Each selected stock receives exactly 10% target weight. Click any position below to inspect its contract weight.</div>
        <div class="v8si-positions">${Array.from({length:10},(_,i)=>`<button type="button" class="v8si-position${selectedPosition===i?' active':''}" data-position="${i}">Position ${i+1}<br><span style="color:var(--gold)">10%</span></button>`).join('')}</div>
        ${selectedPosition!==null?`<div class="v8si-copy" style="margin-top:9px"><strong>Position ${selectedPosition+1}</strong> carries 10% of the basket; all other nine positions carry the same target weight.</div>`:''}`,
      execution: () => `
        <div class="v8si-title">Decision → next-open entry → 5-session exit</div>
        <div class="v8si-copy">V8 ranks the frozen 100-stock universe, selects the top 10, enters at the next session's open, then exits five sessions later. Modeled trading friction is 10 bps per dollar traded.</div>
        <div class="v8si-live"><div><span>ENTRY</span><strong>Next Open</strong></div><div><span>HOLD</span><strong>5 Sessions</strong></div><div><span>COST</span><strong>10 bps</strong></div></div>`,
      cohorts: () => `
        <div class="v8si-title">Five staggered cohort offsets</div>
        <div class="v8si-copy">The frozen contract uses cohort offsets 0 through 4 so one 5-session holding cycle can mature each session once the process is fully active.</div>
        <div class="v8si-cohorts">${[0,1,2,3,4].map(i=>`<div title="Cohort offset ${i}" class="v8si-cohort"><span style="width:${20*(i+1)}%"></span></div>`).join('')}</div>
        <div class="v8si-copy" style="margin-top:9px">Offsets: 0 · 1 · 2 · 3 · 4</div>`,
      holdout: () => {
        const d = holdout || {};
        const state = String(d.state || 'LOADING').replaceAll('_',' ');
        return `<div class="v8si-title">Formal forward holdout</div>
          <div class="v8si-copy">The strategy remains frozen while the Sep 1, 2026+ append-only evidence stream accumulates. No pre-boundary observations are counted as holdout evidence.</div>
          <div class="v8si-live"><div><span>STATE</span><strong>${state}</strong></div><div><span>DECISIONS</span><strong>${d.decisions ?? '—'}</strong></div><div><span>COMPLETED</span><strong>${d.completed_cohorts ?? '—'}</strong></div></div>`;
      }
    };

    function show(view){
      tabs.forEach(b=>b.classList.toggle('active',b.dataset.view===view));
      panel.innerHTML = views[view]();
      panel.querySelectorAll('[data-position]').forEach(btn=>btn.addEventListener('click',()=>{
        selectedPosition = Number(btn.dataset.position);
        show('allocation');
      }));
    }

    tabs.forEach(btn=>btn.addEventListener('click',()=>show(btn.dataset.view)));
    card.querySelector('.v4-donut')?.addEventListener('click',()=>{
      const current = tabs.findIndex(b=>b.classList.contains('active'));
      const next = tabs[(current+1)%tabs.length];
      show(next.dataset.view);
    });

    window.DataShepherdV8Snapshot.get()
      .then(d=>{holdout=d;if(host.querySelector('.v8si-tab.active')?.dataset.view==='holdout')show('holdout');})
      .catch(()=>{});

    show('allocation');
  };

  boot();
})();

/* Replace the legacy CURRENT V4 TOP FIVE card with the frozen V8 Top-10 snapshot. */
(() => {
  const lower = document.querySelector('.v4-dashboard .v4-lower');
  if (!lower) return;
  const card = Array.from(lower.querySelectorAll(':scope > .card')).find(section => {
    const label = section.querySelector(':scope > .label');
    return label?.textContent.trim() === 'CURRENT V4 TOP FIVE';
  });
  if (!card) return;

  const style = document.createElement('style');
  style.id = 'v8-current-top10-style';
  style.textContent = `
    #v8-current-top10 .v8t-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
    #v8-current-top10 .v8t-state{padding:6px 9px;border:1px solid rgba(239,197,107,.28);border-radius:999px;background:rgba(239,197,107,.07);color:var(--gold);font-size:.68rem;font-weight:900}
    #v8-current-top10 .v8t-note{margin-top:5px;color:var(--muted);font-size:.76rem;line-height:1.45}
    #v8-current-top10 .v8-list-row{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px 12px;border:1px solid rgba(120,155,205,.15);border-radius:12px;background:rgba(8,20,36,.45)}
    #v8-current-top10 .v8-rank{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:rgba(239,197,107,.15);color:var(--gold);font-weight:950}
    #v8-current-top10 .v8-symbol{font-weight:950}.v8t-score{color:var(--muted);font-size:.72rem;margin-top:2px}.v8t-weight{color:var(--green);font-size:.76rem;font-weight:900;text-align:right}
  `;
  document.getElementById(style.id)?.remove();
  document.head.appendChild(style);

  card.id = 'v8-current-top10';
  card.innerHTML = `
    <div class="v8t-head">
      <div><div class="label">LATEST COMPLETED-EOD RESEARCH TOP TEN</div><h3>Frozen DISTANCE_ONLY Ranking Snapshot</h3></div>
      <span class="v8t-state" id="v8t-state">LOADING</span>
    </div>
    <div class="v8t-note" id="v8t-note">Loading the latest eligible frozen-model snapshot…</div>
    <div id="v4-top5" class="v4-list">Loading…</div>`;

  const list = card.querySelector('#v4-top5');
  const state = card.querySelector('#v8t-state');
  const note = card.querySelector('#v8t-note');

  async function loadTop10(){
    try{
      const d = await window.DataShepherdV8Snapshot.get();
      const rows = Array.isArray(d.latest_research_top10) ? d.latest_research_top10 : [];
      state.textContent = String(d.state || 'FROZEN').replaceAll('_',' ');
      const ts = d.latest_research_top10_timestamp_utc ? new Date(d.latest_research_top10_timestamp_utc) : null;
      note.textContent = ts && !Number.isNaN(ts.getTime())
        ? `Completed-EOD research session: ${ts.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'})}. Reference ranking only; not official forward evidence.`
        : 'No completed-EOD research session is currently published. This card never represents official forward evidence.';
      list.innerHTML = rows.length ? rows.map(row => `
        <div class="v8-list-row">
          <div class="v8-rank">${row.rank}</div>
          <div><div class="v8-symbol">${row.symbol}</div><div class="v8t-score">DISTANCE_ONLY score ${Number(row.score).toFixed(4)}</div></div>
          <div class="v8t-weight">10% target</div>
        </div>`).join('') : '<div class="muted">V8 Top-10 snapshot is unavailable.</div>';
    }catch(err){
      state.textContent='DATA UNAVAILABLE';
      note.textContent='V8 Top-10 snapshot is temporarily unavailable.';
      list.innerHTML='<div class="muted">Unable to load V8 ranking snapshot.</div>';
      console.error('V8 Top-10 card failed:',err);
    }
  }

  loadTop10();
  setInterval(loadTop10,30000);
})();
