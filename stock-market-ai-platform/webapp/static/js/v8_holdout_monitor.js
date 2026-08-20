(() => {
  const root = document.getElementById('v8-holdout-monitor');
  if (!root) return;
  const style = document.createElement('style');
  style.textContent = `
    .v8h-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}
    .v8h-card{padding:12px;border:1px solid rgba(120,155,205,.16);border-radius:12px;background:rgba(7,16,31,.48)}
    .v8h-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.v8h-value{font-size:1.05rem;font-weight:700;margin-top:3px}
    .v8h-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;word-break:break-all;color:var(--muted)}
    .v8h-chart{height:280px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.45);overflow:hidden;margin-top:12px}
    .v8h-chart svg{width:100%;height:100%;display:block}.v8h-note{font-size:.78rem;color:var(--muted);margin-top:8px}
    @media(max-width:800px){.v8h-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `; document.head.appendChild(style);
  const fmtPct = v => v == null ? '—' : `${(100*v).toFixed(3)}%`;
  function draw(curve){
    const box=root.querySelector('.v8h-chart'); if(!box)return;
    if(!curve.length){box.innerHTML='<div style="padding:28px;color:var(--muted)">Forward curve will begin after completed holdout cohorts are available.</div>';return;}
    const W=1000,H=280,p=34; const vals=curve.flatMap(x=>[x.strategy_normalized,x.spy_normalized]);
    const lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1,hi-lo);
    const x=i=>p+(W-2*p)*(i/Math.max(1,curve.length-1)); const y=v=>H-p-(H-2*p)*((v-lo)/span);
    const path=k=>curve.map((d,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(d[k]).toFixed(1)}`).join(' ');
    box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${path('strategy_normalized')}" fill="none" stroke="currentColor" stroke-width="3"/><path d="${path('spy_normalized')}" fill="none" stroke="currentColor" stroke-opacity=".45" stroke-width="2" stroke-dasharray="8 6"/></svg>`;
  }
  async function refresh(){
    try{
      const r=await fetch('/api/v8/holdout',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`); const d=await r.json();
      root.querySelector('[data-v8h-state]').textContent=d.state;
      root.querySelector('[data-v8h-decisions]').textContent=d.decisions;
      root.querySelector('[data-v8h-exits]').textContent=d.completed_cohorts;
      root.querySelector('[data-v8h-edge]').textContent=fmtPct(d.mean_net_relative_return);
      root.querySelector('[data-v8h-hit]').textContent=fmtPct(d.net_relative_hit_rate);
      root.querySelector('[data-v8h-sha]').textContent=d.frozen_sha256;
      root.querySelector('[data-v8h-start]').textContent=d.holdout_start_utc.replace('T00:00:00+00:00','');
      draw(d.curve||[]);
    }catch(e){root.querySelector('[data-v8h-state]').textContent='MONITOR ERROR'; console.error(e);}
  }
  refresh(); setInterval(refresh,15000);
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

/* Additive latest-model (frozen V8) equity chart. Inserted above the existing compact V4 chart. */
(() => {
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

    fetch('/api/v8/holdout',{cache:'no-store'})
      .then(r=>r.ok?r.json():Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d=>{holdout=d;if(host.querySelector('.v8si-tab.active')?.dataset.view==='holdout')show('holdout');})
      .catch(()=>{});

    show('allocation');
  };

  boot();
})();
