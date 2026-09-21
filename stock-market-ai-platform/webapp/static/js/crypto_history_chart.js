(() => {
  const refreshMs = 2000;
  const assetNames = {
    'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'
  };
  const palette = ['#36d8ff','#39e3a1','#efc56b','#ff6680','#9b65ff','#4d8cff','#ff9d55','#7ae7ff','#b6e36b','#ff7fc8','#9ad0f5','#d3a6ff'];
  let historical = null;
  let liveQuotes = {};
  let mode = 'normalized';
  let range = '90D';
  const coreAssets = ['BTC-USD','ETH-USD','SOL-USD','XRP-USD','ADA-USD'];
  let showAll = false;
  let selected = new Set(coreAssets);
  let activePreset = 'core';
  let rankingSort = 'return';
  let rankingExpanded = false;
  let zoomLevel = 1;
  let panOffset = 0;
  let hoverSymbol = null;

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
  const pct = value => {
    const n=Number(value); if(!Number.isFinite(n)) return '—';
    return `${n>=0?'+':''}${n.toFixed(2)}%`;
  };
  function svgEl(tag, attrs={}) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag); Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v))); return n; }

  function rangeStart(endMs) {
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
    const filtered=rows.filter(r=>r.t>=start);
    const base=filtered.find(r=>Number.isFinite(r.close)&&r.close>0)?.close;
    return filtered.map(r=>({...r,rangeIndex:base>0?r.close/base*100:null}));
  }

  function seriesMetrics(symbol) {
    const rows=getSeries(symbol).filter(row=>Number.isFinite(row.close)&&row.close>0);
    if(rows.length<2)return null;
    const first=rows[0].close,last=rows[rows.length-1].close;
    let peak=first,maxDrawdown=0;
    const returns=[];
    rows.forEach((row,index)=>{
      peak=Math.max(peak,row.close);
      maxDrawdown=Math.min(maxDrawdown,row.close/peak-1);
      if(index){const previous=rows[index-1].close;if(previous>0)returns.push(row.close/previous-1);}
    });
    const mean=returns.length?returns.reduce((sum,value)=>sum+value,0)/returns.length:0;
    const variance=returns.length>1?returns.reduce((sum,value)=>sum+(value-mean)**2,0)/(returns.length-1):0;
    return {symbol,rows,first,last,returnPct:(last/first-1)*100,maxDrawdownPct:maxDrawdown*100,volatilityPct:Math.sqrt(variance)*Math.sqrt(365)*100,start:rows[0].t,end:rows[rows.length-1].t};
  }

  function allMetrics() {
    return Object.keys(historical?.series||{}).filter(symbol=>historical.series[symbol]?.available).map(seriesMetrics).filter(Boolean);
  }

  function colorFor(symbol) {
    const symbols=Object.keys(historical?.series||{}).filter(item=>historical.series[item]?.available).sort();
    return palette[Math.max(0,symbols.indexOf(symbol))%palette.length];
  }

  function activeSymbols() {
    const all=Object.keys(historical?.series||{}).filter(s=>historical.series[s]?.available).sort();
    return showAll?all:[...selected].filter(s=>historical?.series?.[s]?.available);
  }

  function focusOnly(symbol) {
    if(!historical?.series?.[symbol]?.available) return;
    showAll=false;
    selected=new Set([symbol]);
    activePreset='custom';
    hoverSymbol=null;
    zoomLevel=1;
    panOffset=0;
    renderAll();
  }

  function toggleCompare(symbol) {
    showAll=false;
    activePreset='custom';
    if(selected.has(symbol)) selected.delete(symbol);
    else selected.add(symbol);
    hoverSymbol=null;
    renderAll();
  }

  function selectAllAssets() {
    showAll=true;
    selected.clear();
    activePreset='all';
    hoverSymbol=null;
    zoomLevel=1;
    panOffset=0;
    renderAll();
  }

  function clearSelection() {
    showAll=false;
    selected.clear();
    activePreset='custom';
    hoverSymbol=null;
    renderAll();
  }

  function applyPreset(name) {
    const metrics=allMetrics();
    showAll=name==='all';
    if(name==='core')selected=new Set(coreAssets.filter(symbol=>historical?.series?.[symbol]?.available));
    if(name==='leaders')selected=new Set([...metrics].sort((a,b)=>b.returnPct-a.returnPct).slice(0,5).map(row=>row.symbol));
    if(name==='risk')selected=new Set([...metrics].sort((a,b)=>b.maxDrawdownPct-a.maxDrawdownPct||a.volatilityPct-b.volatilityPct).slice(0,5).map(row=>row.symbol));
    if(name==='all')selected.clear();
    activePreset=name;
    hoverSymbol=null;
    zoomLevel=1;
    panOffset=0;
    renderAll();
  }

  function renderLegend() {
    const root=document.getElementById('history-legend'); if(!root||!historical) return;
    const symbols=Object.keys(historical?.series||{}).filter(s=>historical.series[s]?.available).sort();
    root.innerHTML=symbols.map((s,i)=>{
      const on=showAll||selected.has(s);
      return `<button type="button" class="history-legend-chip${on?' history-selected':''}" data-symbol="${esc(s)}" title="Click to add/remove. Double-click to focus only." aria-pressed="${on?'true':'false'}"><i style="background:${palette[i%palette.length]}"></i><span>${esc(s.replace('-USD',''))}</span><small>${esc(assetNames[s]||'')}</small></button>`;
    }).join('');
    root.querySelectorAll('.history-legend-chip').forEach(btn=>{
      let clickTimer=null;
      btn.addEventListener('click',()=>{
        if(clickTimer) window.clearTimeout(clickTimer);
        clickTimer=window.setTimeout(()=>{toggleCompare(btn.dataset.symbol);clickTimer=null;},220);
      });
      btn.addEventListener('dblclick',event=>{
        event.preventDefault();
        if(clickTimer){window.clearTimeout(clickTimer);clickTimer=null;}
        focusOnly(btn.dataset.symbol);
      });
      btn.addEventListener('mouseenter',()=>{hoverSymbol=btn.dataset.symbol;applyLineEmphasis();});
      btn.addEventListener('mouseleave',()=>{hoverSymbol=null;applyLineEmphasis();});
    });
  }

  function renderSearch(query='') {
    const root=document.getElementById('history-search-results'); if(!root||!historical) return;
    const q=query.trim().toLowerCase();
    const symbols=Object.keys(historical.series).filter(s=>historical.series[s]?.available).filter(s=>!q||s.toLowerCase().includes(q)||(assetNames[s]||'').toLowerCase().includes(q)).slice(0,12);
    root.innerHTML=symbols.map(s=>`<button type="button" data-symbol="${esc(s)}"><strong>${esc(s)}</strong><span>${esc(assetNames[s]||'')}</span><small>${historical.series[s].start_utc?.slice(0,10)||'—'} → now</small></button>`).join('');
    root.classList.toggle('open',symbols.length>0);
    root.querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>{
      toggleCompare(btn.dataset.symbol);
      document.getElementById('history-search').value=''; root.classList.remove('open');
    }));
  }

  function renderSummary() {
    if(!historical) return;
    const symbols=activeSymbols();
    const set=(id,v)=>{const n=document.getElementById(id);if(n)n.textContent=v;};
    set('history-series-count',`${symbols.length} / ${Object.keys(historical.series||{}).length}`);
    set('history-start',historical.archive_global_start_utc?new Date(historical.archive_global_start_utc).toLocaleDateString():'—');
    set('history-points',historical.archive_total_chart_points?.toLocaleString()||'0');
    set('history-resolution','DAILY + LIVE');
  }

  function renderInsights() {
    const metrics=allMetrics();
    if(!metrics.length)return;
    const leader=[...metrics].sort((a,b)=>b.returnPct-a.returnPct)[0];
    const laggard=[...metrics].sort((a,b)=>a.returnPct-b.returnPct)[0];
    const lowestDrawdown=[...metrics].sort((a,b)=>b.maxDrawdownPct-a.maxDrawdownPct||a.volatilityPct-b.volatilityPct)[0];
    const btc=metrics.find(row=>row.symbol==='BTC-USD');
    const set=(id,text,cls='')=>{const node=document.getElementById(id);if(node){node.textContent=text;node.className=cls;}};
    set('history-period-leader',`${leader.symbol.replace('-USD','')} ${pct(leader.returnPct)}`,'positive');
    set('history-period-leader-detail',`${assetNames[leader.symbol]} · ${range} available window`);
    set('history-period-laggard',`${laggard.symbol.replace('-USD','')} ${pct(laggard.returnPct)}`,laggard.returnPct>=0?'positive':'negative');
    set('history-period-laggard-detail',`${assetNames[laggard.symbol]} · ${range} available window`);
    set('history-lowest-drawdown',`${lowestDrawdown.symbol.replace('-USD','')} ${lowestDrawdown.maxDrawdownPct.toFixed(2)}%`,lowestDrawdown.maxDrawdownPct>=-10?'positive':'');
    set('history-lowest-drawdown-detail',`${lowestDrawdown.volatilityPct.toFixed(1)}% annualized daily volatility`);
    set('history-btc-period-return',btc?pct(btc.returnPct):'—',btc?.returnPct>=0?'positive':'negative');
    set('history-btc-period-detail',btc?`${new Date(btc.start).toLocaleDateString()} → ${new Date(btc.end).toLocaleDateString()}`:'BTC history unavailable');
  }

  function renderRanking() {
    const root=document.getElementById('history-ranking-body');if(!root)return;
    const metrics=allMetrics();
    const btc=metrics.find(row=>row.symbol==='BTC-USD');
    const sorters={return:(a,b)=>b.returnPct-a.returnPct,drawdown:(a,b)=>b.maxDrawdownPct-a.maxDrawdownPct,volatility:(a,b)=>a.volatilityPct-b.volatilityPct};
    metrics.sort(sorters[rankingSort]||sorters.return);
    const rows=rankingExpanded?metrics:metrics.slice(0,10);
    const maxRisk=Math.max(1,...metrics.map(row=>Math.abs(row.maxDrawdownPct)));
    const symbols=Object.keys(historical?.series||{}).filter(symbol=>historical.series[symbol]?.available).sort();
    root.innerHTML=rows.map(row=>{
      const color=palette[Math.max(0,symbols.indexOf(row.symbol))%palette.length];
      const relative=btc?row.returnPct-btc.returnPct:null;
      const coverage=`${new Date(row.start).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'2-digit'})} → ${new Date(row.end).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'2-digit'})}`;
      return `<tr data-history-symbol="${esc(row.symbol)}"><td><div class="history-asset-cell"><i style="background:${color}"></i><div><strong>${esc(row.symbol.replace('-USD',''))}</strong><small>${esc(assetNames[row.symbol]||'')}</small></div></div></td><td class="${row.returnPct>=0?'positive':'negative'}"><strong>${pct(row.returnPct)}</strong></td><td class="${relative>=0?'positive':'negative'}">${pct(relative)}</td><td>${row.maxDrawdownPct.toFixed(2)}%<span class="history-risk-bar"><i style="width:${Math.abs(row.maxDrawdownPct)/maxRisk*100}%"></i></span></td><td>${row.volatilityPct.toFixed(1)}%</td><td>${coverage}</td><td>${money(row.last)}</td></tr>`;
    }).join('')||'<tr><td colspan="7">No comparable history in this range.</td></tr>';
    root.querySelectorAll('[data-history-symbol]').forEach(row=>row.addEventListener('click',()=>focusOnly(row.dataset.historySymbol)));
    const note=document.getElementById('history-ranking-note');if(note)note.textContent=`${range} · ${metrics.length} assets · daily-close volatility annualized over 365 days`;
    const toggle=document.getElementById('history-ranking-toggle');if(toggle){toggle.textContent=rankingExpanded?'SHOW TOP 10':`SHOW ALL ${metrics.length}`;toggle.hidden=metrics.length<=10;}
    document.querySelectorAll('[data-history-sort]').forEach(button=>button.classList.toggle('active',button.dataset.historySort===rankingSort));
  }

  function syncRangeAvailability() {
    const start=Date.parse(historical?.archive_global_start_utc||'');
    const end=Date.parse(historical?.archive_global_end_utc||'');
    const availableDays=Number.isFinite(start)&&Number.isFinite(end)?Math.max(0,(end-start)/86400000):0;
    const required={'30D':30,'90D':90,'1Y':365,'3Y':1095,'5Y':1825};
    document.querySelectorAll('[data-history-range]').forEach(button=>{
      const need=required[button.dataset.historyRange];
      const unavailable=Number.isFinite(need)&&availableDays+2<need;
      button.disabled=unavailable;
      button.title=unavailable?`Requires ${need} archive days; ${Math.floor(availableDays)} are available.`:'';
    });
  }

  function applyLineEmphasis(symbol=hoverSymbol) {
    const svg=document.getElementById('crypto-history-chart'); if(!svg) return;
    svg.querySelectorAll('[data-history-line]').forEach(line=>{
      const match=!symbol||line.dataset.historyLine===symbol;
      line.setAttribute('stroke-opacity',symbol?(match?'1':'0.10'):(showAll?'0.62':'0.95'));
      line.setAttribute('stroke-width',symbol?(match?'4':'1'):(showAll?'1.35':'2.6'));
    });
    svg.querySelectorAll('[data-history-dot]').forEach(dot=>{
      const match=!symbol||dot.dataset.historyDot===symbol;
      dot.setAttribute('opacity',symbol?(match?'1':'0.14'):'1');
      dot.setAttribute('r',symbol&&match?'5':showAll?'2.2':'4');
    });
    document.querySelectorAll('.history-legend-chip').forEach(chip=>{
      chip.classList.toggle('history-hover',!!symbol&&chip.dataset.symbol===symbol);
      chip.style.opacity=symbol&&chip.dataset.symbol!==symbol?'.38':'1';
    });
  }

  function zoomWindow(minT,maxT) {
    if(zoomLevel<=1) return [minT,maxT];
    const full=maxT-minT;
    const visible=full/zoomLevel;
    const maxPan=Math.max(0,full-visible);
    const start=minT+Math.min(maxPan,Math.max(0,panOffset*maxPan));
    return [start,start+visible];
  }

  function nearestAtTime(rows,targetT) {
    let best=null,dist=Infinity;
    for(const row of rows){const d=Math.abs(row.t-targetT);if(d<dist){dist=d;best=row;}}
    return best;
  }

  function renderChart() {
    const svg=document.getElementById('crypto-history-chart'); if(!svg||!historical) return;
    svg.innerHTML='';
    const W=1200,H=520,p={l:86,r:34,t:28,b:58};
    const symbols=activeSymbols();
    let bundles=symbols.map(s=>({symbol:s,color:colorFor(s),rows:getSeries(s)})).filter(b=>b.rows.length);
    if(!bundles.length){const t=svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2'});t.textContent='No historical observations available.';svg.appendChild(t);return;}
    const sourceRows=bundles.flatMap(b=>b.rows);
    const sourceMinT=Math.min(...sourceRows.map(r=>r.t)), sourceMaxT=Math.max(...sourceRows.map(r=>r.t));
    const [minT,maxT]=zoomWindow(sourceMinT,sourceMaxT);
    bundles=bundles.map(b=>({...b,rows:b.rows.filter(r=>r.t>=minT&&r.t<=maxT)})).filter(b=>b.rows.length);
    const allRows=bundles.flatMap(b=>b.rows);
    const value=r=>mode==='normalized'?r.rangeIndex:r.close;
    const values=allRows.map(value).filter(Number.isFinite);
    let minV=Math.min(...values),maxV=Math.max(...values); if(maxV===minV){minV*=.99;maxV*=1.01;}
    const logScale=minV>0 && ((mode==='raw'&&maxV/minV>100)||(mode==='normalized'&&showAll&&maxV/minV>80));
    const transform=v=>logScale?Math.log10(v):v;
    let yMin=transform(minV),yMax=transform(maxV);
    const pad=(yMax-yMin)*.07||1;
    if(mode==='normalized' && !logScale) {
      yMin=Math.max(0,yMin-pad);
    } else {
      yMin-=pad;
    }
    yMax+=pad;
    const x=t=>p.l+(W-p.l-p.r)*((t-minT)/Math.max(1,maxT-minT));
    const y=v=>p.t+(H-p.t-p.b)*(1-(transform(v)-yMin)/(yMax-yMin));

    for(let i=0;i<5;i++){
      const tv=yMin+(yMax-yMin)*i/4; const raw=logScale?10**tv:tv; const yy=p.t+(H-p.t-p.b)*(1-i/4);
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
      if(pts){const line=svgEl('polyline',{points:pts,fill:'none',stroke:b.color,'stroke-width':showAll?1.35:2.6,'stroke-opacity':showAll?.62:.95,'stroke-linejoin':'round','stroke-linecap':'round','data-history-line':b.symbol});line.dataset.historyLine=b.symbol;svg.appendChild(line);}
      const last=b.rows[b.rows.length-1]; if(last&&Number.isFinite(value(last))){const dot=svgEl('circle',{cx:x(last.t),cy:y(value(last)),r:showAll?2.2:4,fill:b.color,'data-history-dot':b.symbol});dot.dataset.historyDot=b.symbol;svg.appendChild(dot);}
    });

    const guide=svgEl('line',{y1:p.t,y2:H-p.b,stroke:'#efc56b','stroke-width':1,'stroke-dasharray':'4 4',visibility:'hidden'});svg.appendChild(guide);
    const tooltip=svgEl('g',{visibility:'hidden'}); const bg=svgEl('rect',{width:235,height:94,rx:10,fill:'#081526',stroke:'#244261'});tooltip.appendChild(bg);svg.appendChild(tooltip);
    let pointerSymbol=null;

    svg.onmousemove=e=>{
      const rect=svg.getBoundingClientRect();
      const mx=(e.clientX-rect.left)/rect.width*W, my=(e.clientY-rect.top)/rect.height*H;
      if(mx<p.l||mx>W-p.r||my<p.t||my>H-p.b){guide.setAttribute('visibility','hidden');tooltip.setAttribute('visibility','hidden');hoverSymbol=null;applyLineEmphasis();return;}
      const targetT=minT+(mx-p.l)/(W-p.l-p.r)*(maxT-minT);
      let closest=null,closestRow=null,closestPx=Infinity;
      bundles.forEach(b=>{const row=nearestAtTime(b.rows,targetT);if(!row||!Number.isFinite(value(row)))return;const d=Math.abs(y(value(row))-my);if(d<closestPx){closestPx=d;closest=b;closestRow=row;}});
      if(!closest||!closestRow)return;
      pointerSymbol=closest.symbol;hoverSymbol=closest.symbol;applyLineEmphasis();
      const xx=x(closestRow.t);guide.setAttribute('x1',xx);guide.setAttribute('x2',xx);guide.setAttribute('visibility','visible');
      while(tooltip.childNodes.length>1) tooltip.removeChild(tooltip.lastChild);
      const title=svgEl('text',{x:12,y:22,fill:closest.color,'font-size':13,'font-weight':800});title.textContent=`${closest.symbol.replace('-USD','')} · ${assetNames[closest.symbol]||''}`;tooltip.appendChild(title);
      const date=svgEl('text',{x:12,y:43,fill:'#91a6c2','font-size':11});date.textContent=new Date(closestRow.t).toLocaleDateString();tooltip.appendChild(date);
      const val=svgEl('text',{x:12,y:66,fill:'#f2f6ff','font-size':13,'font-weight':800});val.textContent=mode==='normalized'?`Index ${compact(closestRow.rangeIndex)} · ${money(closestRow.close)}`:money(closestRow.close);tooltip.appendChild(val);
      const hint=svgEl('text',{x:12,y:84,fill:'#91a6c2','font-size':10});hint.textContent='Click to add/remove · Double-click to focus only';tooltip.appendChild(hint);
      tooltip.setAttribute('transform',`translate(${Math.min(W-250,Math.max(p.l+8,mx+14))},${Math.min(H-p.b-104,Math.max(p.t+8,my-30))})`);tooltip.setAttribute('visibility','visible');
    };
    svg.onmouseleave=()=>{guide.setAttribute('visibility','hidden');tooltip.setAttribute('visibility','hidden');pointerSymbol=null;hoverSymbol=null;applyLineEmphasis();};
    let chartClickTimer=null;
    svg.onclick=()=>{
      if(!pointerSymbol)return;
      const symbol=pointerSymbol;
      if(chartClickTimer)window.clearTimeout(chartClickTimer);
      chartClickTimer=window.setTimeout(()=>{toggleCompare(symbol);chartClickTimer=null;},220);
    };
    svg.ondblclick=e=>{
      e.preventDefault();
      if(!pointerSymbol)return;
      if(chartClickTimer){window.clearTimeout(chartClickTimer);chartClickTimer=null;}
      focusOnly(pointerSymbol);
    };

    const note=document.getElementById('history-scale-note');if(note){
      const base=mode==='normalized'?'Growth index: each asset starts at 100 at its first available observation inside the selected range.':'Raw USD prices.';
      note.textContent=base+(logScale?' Automatic logarithmic scale is active so large winners do not flatten the other lines.':'')+(zoomLevel>1?` Zoom ${zoomLevel.toFixed(1)}×.`:'');
    }
    applyLineEmphasis();
  }

  function syncHistorySelectionUI() {
    const all=document.getElementById('history-show-all');
    if(all){all.textContent=showAll?'SHOWING ALL 25':'ALL 25';all.classList.toggle('active',showAll);}
    document.querySelectorAll('.history-legend-chip').forEach(chip=>{
      const on=showAll||selected.has(chip.dataset.symbol);
      chip.classList.toggle('history-selected',on);
      chip.setAttribute('aria-pressed',on?'true':'false');
    });
    document.querySelectorAll('[data-history-preset]').forEach(button=>button.classList.toggle('active',button.dataset.historyPreset===activePreset));
  }

  function renderAll(){
    renderSummary();renderInsights();renderLegend();syncHistorySelectionUI();syncRangeAvailability();renderChart();renderRanking();
    document.querySelectorAll('[data-history-range]').forEach(b=>b.classList.toggle('active',b.dataset.historyRange===range));
    document.querySelectorAll('[data-history-mode]').forEach(b=>b.classList.toggle('active',b.dataset.historyMode===mode));
    const zoom=document.getElementById('history-zoom-status');if(zoom)zoom.textContent=zoomLevel>1?`${zoomLevel.toFixed(1)}× ZOOM`:'FULL RANGE';
  }

  async function loadHistory(){
    const status=document.getElementById('history-load-status');
    try{
      if(status)status.textContent='LOADING 90D';
      historical=await window.DataShepherdCryptoHistory.load('90D');
      range='90D';
      if(status){status.textContent='HISTORY LOADED';status.className='mode';}
      renderAll();
    }
    catch(err){if(status){status.textContent='HISTORY ERROR';status.className='negative';}console.warn('[CRYPTO HISTORY]',err);}
  }
  async function refreshLive(){
    try{const r=await fetch('/api/crypto-live',{credentials:'same-origin',cache:'no-store'});if(!r.ok)return;const d=await r.json();liveQuotes=d.quotes||{};if(historical){renderChart();renderInsights();renderRanking();}}
    catch(_err){}
  }

  document.querySelectorAll('[data-history-range]').forEach(b=>b.addEventListener('click',async()=>{
    const nextRange=b.dataset.historyRange;
    if(!nextRange||nextRange===range)return;
    const status=document.getElementById('history-load-status');
    try{
      if(status)status.textContent=`LOADING ${nextRange}`;
      const nextPayload=await window.DataShepherdCryptoHistory.load(nextRange);
      historical=nextPayload;
      range=nextRange;
      zoomLevel=1;
      panOffset=0;
      if(status){status.textContent='HISTORY LOADED';status.className='mode';}
      renderAll();
    }catch(err){
      if(status){status.textContent='HISTORY ERROR';status.className='negative';}
      console.warn('[CRYPTO HISTORY RANGE]',nextRange,err);
    }
  }));
  document.querySelectorAll('[data-history-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.historyMode;renderAll();}));
  document.getElementById('history-zoom-in')?.addEventListener('click',()=>{zoomLevel=Math.min(16,zoomLevel*1.6);panOffset=Math.min(1,panOffset+.18);renderAll();});
  document.getElementById('history-zoom-out')?.addEventListener('click',()=>{zoomLevel=Math.max(1,zoomLevel/1.6);if(zoomLevel===1)panOffset=0;renderAll();});
  document.getElementById('history-pan-left')?.addEventListener('click',()=>{if(zoomLevel>1){panOffset=Math.max(0,panOffset-.18);renderAll();}});
  document.getElementById('history-pan-right')?.addEventListener('click',()=>{if(zoomLevel>1){panOffset=Math.min(1,panOffset+.18);renderAll();}});
  document.getElementById('history-reset-view')?.addEventListener('click',async()=>{
    const status=document.getElementById('history-load-status');
    try{
      if(status)status.textContent='LOADING 90D';
      historical=await window.DataShepherdCryptoHistory.load('90D');
      range='90D';
      mode='normalized';
      showAll=false;
      selected=new Set(coreAssets);
      activePreset='core';
      rankingSort='return';
      rankingExpanded=false;
      zoomLevel=1;
      panOffset=0;
      hoverSymbol=null;
      if(status){status.textContent='HISTORY LOADED';status.className='mode';}
      renderAll();
    }catch(err){
      if(status){status.textContent='HISTORY ERROR';status.className='negative';}
      console.warn('[CRYPTO HISTORY RESET]',err);
    }
  });
  document.querySelectorAll('[data-history-preset]').forEach(button=>button.addEventListener('click',()=>applyPreset(button.dataset.historyPreset)));
  document.getElementById('history-clear-selection')?.addEventListener('click',clearSelection);
  document.querySelectorAll('[data-history-sort]').forEach(button=>button.addEventListener('click',()=>{rankingSort=button.dataset.historySort;renderRanking();}));
  document.getElementById('history-ranking-toggle')?.addEventListener('click',()=>{rankingExpanded=!rankingExpanded;renderRanking();});
  const search=document.getElementById('history-search');search?.addEventListener('focus',()=>renderSearch(search.value));search?.addEventListener('input',()=>renderSearch(search.value));search?.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('history-search-results')?.classList.remove('open');});
  document.addEventListener('click',e=>{if(!e.target.closest('.history-search-wrap'))document.getElementById('history-search-results')?.classList.remove('open');});
  loadHistory();refreshLive();window.setInterval(refreshLive,refreshMs);
})();
