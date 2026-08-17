(() => {
  const refreshMs = 2000;
  const assetNames = {
    'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'
  };
  const palette = ['#36d8ff','#39e3a1','#efc56b','#ff6680','#9b65ff','#4d8cff','#ff9d55','#7ae7ff','#b6e36b','#ff7fc8','#9ad0f5','#d3a6ff'];
  let historical = null;
  let liveQuotes = {};
  let mode = 'normalized';
  let range = 'ALL';
  let showAll = false;
  let selected = new Set(['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD']);

  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => {
    const n=Number(value); if(!Number.isFinite(n)) return '—';
    const digits=Math.abs(n)>=1000?2:Math.abs(n)>=1?4:8;
    return '$'+n.toLocaleString(undefined,{maximumFractionDigits:digits});
  };
  const compact = value => {
    const n=Number(value); if(!Number.isFinite(n)) return '—';
    if(Math.abs(n)>=1000000) return n.toLocaleString(undefined,{maximumFractionDigits:1,notation:'compact'});
    return n.toLocaleString(undefined,{maximumFractionDigits:2});
  };
  function svgEl(tag, attrs={}) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v))); return n; }

  function rangeStart(endMs) {
    const d = new Date(endMs);
    const day = 86400000;
    if(range==='30D') return endMs-30*day;
    if(range==='90D') return endMs-90*day;
    if(range==='1Y') return endMs-365*day;
    if(range==='3Y') return endMs-3*365*day;
    if(range==='5Y') return endMs-5*365*day;
    return -Infinity;
  }

  function getSeries(symbol) {
    const src=historical?.series?.[symbol];
    if(!src?.available) return [];
    const rows=src.points.map(p=>({t:Date.parse(p.t),close:Number(p.close),index:Number(p.index_100)})).filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.close));
    const q=liveQuotes[symbol];
    if(q && Number.isFinite(Number(q.price))) {
      const t=Date.parse(q.received_at||new Date().toISOString());
      const first=Number(src.first_close);
      rows.push({t,close:Number(q.price),index:first>0?Number(q.price)/first*100:null,live:true});
    }
    rows.sort((a,b)=>a.t-b.t);
    const end=rows.length?rows[rows.length-1].t:Date.now();
    const start=rangeStart(end);
    return rows.filter(r=>r.t>=start);
  }

  function activeSymbols() {
    const all=Object.keys(historical?.series||{}).filter(s=>historical.series[s]?.available).sort();
    return showAll?all:[...selected].filter(s=>historical?.series?.[s]?.available);
  }

  function renderLegend() {
    const root=document.getElementById('history-legend'); if(!root||!historical) return;
    const symbols=activeSymbols();
    root.innerHTML=symbols.map((s,i)=>`<button type="button" class="history-legend-chip" data-symbol="${esc(s)}" title="Remove ${esc(s)}"><i style="background:${palette[i%palette.length]}"></i><span>${esc(s.replace('-USD',''))}</span><small>${esc(assetNames[s]||'')}</small></button>`).join('');
    root.querySelectorAll('.history-legend-chip').forEach(btn=>btn.addEventListener('click',()=>{
      if(showAll){showAll=false; selected=new Set([btn.dataset.symbol]);}
      else if(selected.size>1) selected.delete(btn.dataset.symbol);
      renderAll();
    }));
  }

  function renderSearch(query='') {
    const root=document.getElementById('history-search-results'); if(!root||!historical) return;
    const q=query.trim().toLowerCase();
    const symbols=Object.keys(historical.series).filter(s=>historical.series[s]?.available).filter(s=>!q||s.toLowerCase().includes(q)||(assetNames[s]||'').toLowerCase().includes(q)).slice(0,12);
    root.innerHTML=symbols.map(s=>`<button type="button" data-symbol="${esc(s)}"><strong>${esc(s)}</strong><span>${esc(assetNames[s]||'')}</span><small>${historical.series[s].start_utc?.slice(0,10)||'—'} → now</small></button>`).join('');
    root.classList.toggle('open',symbols.length>0);
    root.querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>{
      showAll=false; selected.add(btn.dataset.symbol); document.getElementById('history-search').value=''; root.classList.remove('open'); renderAll();
    }));
  }

  function renderSummary() {
    if(!historical) return;
    const symbols=activeSymbols();
    const set=(id,v)=>{const n=document.getElementById(id);if(n)n.textContent=v;};
    set('history-series-count',`${symbols.length} / ${Object.keys(historical.series||{}).length}`);
    set('history-start',historical.global_start_utc?new Date(historical.global_start_utc).toLocaleDateString():'—');
    set('history-points',historical.total_chart_points?.toLocaleString()||'0');
    set('history-resolution','DAILY + LIVE');
  }

  function renderChart() {
    const svg=document.getElementById('crypto-history-chart'); if(!svg||!historical) return;
    svg.innerHTML='';
    const W=1200,H=520,p={l:86,r:34,t:28,b:58};
    const symbols=activeSymbols();
    const bundles=symbols.map((s,i)=>({symbol:s,color:palette[i%palette.length],rows:getSeries(s)})).filter(b=>b.rows.length);
    if(!bundles.length){const t=svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2'});t.textContent='No historical observations available.';svg.appendChild(t);return;}
    const allRows=bundles.flatMap(b=>b.rows);
    const minT=Math.min(...allRows.map(r=>r.t)), maxT=Math.max(...allRows.map(r=>r.t));
    const value=r=>mode==='normalized'?r.index:r.close;
    const values=allRows.map(value).filter(Number.isFinite);
    let minV=Math.min(...values),maxV=Math.max(...values); if(maxV===minV){minV*=.99;maxV*=1.01;}
    const logRaw=mode==='raw' && minV>0 && maxV/minV>100;
    const transform=v=>logRaw?Math.log10(v):v;
    let yMin=transform(minV),yMax=transform(maxV); const pad=(yMax-yMin)*.07||1; yMin-=pad;yMax+=pad;
    const x=t=>p.l+(W-p.l-p.r)*((t-minT)/Math.max(1,maxT-minT));
    const y=v=>p.t+(H-p.t-p.b)*(1-(transform(v)-yMin)/(yMax-yMin));
    for(let i=0;i<5;i++){
      const tv=yMin+(yMax-yMin)*i/4; const raw=logRaw?10**tv:tv; const yy=p.t+(H-p.t-p.b)*(1-i/4);
      svg.appendChild(svgEl('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.13)','stroke-width':1}));
      const label=svgEl('text',{x:p.l-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':11}); label.textContent=mode==='normalized'?compact(raw):money(raw);svg.appendChild(label);
    }
    const yearMs=365.25*86400000; const span=maxT-minT; const ticks=span>4*yearMs?7:span>yearMs?6:5;
    for(let i=0;i<ticks;i++){
      const t=minT+(maxT-minT)*i/(ticks-1); const xx=x(t); const d=new Date(t);
      const label=svgEl('text',{x:xx,y:H-22,'text-anchor':i===0?'start':i===ticks-1?'end':'middle',fill:'#91a6c2','font-size':11});
      label.textContent=span>2*yearMs?String(d.getFullYear()):d.toLocaleDateString([], {month:'short',year:'numeric'});svg.appendChild(label);
    }
    bundles.forEach(b=>{
      const pts=b.rows.filter(r=>Number.isFinite(value(r))).map(r=>`${x(r.t)},${y(value(r))}`).join(' ');
      if(pts) svg.appendChild(svgEl('polyline',{points:pts,fill:'none',stroke:b.color,'stroke-width':showAll?1.35:2.4,'stroke-opacity':showAll?.72:.95,'stroke-linejoin':'round','stroke-linecap':'round'}));
      const last=b.rows[b.rows.length-1]; if(last&&Number.isFinite(value(last))) svg.appendChild(svgEl('circle',{cx:x(last.t),cy:y(value(last)),r:showAll?2.2:4,fill:b.color}));
    });
    const guide=svgEl('line',{y1:p.t,y2:H-p.b,stroke:'#efc56b','stroke-width':1,'stroke-dasharray':'4 4',visibility:'hidden'});svg.appendChild(guide);
    const tooltip=svgEl('g',{visibility:'hidden'}); const bg=svgEl('rect',{width:250,height:Math.min(320,50+bundles.length*22),rx:10,fill:'#081526',stroke:'#244261'});tooltip.appendChild(bg);svg.appendChild(tooltip);
    svg.onmousemove=e=>{
      const rect=svg.getBoundingClientRect(),mx=(e.clientX-rect.left)/rect.width*W; const targetT=minT+(Math.max(p.l,Math.min(W-p.r,mx))-p.l)/(W-p.l-p.r)*(maxT-minT); const xx=x(targetT);
      guide.setAttribute('x1',xx);guide.setAttribute('x2',xx);guide.setAttribute('visibility','visible');
      while(tooltip.childNodes.length>1) tooltip.removeChild(tooltip.lastChild);
      const date=svgEl('text',{x:12,y:20,fill:'#f2f6ff','font-size':12,'font-weight':700});date.textContent=new Date(targetT).toLocaleDateString();tooltip.appendChild(date);
      bundles.slice(0,12).forEach((b,i)=>{let best=null,dist=Infinity;for(const r of b.rows){const d=Math.abs(r.t-targetT);if(d<dist){dist=d;best=r;}}if(!best)return;const text=svgEl('text',{x:12,y:43+i*22,fill:b.color,'font-size':11});text.textContent=`${b.symbol.replace('-USD','')}  ${mode==='normalized'?compact(best.index):money(best.close)}`;tooltip.appendChild(text);});
      tooltip.setAttribute('transform',`translate(${Math.min(W-270,Math.max(p.l+8,xx+12))},${p.t+8})`);tooltip.setAttribute('visibility','visible');
    };
    svg.onmouseleave=()=>{guide.setAttribute('visibility','hidden');tooltip.setAttribute('visibility','hidden');};
    const note=document.getElementById('history-scale-note');if(note)note.textContent=mode==='normalized'?'Growth index: each asset starts at 100 on its own first available historical observation.':'Raw USD prices'+(logRaw?' · logarithmic scale':'')+'.';
  }

  function renderAll(){renderSummary();renderLegend();renderChart();document.querySelectorAll('[data-history-range]').forEach(b=>b.classList.toggle('active',b.dataset.historyRange===range));document.querySelectorAll('[data-history-mode]').forEach(b=>b.classList.toggle('active',b.dataset.historyMode===mode));const all=document.getElementById('history-show-all');if(all){all.textContent=showAll?'SHOWING ALL 25':'SHOW ALL 25';all.classList.toggle('active',showAll);}}

  async function loadHistory(){
    const status=document.getElementById('history-load-status');
    try{const r=await fetch('/api/crypto-history',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);historical=await r.json();if(status)status.textContent='HISTORY LOADED';renderAll();}
    catch(err){if(status){status.textContent='HISTORY ERROR';status.className='negative';}console.warn('[CRYPTO HISTORY]',err);}
  }
  async function refreshLive(){
    try{const r=await fetch('/api/crypto-live',{credentials:'same-origin',cache:'no-store'});if(!r.ok)return;const d=await r.json();liveQuotes=d.quotes||{};if(historical)renderChart();}
    catch(_err){}
  }

  document.querySelectorAll('[data-history-range]').forEach(b=>b.addEventListener('click',()=>{range=b.dataset.historyRange;renderAll();}));
  document.querySelectorAll('[data-history-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.historyMode;renderAll();}));
  document.getElementById('history-show-all')?.addEventListener('click',()=>{showAll=!showAll;renderAll();});
  const search=document.getElementById('history-search');search?.addEventListener('focus',()=>renderSearch(search.value));search?.addEventListener('input',()=>renderSearch(search.value));search?.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('history-search-results')?.classList.remove('open');});
  document.addEventListener('click',e=>{if(!e.target.closest('.history-search-wrap'))document.getElementById('history-search-results')?.classList.remove('open');});
  loadHistory();refreshLive();window.setInterval(refreshLive,refreshMs);
})();
