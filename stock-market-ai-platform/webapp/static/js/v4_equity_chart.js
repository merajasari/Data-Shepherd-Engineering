(() => {
  const card = document.querySelector('.v4-chart-card');
  if (!card) return;

  const style = document.createElement('style');
  style.id = 'v4-equity-history-v2-style';
  style.textContent = `
    .v4h-card{border-color:rgba(155,101,255,.42)}
    .v4h-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}
    .v4h-title{font-size:1.2rem;font-weight:900}.v4h-subtitle{color:var(--muted);font-size:.88rem;margin-top:4px;line-height:1.5}
    .v4h-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:16px 0}
    .v4h-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}
    .v4h-btn{padding:9px 13px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}
    .v4h-btn:hover,.v4h-btn.active{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}
    .v4h-ux{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:10px 0 14px;padding:10px 12px;border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(8,20,36,.42)}
    .v4h-ux .hint{color:var(--muted);font-size:.82rem;margin-right:auto;line-height:1.45}
    .v4h-nav{padding:8px 11px;border:1px solid var(--border);border-radius:10px;background:var(--panel2);color:var(--text);font-weight:850;cursor:pointer}
    .v4h-nav:hover{border-color:rgba(54,216,255,.65);background:rgba(54,216,255,.08)}
    .v4h-zoom-status{padding:7px 10px;border-radius:10px;background:rgba(54,216,255,.08);border:1px solid rgba(54,216,255,.22);color:var(--cyan);font-size:.76rem;font-weight:900;letter-spacing:.05em}
    .v4h-help{display:flex;gap:18px;flex-wrap:wrap;margin:10px 0 8px;color:var(--muted);font-size:.8rem}.v4h-help strong{color:var(--text)}
    .v4h-panel{position:relative;background:rgba(8,20,36,.66);border:1px solid var(--border);border-radius:18px;padding:18px;min-width:0}
    .v4h-svg{width:100%;height:520px;display:block;cursor:crosshair;touch-action:pan-y}
    .v4h-note{margin-top:8px;color:var(--muted);font-size:.82rem;line-height:1.5}
    .v4h-tooltip{position:absolute;display:none;pointer-events:none;z-index:30;min-width:235px;padding:12px 14px;border:1px solid var(--border);border-radius:10px;background:#081526;box-shadow:0 18px 40px rgba(0,0,0,.38);font-size:.78rem;line-height:1.5;color:var(--text)}
    .v4h-tooltip strong{display:block;margin-bottom:5px}.v4h-tooltip-row{display:flex;justify-content:space-between;gap:18px}.v4h-tooltip-row span:first-child{color:var(--muted)}
    .v4h-warning{padding:14px;border-radius:14px;border:1px solid rgba(239,197,107,.25);background:rgba(239,197,107,.07);color:var(--gold);line-height:1.5;margin-top:14px}
    @media(max-width:1050px){.v4h-metrics{grid-template-columns:repeat(2,1fr)}}
    @media(max-width:650px){.v4h-metrics{grid-template-columns:1fr}.v4h-svg{height:360px}.v4h-ux .hint{width:100%;flex-basis:100%}.v4h-nav{padding:8px 9px;font-size:.78rem}}
  `;
  document.getElementById(style.id)?.remove();
  document.head.appendChild(style);

  card.innerHTML = `
    <div class="v4h-head">
      <div>
        <div class="label">PORTFOLIO EQUITY OVER TIME</div>
        <div class="v4h-title">Full V4 portfolio history</div>
        <div class="v4h-subtitle">Explore reconstructed V4 history, recorded paper-journal observations, and the current read-only mark-to-market point with the same interaction model used by Full Crypto Market History.</div>
      </div>
      <span id="v4h-load-status" class="mode">LOADING HISTORY</span>
    </div>
    <div class="v4h-metrics">
      <div class="metric"><span>VISIBLE RANGE</span><strong id="v4h-visible-range">—</strong></div>
      <div class="metric"><span>OBSERVATIONS</span><strong id="v4h-point-count">—</strong></div>
      <div class="metric"><span>STARTING EQUITY</span><strong id="v4-chart-start">—</strong></div>
      <div class="metric"><span>CURRENT EQUITY</span><strong id="v4-chart-current">—</strong></div>
    </div>
    <div class="v4h-toolbar">
      <strong class="muted">RANGE</strong>
      <button class="v4h-btn" type="button" data-v4h-range="ALL">ALL</button>
      <button class="v4h-btn" type="button" data-v4h-range="5Y">5Y</button>
      <button class="v4h-btn" type="button" data-v4h-range="3Y">3Y</button>
      <button class="v4h-btn" type="button" data-v4h-range="1Y">1Y</button>
      <button class="v4h-btn active" type="button" data-v4h-range="90D">90D</button>
      <button class="v4h-btn" type="button" data-v4h-range="30D">30D</button>
      <strong class="muted" style="margin-left:10px">VIEW</strong>
      <button class="v4h-btn active" type="button" data-v4h-mode="equity">EQUITY USD</button>
      <button class="v4h-btn" type="button" data-v4h-mode="normalized">NORMALIZED GROWTH</button>
    </div>
    <div class="v4h-ux">
      <div class="hint"><strong>Easy explore:</strong> hover anywhere on the chart to inspect the nearest observation · click to pin/unpin it · zoom and pan with the controls.</div>
      <button id="v4h-pan-left" class="v4h-nav" type="button" title="Move the zoomed window earlier">◀ EARLIER</button>
      <button id="v4h-zoom-out" class="v4h-nav" type="button">− ZOOM OUT</button>
      <span id="v4h-zoom-status" class="v4h-zoom-status">FULL RANGE</span>
      <button id="v4h-zoom-in" class="v4h-nav" type="button">+ ZOOM IN</button>
      <button id="v4h-pan-right" class="v4h-nav" type="button" title="Move the zoomed window later">LATER ▶</button>
      <button id="v4h-reset-view" class="v4h-nav" type="button">RESET VIEW</button>
    </div>
    <div class="v4h-help">
      <span><strong>Hover:</strong> exact timestamp, equity, change, and source</span>
      <span><strong>Click:</strong> pins the selected observation</span>
      <span><strong>Range:</strong> filters by actual timestamp</span>
      <span><strong>Auto scale:</strong> keeps small portfolio moves readable</span>
    </div>
    <div class="v4h-panel">
      <svg id="v4-equity-chart" class="v4h-svg" viewBox="0 0 1200 520" preserveAspectRatio="none" aria-label="Interactive V4 portfolio equity history"></svg>
      <div id="v4h-tooltip" class="v4h-tooltip"></div>
      <div id="v4h-scale-note" class="v4h-note">Equity USD view.</div>
    </div>
    <div class="v4h-warning">Historical observations are display-only. Reconstructed history, paper-journal observations, and live read-only marks are visually combined without changing portfolio state, frozen models, journals, or brokerage settings.</div>`;

  const svg = document.getElementById('v4-equity-chart');
  const tooltip = document.getElementById('v4h-tooltip');
  const panel = svg.closest('.v4h-panel');
  const ns = 'http://www.w3.org/2000/svg';

  let allRows = [];
  let startingEquity = 100000;
  let currentEquity = 100000;
  let range = '90D';
  let mode = 'equity';
  let zoomLevel = 1;
  let panOffset = 0;
  let pinnedIndex = null;
  let pointerActive = false;

  const money = v => '$' + Number(v || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const signedMoney = v => `${Number(v)>=0?'+':'-'}$${Math.abs(Number(v||0)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const pct = v => `${Number(v)>=0?'+':''}${Number(v||0).toFixed(2)}%`;
  const compactDate = t => new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});
  const fullDate = t => new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'});
  function svgEl(tag, attrs={}) { const n=document.createElementNS(ns,tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v))); return n; }

  function parseRows(raw) {
    const rows = (raw || []).map((row, i) => {
      const t = Date.parse(row.timestamp || '');
      const equity = Number(row.equity);
      if (!Number.isFinite(t) || !Number.isFinite(equity)) return null;
      let source = 'Recorded journal';
      if (row.synthetic_baseline) source = 'Synthetic baseline';
      else if (row.current_mark || row.label === 'Current') source = 'Current mark-to-market';
      else if (row.history_type || row.reconstructed || row.source === 'RECONSTRUCTED') source = 'Reconstructed history';
      return {...row, _i:i, t, equity, source};
    }).filter(Boolean).sort((a,b)=>a.t-b.t);
    const dedup = [];
    for (const row of rows) {
      const last = dedup[dedup.length-1];
      if (last && last.t === row.t && Math.abs(last.equity-row.equity) < 1e-9) dedup[dedup.length-1] = row;
      else dedup.push(row);
    }
    return dedup;
  }

  function rangeStart(endMs) {
    const day = 86400000;
    if(range==='30D') return endMs-30*day;
    if(range==='90D') return endMs-90*day;
    if(range==='1Y') return endMs-365*day;
    if(range==='3Y') return endMs-3*365*day;
    if(range==='5Y') return endMs-5*365*day;
    return -Infinity;
  }

  function rangedRows() {
    if (!allRows.length) return [];
    const end = allRows[allRows.length-1].t;
    const start = rangeStart(end);
    const rows = allRows.filter(r=>r.t>=start);
    return rows.length ? rows : allRows.slice(-1);
  }

  function zoomWindow(rows) {
    if (rows.length < 2 || zoomLevel <= 1) return rows;
    const minT=rows[0].t,maxT=rows[rows.length-1].t,full=Math.max(1,maxT-minT);
    const visible=full/zoomLevel,maxPan=Math.max(0,full-visible);
    const start=minT+Math.min(maxPan,Math.max(0,panOffset*maxPan));
    const end=start+visible;
    const filtered=rows.filter(r=>r.t>=start&&r.t<=end);
    return filtered.length>=2?filtered:rows;
  }

  function nearestByTime(rows,targetT) {
    let best=0,dist=Infinity;
    rows.forEach((r,i)=>{const d=Math.abs(r.t-targetT);if(d<dist){dist=d;best=i;}});
    return best;
  }

  function valueOf(row) {
    if (mode === 'normalized') return startingEquity > 0 ? row.equity / startingEquity * 100 : 100;
    return row.equity;
  }

  function sourceLabel(row) {
    if (row.label === 'Start') return 'Start baseline';
    if (row.label === 'Current' || row.current_mark) return 'Current mark-to-market';
    if (row.synthetic_baseline) return 'Synthetic baseline';
    if (row.history_type || row.reconstructed || row.source === 'RECONSTRUCTED') return 'Reconstructed history';
    return row.source || 'Recorded observation';
  }

  function updateTopMetrics(rows) {
    const set=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=v;};
    set('v4h-point-count', rows.length.toLocaleString());
    set('v4-chart-start', money(startingEquity));
    set('v4-chart-current', money(currentEquity));
    if(rows.length){
      const start=compactDate(rows[0].t),end=compactDate(rows[rows.length-1].t);
      set('v4h-visible-range', start===end?start:`${start} → ${end}`);
    } else set('v4h-visible-range','—');
  }

  function showTooltip(row, clientX, clientY, index, visibleRows) {
    if (!row) return;
    const change=row.equity-startingEquity;
    const changePct=startingEquity?change/startingEquity*100:0;
    tooltip.innerHTML=`<strong>${row.label || fullDate(row.t)}</strong>
      <div class="v4h-tooltip-row"><span>Portfolio equity</span><b>${money(row.equity)}</b></div>
      <div class="v4h-tooltip-row"><span>Vs start</span><b class="${change>=0?'positive':'negative'}">${signedMoney(change)} (${pct(changePct)})</b></div>
      <div class="v4h-tooltip-row"><span>Observation</span><b>${index+1} / ${visibleRows.length}</b></div>
      <div class="v4h-tooltip-row"><span>Source</span><b>${sourceLabel(row)}</b></div>`;
    tooltip.style.display='block';
    const rect=panel.getBoundingClientRect();
    const tw=tooltip.offsetWidth||235,th=tooltip.offsetHeight||115;
    let left=clientX-rect.left+16,top=clientY-rect.top-th/2;
    if(left+tw>rect.width-8)left=clientX-rect.left-tw-16;
    tooltip.style.left=Math.max(8,left)+'px';
    tooltip.style.top=Math.max(8,Math.min(top,rect.height-th-8))+'px';
  }

  function render() {
    svg.innerHTML='';
    const baseRows=rangedRows();
    const rows=zoomWindow(baseRows);
    updateTopMetrics(rows);
    document.querySelectorAll('[data-v4h-range]').forEach(b=>b.classList.toggle('active',b.dataset.v4hRange===range));
    document.querySelectorAll('[data-v4h-mode]').forEach(b=>b.classList.toggle('active',b.dataset.v4hMode===mode));
    const zoom=document.getElementById('v4h-zoom-status');if(zoom)zoom.textContent=zoomLevel>1?`${zoomLevel.toFixed(1)}× ZOOM`:'FULL RANGE';
    const note=document.getElementById('v4h-scale-note');if(note)note.textContent=mode==='normalized'?'Normalized growth index: starting equity = 100.':'Equity USD view with automatic y-axis scaling.';

    const W=1200,H=520,p={l:92,r:38,t:30,b:62};
    if(rows.length<1){const t=svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2','font-size':15});t.textContent='No portfolio observations available.';svg.appendChild(t);return;}
    const minT=rows[0].t,maxT=rows[rows.length-1].t;
    const vals=rows.map(valueOf).filter(Number.isFinite);
    let minV=Math.min(...vals),maxV=Math.max(...vals);
    if(mode==='equity'){minV=Math.min(minV,startingEquity);maxV=Math.max(maxV,startingEquity);}
    let span=Math.max(maxV-minV,mode==='equity'?Math.max(100,startingEquity*.002):.5);
    minV-=span*.10;maxV+=span*.10;
    const x=t=>rows.length===1?p.l+(W-p.l-p.r)/2:p.l+(W-p.l-p.r)*((t-minT)/Math.max(1,maxT-minT));
    const y=v=>p.t+(H-p.t-p.b)*(1-(v-minV)/Math.max(.000001,maxV-minV));

    for(let i=0;i<5;i++){
      const v=minV+(maxV-minV)*i/4,yy=y(v);
      svg.appendChild(svgEl('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.13)','stroke-width':1}));
      const label=svgEl('text',{x:p.l-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});label.textContent=mode==='normalized'?v.toFixed(1):money(v);svg.appendChild(label);
    }

    if(mode==='equity'){
      const by=y(startingEquity);
      svg.appendChild(svgEl('line',{x1:p.l,y1:by,x2:W-p.r,y2:by,stroke:'#91a6c2','stroke-width':1.1,'stroke-dasharray':'6 5',opacity:.7}));
      const base=svgEl('text',{x:p.l+8,y:by-7,fill:'#91a6c2','font-size':11,'font-weight':700});base.textContent=`${money(startingEquity)} baseline`;svg.appendChild(base);
    } else {
      const by=y(100);
      svg.appendChild(svgEl('line',{x1:p.l,y1:by,x2:W-p.r,y2:by,stroke:'#91a6c2','stroke-width':1.1,'stroke-dasharray':'6 5',opacity:.7}));
    }

    const tickCount=5;
    for(let i=0;i<tickCount;i++){
      const t=minT+(maxT-minT)*i/(tickCount-1||1),xx=x(t),d=new Date(t);
      const label=svgEl('text',{x:xx,y:H-24,'text-anchor':i===0?'start':i===tickCount-1?'end':'middle',fill:'#91a6c2','font-size':11});
      const daySpan=(maxT-minT)/86400000;
      label.textContent=daySpan>730?String(d.getFullYear()):daySpan>120?d.toLocaleDateString([],{month:'short',year:'numeric'}):d.toLocaleDateString([],{month:'short',day:'numeric'});
      svg.appendChild(label);
    }

    if(rows.length>1){
      const pts=rows.map(r=>[x(r.t),y(valueOf(r))]);
      svg.appendChild(svgEl('path',{d:`M ${pts[0][0]} ${H-p.b} L ${pts.map(q=>q.join(' ')).join(' L ')} L ${pts.at(-1)[0]} ${H-p.b} Z`,fill:'rgba(57,227,161,.08)'}));
      svg.appendChild(svgEl('polyline',{points:pts.map(q=>q.join(',')).join(' '),fill:'none',stroke:'#39e3a1','stroke-width':3,'stroke-linejoin':'round','stroke-linecap':'round'}));
    }

    const last=rows[rows.length-1];
    svg.appendChild(svgEl('circle',{cx:x(last.t),cy:y(valueOf(last)),r:4.5,fill:'#39e3a1',stroke:'#07101f','stroke-width':2}));
    const guide=svgEl('line',{y1:p.t,y2:H-p.b,stroke:'#efc56b','stroke-width':1,'stroke-dasharray':'4 4',visibility:'hidden'});svg.appendChild(guide);
    const dot=svgEl('circle',{r:5,fill:'#efc56b',stroke:'#07101f','stroke-width':2,visibility:'hidden'});svg.appendChild(dot);
    const overlay=svgEl('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'rgba(0,0,0,.001)','pointer-events':'all',style:'cursor:crosshair;touch-action:none'});svg.appendChild(overlay);

    function selectAt(event, pin=false){
      const rect=svg.getBoundingClientRect(),mx=(event.clientX-rect.left)/rect.width*W;
      if(mx<p.l||mx>W-p.r)return;
      const target=minT+(mx-p.l)/(W-p.l-p.r)*Math.max(1,maxT-minT);
      const idx=nearestByTime(rows,target),row=rows[idx],xx=x(row.t),yy=y(valueOf(row));
      guide.setAttribute('x1',xx);guide.setAttribute('x2',xx);guide.setAttribute('visibility','visible');
      dot.setAttribute('cx',xx);dot.setAttribute('cy',yy);dot.setAttribute('visibility','visible');
      showTooltip(row,event.clientX,event.clientY,idx,rows);
      if(pin)pinnedIndex=(pinnedIndex===idx?null:idx);
    }

    overlay.addEventListener('pointerenter',()=>{pointerActive=true;});
    overlay.addEventListener('pointermove',event=>{if(pinnedIndex===null)selectAt(event,false);});
    overlay.addEventListener('pointerdown',event=>{overlay.setPointerCapture?.(event.pointerId);selectAt(event,true);});
    overlay.addEventListener('pointerleave',()=>{pointerActive=false;if(pinnedIndex===null){guide.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');tooltip.style.display='none';}});
  }

  async function load() {
    const status=document.getElementById('v4h-load-status');
    try{
      if(status)status.textContent='LOADING HISTORY';
      const response=await fetch('/api/v4-forward',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const d=await response.json();
      startingEquity=Number(d.portfolio?.starting_cash||100000);
      currentEquity=Number(d.portfolio?.equity||startingEquity);
      allRows=parseRows(d.forward?.chart_history||[]);
      if(status){status.textContent='HISTORY LOADED';status.className='mode';}
      render();
    }catch(err){
      if(status){status.textContent='HISTORY ERROR';status.className='negative';}
      console.error('[V4 EQUITY HISTORY]',err);
    }
  }

  document.querySelectorAll('[data-v4h-range]').forEach(b=>b.addEventListener('click',()=>{range=b.dataset.v4hRange;zoomLevel=1;panOffset=0;pinnedIndex=null;tooltip.style.display='none';render();}));
  document.querySelectorAll('[data-v4h-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.v4hMode;pinnedIndex=null;tooltip.style.display='none';render();}));
  document.getElementById('v4h-zoom-in')?.addEventListener('click',()=>{zoomLevel=Math.min(16,zoomLevel*1.6);panOffset=Math.min(1,panOffset+.18);pinnedIndex=null;render();});
  document.getElementById('v4h-zoom-out')?.addEventListener('click',()=>{zoomLevel=Math.max(1,zoomLevel/1.6);if(zoomLevel===1)panOffset=0;pinnedIndex=null;render();});
  document.getElementById('v4h-pan-left')?.addEventListener('click',()=>{if(zoomLevel>1){panOffset=Math.max(0,panOffset-.18);pinnedIndex=null;render();}});
  document.getElementById('v4h-pan-right')?.addEventListener('click',()=>{if(zoomLevel>1){panOffset=Math.min(1,panOffset+.18);pinnedIndex=null;render();}});
  document.getElementById('v4h-reset-view')?.addEventListener('click',()=>{range='90D';mode='equity';zoomLevel=1;panOffset=0;pinnedIndex=null;tooltip.style.display='none';render();});

  const begin=()=>load();
  if('requestIdleCallback' in window)requestIdleCallback(begin,{timeout:600});else setTimeout(begin,60);
  window.setInterval(()=>{if(!pointerActive&&pinnedIndex===null)load();},5000);
})();
