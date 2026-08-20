(() => {
  if (location.pathname !== '/dashboard' || new URLSearchParams(location.search).get('view') !== 'live') return;

  const marketCard = Array.from(document.querySelectorAll('.card')).find(
    card => card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET'
  );
  if (!marketCard || document.getElementById('ds-top-live-comparison')) return;

  marketCard.parentElement?.classList.add('ds-market-comparison-grid');

  const card = document.createElement('div');
  card.id = 'ds-top-live-comparison';
  card.className = 'card ds-live-stock-keep';
  card.innerHTML = `
    <div class="tlc-head">
      <div>
        <div class="label">TOP LIVE STOCK COMPARISON</div>
        <h2>Top 10 Performing Stocks</h2>
        <div class="muted">Historical close-to-close performance with the current IEX mark appended live.</div>
      </div>
      <div id="tlc-stamp" class="mode">READY</div>
    </div>
    <div class="tlc-toolbar">
      <strong class="muted">RANGE</strong>
      <button data-range="ALL">ALL</button><button data-range="5Y">5Y</button><button data-range="3Y">3Y</button><button data-range="1Y">1Y</button><button data-range="90D" class="active">90D</button><button data-range="30D">30D</button>
      <strong class="muted tlc-view-label">VIEW</strong>
      <button data-mode="growth" class="active">NORMALIZED GROWTH</button><button data-mode="price">PRICE USD</button>
    </div>
    <div id="tlc-lines" class="tlc-lines"><strong class="muted">LINES</strong></div>
    <div class="tlc-nav">
      <span class="muted">Move across the chart for a vertical guide · hover near a line to isolate it and inspect only that stock.</span>
      <button data-action="left">◀ EARLIER</button><button data-action="out">− ZOOM OUT</button><span id="tlc-zoom">FULL RANGE</span><button data-action="in">+ ZOOM IN</button><button data-action="right">LATER ▶</button><button data-action="reset">RESET VIEW</button>
    </div>
    <div class="tlc-chart-wrap">
      <svg id="tlc-chart" viewBox="0 0 1000 390" preserveAspectRatio="none"></svg>
      <div id="tlc-tip" class="tlc-tip"></div>
    </div>
    <div class="muted tlc-note">Top 10 are ranked by return over the selected range. Historical loading is deferred and throttled so it does not block the Live Stock Viewer.</div>`;
  marketCard.insertAdjacentElement('afterend', card);

  const style = document.createElement('style');
  style.textContent = `
    body.ds-live-stock-view .ds-market-comparison-grid{display:grid!important;grid-template-columns:minmax(300px,.72fr) minmax(560px,1.28fr)!important;gap:22px;align-items:start}
    .tlc-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.tlc-toolbar,.tlc-lines,.tlc-nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}
    .tlc-toolbar button,.tlc-lines button,.tlc-nav button{padding:7px 10px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}
    .tlc-toolbar button.active,.tlc-toolbar button:hover,.tlc-lines button:not(.off):hover{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}.tlc-lines button.off{opacity:.35}.tlc-lines button.hovered{outline:2px solid rgba(242,246,255,.7);outline-offset:2px}
    .tlc-view-label{margin-left:8px}.tlc-nav span:first-child{margin-right:auto;font-size:.74rem}.tlc-nav #tlc-zoom{padding:6px 9px;border-radius:9px;background:rgba(54,216,255,.08);color:var(--cyan);font-size:.7rem;font-weight:900}
    .tlc-chart-wrap{height:390px;position:relative;margin-top:12px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.5);overflow:hidden}.tlc-chart-wrap svg{width:100%;height:100%;display:block;cursor:crosshair}
    .tlc-tip{position:absolute;display:none;pointer-events:none;z-index:10;min-width:205px;padding:11px 12px;border:1px solid var(--border);border-radius:10px;background:#081526;box-shadow:0 15px 35px rgba(0,0,0,.4);font-size:.74rem;line-height:1.5}.tlc-tip-title{display:flex;align-items:center;gap:7px;font-weight:950;font-size:.82rem;margin-bottom:5px}.tlc-tip-dot{width:9px;height:9px;border-radius:50%;display:inline-block}.tlc-tip-row{display:flex;justify-content:space-between;gap:18px}.tlc-tip-row span{color:var(--muted)}
    .tlc-note{font-size:.72rem;margin-top:8px}@media(max-width:1050px){body.ds-live-stock-view .ds-market-comparison-grid{grid-template-columns:1fr!important}.tlc-chart-wrap{height:340px}}
  `;
  document.head.appendChild(style);

  const svg = card.querySelector('#tlc-chart');
  const lines = card.querySelector('#tlc-lines');
  const stamp = card.querySelector('#tlc-stamp');
  const tip = card.querySelector('#tlc-tip');
  const colors = ['#36d8ff','#39e3a1','#efc56b','#9b65ff','#ff6680','#58a6ff','#f778ba','#a5d6ff','#d2a8ff','#7ee787'];
  let range='90D', mode='growth', zoom=1, pan=1, liveQuotes={}, series=new Map(), active=new Set(), ranked=[], loading=false;
  let hoverGeometry = null;
  let hoveredSymbol = null;
  const universe=[...document.querySelectorAll('#stock-select option')].map(o=>o.value).filter(Boolean);
  const days={ALL:3650,'5Y':1827,'3Y':1096,'1Y':366,'90D':90,'30D':30};

  const E=(tag,a={})=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(a).forEach(([k,v])=>e.setAttribute(k,v));svg.appendChild(e);return e;};
  async function fetchSymbol(symbol){try{const r=await fetch(`/api/prices/${encodeURIComponent(symbol)}?t=${Date.now()}`,{cache:'no-store'});if(!r.ok)return null;const rows=(await r.json()).map(x=>({t:Date.parse(x.timestamp||x.session_date),price:Number(x.close)})).filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.price)).sort((a,b)=>a.t-b.t);return[symbol,rows];}catch{return null;}}
  async function load(){if(loading)return;loading=true;stamp.textContent=`LOADING ${range} · BACKGROUND`;series=new Map();let next=0,completed=0;const workers=Array.from({length:4},async()=>{while(next<universe.length){const i=next++,symbol=universe[i],result=await fetchSymbol(symbol);if(result)series.set(result[0],result[1]);completed++;if(completed%8===0){stamp.textContent=`LOADING ${range} · ${completed}/${universe.length}`;render();await new Promise(r=>setTimeout(r,0));}}});await Promise.all(workers);loading=false;render();}
  function rangeRows(rows){if(!rows.length)return[];const end=rows.at(-1).t,cut=range==='ALL'?-Infinity:end-days[range]*86400000;let r=rows.filter(x=>x.t>=cut);if(zoom>1&&r.length>2){const n=Math.max(2,Math.floor(r.length/zoom)),max=r.length-n,start=Math.round(max*Math.max(0,Math.min(1,pan)));r=r.slice(start,start+n);}return r;}
  function buildRank(){ranked=[...series].map(([symbol,rows])=>{const r=rangeRows(rows);const live=Number(liveQuotes[symbol]?.reference_price);if(r.length&&Number.isFinite(live))r.push({t:Date.now(),price:live,live:true});const ret=r.length>1?r.at(-1).price/r[0].price-1:-Infinity;return{symbol,rows:r,ret};}).filter(x=>x.rows.length>1).sort((a,b)=>b.ret-a.ret).slice(0,10);ranked.forEach(x=>{if(!active.has(x.symbol))active.add(x.symbol);});}
  function nearest(rows,target){if(!rows.length)return null;let best=rows[0],dist=Math.abs(best.t-target);for(let i=1;i<rows.length;i++){const d=Math.abs(rows[i].t-target);if(d<dist){best=rows[i];dist=d;}}return best;}

  function clearHover(){
    hoveredSymbol=null;tip.style.display='none';
    svg.querySelector('#tlc-crosshair')?.setAttribute('visibility','hidden');
    svg.querySelector('#tlc-hover-dot')?.setAttribute('visibility','hidden');
    svg.querySelectorAll('[data-tlc-line]').forEach(path=>{path.setAttribute('opacity','.94');path.setAttribute('stroke-width',path.dataset.baseWidth||'2');});
    lines.querySelectorAll('button[data-symbol]').forEach(b=>b.classList.remove('hovered'));
  }

  function render(){
    buildRank();svg.innerHTML='';hoveredSymbol=null;tip.style.display='none';
    card.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('active',b.dataset.range===range));
    card.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));
    lines.innerHTML='<strong class="muted">LINES</strong>'+ranked.map((r,i)=>`<button data-symbol="${r.symbol}" class="${active.has(r.symbol)?'':'off'}"><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colors[i]};margin-right:5px"></i>${i+1}. ${r.symbol} ${(r.ret*100)>=0?'+':''}${(r.ret*100).toFixed(2)}%</button>`).join('');
    if(!ranked.length){const t=E('text',{x:500,y:195,'text-anchor':'middle',fill:'#91a6c2'});t.textContent=loading?'Loading comparison history in background…':'Waiting for market history…';return;}
    const shown=ranked.filter(r=>active.has(r.symbol));if(!shown.length)return;
    const W=1000,H=390,p={l:66,r:25,t:20,b:40};
    const vals=shown.flatMap(r=>r.rows.map(x=>mode==='growth'?(x.price/r.rows[0].price-1):x.price));let min=Math.min(...vals),max=Math.max(...vals);if(mode==='growth'){min=Math.min(0,min);max=Math.max(0,max);}let sp=Math.max(max-min,mode==='growth'?.002:1);min-=sp*.1;max+=sp*.1;
    const ts=shown.flatMap(r=>r.rows.map(x=>x.t)),t0=Math.min(...ts),t1=Math.max(...ts),td=Math.max(1,t1-t0),X=t=>p.l+(W-p.l-p.r)*(t-t0)/td,Y=v=>p.t+(H-p.t-p.b)*(1-(v-min)/(max-min));
    for(let i=0;i<5;i++){const v=min+(max-min)*i/4,y=Y(v);E('line',{x1:p.l,y1:y,x2:W-p.r,y2:y,stroke:'rgba(145,166,194,.14)'});const tx=E('text',{x:p.l-7,y:y+4,'text-anchor':'end',fill:'#91a6c2','font-size':'11'});tx.textContent=mode==='growth'?`${v>=0?'+':''}${(v*100).toFixed(1)}%`:`$${v.toFixed(0)}`;}
    shown.forEach(r=>{const i=ranked.indexOf(r),baseWidth=i<3?3:2,pts=r.rows.map(x=>`${X(x.t)},${Y(mode==='growth'?(x.price/r.rows[0].price-1):x.price)}`).join(' ');const path=E('polyline',{points:pts,fill:'none',stroke:colors[i],'stroke-width':baseWidth,'stroke-linejoin':'round','stroke-linecap':'round',opacity:'.94','data-tlc-line':r.symbol});path.dataset.baseWidth=String(baseWidth);});
    [t0,t0+td/2,t1].forEach((t,i)=>{const tx=E('text',{x:X(t),y:H-13,'text-anchor':i===0?'start':i===2?'end':'middle',fill:'#91a6c2','font-size':'11'});tx.textContent=new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'2-digit'});});
    E('line',{id:'tlc-crosshair',x1:p.l,x2:p.l,y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-width':'1.1','stroke-dasharray':'5 4',opacity:'.75',visibility:'hidden'});
    E('circle',{id:'tlc-hover-dot',cx:p.l,cy:p.t,r:'5.5',fill:'#f2f6ff',stroke:'#07101f','stroke-width':'2',visibility:'hidden'});
    hoverGeometry={W,H,p,t0,t1,td,X,Y,shown};
    stamp.textContent=loading?`LOADING ${range} · ${series.size}/${universe.length}`:`${range} · LIVE ${new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',second:'2-digit'})}`;
    card.querySelector('#tlc-zoom').textContent=zoom===1?'FULL RANGE':`${zoom.toFixed(1)}× ZOOM`;
  }

  svg.addEventListener('pointermove',event=>{
    if(!hoverGeometry)return;
    const {W,H,p,t0,td,X,Y,shown}=hoverGeometry,rect=svg.getBoundingClientRect();
    const sx=(event.clientX-rect.left)*W/rect.width,sy=(event.clientY-rect.top)*H/rect.height;
    if(sx<p.l||sx>W-p.r||sy<p.t||sy>H-p.b){clearHover();return;}
    const ratio=Math.max(0,Math.min(1,(sx-p.l)/(W-p.l-p.r))),target=t0+ratio*td,crossX=X(target);
    const cross=svg.querySelector('#tlc-crosshair');cross?.setAttribute('x1',crossX);cross?.setAttribute('x2',crossX);cross?.setAttribute('visibility','visible');
    let best=null;
    shown.forEach(r=>{const q=nearest(r.rows,target);if(!q)return;const value=mode==='growth'?(q.price/r.rows[0].price-1):q.price,yy=Y(value),distance=Math.abs(yy-sy);if(!best||distance<best.distance)best={r,q,value,yy,distance};});
    if(!best||best.distance>30){hoveredSymbol=null;tip.style.display='none';svg.querySelector('#tlc-hover-dot')?.setAttribute('visibility','hidden');svg.querySelectorAll('[data-tlc-line]').forEach(path=>{path.setAttribute('opacity','.94');path.setAttribute('stroke-width',path.dataset.baseWidth||'2');});lines.querySelectorAll('button[data-symbol]').forEach(b=>b.classList.remove('hovered'));return;}
    hoveredSymbol=best.r.symbol;
    svg.querySelectorAll('[data-tlc-line]').forEach(path=>{const on=path.getAttribute('data-tlc-line')===hoveredSymbol;path.setAttribute('opacity',on?'1':'.18');path.setAttribute('stroke-width',on?'5':path.dataset.baseWidth||'2');});
    const dot=svg.querySelector('#tlc-hover-dot');dot?.setAttribute('cx',X(best.q.t));dot?.setAttribute('cy',best.yy);dot?.setAttribute('fill',colors[ranked.indexOf(best.r)]);dot?.setAttribute('visibility','visible');
    lines.querySelectorAll('button[data-symbol]').forEach(b=>b.classList.toggle('hovered',b.dataset.symbol===hoveredSymbol));
    const returnPct=best.q.price/best.r.rows[0].price-1;
    tip.innerHTML=`<div class="tlc-tip-title"><i class="tlc-tip-dot" style="background:${colors[ranked.indexOf(best.r)]}"></i>${best.r.symbol}${best.q.live?' · LIVE':''}</div><div class="tlc-tip-row"><span>Date / time</span><b>${new Date(best.q.t).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'})}</b></div><div class="tlc-tip-row"><span>Price</span><b>$${best.q.price.toFixed(2)}</b></div><div class="tlc-tip-row"><span>Range return</span><b class="${returnPct>=0?'positive':'negative'}">${returnPct>=0?'+':''}${(returnPct*100).toFixed(2)}%</b></div><div class="tlc-tip-row"><span>Current rank</span><b>#${ranked.indexOf(best.r)+1} of 10</b></div>`;
    tip.style.display='block';const localX=event.clientX-rect.left,localY=event.clientY-rect.top,tw=tip.offsetWidth||205,th=tip.offsetHeight||120;let left=localX+16;if(left+tw>rect.width-8)left=localX-tw-16;tip.style.left=`${Math.max(8,left)}px`;tip.style.top=`${Math.max(8,Math.min(localY-th/2,rect.height-th-8))}px`;
  });
  svg.addEventListener('pointerleave',clearHover);

  card.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.dataset.range){range=b.dataset.range;zoom=1;pan=1;render();}else if(b.dataset.mode){mode=b.dataset.mode;render();}else if(b.dataset.symbol){active.has(b.dataset.symbol)?active.delete(b.dataset.symbol):active.add(b.dataset.symbol);render();}else if(b.dataset.action){if(b.dataset.action==='in')zoom=Math.min(8,zoom*1.5);if(b.dataset.action==='out')zoom=Math.max(1,zoom/1.5);if(b.dataset.action==='left')pan=Math.max(0,pan-.2);if(b.dataset.action==='right')pan=Math.min(1,pan+.2);if(b.dataset.action==='reset'){zoom=1;pan=1;}render();}});
  window.addEventListener('ds:all-live-stock-quotes',event=>{liveQuotes=event.detail?.quotes||{};render();});
  render();
  const startLoad=()=>load();
  if('requestIdleCallback' in window)requestIdleCallback(startLoad,{timeout:2500});else setTimeout(startLoad,1800);
})();
