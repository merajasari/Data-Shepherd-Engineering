(() => {
  const colors=['#36d8ff','#39e3a1','#efc56b','#ff6680','#9b65ff','#4d8cff'];
  const money=n=>Number.isFinite(+n)?'$'+(+n).toLocaleString(undefined,{maximumFractionDigits:0}):'—',pct=n=>Number.isFinite(+n)?`${+n>=0?'+':''}${(+n).toFixed(2)}%`:'—',val=n=>Number.isFinite(+n)?(+n).toFixed(2):'—';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let payload,range='10Y',enabled=new Set(),zoom=1,pan=0,pinned=false;
  let marketQuotes={},marketFilter='all',marketSort='change',marketSearch='',marketTimer=null,marketInFlight=false,marketLastSuccess=null,marketFailures=0;

  function setupTabs(){const tabs=[...document.querySelectorAll('[data-crypto-tab]')],panels=[...document.querySelectorAll('[data-crypto-panel]')];const show=id=>{tabs.forEach(t=>{const on=t.dataset.cryptoTab===id;t.classList.toggle('active',on);t.setAttribute('aria-selected',on);t.tabIndex=on?0:-1});panels.forEach(p=>p.hidden=p.dataset.cryptoPanel!==id);history.replaceState(null,'',id==='overview'?location.pathname:`#${id}`);if(id!=='overview')modelCard(id)};tabs.forEach((t,i)=>{t.onclick=()=>show(t.dataset.cryptoTab);t.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();show(tabs[n].dataset.cryptoTab)}});const initial=location.hash.slice(1);show(tabs.some(t=>t.dataset.cryptoTab===initial)?initial:'overview')}
  function modelCard(id){
    const model={v1:'CRYPTO_V1',v2:'CRYPTO_V2',v3:'CRYPTO_V3',v4:'CRYPTO_V4',v5:'CRYPTO_V5'}[id];
    if(!model||!payload)return;
    const host=document.querySelector(`[data-model-chart="${model}"]`);
    if(!host||host.dataset.ready)return;
    host.dataset.ready='1';
    const s=payload.series.find(x=>x.model_id===model);
    if(!s){host.innerHTML='<div class="notice">A scientifically admissible reconstruction is not available in the current generated artifact.</div>';return}
    const status=esc(s.status||'historical reconstruction');
    const start=esc((s.start_timestamp||'').slice(0,10));
    const end=esc((s.end_timestamp||'').slice(0,10));
    host.innerHTML=`<div class="grid metrics" style="margin-top:18px">
      <div class="metric"><span>STARTING VALUE</span><strong>${money(s.starting_capital)}</strong></div>
      <div class="metric"><span>ENDING VALUE</span><strong>${money(s.ending_equity)}</strong></div>
      <div class="metric"><span>TOTAL RETURN</span><strong class="${+s.total_return_pct>=0?'positive':'negative'}">${pct(s.total_return_pct)}</strong></div>
      <div class="metric"><span>CAGR</span><strong>${pct(s.cagr_pct)}</strong></div>
      <div class="metric"><span>MAX DRAWDOWN</span><strong class="negative">${pct(s.max_drawdown_pct)}</strong></div>
      <div class="metric"><span>SHARPE</span><strong>${val(s.sharpe)}</strong></div>
    </div>
    <div class="grid2" style="margin-top:18px">
      <div class="notice"><strong>Eligible evidence:</strong> ${start} → ${end} · ${Number(s.observations||0).toLocaleString()} observations.</div>
      <div class="notice"><strong>Classification:</strong> ${status}. Normalized historical reconstruction; not live performance.</div>
    </div>`;
  }
  function chosen(){return(payload?.series||[]).filter(s=>enabled.has(s.model_id))}
  function bounds(){const ts=chosen().flatMap(s=>s.history.map(p=>Date.parse(p.timestamp)).filter(Number.isFinite));if(!ts.length)return[0,1];const hi=Math.max(...ts),lo=Math.min(...ts),days={10:3652.5,5:1826.25,3:1095.75,1:365.25,90:90,30:30}[parseInt(range)],base=Math.max(lo,days?hi-days*864e5:lo),baseSpan=Math.max(864e5,hi-base),span=baseSpan/zoom,room=baseSpan-span,offset=room*(pan+1)/2;return[base+offset,base+offset+span]}
  function raw(s,dd){const p=s.history.map(q=>({t:Date.parse(q.timestamp),v:+q.equity})).filter(q=>Number.isFinite(q.t)&&Number.isFinite(q.v));if(!dd)return p;let peak=0;return p.map(q=>{peak=Math.max(peak,q.v);return{t:q.t,v:(q.v/peak-1)*100}})}
  function nearest(ps,t){let b=ps[0];for(const p of ps)if(Math.abs(p.t-t)<Math.abs(b.t-t))b=p;return b}
  function dateLabel(ms,span){return new Date(ms).toLocaleDateString(undefined,span>63072000000?{year:'numeric'}:{month:'short',year:'2-digit'})}
  function chart(id,dd=false){const svg=document.getElementById(id),tip=document.getElementById(`${id}-tip`);if(!svg)return;svg.innerHTML='';tip?.classList.remove('visible');const[minT,maxT]=bounds(),sets=chosen().map(s=>({s,c:colors[payload.series.indexOf(s)%colors.length],p:raw(s,dd).filter(q=>q.t>=minT&&q.t<=maxT)})).filter(o=>o.p.length>1);if(!sets.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">No eligible series in this range</text>';return}const W=1100,H=dd?260:430,pad={l:82,r:76,t:28,b:48},all=sets.flatMap(o=>o.p);let minV=Math.min(...all.map(q=>q.v)),maxV=Math.max(...all.map(q=>q.v));if(dd)maxV=0;else{const s=Math.max(1,maxV-minV);minV=Math.max(0,minV-s*.08);maxV+=s*.12}const x=t=>pad.l+(W-pad.l-pad.r)*(t-minT)/Math.max(1,maxT-minT),y=v=>pad.t+(H-pad.t-pad.b)*(1-(v-minV)/Math.max(1e-9,maxV-minV)),add=(tag,a,parent=svg)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(a).forEach(([k,v])=>n.setAttribute(k,v));parent.appendChild(n);return n};for(let i=0;i<5;i++){const v=minV+(maxV-minV)*i/4;add('line',{x1:pad.l,x2:W-pad.r,y1:y(v),y2:y(v),stroke:'rgba(145,166,194,.16)'});const t=add('text',{x:pad.l-10,y:y(v)+4,fill:'#91a6c2','text-anchor':'end','font-size':12});t.textContent=dd?`${v.toFixed(0)}%`:money(v)}for(let i=0;i<6;i++){const ms=minT+(maxT-minT)*i/5;add('line',{x1:x(ms),x2:x(ms),y1:H-pad.b,y2:H-pad.b+5,stroke:'#7187a3'});const t=add('text',{x:x(ms),y:H-15,fill:'#91a6c2','text-anchor':i===0?'start':i===5?'end':'middle','font-size':12});t.textContent=dateLabel(ms,maxT-minT)}const lines=[];sets.forEach(o=>{o.line=add('polyline',{points:o.p.map(q=>`${x(q.t)},${y(q.v)}`).join(' '),fill:'none',stroke:o.c,'stroke-width':3});lines.push(o);const q=o.p[o.p.length-1],t=add('text',{x:W-pad.r+7,y:y(q.v)+4,fill:o.c,'font-size':11,'font-weight':800});t.textContent=o.s.label});const overlay=add('g',{'pointer-events':'none'}),guide=add('line',{y1:pad.t,y2:H-pad.b,stroke:'rgba(242,246,255,.45)','stroke-dasharray':'4 4',visibility:'hidden'},overlay);function inspect(e){const rect=svg.getBoundingClientRect(),px=(e.clientX-rect.left)*W/rect.width;if(px<pad.l||px>W-pad.r)return;const at=minT+(px-pad.l)/(W-pad.l-pad.r)*(maxT-minT),rows=lines.map(o=>({...o,q:nearest(o.p,at)})),py=(e.clientY-rect.top)*H/rect.height;let focus=rows[0];rows.forEach(r=>{if(Math.abs(y(r.q.v)-py)<Math.abs(y(focus.q.v)-py))focus=r});lines.forEach(o=>{o.line.setAttribute('stroke-width',o.s===focus.s?5:2);o.line.setAttribute('opacity',o.s===focus.s?1:.38)});overlay.querySelectorAll('circle').forEach(n=>n.remove());guide.setAttribute('x1',x(focus.q.t));guide.setAttribute('x2',x(focus.q.t));guide.setAttribute('visibility','visible');rows.forEach(r=>add('circle',{cx:x(r.q.t),cy:y(r.q.v),r:r.s===focus.s?5:3,fill:r.c,stroke:'#07101f','stroke-width':2},overlay));if(tip){tip.innerHTML=`<strong>${new Date(focus.q.t).toLocaleDateString()}</strong>`+rows.map(r=>`<div style="color:${r.c}">${esc(r.s.label)}: <strong>${dd?pct(r.q.v):money(r.q.v)}</strong></div>`).join('');tip.style.left=`${Math.min(rect.width-210,Math.max(8,e.clientX-rect.left+14))}px`;tip.style.top=`${Math.max(8,e.clientY-rect.top-20)}px`;tip.classList.add('visible')}}svg.onpointermove=e=>{if(!pinned)inspect(e)};svg.onpointerleave=()=>{if(!pinned){tip?.classList.remove('visible');guide.setAttribute('visibility','hidden');lines.forEach(o=>{o.line.setAttribute('stroke-width',3);o.line.setAttribute('opacity',1)})}};svg.onclick=e=>{pinned=!pinned;inspect(e)}}
  function render(){document.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('active',b.dataset.range===range));const legend=document.getElementById('cmr-legend');legend.innerHTML=payload.series.map((s,i)=>`<button class="cmr-chip ${enabled.has(s.model_id)?'active':''}" data-id="${esc(s.model_id)}"><i style="background:${colors[i%colors.length]}"></i>${esc(s.label)}</button>`).join('');legend.querySelectorAll('button').forEach(b=>b.onclick=()=>{enabled.has(b.dataset.id)?enabled.delete(b.dataset.id):enabled.add(b.dataset.id);pinned=false;render()});document.getElementById('cmr-table-body').innerHTML=chosen().map(s=>`<tr><td><strong>${esc(s.label)}</strong><small>${esc(s.status)}</small></td><td>${esc((s.start_timestamp||'').slice(0,10))}</td><td>${money(s.starting_capital)}</td><td>${money(s.ending_equity)}</td><td class="${+s.total_return_pct>=0?'up':'down'}">${pct(s.total_return_pct)}</td><td>${pct(s.cagr_pct)}</td><td>${pct(s.max_drawdown_pct)}</td><td>${val(s.sharpe)}</td></tr>`).join('');document.getElementById('cmr-zoom-status').textContent=`${Math.round(zoom*100)}% ZOOM`;chart('cmr-equity');chart('cmr-drawdown',true)}

  function forwardLineChart(id,rows,definitions,{percent=false,currency=false,height=430}={}){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';
    const data=(rows||[]).map(row=>({...row,_t:Date.parse(row.timestamp)})).filter(row=>Number.isFinite(row._t));
    const defs=definitions.filter(def=>data.some(row=>Number.isFinite(+row[def.key])));
    if(data.length<2||!defs.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">Forward observations will appear here as they complete</text>';return}
    const W=1100,H=height,pad={l:88,r:40,t:38,b:48},times=data.map(row=>row._t),minT=Math.min(...times),maxT=Math.max(...times);
    const values=data.flatMap(row=>defs.map(def=>+row[def.key])).filter(Number.isFinite);let minV=Math.min(...values),maxV=Math.max(...values);
    if(percent){minV=Math.min(minV,0);maxV=Math.max(maxV,0)}else{const span=Math.max(1,maxV-minV);minV-=span*.12;maxV+=span*.12}
    const ns='http://www.w3.org/2000/svg',add=(tag,attrs,parent=svg)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));parent.appendChild(el);return el};
    const x=time=>pad.l+(W-pad.l-pad.r)*(time-minT)/Math.max(1,maxT-minT),y=value=>pad.t+(H-pad.t-pad.b)*(1-(value-minV)/Math.max(1e-9,maxV-minV));
    for(let i=0;i<5;i++){const value=minV+(maxV-minV)*i/4;add('line',{x1:pad.l,x2:W-pad.r,y1:y(value),y2:y(value),stroke:'rgba(145,166,194,.15)'});const label=add('text',{x:pad.l-10,y:y(value)+4,fill:'#91a6c2','text-anchor':'end','font-size':12});label.textContent=currency?money(value):percent?`${(value*100).toFixed(1)}%`:value.toFixed(2)}
    for(let i=0;i<5;i++){const time=minT+(maxT-minT)*i/4;const label=add('text',{x:x(time),y:H-16,fill:'#91a6c2','text-anchor':i===0?'start':i===4?'end':'middle','font-size':12});label.textContent=new Date(time).toLocaleDateString(undefined,{month:'short',day:'numeric'})}
    defs.forEach((def,index)=>{const points=data.filter(row=>Number.isFinite(+row[def.key]));add('polyline',{points:points.map(row=>`${x(row._t)},${y(+row[def.key])}`).join(' '),fill:'none',stroke:def.color,'stroke-width':3.5,'stroke-linejoin':'round','stroke-linecap':'round'});points.forEach(row=>add('circle',{cx:x(row._t),cy:y(+row[def.key]),r:3.5,fill:def.color,stroke:'#07101f','stroke-width':2}));const legendX=pad.l+index*190;add('line',{x1:legendX,x2:legendX+24,y1:17,y2:17,stroke:def.color,'stroke-width':4});const label=add('text',{x:legendX+31,y:21,fill:'#dfeaff','font-size':12,'font-weight':800});label.textContent=def.label});
  }

  function forwardBarChart(id,rows,definitions){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';const data=(rows||[]).map(row=>({...row,_t:Date.parse(row.timestamp)})).filter(row=>Number.isFinite(row._t));
    if(!data.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">Completed return periods will appear here</text>';return}
    const W=1100,H=260,pad={l:76,r:30,t:36,b:46},values=data.flatMap(row=>definitions.map(def=>+row[def.key])).filter(Number.isFinite),limit=Math.max(.001,...values.map(Math.abs));
    const ns='http://www.w3.org/2000/svg',add=(tag,attrs)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));svg.appendChild(el);return el},y=value=>pad.t+(H-pad.t-pad.b)*(1-(value+limit)/(2*limit)),group=(W-pad.l-pad.r)/data.length,bar=Math.max(2,Math.min(22,group/(definitions.length+1)));
    add('line',{x1:pad.l,x2:W-pad.r,y1:y(0),y2:y(0),stroke:'rgba(242,246,255,.5)','stroke-width':1.5});
    data.forEach((row,i)=>definitions.forEach((def,j)=>{const value=+row[def.key];if(!Number.isFinite(value))return;const x=pad.l+i*group+(group-definitions.length*bar)/2+j*bar;add('rect',{x,y:Math.min(y(value),y(0)),width:Math.max(1,bar-2),height:Math.max(1,Math.abs(y(value)-y(0))),rx:2,fill:def.color,opacity:.9})}));
    definitions.forEach((def,index)=>{const x=pad.l+index*180;add('rect',{x,y:10,width:13,height:13,rx:3,fill:def.color});const label=add('text',{x:x+20,y:21,fill:'#dfeaff','font-size':12,'font-weight':800});label.textContent=def.label});
    const top=add('text',{x:pad.l-8,y:y(limit)+4,fill:'#91a6c2','text-anchor':'end','font-size':11});top.textContent=`+${(limit*100).toFixed(1)}%`;const bottom=add('text',{x:pad.l-8,y:y(-limit)+4,fill:'#91a6c2','text-anchor':'end','font-size':11});bottom.textContent=`-${(limit*100).toFixed(1)}%`;
  }

  function renderForwardCharts(){
    const source=document.getElementById('crypto-forward-chart-data');if(!source)return;let data;try{data=JSON.parse(source.textContent)}catch{return}
    const shared=data.shared_v2||{},v5=data.v5||{};
    forwardLineChart('shared-v2-equity',shared.chart_points,[{key:'candidate',label:'Shared V2',color:'#39e3a1'},{key:'benchmark',label:'Always BTC',color:'#4d8cff'}],{currency:true});
    forwardLineChart('shared-v2-drawdown',shared.chart_points,[{key:'candidate_drawdown',label:'Shared V2',color:'#39e3a1'},{key:'benchmark_drawdown',label:'Always BTC',color:'#4d8cff'}],{percent:true,height:260});
    forwardBarChart('shared-v2-returns',shared.return_points,[{key:'net_return',label:'Selected sleeve',color:'#39e3a1'},{key:'btc_return',label:'BTC',color:'#4d8cff'}]);
    forwardLineChart('shared-v2-probabilities',shared.probability_points,[{key:'btc',label:'BTC probability',color:'#4d8cff'},{key:'alt',label:'ALT probability',color:'#39e3a1'},{key:'cash',label:'CASH probability',color:'#efc56b'}],{percent:true,height:360});
    forwardLineChart('v5-forward-equity',v5.chart_points,[{key:'candidate',label:'Crypto V5',color:'#36d8ff'}],{currency:true});
    forwardLineChart('v5-forward-drawdown',v5.chart_points,[{key:'candidate_drawdown',label:'Crypto V5',color:'#ff6680'}],{percent:true,height:260});
    forwardBarChart('v5-forward-returns',v5.return_points,[{key:'net_return',label:'Net return',color:'#36d8ff'},{key:'gross_return',label:'Gross return',color:'#9b65ff'}]);
  }

  const marketNames={'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'};
  const liveMoney=value=>{const n=Number(value);if(!Number.isFinite(n))return'—';const digits=Math.abs(n)>=1000?2:Math.abs(n)>=1?4:8;return'$'+n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:digits})};
  const livePct=value=>{const n=Number(value);if(!Number.isFinite(n))return'—';return`${n>=0?'+':''}${n.toFixed(2)}%`};
  const changeOf=quote=>{const n=Number(quote?.price_percent_chg_24_h);return Number.isFinite(n)?n:null};

  function marketRows(){
    const btcChange=changeOf(marketQuotes['BTC-USD']);
    let rows=Object.entries(marketQuotes).map(([symbol,quote])=>({symbol,quote,price:Number(quote?.price),change:changeOf(quote),relative:Number.isFinite(btcChange)&&Number.isFinite(changeOf(quote))?changeOf(quote)-btcChange:null})).filter(row=>Number.isFinite(row.price)&&Number.isFinite(row.change));
    const query=marketSearch.trim().toLowerCase();
    if(query)rows=rows.filter(row=>row.symbol.toLowerCase().includes(query)||(marketNames[row.symbol]||'').toLowerCase().includes(query));
    if(marketFilter==='gainers')rows=rows.filter(row=>row.change>0);
    if(marketFilter==='losers')rows=rows.filter(row=>row.change<0);
    if(marketFilter==='extreme')rows=rows.filter(row=>Math.abs(row.change)>=5);
    const sorters={symbol:(a,b)=>a.symbol.localeCompare(b.symbol),price:(a,b)=>b.price-a.price,change:(a,b)=>b.change-a.change,relative:(a,b)=>b.relative-a.relative};
    return rows.sort(sorters[marketSort]||sorters.change);
  }

  function renderMarketBoard(updatedAt){
    const all=Object.entries(marketQuotes).map(([symbol,quote])=>({symbol,price:Number(quote?.price),change:changeOf(quote)})).filter(row=>Number.isFinite(row.price)&&Number.isFinite(row.change)).sort((a,b)=>b.change-a.change);
    if(!all.length)return;
    const btc=all.find(row=>row.symbol==='BTC-USD'),up=all.filter(row=>row.change>0).length,down=all.filter(row=>row.change<0).length;
    const ordered=[...all].map(row=>row.change).sort((a,b)=>a-b),mid=Math.floor(ordered.length/2),median=ordered.length%2?ordered[mid]:(ordered[mid-1]+ordered[mid])/2;
    const extreme=all.filter(row=>Math.abs(row.change)>=5).length,leader=all[0],laggard=all[all.length-1],maxAbs=Math.max(0.01,...all.map(row=>Math.abs(row.change)));
    const set=(id,text,cls='')=>{const node=document.getElementById(id);if(node){node.textContent=text;node.className=cls;}};
    set('crypto-market-breadth',`${up} UP · ${down} DOWN`,up>=down?'positive':'negative');
    set('crypto-market-breadth-detail',`${Math.round(up/all.length*100)}% of tracked assets are positive`);
    set('crypto-market-median',livePct(median),median>=0?'positive':'negative');
    set('crypto-market-extremes',`${leader.symbol.replace('-USD','')} / ${laggard.symbol.replace('-USD','')}`);
    set('crypto-market-extremes-detail',`${livePct(leader.change)} · ${livePct(laggard.change)}`);
    set('crypto-market-extreme-count',`${extreme} / ${all.length}`,extreme?'gold':'');
    set('crypto-market-btc-change',btc?livePct(btc.change):'—',btc?.change>=0?'positive':'negative');
    set('crypto-market-btc-price',btc?liveMoney(btc.price):'Price unavailable');
    const stamp=document.getElementById('crypto-live-ticker-stamp');if(stamp){stamp.textContent=`LIVE CACHE · ${updatedAt||'CURRENT'}`;stamp.className='mode';}
    const detail=document.getElementById('crypto-live-ticker-detail');if(detail)detail.textContent=`Auto-refresh · ${new Date().toLocaleTimeString()} · ${all.length} Coinbase USD markets`;
    const rows=marketRows(),root=document.getElementById('crypto-market-board');if(!root)return;
    root.innerHTML=rows.map(row=>`<tr><td><div class="market-asset"><span class="market-coin">${esc(row.symbol.replace('-USD','').slice(0,4))}</span><div><strong>${esc(row.symbol)}</strong><small>${esc(marketNames[row.symbol]||'')}</small></div></div></td><td><strong>${liveMoney(row.price)}</strong></td><td class="market-change-cell ${row.change>=0?'positive':'negative'}"><strong>${livePct(row.change)}</strong><small>${row.change>=0?'GAINING':'DECLINING'}</small></td><td class="${row.relative>=0?'positive':'negative'}">${livePct(row.relative)}</td><td><div class="market-intensity"><span>${Math.abs(row.change).toFixed(1)}%</span><span class="market-intensity-track"><i class="${row.change<0?'down':''}" style="width:${Math.max(2,Math.abs(row.change)/maxAbs*100).toFixed(1)}%"></i></span></div></td></tr>`).join('')||'<tr><td colspan="5">No assets match this search and filter.</td></tr>';
    document.querySelectorAll('[data-market-filter]').forEach(button=>button.classList.toggle('active',button.dataset.marketFilter===marketFilter));
    document.querySelectorAll('[data-market-sort]').forEach(button=>button.classList.toggle('active',button.dataset.marketSort===marketSort));
  }

  function scheduleMarketRefresh(delay=2000){if(marketTimer)window.clearTimeout(marketTimer);marketTimer=window.setTimeout(refreshMarket,delay)}
  async function refreshMarket(){
    if(!document.getElementById('crypto-market-board'))return;
    if(document.hidden){scheduleMarketRefresh();return}
    if(marketInFlight)return;marketInFlight=true;
    try{const response=await fetch('/api/crypto-live',{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);const data=await response.json();marketQuotes=data.quotes||{};if(!Object.keys(marketQuotes).length)throw new Error(data.error||'No live quotes available');marketLastSuccess=new Date();marketFailures=0;renderMarketBoard(data.updated_at)}catch(error){marketFailures+=1;const stamp=document.getElementById('crypto-live-ticker-stamp');if(stamp){stamp.textContent=marketLastSuccess?'STALE · RETRYING':'UNAVAILABLE · RETRYING';stamp.className='mode negative'}const detail=document.getElementById('crypto-live-ticker-detail');if(detail)detail.textContent=`${error.message} · retry ${marketFailures} · last success ${marketLastSuccess?.toLocaleTimeString()||'none'}`;}finally{marketInFlight=false;scheduleMarketRefresh()}
  }

  function initMarketBoard(){
    if(!document.getElementById('crypto-market-board'))return;
    document.getElementById('crypto-market-search')?.addEventListener('input',event=>{marketSearch=event.target.value;renderMarketBoard()});
    document.querySelectorAll('[data-market-filter]').forEach(button=>button.addEventListener('click',()=>{marketFilter=button.dataset.marketFilter;renderMarketBoard()}));
    document.querySelectorAll('[data-market-sort]').forEach(button=>button.addEventListener('click',()=>{marketSort=button.dataset.marketSort;renderMarketBoard()}));
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshMarket()});
    refreshMarket();
  }
  async function init(){const status=document.getElementById('cmr-status');try{const r=await fetch('/api/crypto-model-comparison',{credentials:'same-origin'});payload=await r.json();if(!r.ok||!payload.available)throw new Error(payload.error||`HTTP ${r.status}`);enabled=new Set(payload.series.map(s=>s.model_id));status.textContent=`${payload.series.length} ELIGIBLE SERIES · GENERATED ${(payload.generated_at_utc||'').slice(0,10)}`;document.getElementById('cmr-policy').textContent=payload.common_clock_policy;const u=document.getElementById('cmr-unavailable');if(payload.unavailable_series?.length){u.hidden=false;u.innerHTML='<strong>Not charted:</strong> '+payload.unavailable_series.map(s=>`${esc(s.label)} — ${esc(s.reason)}`).join(' · ')}render();modelCard(document.querySelector('[data-crypto-tab].active')?.dataset.cryptoTab)}catch(e){status.textContent='COMPARISON NOT BUILT';const box=document.getElementById('cmr-error');box.hidden=false;box.textContent=`${e.message} Run: python -m ml.build_crypto_model_comparison`}}
  document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{range=b.dataset.range;zoom=1;pan=0;pinned=false;render()});document.querySelectorAll('[data-chart-nav]').forEach(b=>b.onclick=()=>{const a=b.dataset.chartNav;if(a==='in')zoom=Math.min(16,zoom*1.6);if(a==='out')zoom=Math.max(1,zoom/1.6);if(a==='earlier')pan=Math.max(-1,pan-.25);if(a==='later')pan=Math.min(1,pan+.25);if(a==='reset'){zoom=1;pan=0;pinned=false}render()});setupTabs();renderForwardCharts();initMarketBoard();init();
})();
