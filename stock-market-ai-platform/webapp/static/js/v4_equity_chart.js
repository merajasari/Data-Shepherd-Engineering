(() => {
  const card = document.querySelector('.v4-chart-card');
  if (!card) return;

  const DATA_URL = '/static/generated/stock_model_comparison.json';
  const COLORS = { V4:'#39e3a1', V5:'#36d8ff', V8:'#efc56b', SPY:'#a78bfa' };
  const ORDER = ['V4','V5','V8','SPY'];

  const style = document.createElement('style');
  style.id = 'stock-model-comparison-style';
  style.textContent = `
    .smc-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}.smc-title{font-size:1.2rem;font-weight:900}.smc-subtitle{color:var(--muted);font-size:.88rem;margin-top:4px;line-height:1.5;max-width:900px}
    .smc-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}.smc-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}.smc-btn{padding:9px 13px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}.smc-btn:hover,.smc-btn.active{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}
    .smc-models{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0 14px}.smc-model{display:flex;gap:8px;align-items:center;padding:8px 11px;border:1px solid var(--border);border-radius:12px;background:rgba(8,20,36,.5);cursor:pointer;font-weight:850}.smc-model.off{opacity:.42}.smc-dot{width:10px;height:10px;border-radius:50%;display:inline-block}.smc-model-value{color:var(--muted);font-size:.78rem;font-weight:750;margin-left:2px}
    .smc-ux{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:10px 0 14px;padding:10px 12px;border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(8,20,36,.42)}.smc-ux .hint{color:var(--muted);font-size:.82rem;margin-right:auto;line-height:1.45}.smc-nav{padding:8px 11px;border:1px solid var(--border);border-radius:10px;background:var(--panel2);color:var(--text);font-weight:850;cursor:pointer}.smc-nav:hover{border-color:rgba(54,216,255,.65);background:rgba(54,216,255,.08)}.smc-zoom-status{padding:7px 10px;border-radius:10px;background:rgba(54,216,255,.08);border:1px solid rgba(54,216,255,.22);color:var(--cyan);font-size:.76rem;font-weight:900}
    .smc-panel{position:relative;background:rgba(8,20,36,.66);border:1px solid var(--border);border-radius:18px;padding:18px;min-width:0}.smc-svg{width:100%;height:520px;display:block;cursor:crosshair;touch-action:pan-y}.smc-tooltip{position:absolute;display:none;pointer-events:none;z-index:30;min-width:270px;padding:12px 14px;border:1px solid var(--border);border-radius:10px;background:#081526;box-shadow:0 18px 40px rgba(0,0,0,.38);font-size:.78rem;line-height:1.5;color:var(--text)}.smc-tooltip strong{display:block;margin-bottom:5px}.smc-tooltip-row{display:flex;justify-content:space-between;gap:18px}.smc-note{margin-top:9px;color:var(--muted);font-size:.82rem;line-height:1.55}.smc-range-message{min-height:20px;margin:5px 0;color:var(--cyan);font-size:.8rem;font-weight:750}.smc-warning{padding:14px;border-radius:14px;border:1px solid rgba(239,197,107,.25);background:rgba(239,197,107,.07);color:var(--gold);line-height:1.5;margin-top:14px}
    @media(max-width:1050px){.smc-metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.smc-metrics{grid-template-columns:1fr}.smc-svg{height:360px}.smc-ux .hint{width:100%;flex-basis:100%}}
  `;
  document.getElementById(style.id)?.remove(); document.head.appendChild(style);

  card.innerHTML = `
    <div class="smc-head"><div><div class="label">MODEL PERFORMANCE COMPARISON</div><div class="smc-title">V4 vs V5 vs frozen V8 vs SPY</div><div class="smc-subtitle">Every strategy is shown on the same hypothetical $100,000 basis. Live paper-account balances are intentionally excluded, so there is no artificial reset or vertical drop when reconstructed history reaches the present.</div></div><span id="smc-load-status" class="mode">LOADING MODELS</span></div>
    <div class="smc-metrics"><div class="metric"><span>VISIBLE RANGE</span><strong id="smc-visible-range">—</strong></div><div class="metric"><span>MODELS SHOWN</span><strong id="smc-model-count">—</strong></div><div class="metric"><span>START CAPITAL</span><strong>$100,000</strong></div><div class="metric"><span>LATEST DATA</span><strong id="smc-latest-date">—</strong></div></div>
    <div class="smc-toolbar"><strong class="muted">RANGE</strong><button class="smc-btn" data-range="ALL">ALL</button><button class="smc-btn" data-range="5Y">5Y</button><button class="smc-btn active" data-range="3Y">3Y</button><button class="smc-btn" data-range="1Y">1Y</button><button class="smc-btn" data-range="90D">90D</button><button class="smc-btn" data-range="30D">30D</button><strong class="muted" style="margin-left:10px">VIEW</strong><button class="smc-btn active" data-mode="equity">EQUITY USD</button><button class="smc-btn" data-mode="normalized">NORMALIZED GROWTH</button></div>
    <div id="smc-range-message" class="smc-range-message"></div>
    <div id="smc-models" class="smc-models"></div>
    <div class="smc-ux"><div class="hint"><strong>Explore:</strong> hover to compare every visible model at a date · click to pin · toggle models · choose range · zoom and pan.</div><button class="smc-nav" data-action="left">◀ EARLIER</button><button class="smc-nav" data-action="out">− ZOOM OUT</button><span id="smc-zoom-status" class="smc-zoom-status">FULL RANGE</span><button class="smc-nav" data-action="in">+ ZOOM IN</button><button class="smc-nav" data-action="right">LATER ▶</button><button class="smc-nav" data-action="reset">RESET VIEW</button></div>
    <div class="smc-panel"><svg id="smc-chart" class="smc-svg" viewBox="0 0 1200 520" preserveAspectRatio="none"></svg><div id="smc-tooltip" class="smc-tooltip"></div><div id="smc-scale-note" class="smc-note">Each model begins at $100,000 on its own first scientifically eligible historical date.</div></div>
    <div id="smc-method-note" class="smc-warning">V6 and V7 are intentionally excluded. V8 historical reconstruction is development-era evidence; the genuine Sep-1-2026+ forward holdout remains separate.</div>`;

  const svg=card.querySelector('#smc-chart'), panel=svg.closest('.smc-panel'), tooltip=card.querySelector('#smc-tooltip'), ns='http://www.w3.org/2000/svg';
  let payload=null, series={}, active=new Set(ORDER), range='3Y', mode='equity', zoomLevel=1, panOffset=1, pinned=false;
  const money=v=>'$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const pct=v=>(Number(v)>=0?'+':'')+Number(v||0).toFixed(2)+'%';
  const date=t=>new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});
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

    const W=1200,H=520,p={l:92,r:38,t:30,b:62};const activeSeries=ORDER.filter(id=>active.has(id)&&series[id]);const vis={};let vals=[];
    activeSeries.forEach(id=>{vis[id]=rowsInDomain(series[id],a,b);vals.push(...vis[id].map(r=>value(series[id],r)));});
    if(!vals.length){const n=el('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2'});n.textContent='No model observations in this range.';svg.appendChild(n);return;}
    let minV=Math.min(...vals),maxV=Math.max(...vals),span=Math.max(maxV-minV,mode==='equity'?1000:1);minV-=span*.1;maxV+=span*.1;
    const x=t=>p.l+(W-p.l-p.r)*(t-a)/Math.max(1,b-a),y=v=>p.t+(H-p.t-p.b)*(1-(v-minV)/Math.max(.000001,maxV-minV));
    for(let i=0;i<5;i++){const v=minV+(maxV-minV)*i/4,yy=y(v);svg.appendChild(el('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.13)'}));const n=el('text',{x:p.l-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});n.textContent=mode==='normalized'?v.toFixed(1):money(v);svg.appendChild(n);}
    for(let i=0;i<5;i++){const t=a+(b-a)*i/4,n=el('text',{x:x(t),y:H-24,'text-anchor':i===0?'start':i===4?'end':'middle',fill:'#91a6c2','font-size':11});n.textContent=date(t);svg.appendChild(n);}
    activeSeries.forEach(id=>{const rows=vis[id];if(rows.length<2)return;const pts=rows.map(r=>[x(r.t),y(value(series[id],r))]);svg.appendChild(el('polyline',{points:pts.map(q=>q.join(',')).join(' '),fill:'none',stroke:COLORS[id],'stroke-width':id==='V8'?3.2:2.7,'stroke-linejoin':'round','stroke-linecap':'round'}));});

    const guide=el('line',{y1:p.t,y2:H-p.b,stroke:'#e7edf7','stroke-dasharray':'4 4',opacity:.55,visibility:'hidden'});svg.appendChild(guide);const dots={};activeSeries.forEach(id=>{dots[id]=el('circle',{r:4.5,fill:COLORS[id],stroke:'#07101f','stroke-width':2,visibility:'hidden'});svg.appendChild(dots[id]);});
    const overlay=el('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'rgba(0,0,0,.001)','pointer-events':'all'});svg.appendChild(overlay);
    function inspect(e,pin=false){const rect=svg.getBoundingClientRect(),mx=(e.clientX-rect.left)/rect.width*W;if(mx<p.l||mx>W-p.r)return;const t=a+(mx-p.l)/(W-p.l-p.r)*(b-a);guide.setAttribute('x1',x(t));guide.setAttribute('x2',x(t));guide.setAttribute('visibility','visible');let html=`<strong>${dateTime(t)}</strong>`;activeSeries.forEach(id=>{const r=nearest(vis[id],t);if(!r)return;dots[id].setAttribute('cx',x(r.t));dots[id].setAttribute('cy',y(value(series[id],r)));dots[id].setAttribute('visibility','visible');html+=`<div class="smc-tooltip-row"><span><span class="smc-dot" style="background:${COLORS[id]};margin-right:6px"></span>${series[id].label}</span><b>${mode==='normalized'?value(series[id],r).toFixed(2):money(r.equity)}</b></div>`;});tooltip.innerHTML=html;tooltip.style.display='block';const pr=panel.getBoundingClientRect();tooltip.style.left=Math.min(e.clientX-pr.left+14,pr.width-300)+'px';tooltip.style.top=Math.max(8,e.clientY-pr.top-20)+'px';if(pin)pinned=!pinned;}
    overlay.addEventListener('pointermove',e=>{if(!pinned)inspect(e,false)});overlay.addEventListener('click',e=>inspect(e,true));overlay.addEventListener('pointerleave',()=>{if(!pinned){tooltip.style.display='none';guide.setAttribute('visibility','hidden');Object.values(dots).forEach(d=>d.setAttribute('visibility','hidden'));}});
  }

  card.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.range){range=b.dataset.range;zoomLevel=1;panOffset=1;pinned=false;render();return;}if(b.dataset.mode){mode=b.dataset.mode;pinned=false;render();return;}if(b.dataset.model){const id=b.dataset.model;if(active.has(id)&&active.size>1)active.delete(id);else active.add(id);pinned=false;render();return;}const action=b.dataset.action;if(!action)return;if(action==='reset'){zoomLevel=1;panOffset=1;}else if(action==='in'){zoomLevel=Math.min(12,zoomLevel*1.6);}else if(action==='out'){zoomLevel=Math.max(1,zoomLevel/1.6);}else if(action==='left'){panOffset=Math.max(0,panOffset-.18);}else if(action==='right'){panOffset=Math.min(1,panOffset+.18);}pinned=false;render();});

  async function load(){try{const r=await fetch(DATA_URL,{cache:'no-store'});if(!r.ok)throw new Error(`comparison artifact unavailable (${r.status})`);payload=await r.json();series={};(payload.series||[]).forEach(s=>{series[s.model_id]={...s,rows:parseRows(s.history),startingCapital:Number(s.starting_capital||100000),totalReturnPct:Number(s.total_return_pct||0)};});if(!ORDER.some(id=>series[id]))throw new Error('no model series found');buildModelToggles();set('smc-load-status','COMPARISON READY');set('smc-method-note',`${payload.comparison_policy||''} ${payload.holdout_note||''}`.trim());render();}catch(err){set('smc-load-status','BUILD REQUIRED');card.querySelector('#smc-range-message').textContent=`${err.message}. Run: python -m ml.build_stock_model_comparison`;console.error(err);}}
  load();
})();
