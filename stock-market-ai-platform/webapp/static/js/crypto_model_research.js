(() => {
  const money=n=>Number.isFinite(+n)?'$'+(+n).toLocaleString(undefined,{maximumFractionDigits:0}):'—';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let marketQuotes={},marketFilter='all',marketSort='change',marketSearch='',marketTimer=null,marketInFlight=false,marketLastSuccess=null,marketFailures=0;

  function setupTabs(){const tabs=[...document.querySelectorAll('[data-crypto-tab]')],panels=[...document.querySelectorAll('[data-crypto-panel]')];const show=id=>{tabs.forEach(t=>{const on=t.dataset.cryptoTab===id;t.classList.toggle('active',on);t.setAttribute('aria-selected',on);t.tabIndex=on?0:-1});panels.forEach(p=>p.hidden=p.dataset.cryptoPanel!==id);history.replaceState(null,'',id==='overview'?location.pathname:`#${id}`)};tabs.forEach((t,i)=>{t.onclick=()=>show(t.dataset.cryptoTab);t.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();show(tabs[n].dataset.cryptoTab)}});const initial=location.hash.slice(1);show(tabs.some(t=>t.dataset.cryptoTab===initial)?initial:'overview')}

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
    forwardLineChart('shared-v2-equity',shared.chart_points,[{key:'candidate',label:'Shared V4',color:'#39e3a1'},{key:'benchmark',label:'Always BTC',color:'#4d8cff'}],{currency:true});
    forwardLineChart('shared-v2-drawdown',shared.chart_points,[{key:'candidate_drawdown',label:'Shared V4',color:'#39e3a1'},{key:'benchmark_drawdown',label:'Always BTC',color:'#4d8cff'}],{percent:true,height:260});
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
  function initPaperCountdowns(){
    const formatDuration=ms=>{const total=Math.max(0,Math.floor(ms/1000)),hours=Math.floor(total/3600),minutes=Math.floor((total%3600)/60);return hours?hours+'h '+minutes+'m':minutes+'m'};
    const formatPacific=date=>new Intl.DateTimeFormat(undefined,{timeZone:'America/Los_Angeles',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(date);
    const update=()=>document.querySelectorAll('[data-paper-countdown]').forEach(node=>{const target=new Date(node.dataset.target),label=node.dataset.label,cadence=node.dataset.cadence,span=node.querySelector('span');if(!span||!Number.isFinite(target.getTime()))return;const now=new Date();if(now<target){span.textContent=label+' begins in '+formatDuration(target-now)+' · '+formatPacific(target);return}if(cadence==='hourly'){const next=new Date(now);next.setUTCMinutes(0,0,0);next.setUTCHours(next.getUTCHours()+1);span.textContent='PAPER TRADING ACTIVE · next hourly boundary '+formatPacific(next)}else{span.textContent='CLEAN WINDOW OPEN · first/next daily decision at 5:00 PM Pacific'}});
    update();window.setInterval(update,30000);
  }

  setupTabs();renderForwardCharts();initMarketBoard();initPaperCountdowns();
})();
