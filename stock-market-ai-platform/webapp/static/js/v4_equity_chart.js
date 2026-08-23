(() => {
  const card = document.querySelector('.v4-chart-card');
  if (!card) return;

  const comparisonGrid = card.closest('.v4-main');
  if (comparisonGrid) {
    comparisonGrid.classList.add('smc-single-column');
    comparisonGrid.insertAdjacentElement('afterend', card);
    card.classList.add('smc-full-width-card');
  }

  const DATA_URL = '/static/generated/stock_model_comparison.json';
  const COLORS = { V4:'#39e3a1', V5:'#36d8ff', V8:'#efc56b', V10:'#ff7ad9', SPY:'#a78bfa' };
  const ORDER = ['V4','V5','V8','V10','SPY'];

  const style = document.createElement('style');
  style.id = 'stock-model-comparison-style';
  style.textContent = `
    .v4-main.smc-single-column{grid-template-columns:1fr}.smc-full-width-card{width:100%;margin-top:20px}
    .smc-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}.smc-title{font-size:1.2rem;font-weight:900}.smc-subtitle{color:var(--muted);font-size:.88rem;margin-top:4px;line-height:1.5;max-width:900px}
    .smc-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.smc-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}.smc-btn{padding:9px 13px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}.smc-btn:hover,.smc-btn.active{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}
    .smc-models{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0 14px}.smc-model{display:flex;gap:8px;align-items:center;padding:8px 11px;border:1px solid var(--border);border-radius:12px;background:rgba(8,20,36,.5);cursor:pointer;font-weight:850}.smc-model.off{opacity:.42}.smc-dot{width:10px;height:10px;border-radius:50%;display:inline-block}.smc-model-value{color:var(--muted);font-size:.78rem;font-weight:750;margin-left:2px}
    .smc-ux{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:10px 0 14px;padding:10px 12px;border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(8,20,36,.42)}.smc-ux .hint{color:var(--muted);font-size:.82rem;margin-right:auto;line-height:1.45}.smc-nav{padding:8px 11px;border:1px solid var(--border);border-radius:10px;background:var(--panel2);color:var(--text);font-weight:850;cursor:pointer}.smc-nav:hover{border-color:rgba(54,216,255,.65);background:rgba(54,216,255,.08)}.smc-zoom-status{padding:7px 10px;border-radius:10px;background:rgba(54,216,255,.08);border:1px solid rgba(54,216,255,.22);color:var(--cyan);font-size:.76rem;font-weight:900}
    .smc-panel{position:relative;background:rgba(8,20,36,.66);border:1px solid var(--border);border-radius:18px;padding:18px;min-width:0}.smc-svg{width:100%;height:520px;display:block;cursor:crosshair;touch-action:pan-y}.smc-tooltip{position:absolute;display:none;pointer-events:none;z-index:30;min-width:270px;padding:12px 14px;border:1px solid var(--border);border-radius:10px;background:#081526;box-shadow:0 18px 40px rgba(0,0,0,.38);font-size:.78rem;line-height:1.5;color:var(--text)}.smc-tooltip strong{display:block;margin-bottom:5px}.smc-tooltip-row{display:flex;justify-content:space-between;gap:18px}.smc-note{margin-top:9px;color:var(--muted);font-size:.82rem;line-height:1.55}.smc-range-message{min-height:20px;margin:5px 0;color:var(--cyan);font-size:.8rem;font-weight:750}.smc-warning{padding:14px;border-radius:14px;border:1px solid rgba(239,197,107,.25);background:rgba(239,197,107,.07);color:var(--gold);line-height:1.5;margin-top:14px}
    .smc-holdout{margin-top:14px;padding:18px;border:1px solid var(--border);border-radius:18px;background:rgba(8,20,36,.62)}.smc-holdout-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}.smc-holdout-title{font-size:1rem;font-weight:900}.smc-holdout-sub{color:var(--muted);font-size:.82rem;line-height:1.45;margin-top:4px;max-width:820px}.smc-holdout-state{padding:7px 10px;border-radius:999px;border:1px solid rgba(239,197,107,.3);background:rgba(239,197,107,.08);color:var(--gold);font-size:.72rem;font-weight:900}.smc-holdout-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}.smc-holdout-metric{padding:11px 12px;border:1px solid rgba(120,155,205,.16);border-radius:12px;background:rgba(7,16,31,.45)}.smc-holdout-metric span{display:block;color:var(--muted);font-size:.63rem;font-weight:900;letter-spacing:.08em}.smc-holdout-metric strong{display:block;margin-top:5px;font-size:1rem}.smc-holdout-chart-wrap{position:relative;height:300px;margin-top:14px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.44);overflow:hidden}.smc-holdout-chart{width:100%;height:100%;display:block}.smc-holdout-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:24px;color:var(--muted);font-size:.82rem;line-height:1.5;pointer-events:none}.smc-holdout-legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;color:var(--muted);font-size:.76rem}.smc-holdout-legend span{display:flex;gap:7px;align-items:center}.smc-holdout-key{width:10px;height:10px;border-radius:50%;display:inline-block}.smc-holdout-note{margin-top:10px;color:var(--muted);font-size:.76rem;line-height:1.5}
    @media(max-width:1050px){.smc-metrics{grid-template-columns:repeat(2,1fr)}.smc-holdout-metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.smc-metrics{grid-template-columns:1fr}.smc-svg{height:360px}.smc-ux .hint{width:100%;flex-basis:100%}.smc-holdout-metrics{grid-template-columns:1fr}.smc-holdout-chart-wrap{height:250px}}
  `;
  document.getElementById(style.id)?.remove(); document.head.appendChild(style);

  card.innerHTML = `
    <div class="smc-head"><div><div class="label">MODEL PERFORMANCE COMPARISON</div><div class="smc-title">V4 vs V5 vs frozen V8 vs V10 vs SPY</div><div class="smc-subtitle">Every strategy is shown on the same hypothetical $100,000 basis. Live paper-account balances are intentionally excluded, so there is no artificial reset or vertical drop when reconstructed history reaches the present.</div></div><span id="smc-load-status" class="mode">LOADING MODELS</span></div>
    <div class="smc-metrics"><div class="metric"><span>VISIBLE RANGE</span><strong id="smc-visible-range">—</strong></div><div class="metric"><span>MODELS SHOWN</span><strong id="smc-model-count">—</strong></div><div class="metric"><span>START CAPITAL</span><strong>$100,000</strong></div><div class="metric"><span>LATEST DATA</span><strong id="smc-latest-date">—</strong></div></div>
    <div class="smc-toolbar"><strong class="muted">RANGE</strong><button class="smc-btn" data-range="ALL">ALL</button><button class="smc-btn" data-range="5Y">5Y</button><button class="smc-btn active" data-range="3Y">3Y</button><button class="smc-btn" data-range="1Y">1Y</button><button class="smc-btn" data-range="90D">90D</button><button class="smc-btn" data-range="30D">30D</button><strong class="muted" style="margin-left:10px">VIEW</strong><button class="smc-btn active" data-mode="equity">EQUITY USD</button><button class="smc-btn" data-mode="normalized">NORMALIZED GROWTH</button></div>
    <div id="smc-range-message" class="smc-range-message"></div>
    <div id="smc-models" class="smc-models"></div>
    <div class="smc-ux"><div class="hint"><strong>Explore:</strong> move near a line to highlight that model · click to pin · click again to release · toggle models · choose range · zoom and pan.</div><button class="smc-nav" data-action="left">◀ EARLIER</button><button class="smc-nav" data-action="out">− ZOOM OUT</button><span id="smc-zoom-status" class="smc-zoom-status">FULL RANGE</span><button class="smc-nav" data-action="in">+ ZOOM IN</button><button class="smc-nav" data-action="right">LATER ▶</button><button class="smc-nav" data-action="reset">RESET VIEW</button></div>
    <div class="smc-panel"><svg id="smc-chart" class="smc-svg" viewBox="0 0 1200 520" preserveAspectRatio="none"></svg><div id="smc-tooltip" class="smc-tooltip"></div><div id="smc-scale-note" class="smc-note">Each model begins at $100,000 on its own first scientifically eligible historical date.</div></div>
    <div id="smc-method-note" class="smc-warning">V6 and V7 are intentionally excluded. V8 and V10 are development-era reconstructions; genuine V8 forward evidence and V10 confirmation/Nov-2-2026+ holdout evidence remain separate.</div>
    <div class="smc-holdout" id="smc-v8-holdout-interaction">
      <div class="smc-holdout-head"><div><div class="label">V8 HOLDOUT INTERACTION</div><div class="smc-holdout-title">Frozen V8 → append-only forward evidence</div><div class="smc-holdout-sub">This chart shows how the frozen V8 model is progressing through the genuine holdout lifecycle: decision, next-open entry, and completed 5-session exit. Before Sep 1, the correct state is zero holdout evidence.</div></div><span id="smc-holdout-state" class="smc-holdout-state">LOADING</span></div>
      <div class="smc-holdout-metrics"><div class="smc-holdout-metric"><span>DECISIONS</span><strong id="smc-holdout-decisions">—</strong></div><div class="smc-holdout-metric"><span>ENTRIES</span><strong id="smc-holdout-entries">—</strong></div><div class="smc-holdout-metric"><span>COMPLETED COHORTS</span><strong id="smc-holdout-exits">—</strong></div><div class="smc-holdout-metric"><span>HOLDOUT START</span><strong id="smc-holdout-start">—</strong></div></div>
      <div class="smc-holdout-chart-wrap"><svg id="smc-holdout-chart" class="smc-holdout-chart" viewBox="0 0 1000 300" preserveAspectRatio="none"></svg><div id="smc-holdout-empty" class="smc-holdout-empty"></div></div>
      <div class="smc-holdout-legend"><span><i class="smc-holdout-key" style="background:#efc56b"></i>V8 decisions</span><span><i class="smc-holdout-key" style="background:#36d8ff"></i>Next-open entries</span><span><i class="smc-holdout-key" style="background:#39e3a1"></i>Completed exits</span></div>
      <div id="smc-holdout-note" class="smc-holdout-note">Read-only visualization of the formal holdout journal. It does not create, backfill, or modify holdout evidence.</div>
    </div>`;

  const svg=card.querySelector('#smc-chart'), panel=svg.closest('.smc-panel'), tooltip=card.querySelector('#smc-tooltip'), ns='http://www.w3.org/2000/svg';
  let payload=null, series={}, active=new Set(ORDER), range='3Y', mode='equity', zoomLevel=1, panOffset=1, pinned=false;
  const money=v=>'$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const pct=v=>(Number(v)>=0?'+':'')+Number(v||0).toFixed(2)+'%';
  const date=t=>new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
  const dateTime=t=>new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'});
  const el=(tag,a={})=>{const n=document.createElementNS(ns,tag);Object.entries(a).forEach(([k,v])=>n.setAttribute(k,String(v)));return n;};
  const set=(id,v)=>{const n=card.querySelector('#'+id);if(n)n.textContent=v;};
  const parseRows=rows=>(rows||[]).map(r=>{const t=Date.parse(r.timestamp||''),equity=Number(r.equity);return Number.isFinite(t)&&Number.isFinite(equity)?{...r,t,equity}:null;}).filter(Boolean).sort((a,b)=>a.t-b.t);

  function endTime(){return Math.max(...Object.values(series).flatMap(s=>s.rows.length?[s.rows.at(-1).t]:[]));}
  function cutoff(end){const d=new Date(end);if(range==='ALL')return-Infinity;if(range==='30D')d.setUTCDate(d.getUTCDate()-30);else if(range==='90D')d.setUTCDate(d.getUTCDate()-90);else if(range==='1Y')d.setUTCFullYear(d.getUTCFullYear()-1);else if(range==='3Y')d.setUTCFullYear(d.getUTCFullYear()-3);else if(range==='5Y')d.setUTCFullYear(d.getUTCFullYear()-5);return d.getTime();}
  function visibleDomain(){const end=endTime(), start=cutoff(end);let a=start,b=end;if(zoomLevel>1&&Number.isFinite(start)){const full=b-a,span=full/zoomLevel,maxShift=full-span;a=start+(maxShift*Math.max(0,Math.min(1,panOffset)));b=a+span;}return[a,b];}
  function rowsInDomain(s,a,b){return s.rows.filter(r=>r.t>=a&&r.t<=b);}
  function value(s,r){if(mode==='normalized'){const base=s.startingCapital||100000;return 100*r.equity/base;}return r.equity;}
  function nearest(rows,t){if(!rows.length)return null;let lo=0,hi=rows.length-1;while(lo<hi){const mid=Math.floor((lo+hi)/2);if(rows[mid].t<t)lo=mid+1;else hi=mid;}const a=rows[lo],b=lo>0?rows[lo-1]:null;return b&&Math.abs(b.t-t)<Math.abs(a.t-t)?b:a;}

  function buildModelToggles(){const host=card.querySelector('#smc-models');host.innerHTML='<strong class="muted">LINES</strong>';ORDER.forEach(id=>{const s=series[id];if(!s)return;const b=document.createElement('button');b.type='button';b.className='smc-model';b.dataset.model=id;b.innerHTML=`<span class="smc-dot" style="background:${COLORS[id]}"></span><span>${s.label}</span><span class="smc-model-value">${money(s.rows.at(-1)?.equity)} · ${pct(s.totalReturnPct)}</span>`;host.appendChild(b);});}

  function render(){
    if(!payload)return; const [a,b]=visibleDomain(); svg.innerHTML='';
    card.querySelectorAll('[data-range]').forEach(x=>x.classList.toggle('active',x.dataset.range===range));card.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('active',x.dataset.mode===mode));card.querySelectorAll('[data-model]').forEach(x=>x.classList.toggle('off',!active.has(x.dataset.model)));
    set('smc-visible-range',`${date(a)} → ${date(b)}`);set('smc-model-count',String(active.size));set('smc-latest-date',date(endTime()));set('smc-zoom-status',zoomLevel>1?`${zoomLevel.toFixed(1)}× ZOOM`:'FULL RANGE');set('smc-range-message',`${range} selected — ${active.size} comparison lines shown.`);
    set('smc-scale-note',mode==='normalized'?'Normalized growth index: each model starts at 100 on its own first eligible date.':'Equity USD: every model starts with the same hypothetical $100,000 capital.');

    const W=1200,H=520,p={l:92,r:128,t:30,b:62};const activeSeries=ORDER.filter(id=>active.has(id)&&series[id]);const vis={};let vals=[];
    activeSeries.forEach(id=>{vis[id]=rowsInDomain(series[id],a,b);vals.push(...vis[id].map(r=>value(series[id],r)));});
    if(!vals.length){const n=el('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2'});n.textContent='No model observations in this range.';svg.appendChild(n);return;}
    let minV=Math.min(...vals),maxV=Math.max(...vals),span=Math.max(maxV-minV,mode==='equity'?1000:1);minV-=span*.1;maxV+=span*.1;
    const x=t=>p.l+(W-p.l-p.r)*(t-a)/Math.max(1,b-a),y=v=>p.t+(H-p.t-p.b)*(1-(v-minV)/Math.max(.000001,maxV-minV));
    for(let i=0;i<5;i++){const v=minV+(maxV-minV)*i/4,yy=y(v);svg.appendChild(el('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.13)'}));const n=el('text',{x:p.l-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});n.textContent=mode==='normalized'?v.toFixed(1):money(v);svg.appendChild(n);}
    for(let i=0;i<5;i++){const t=a+(b-a)*i/4,n=el('text',{x:x(t),y:H-24,'text-anchor':i===0?'start':i===4?'end':'middle',fill:'#91a6c2','font-size':11});n.textContent=date(t);svg.appendChild(n);}
    activeSeries.forEach(id=>{const rows=vis[id];if(rows.length<2)return;const pts=rows.map(r=>[x(r.t),y(value(series[id],r))]),width=(id==='V8'||id==='V10')?3.2:2.7;svg.appendChild(el('polyline',{points:pts.map(q=>q.join(',')).join(' '),fill:'none',stroke:COLORS[id],'stroke-width':width,opacity:.94,'stroke-linejoin':'round','stroke-linecap':'round','data-model':id,'data-width':width}));});

    const endpointLabels=activeSeries.map(id=>{const rows=vis[id];if(!rows.length)return null;const r=rows.at(-1);return{id,r,anchorX:x(r.t),anchorY:y(value(series[id],r)),label:id==='V8'?'V8 FROZEN':id};}).filter(Boolean).sort((u,v)=>u.anchorY-v.anchorY);
    const minLabelY=p.t+12,maxLabelY=H-p.b-12,labelGap=25;
    endpointLabels.forEach((item,index)=>{
      item.labelY=Math.max(item.anchorY,index?endpointLabels[index-1].labelY+labelGap:minLabelY);
    });
    if(endpointLabels.length&&endpointLabels.at(-1).labelY>maxLabelY){
      const shift=endpointLabels.at(-1).labelY-maxLabelY;
      endpointLabels.forEach(item=>item.labelY-=shift);
      for(let i=endpointLabels.length-2;i>=0;i--)endpointLabels[i].labelY=Math.min(endpointLabels[i].labelY,endpointLabels[i+1].labelY-labelGap);
    }
    endpointLabels.forEach(item=>{
      const labelX=Math.min(W-p.r-4,item.anchorX+14),textWidth=Math.max(36,item.label.length*7+14);
      svg.appendChild(el('line',{x1:item.anchorX+2,y1:item.anchorY,x2:labelX,y2:item.labelY,stroke:COLORS[item.id],'stroke-width':1.5,opacity:.7,'pointer-events':'none'}));
      svg.appendChild(el('rect',{x:labelX,y:item.labelY-11,width:textWidth,height:22,rx:8,fill:'#081526',stroke:COLORS[item.id],'stroke-width':1.4,opacity:.96,'pointer-events':'none'}));
      const label=el('text',{x:labelX+7,y:item.labelY+4,fill:COLORS[item.id],'font-size':11,'font-weight':900,'pointer-events':'none'});
      label.textContent=item.label;
      svg.appendChild(label);
    });

    const guide=el('line',{y1:p.t,y2:H-p.b,stroke:'#e7edf7','stroke-dasharray':'4 4',opacity:.7,visibility:'hidden'});svg.appendChild(guide);
    const focusDot=el('circle',{r:5.5,fill:'#fff',stroke:'#07101f','stroke-width':2,visibility:'hidden'});svg.appendChild(focusDot);
    const overlay=el('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'rgba(0,0,0,.001)','pointer-events':'all'});svg.appendChild(overlay);

    function clearFocus(){
      tooltip.style.display='none';
      guide.setAttribute('visibility','hidden');
      focusDot.setAttribute('visibility','hidden');
      svg.querySelectorAll('[data-model]').forEach(line=>{line.setAttribute('opacity','.94');line.setAttribute('stroke-width',line.dataset.width);});
    }

    function inspect(e,pin=false){
      const rect=svg.getBoundingClientRect(),mx=(e.clientX-rect.left)/rect.width*W,my=(e.clientY-rect.top)/rect.height*H;
      if(mx<p.l||mx>W-p.r||my<p.t||my>H-p.b)return;
      const t=a+(mx-p.l)/(W-p.l-p.r)*(b-a);
      let best=null;
      activeSeries.forEach(id=>{const r=nearest(vis[id],t);if(!r)return;const yy=y(value(series[id],r)),distance=Math.abs(yy-my);if(!best||distance<best.distance)best={id,r,yy,distance};});
      if(!best||best.distance>38){if(!pinned)clearFocus();return;}

      const selectedX=x(best.r.t),selectedValue=value(series[best.id],best.r);
      guide.setAttribute('x1',mx);guide.setAttribute('x2',mx);guide.setAttribute('visibility','visible');
      focusDot.setAttribute('cx',selectedX);focusDot.setAttribute('cy',best.yy);focusDot.setAttribute('fill',COLORS[best.id]);focusDot.setAttribute('visibility','visible');
      svg.querySelectorAll('[data-model]').forEach(line=>{const selected=line.dataset.model===best.id;line.setAttribute('opacity',selected?'1':'.16');line.setAttribute('stroke-width',selected?'5':line.dataset.width);});

      const ranked=activeSeries.map(id=>({id,equity:nearest(vis[id],best.r.t)?.equity})).filter(item=>Number.isFinite(item.equity)).sort((u,v)=>v.equity-u.equity);
      const rank=ranked.findIndex(item=>item.id===best.id)+1;
      tooltip.innerHTML=`<strong><span class="smc-dot" style="background:${COLORS[best.id]};margin-right:7px"></span>${series[best.id].label}</strong><div class="smc-tooltip-row"><span>Date</span><b>${dateTime(best.r.t)}</b></div><div class="smc-tooltip-row"><span>${mode==='normalized'?'Growth index':'Portfolio equity'}</span><b>${mode==='normalized'?selectedValue.toFixed(2):money(best.r.equity)}</b></div><div class="smc-tooltip-row"><span>Historical total return</span><b>${pct(series[best.id].totalReturnPct)}</b></div><div class="smc-tooltip-row"><span>Rank at this date</span><b>#${rank} of ${ranked.length}</b></div>`;
      tooltip.style.display='block';const pr=panel.getBoundingClientRect();tooltip.style.left=Math.min(e.clientX-pr.left+14,pr.width-300)+'px';tooltip.style.top=Math.max(8,e.clientY-pr.top-20)+'px';
      if(pin)pinned=!pinned;
    }
    overlay.addEventListener('pointermove',e=>{if(!pinned)inspect(e,false)});
    overlay.addEventListener('click',e=>{if(pinned){pinned=false;clearFocus();}else inspect(e,true);});
    overlay.addEventListener('pointerleave',()=>{if(!pinned)clearFocus();});
  }

  function renderHoldoutInteraction(d){
    set('smc-holdout-state',d.state||'UNKNOWN');
    set('smc-holdout-decisions',String(d.decisions??0));
    set('smc-holdout-entries',String(d.entries??0));
    set('smc-holdout-exits',String(d.completed_cohorts??0));
    const holdoutStart=Date.parse(d.holdout_start_utc||'2026-09-01T00:00:00Z');
    set('smc-holdout-start',Number.isFinite(holdoutStart)?date(holdoutStart):'Sep 1, 2026');
    const hsvg=card.querySelector('#smc-holdout-chart'), empty=card.querySelector('#smc-holdout-empty');
    if(!hsvg)return; hsvg.innerHTML='';
    const events=(d.event_history||[]).map(e=>({...e,t:Date.parse(e.timestamp_utc||'')})).filter(e=>Number.isFinite(e.t)).sort((a,b)=>a.t-b.t);
    const now=Date.now(), W=1000,H=300,p={l:66,r:28,t:26,b:52};
    const start=Math.min(now,holdoutStart)-3*86400000, end=Math.max(now,holdoutStart)+14*86400000;
    const x=t=>p.l+(W-p.l-p.r)*(t-start)/Math.max(1,end-start), y=v=>p.t+(H-p.t-p.b)*(1-v/Math.max(1,Math.max(d.decisions||0,d.entries||0,d.completed_cohorts||0,1)));
    for(let i=0;i<4;i++){const yy=p.t+(H-p.t-p.b)*i/3;hsvg.appendChild(el('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.13)'}));}
    [start,holdoutStart,now,end].sort((a,b)=>a-b).forEach((t,i,arr)=>{if(i&&Math.abs(t-arr[i-1])<3600000)return;const tx=el('text',{x:x(t),y:H-18,'text-anchor':'middle',fill:t===holdoutStart?'#efc56b':'#91a6c2','font-size':10});tx.textContent=t===holdoutStart?'HOLDOUT START':date(t);hsvg.appendChild(tx);});
    const bx=x(holdoutStart);hsvg.appendChild(el('line',{x1:bx,y1:p.t,x2:bx,y2:H-p.b,stroke:'#efc56b','stroke-width':2,'stroke-dasharray':'6 5',opacity:.8}));
    const before=el('text',{x:Math.max(p.l+70,bx-10),y:p.t+14,'text-anchor':'end',fill:'#91a6c2','font-size':11});before.textContent='No evidence before boundary';hsvg.appendChild(before);
    const counts={DECISION:0,ENTRY:0,EXIT:0}, seriesPts={DECISION:[],ENTRY:[],EXIT:[]};
    events.forEach(e=>{counts[e.event_type]=(counts[e.event_type]||0)+1;Object.keys(seriesPts).forEach(k=>seriesPts[k].push({t:e.t,v:counts[k]}));});
    const colors={DECISION:'#efc56b',ENTRY:'#36d8ff',EXIT:'#39e3a1'};
    Object.keys(seriesPts).forEach(k=>{const pts=seriesPts[k];if(!pts.length)return;const path=[[holdoutStart,0],...pts.map(q=>[q.t,q.v])];hsvg.appendChild(el('polyline',{points:path.map(q=>`${x(q[0])},${y(q[1])}`).join(' '),fill:'none',stroke:colors[k],'stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'}));pts.forEach(q=>hsvg.appendChild(el('circle',{cx:x(q.t),cy:y(q.v),r:4,fill:colors[k],stroke:'#07101f','stroke-width':2})));});
    if(!events.length){empty.textContent=`V8 is currently ${d.state||'waiting'}. The formal holdout begins Sep 1, 2026; decisions, next-open entries, and completed exits will appear here only when genuine append-only evidence exists.`;}
    else empty.textContent='';
    set('smc-holdout-note',`Frozen SHA ${String(d.frozen_sha256||'').slice(0,12)}… · brokerage orders: ${d.brokerage_orders?'YES':'NO'} · strategy modified: ${d.strategy_modified?'YES':'NO'}.`);
  }

  async function loadHoldoutInteraction(){try{const r=await fetch('/api/v8/holdout',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);renderHoldoutInteraction(await r.json());}catch(err){set('smc-holdout-state','MONITOR ERROR');const empty=card.querySelector('#smc-holdout-empty');if(empty)empty.textContent='V8 holdout interaction data is temporarily unavailable.';console.error(err);}}

  card.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.range){range=b.dataset.range;zoomLevel=1;panOffset=1;pinned=false;render();return;}if(b.dataset.mode){mode=b.dataset.mode;pinned=false;render();return;}if(b.dataset.model){const id=b.dataset.model;if(active.has(id)&&active.size>1)active.delete(id);else active.add(id);pinned=false;render();return;}const action=b.dataset.action;if(!action)return;if(action==='reset'){zoomLevel=1;panOffset=1;}else if(action==='in'){zoomLevel=Math.min(12,zoomLevel*1.6);}else if(action==='out'){zoomLevel=Math.max(1,zoomLevel/1.6);}else if(action==='left'){panOffset=Math.max(0,panOffset-.18);}else if(action==='right'){panOffset=Math.min(1,panOffset+.18);}pinned=false;render();});

  async function load(){try{const r=await fetch(DATA_URL,{cache:'no-store'});if(!r.ok)throw new Error(`comparison artifact unavailable (${r.status})`);payload=await r.json();series={};(payload.series||[]).forEach(s=>{series[s.model_id]={...s,rows:parseRows(s.history),startingCapital:Number(s.starting_capital||100000),totalReturnPct:Number(s.total_return_pct||0)};});if(!ORDER.some(id=>series[id]))throw new Error('no model series found');buildModelToggles();set('smc-load-status','COMPARISON READY');set('smc-method-note',`${payload.comparison_policy||''} ${payload.holdout_note||''}`.trim());render();}catch(err){set('smc-load-status','BUILD REQUIRED');card.querySelector('#smc-range-message').textContent=`${err.message}. Run: python -m ml.build_stock_model_comparison`;console.error(err);}}
  load();
  loadHoldoutInteraction();
  setInterval(loadHoldoutInteraction,30000);
})();

