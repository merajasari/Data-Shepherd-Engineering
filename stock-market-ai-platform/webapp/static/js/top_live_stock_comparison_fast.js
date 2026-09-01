(()=>{
  if(location.pathname!='/dashboard'||new URLSearchParams(location.search).get('view')!=='live')return;
  const market=[...document.querySelectorAll('.card')].find(c=>c.querySelector(':scope > .label')?.textContent?.trim()==='MARKET');
  if(!market)return;
  market.parentElement?.classList.add('ds-market-comparison-grid');

  const row=document.createElement('div');
  row.id='ds-top-live-row';
  row.className='ds-top-live-row ds-live-stock-keep';

  const listCard=document.createElement('div');
  listCard.id='ds-top-live-performance-list';
  listCard.className='card ds-live-stock-keep';
  listCard.innerHTML=`<div class="tlrank-head"><div><div class="label">TOP LIVE STOCKS</div><h2>Top 10 Performance</h2><div class="muted">Ranked by total return for the selected range.</div></div><div id="tlrank-range" class="mode">90D</div></div><div id="tlrank-list" class="tlrank-list"><div class="muted">Loading rankings…</div></div>`;

  const card=document.createElement('div');
  card.id='ds-top-live-comparison';
  card.className='card ds-live-stock-keep';
  card.innerHTML=`<div class="tlh"><div><div class="label">TOP LIVE STOCK COMPARISON</div><h2>Top 10 Performing Stocks</h2><div id="tl-subtitle" class="muted">Historical performance through the latest completed close.</div></div><div id="tls" class="mode">LOADING</div></div><div class="tlt"><b class="muted">RANGE</b>${['ALL','5Y','3Y','1Y','90D','30D','2W','1W','2D','TODAY'].map(x=>`<button data-r="${x}" class="${x==='90D'?'on':''}">${x}</button>`).join('')}<b class="muted">VIEW</b><button data-m="growth" class="on">NORMALIZED GROWTH</button><button data-m="price">PRICE USD</button></div><div id="tll" class="tlt"><b class="muted">LINES</b></div><div class="tlt"><button data-a="left">◀ EARLIER</button><button data-a="out">− ZOOM OUT</button><span id="tlz" class="muted">FULL RANGE</span><button data-a="in">+ ZOOM IN</button><button data-a="right">LATER ▶</button><button data-a="reset">RESET VIEW</button></div><div class="tlw"><svg id="tlc" viewBox="0 0 1000 390" preserveAspectRatio="none"></svg><div id="tip" class="tli"></div></div><div id="tl-note" class="muted" style="font-size:.72rem;margin-top:8px">One local bulk history request; live prices update separately without blocking the page.</div>`;

  row.append(listCard,card);
  market.insertAdjacentElement('afterend',row);

  const style=document.createElement('style');
  style.textContent=`body.ds-live-stock-view .ds-market-comparison-grid{display:grid!important;grid-template-columns:1fr!important;gap:22px}.ds-top-live-row{display:grid;grid-template-columns:minmax(280px,.62fr) minmax(620px,1.38fr);gap:22px;align-items:stretch}.ds-top-live-row>.card{min-width:0}.tlh,.tlrank-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.tlt{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}.tlt button{padding:7px 10px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}.tlt button.on{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}.tlt button.off{opacity:.3}.tlw{height:390px;position:relative;margin-top:12px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.5);overflow:hidden}.tlw svg{width:100%;height:100%;cursor:crosshair}.tli{position:absolute;display:none;pointer-events:none;z-index:5;min-width:220px;padding:11px;border:1px solid var(--border);border-radius:10px;background:#081526;font-size:.74rem;line-height:1.5}.tlrank-list{display:grid;gap:9px;margin-top:18px}.tlrank-row{display:grid;grid-template-columns:48px minmax(0,1fr) auto;gap:11px;align-items:center;padding:11px;border:1px solid rgba(120,155,205,.18);border-radius:14px;background:rgba(7,16,31,.42);transition:border-color .15s ease,transform .15s ease}.tlrank-row:hover{border-color:rgba(54,216,255,.42);transform:translateY(-1px)}.tlrank-row.top3{border-color:rgba(239,197,107,.32)}.tlrank-badge{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:rgba(239,197,107,.15);color:var(--gold);font-weight:950;font-size:1.05rem}.tlrank-symbol{font-weight:950;font-size:1.02rem;line-height:1.1}.tlrank-company{color:var(--muted);font-size:.7rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}.tlrank-track{height:7px;border-radius:99px;background:#172943;overflow:hidden;margin-top:8px}.tlrank-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--gold),var(--cyan))}.tlrank-return{text-align:right;font-weight:950;font-size:.96rem;white-space:nowrap}.tlrank-return.pos{color:var(--green)}.tlrank-return.neg{color:var(--red)}.tlrank-caption{color:var(--muted);font-size:.64rem;font-weight:850;letter-spacing:.08em;margin-bottom:3px}@media(max-width:1180px){.ds-top-live-row{grid-template-columns:1fr}.tlrank-list{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.tlrank-list{grid-template-columns:1fr}}`;
  document.head.appendChild(style);

  const svg=card.querySelector('#tlc');
  const tip=card.querySelector('#tip');
  const legend=card.querySelector('#tll');
  const stamp=card.querySelector('#tls');
  const subtitle=card.querySelector('#tl-subtitle');
  const note=card.querySelector('#tl-note');
  const rankList=listCard.querySelector('#tlrank-list');
  const rankRange=listCard.querySelector('#tlrank-range');
  const colors=['#36d8ff','#39e3a1','#efc56b','#9b65ff','#ff6680','#58a6ff','#f778ba','#a5d6ff','#d2a8ff','#7ee787'];
  const names=Object.fromEntries([...document.querySelectorAll('#stock-select option')].map(o=>[o.value,(o.textContent||'').replace(/^\s*[A-Z.\-]+\s*[—-]\s*/,'').trim()]));

  let data=new Map(),todayData=new Map(),todayLoading=false,todayLoadedAt=0,quotes={},marketOpen=null,dataLimit=0,historyLoading=false;
  let range='90D',mode='growth',zoom=1,pan=1,hidden=new Set(),geo=null,hoverActive=false,pendingRender=false;
  const days={ALL:99999,'5Y':1827,'3Y':1096,'1Y':366,'90D':90,'30D':30,'2W':14,'1W':7,'2D':2};
  const longRanges=new Set(['ALL','5Y','3Y','1Y']);
  const E=(tag,attrs={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);svg.appendChild(el);return el;};

  function easternParts(ms){const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(ms));const out={};for(const p of parts)if(p.type!=='literal')out[p.type]=Number(p.value);return out;}
  function easternWallClockMs(y,m,d,h,min){const guess=Date.UTC(y,m-1,d,h,min,0);const gp=easternParts(guess);const represented=Date.UTC(gp.year,gp.month-1,gp.day,gp.hour,gp.minute,gp.second);return guess-(represented-guess);}
  function marketOpenMs(nowMs=Date.now()){
    const cachedTimes=[...todayData.values()].flatMap(rows=>rows.map(r=>r.t)).filter(t=>Number.isFinite(t)&&t<=nowMs);
    let anchor=cachedTimes.length?Math.max(...cachedTimes):nowMs;
    let n=easternParts(anchor);
    let open=easternWallClockMs(n.year,n.month,n.day,9,30);
    if(!cachedTimes.length&&nowMs<open){
      let day=Date.UTC(n.year,n.month-1,n.day);
      do{day-=864e5;const d=new Date(day);n={year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate()};}while([0,6].includes(new Date(Date.UTC(n.year,n.month-1,n.day)).getUTCDay()));
      open=easternWallClockMs(n.year,n.month,n.day,9,30);
    }
    return open;
  }
  function liveQuote(symbol){if(marketOpen!==true)return null;const q=quotes[symbol];if(!q||q.reference_price==null)return null;const price=Number(q.reference_price),timestamp=Date.parse(q.timestamp||q.received_at||'');return Number.isFinite(price)&&price>0&&Number.isFinite(timestamp)?{price,timestamp}:null;}
  function appendLive(symbol,rows){const out=[...rows],quote=liveQuote(symbol);if(out.length&&quote){const last=out.at(-1);if(!last||Math.abs(last.t-quote.timestamp)>500)out.push({t:quote.timestamp,price:quote.price,live:true});else out[out.length-1]={t:quote.timestamp,price:quote.price,live:true};}return out;}
  function selectedRangeRows(symbol,rows){const now=Date.now();if(range==='TODAY'){const source=todayData.get(symbol)||[];const open=marketOpenMs(now);return appendLive(symbol,[...source].filter(x=>x.t>=open&&x.t<=now));}return appendLive(symbol,rows.filter(x=>x.t>=now-days[range]*864e5&&x.t<=now));}
  function rowsFor(symbol,rows){if(range==='TODAY')return selectedRangeRows(symbol,rows);const now=Date.now();let out=appendLive(symbol,rows.filter(x=>x.t>=now-days[range]*864e5&&x.t<=now));if(zoom>1&&out.length>2){const n=Math.max(2,Math.floor(out.length/zoom)),max=out.length-n,start=Math.round(max*pan);out=out.slice(start,start+n);}return out;}
  function ranking(){const source=range==='TODAY'?todayData:data;return [...source].map(([symbol,baseRows])=>{const histRows=data.get(symbol)||baseRows,fullRows=selectedRangeRows(symbol,histRows),rows=rowsFor(symbol,histRows),totalRet=fullRows.length>1?fullRows.at(-1).price/fullRows[0].price-1:-Infinity;return{symbol,rows,totalRet,ret:totalRet};}).filter(x=>x.rows.length>1&&Number.isFinite(x.totalRet)).sort((a,b)=>b.totalRet-a.totalRet).slice(0,10);}

  function renderRankingList(rank){rankRange.textContent=range==='TODAY'?'TODAY':range;if(!rank.length){rankList.innerHTML=`<div class="muted">${range==='TODAY'&&todayLoading?'Loading market session…':'No ranked stocks available.'}</div>`;return;}const maxMagnitude=Math.max(...rank.map(x=>Math.abs(x.totalRet)),0.0001);rankList.innerHTML=rank.map((x,i)=>{const pct=x.totalRet*100,width=Math.max(7,Math.min(100,Math.abs(x.totalRet)/maxMagnitude*100)),company=names[x.symbol]||x.symbol;return `<div class="tlrank-row ${i<3?'top3':''}" data-rank-symbol="${x.symbol}"><div class="tlrank-badge">#${i+1}</div><div><div class="tlrank-symbol">${x.symbol}</div><div class="tlrank-company" title="${company}">${company}</div><div class="tlrank-track"><div class="tlrank-fill" style="width:${width.toFixed(1)}%"></div></div></div><div><div class="tlrank-caption">${range==='TODAY'?'TODAY':'TOTAL'} CHANGE</div><div class="tlrank-return ${pct>=0?'pos':'neg'}">${pct>=0?'+':''}${pct.toFixed(2)}%</div></div></div>`;}).join('');}

  function render(){
    svg.innerHTML='';tip.style.display='none';const rank=ranking();renderRankingList(rank);card.querySelectorAll('[data-r]').forEach(b=>b.classList.toggle('on',b.dataset.r===range));card.querySelectorAll('[data-m]').forEach(b=>b.classList.toggle('on',b.dataset.m===mode));legend.innerHTML='<b class="muted">LINES</b>'+rank.map((x,i)=>`<button data-s="${x.symbol}" class="${hidden.has(x.symbol)?'off':''}"><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colors[i]};margin-right:5px"></i>${i+1}. ${x.symbol} ${x.totalRet>=0?'+':''}${(x.totalRet*100).toFixed(2)}%</button>`).join('');
    const shown=rank.filter(x=>!hidden.has(x.symbol));if(!shown.length){const t=E('text',{x:500,y:195,'text-anchor':'middle',fill:'#91a6c2'});t.textContent=range==='TODAY'?(todayLoading?'Loading market session…':'No intraday bars are available for the latest market session.'):(historyLoading?'Loading full history…':'Loading history…');geo=null;stamp.textContent=range==='TODAY'?(todayLoading?'TODAY · LOADING':'TODAY'):(historyLoading?'HISTORY · LOADING':'LOADING');return;}
    let plotted=shown,commonStart=null;
    if(range!=='TODAY'&&!longRanges.has(range)){
      commonStart=Math.max(...shown.map(x=>x.rows[0]?.t||0));
      const aligned=shown.map(x=>({...x,rows:x.rows.filter(q=>q.t>=commonStart)}));
      if(aligned.every(x=>x.rows.length>=2))plotted=aligned;else commonStart=null;
    }
    const W=1000,H=390,p={l:66,r:25,t:20,b:40};let vals=plotted.flatMap(x=>x.rows.map(q=>mode==='growth'?q.price/x.rows[0].price-1:q.price));let mn=Math.min(...vals),mx=Math.max(...vals);if(mode==='growth'){mn=Math.min(0,mn);mx=Math.max(0,mx);}const sp=Math.max(mx-mn,mode==='growth'?.002:1);mn-=sp*.1;mx+=sp*.1;const ts=plotted.flatMap(x=>x.rows.map(q=>q.t)),now=Date.now();let t0,t1;
    if(range==='TODAY'){
      t0=marketOpenMs(now);t1=Math.max(...ts,now);
    }else if(zoom===1){
      t1=Math.max(now,Math.max(...ts));
      if(range==='ALL')t0=Math.min(...ts);
      else if(longRanges.has(range))t0=now-days[range]*864e5;
      else t0=commonStart??Math.min(...ts);
    }else{
      t0=commonStart??Math.min(...ts);t1=Math.max(now,Math.max(...ts));
    }
    const td=Math.max(1,t1-t0),X=t=>p.l+(W-p.l-p.r)*(t-t0)/td,Y=v=>p.t+(H-p.t-p.b)*(1-(v-mn)/(mx-mn));
    for(let i=0;i<5;i++){const v=mn+(mx-mn)*i/4,y=Y(v);E('line',{x1:p.l,y1:y,x2:W-p.r,y2:y,stroke:'rgba(145,166,194,.14)'});const label=E('text',{x:p.l-7,y:y+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});label.textContent=mode==='growth'?`${v>=0?'+':''}${(v*100).toFixed(1)}%`:`$${v.toFixed(0)}`;}
    plotted.forEach(x=>{const i=rank.findIndex(r=>r.symbol===x.symbol),w=i<3?3:2,line=E('polyline',{points:x.rows.map(q=>`${X(q.t)},${Y(mode==='growth'?q.price/x.rows[0].price-1:q.price)}`).join(' '),fill:'none',stroke:colors[i],'stroke-width':w,opacity:.94,'stroke-linejoin':'round','stroke-linecap':'round','data-sym':x.symbol});line.dataset.w=w;});
    [t0,t0+td/2,t1].forEach((t,i)=>{const label=E('text',{x:X(t),y:H-15,'text-anchor':i===0?'start':i===2?'end':'middle',fill:'#91a6c2','font-size':'11'});label.textContent=range==='TODAY'?new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'2-digit'});});
    E('line',{id:'cross',y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-dasharray':'5 4',visibility:'hidden'});E('circle',{id:'dot',r:5.5,fill:'#fff',stroke:'#07101f','stroke-width':2,visibility:'hidden'});const hasLive=plotted.some(x=>x.rows.some(q=>q.live===true)),marketLabel=hasLive?'LIVE':marketOpen===false?'MARKET CLOSED':'LAST CLOSE';geo={W,H,p,t0,td,X,Y,shown:plotted,rank};stamp.textContent=`${range==='TODAY'?'TODAY':range} · ${marketLabel}`;subtitle.textContent=hasLive?'Historical performance + current live IEX mark.':'Historical performance through the latest completed close.';card.querySelector('#tlz').textContent=zoom===1?'FULL RANGE':`${zoom.toFixed(1)}× ZOOM`;
    note.textContent=range==='TODAY'
      ?(hasLive?'TODAY = the latest available U.S. market session from the 9:30 AM ET open through the current live IEX observation.':'TODAY = the latest available U.S. market session; no validated live IEX quote is currently available.')
      :longRanges.has(range)
        ?'Long-range views preserve the selected calendar window; individual stocks begin where their own local history becomes available. ALL lazy-loads the full local history.'
        :(hasLive?'Short historical views align to the first timestamp where all displayed lines have data; the current validated IEX observation is appended when newer than persisted EOD history.':'Short historical views align to the first timestamp where all displayed lines have data and end at the latest completed close.');
  }

  svg.addEventListener('pointermove',e=>{if(!geo)return;const {W,H,p,t0,td,X,Y,shown,rank}=geo,rect=svg.getBoundingClientRect(),sx=(e.clientX-rect.left)*W/rect.width,sy=(e.clientY-rect.top)*H/rect.height;if(sx<p.l||sx>W-p.r)return;const target=t0+(sx-p.l)/(W-p.l-p.r)*td;let best;shown.forEach(x=>{const q=x.rows.reduce((a,b)=>Math.abs(b.t-target)<Math.abs(a.t-target)?b:a),v=mode==='growth'?q.price/x.rows[0].price-1:q.price,y=Y(v),d=Math.abs(y-sy);if(!best||d<best.d)best={x,q,v,y,d};});if(!best||best.d>30){hoverActive=false;tip.style.display='none';return;}hoverActive=true;const cross=svg.querySelector('#cross');cross.setAttribute('x1',sx);cross.setAttribute('x2',sx);cross.setAttribute('visibility','visible');svg.querySelectorAll('[data-sym]').forEach(l=>{const on=l.dataset.sym===best.x.symbol;l.setAttribute('opacity',on?1:.16);l.setAttribute('stroke-width',on?5:l.dataset.w);});const dot=svg.querySelector('#dot');dot.setAttribute('cx',X(best.q.t));dot.setAttribute('cy',best.y);dot.setAttribute('visibility','visible');const rangeText=`${best.x.totalRet>=0?'+':''}${(best.x.totalRet*100).toFixed(2)}%`;tip.innerHTML=`<b>${best.x.symbol}</b><div class="muted">${names[best.x.symbol]||best.x.symbol}</div><div>Rank: <b>#${rank.findIndex(r=>r.symbol===best.x.symbol)+1}</b></div><div>Price: <b>$${best.q.price.toFixed(2)}</b></div><div>${range} Total Change: <b>${rangeText}</b></div><div>${new Date(best.q.t).toLocaleString()}${best.q.live?' · LIVE IEX':best.q.intraday_cache?' · CACHED IEX':''}</div>`;tip.style.display='block';tip.style.left=`${Math.min(rect.width-240,e.clientX-rect.left+12)}px`;tip.style.top=`${Math.max(8,e.clientY-rect.top-20)}px`;});
  svg.addEventListener('pointerleave',()=>{hoverActive=false;tip.style.display='none';svg.querySelector('#cross')?.setAttribute('visibility','hidden');svg.querySelector('#dot')?.setAttribute('visibility','hidden');svg.querySelectorAll('[data-sym]').forEach(l=>{l.setAttribute('opacity',.94);l.setAttribute('stroke-width',l.dataset.w);});if(pendingRender){pendingRender=false;render();}});

  async function loadToday(force=false){if(todayLoading)return;if(!force&&todayData.size&&Date.now()-todayLoadedAt<60000){render();return;}todayLoading=true;if(!hoverActive)render();try{const response=await fetch(`/api/intraday-24h-top10?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);const payload=await response.json();todayData=new Map(Object.entries(payload.series||{}).map(([symbol,rows])=>[symbol,rows.map(x=>({t:Date.parse(x.t),price:Number(x.price),live:!!x.live,intraday_cache:!x.live})).filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.price)&&x.price>0).sort((a,b)=>a.t-b.t)]));todayLoadedAt=Date.now();}catch(err){console.warn('[TODAY INTRADAY]',err);}finally{todayLoading=false;if(hoverActive)pendingRender=true;else render();}}
  card.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.r){range=b.dataset.r;zoom=1;pan=1;if(range==='TODAY'){loadToday();return;}if(range==='ALL'&&dataLimit<2600){load(2600);return;}}else if(b.dataset.m)mode=b.dataset.m;else if(b.dataset.s){hidden.has(b.dataset.s)?hidden.delete(b.dataset.s):hidden.add(b.dataset.s);}else if(b.dataset.a){if(b.dataset.a==='in')zoom=Math.min(8,zoom*1.5);if(b.dataset.a==='out')zoom=Math.max(1,zoom/1.5);if(b.dataset.a==='left')pan=Math.max(0,pan-.2);if(b.dataset.a==='right')pan=Math.min(1,pan+.2);if(b.dataset.a==='reset'){zoom=1;pan=1;}}hoverActive=false;render();});
  window.addEventListener('ds:all-live-stock-quotes',e=>{quotes=e.detail?.quotes||{};if(typeof e.detail?.marketOpen==='boolean')marketOpen=e.detail.marketOpen;if(hoverActive){pendingRender=true;return;}if(range==='TODAY'&&Date.now()-todayLoadedAt>60000&&!todayLoading)loadToday(true);else if(data.size||todayData.size)render();});
  window.addEventListener('ds:stock-market-session-state',e=>{if(typeof e.detail?.marketOpen==='boolean')marketOpen=e.detail.marketOpen;if((data.size||todayData.size)&&!hoverActive)render();});
  async function load(limit=1300){if(historyLoading)return;historyLoading=true;if(range==='ALL')stamp.textContent='ALL · LOADING';try{const response=await fetch(`/api/local-history-bulk?limit=${limit}`),payload=await response.json();data=new Map(Object.entries(payload.series||{}).map(([symbol,rows])=>[symbol,rows.map(x=>({t:Date.parse(x.t),price:Number(x.price),intraday_cache:!!x.intraday_cache})).filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.price)&&x.price>0).sort((a,b)=>a.t-b.t)]));dataLimit=Math.max(dataLimit,limit);}catch(err){console.warn(err);stamp.textContent='HISTORY UNAVAILABLE';rankList.innerHTML='<div class="muted">Ranking history unavailable.</div>';}finally{historyLoading=false;render();}}
  ('requestIdleCallback'in window)?requestIdleCallback(()=>load(1300),{timeout:1200}):setTimeout(()=>load(1300),400);
})();