/* Remove superseded V5 dashboard blocks without touching the underlying data or model artifacts. */
(() => {
  document.getElementById('v5-shadow-comparison')?.remove();
  document.querySelectorAll('section.card').forEach(section => {
    const label = section.querySelector(':scope > .label');
    if (label?.textContent.trim() === 'V5 FROZEN MODEL') section.remove();
  });
})();

/* Replace the legacy V4 portfolio-structure card with the frozen V8 portfolio contract. */
(() => {
  const lower = document.querySelector('.v4-dashboard .v4-lower');
  if (!lower) return;
  const target = Array.from(lower.querySelectorAll(':scope > .card')).find(section => {
    const label = section.querySelector(':scope > .label');
    return label?.textContent.trim() === 'PORTFOLIO STRUCTURE';
  });
  if (!target) return;

  target.id = 'v8-portfolio-structure';
  target.innerHTML = `
    <div class="label">V8 MODEL STRUCTURE</div>
    <h3>Top-10 Equal-Weight Basket</h3>
    <div class="muted" id="v8-structure-state">Frozen contract · formal forward holdout begins Sep 1, 2026</div>
    <div class="v4-structure-inner">
      <div class="v4-donut" style="background:repeating-conic-gradient(var(--gold) 0deg 32deg, rgba(239,197,107,.32) 32deg 36deg)" aria-label="Ten equal-weight V8 stock positions at 10 percent each"></div>
      <div class="v4-legend">
        <div class="v4-legend-item"><span class="v4-dot" style="background:var(--gold)"></span><div><strong>Top-10 Stock Basket (100%)</strong><div class="muted">Ten V8-selected stocks, equal weighted</div></div></div>
        <div class="v4-legend-item"><span class="v4-dot" style="background:var(--cyan)"></span><div><strong>10% per selected stock</strong><div class="muted">No SPY core allocation — SPY is the benchmark only</div></div></div>
        <div class="v4-legend-item"><span class="v4-dot" style="background:var(--green)"></span><div><strong>5-session hold · next-open execution</strong><div class="muted">Five staggered cohort offsets with 10-bps modeled trading cost</div></div></div>
      </div>
    </div>`;

  fetch('/api/v8/holdout',{cache:'no-store'})
    .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
    .then(d => {
      const state = target.querySelector('#v8-structure-state');
      if (!state) return;
      const readable = String(d.state || 'UNKNOWN').replaceAll('_',' ');
      state.textContent = `${readable} · ${d.decisions ?? 0} decisions · ${d.entries ?? 0} entries · ${d.completed_cohorts ?? 0} completed cohorts`;
    })
    .catch(() => {
      const state = target.querySelector('#v8-structure-state');
      if (state) state.textContent = 'Frozen V8 contract · holdout monitor temporarily unavailable';
    });
})();