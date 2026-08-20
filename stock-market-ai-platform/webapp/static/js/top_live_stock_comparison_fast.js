(()=>{
  if(location.pathname!='/dashboard'||new URLSearchParams(location.search).get('view')!=='live')return;
  const market=[...document.querySelectorAll('.card')].find(c=>c.querySelector(':scope > .label')?.textContent?.trim()==='MARKET');
  if(!market)return;
  market.parentElement?.classList.add('ds-market-comparison-grid');

  const card=document.createElement('div');
  card.id='ds-top-live-comparison';
  card.className='card ds-live-stock-keep';
  card.innerHTML=`<div class="tlh"><div><div class="label">TOP LIVE STOCK COMPARISON</div><h2>Top 10 Performing Stocks</h2><div class="muted">Historical performance + current live IEX mark.</div></div><div id="tls" class="mode">LOADING</div></div><div class="tlt"><b class="muted">RANGE</b>${['ALL','5Y','3Y','1Y','90D','30D','2W','1W','TODAY'].map(x=>`<button data-r="${x}" class="${x==='90D'?'on':''}">${x}</button>`).join('')}<b class="muted">VIEW</b><button data-m="growth" class="on">NORMALIZED GROWTH</button><button data-m="price">PRICE USD</button></div><div id="tll" class="tlt"><b class="muted">LINES</b></div><div class="tlt"><button data-a="left">◀ EARLIER</button><button data-a="out">− ZOOM OUT</button><span id="tlz" class="muted">FULL RANGE</span><button data-a="in">+ ZOOM IN</button><button data-a="right">LATER ▶</button><button data-a="reset">RESET VIEW</button></div><div class="tlw"><svg id="tlc" viewBox="0 0 1000 390" preserveAspectRatio="none"></svg><div id="tip" class="tli"></div></div><div id="tl-note" class="muted" style="font-size:.72rem;margin-top:8px">One local bulk history request; live prices update separately without blocking the page.</div>`;
  market.insertAdjacentElement('afterend',card);

  const style=document.createElement('style');
  style.textContent=`body.ds-live-stock-view .ds-market-comparison-grid{display:grid!important;grid-template-columns:minmax(300px,.72fr) minmax(560px,1.28fr)!important;gap:22px}.tlh{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.tlt{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}.tlt button{padding:7px 10px;border-radius:999px;border:1px solid var(--border);background:var(--panel);color:var(--muted);font-weight:850;cursor:pointer}.tlt button.on{color:#06151d;background:linear-gradient(90deg,var(--cyan),var(--green));border-color:transparent}.tlt button.off{opacity:.3}.tlw{height:390px;position:relative;margin-top:12px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.5);overflow:hidden}.tlw svg{width:100%;height:100%;cursor:crosshair}.tli{position:absolute;display:none;pointer-events:none;z-index:5;min-width:220px;padding:11px;border:1px solid var(--border);border-radius:10px;background:#081526;font-size:.74rem;line-height:1.5}@media(max-width:1050px){body.ds-live-stock-view .ds-market-comparison-grid{grid-template-columns:1fr!important}}`;
  document.head.appendChild(style);

  const svg=card.querySelector('#tlc');
  const tip=card.querySelector('#tip');
  const legend=card.querySelector('#tll');
  const stamp=card.querySelector('#tls');
  const note=card.querySelector('#tl-note');
  const colors=['#36d8ff','#39e3a1','#efc56b','#9b65ff','#ff6680','#58a6ff','#f778ba','#a5d6ff','#d2a8ff','#7ee787'];
  const names=Object.fromEntries([...document.querySelectorAll('#stock-select option')].map(o=>[o.value,(o.textContent||'').replace(/^\s*[A-Z.\-]+\s*[—-]\s*/,'').trim()]));

  let data=new Map();
  let todayData=new Map();
  let todayLoading=false;
  let todayLoadedAt=0;
  let quotes={};
  let range='90D',mode='growth',zoom=1,pan=1,active=new Set(),geo=null;
  const days={ALL:99999,'5Y':1827,'3Y':1096,'1Y':366,'90D':90,'30D':30,'2W':14,'1W':7};
  const E=(tag,attrs={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);svg.appendChild(el);return el;};

  function historicalCut(rows){
    const end=rows.at(-1)?.t||0;
    let out=rows.filter(x=>x.t>=end-days[range]*864e5);
    if(zoom>1&&out.length>2){
      const n=Math.max(2,Math.floor(out.length/zoom));
      const max=out.length-n;
      const start=Math.round(max*pan);
      out=out.slice(start,start+n);
    }
    return out;
  }

  function rowsFor(symbol,rows){
    const source=range==='TODAY'?(todayData.get(symbol)||[]):rows;
    let out=range==='TODAY'?[...source]:historicalCut(rows);
    const live=Number(quotes[symbol]?.reference_price);
    if(out.length&&Number.isFinite(live)){
      const liveTs=Date.parse(quotes[symbol]?.timestamp||'')||Date.now();
      const last=out.at(-1);
      if(!last||Math.abs(last.t-liveTs)>500)out.push({t:liveTs,price:live,live:true});
      else out[out.length-1]={t:liveTs,price:live,live:true};
    }
    return out;
  }

  function ranking(){
    const source=range==='TODAY'?todayData:data;
    return [...source].map(([symbol,baseRows])=>{
      const histRows=data.get(symbol)||baseRows;
      const rows=rowsFor(symbol,histRows);
      return {symbol,rows,ret:rows.length>1?rows.at(-1).price/rows[0].price-1:-Infinity};
    }).filter(x=>x.rows.length>1).sort((a,b)=>b.ret-a.ret).slice(0,10);
  }

  function render(){
    svg.innerHTML='';tip.style.display='none';
    const rank=ranking();
    rank.forEach(x=>active.add(x.symbol));
    card.querySelectorAll('[data-r]').forEach(b=>b.classList.toggle('on',b.dataset.r===range));
    card.querySelectorAll('[data-m]').forEach(b=>b.classList.toggle('on',b.dataset.m===mode));
    legend.innerHTML='<b class="muted">LINES</b>'+rank.map((x,i)=>`<button data-s="${x.symbol}" class="${active.has(x.symbol)?'':'off'}"><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${colors[i]};margin-right:5px"></i>${i+1}. ${x.symbol} ${x.ret>=0?'+':''}${(x.ret*100).toFixed(2)}%</button>`).join('');
    const shown=rank.filter(x=>active.has(x.symbol));
    if(!shown.length){
      const t=E('text',{x:500,y:195,'text-anchor':'middle',fill:'#91a6c2'});
      if(range==='TODAY')t.textContent=todayLoading?'Loading last 24 hours…':'No 24-hour intraday bars are available.';
      else t.textContent='Loading history…';
      geo=null;
      stamp.textContent=range==='TODAY'?(todayLoading?'24H · LOADING':'24H'):'LOADING';
      return;
    }

    const W=1000,H=390,p={l:66,r:25,t:20,b:40};
    let vals=shown.flatMap(x=>x.rows.map(q=>mode==='growth'?q.price/x.rows[0].price-1:q.price));
    let mn=Math.min(...vals),mx=Math.max(...vals);
    if(mode==='growth'){mn=Math.min(0,mn);mx=Math.max(0,mx);}
    const sp=Math.max(mx-mn,mode==='growth'?.002:1);mn-=sp*.1;mx+=sp*.1;
    const ts=shown.flatMap(x=>x.rows.map(q=>q.t));
    const t0=Math.min(...ts),t1=Math.max(...ts),td=Math.max(1,t1-t0);
    const X=t=>p.l+(W-p.l-p.r)*(t-t0)/td;
    const Y=v=>p.t+(H-p.t-p.b)*(1-(v-mn)/(mx-mn));

    for(let i=0;i<5;i++){
      const v=mn+(mx-mn)*i/4,y=Y(v);
      E('line',{x1:p.l,y1:y,x2:W-p.r,y2:y,stroke:'rgba(145,166,194,.14)'});
      const label=E('text',{x:p.l-7,y:y+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});
      label.textContent=mode==='growth'?`${v>=0?'+':''}${(v*100).toFixed(1)}%`:`$${v.toFixed(0)}`;
    }

    shown.forEach(x=>{
      const i=rank.indexOf(x),w=i<3?3:2;
      const line=E('polyline',{points:x.rows.map(q=>`${X(q.t)},${Y(mode==='growth'?q.price/x.rows[0].price-1:q.price)}`).join(' '),fill:'none',stroke:colors[i],'stroke-width':w,opacity:.94,'stroke-linejoin':'round','stroke-linecap':'round','data-sym':x.symbol});
      line.dataset.w=w;
    });

    [t0,t0+td/2,t1].forEach((t,i)=>{
      const label=E('text',{x:X(t),y:H-15,'text-anchor':i===0?'start':i===2?'end':'middle',fill:'#91a6c2','font-size':'11'});
      label.textContent=range==='TODAY'?new Date(t).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'2-digit'});
    });

    E('line',{id:'cross',y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-dasharray':'5 4',visibility:'hidden'});
    E('circle',{id:'dot',r:5.5,fill:'#fff',stroke:'#07101f','stroke-width':2,visibility:'hidden'});
    geo={W,H,p,t0,td,X,Y,shown,rank};
    stamp.textContent=`${range==='TODAY'?'24H':range} · LIVE`;
    card.querySelector('#tlz').textContent=zoom===1?'FULL RANGE':`${zoom.toFixed(1)}× ZOOM`;
    note.textContent=range==='TODAY'?'TODAY = rolling last 24 hours of 5-minute intraday history, including available extended-hours data, with the latest live IEX mark appended.':'One local bulk history request; live prices update separately without blocking the page.';
  }

  svg.addEventListener('pointermove',e=>{
    if(!geo)return;
    const {W,H,p,t0,td,X,Y,shown,rank}=geo;
    const rect=svg.getBoundingClientRect();
    const sx=(e.clientX-rect.left)*W/rect.width,sy=(e.clientY-rect.top)*H/rect.height;
    if(sx<p.l||sx>W-p.r)return;
    const target=t0+(sx-p.l)/(W-p.l-p.r)*td;
    const cross=svg.querySelector('#cross');cross.setAttribute('x1',sx);cross.setAttribute('x2',sx);cross.setAttribute('visibility','visible');
    let best;
    shown.forEach(x=>{
      const q=x.rows.reduce((a,b)=>Math.abs(b.t-target)<Math.abs(a.t-target)?b:a);
      const v=mode==='growth'?q.price/x.rows[0].price-1:q.price,y=Y(v),d=Math.abs(y-sy);
      if(!best||d<best.d)best={x,q,v,y,d};
    });
    if(!best||best.d>30){tip.style.display='none';return;}
    svg.querySelectorAll('[data-sym]').forEach(l=>{const on=l.dataset.sym===best.x.symbol;l.setAttribute('opacity',on?1:.16);l.setAttribute('stroke-width',on?5:l.dataset.w);});
    const dot=svg.querySelector('#dot');dot.setAttribute('cx',X(best.q.t));dot.setAttribute('cy',best.y);dot.setAttribute('visibility','visible');
    const ret=best.q.price/best.x.rows[0].price-1;
    tip.innerHTML=`<b>${best.x.symbol}</b><div class="muted">${names[best.x.symbol]||best.x.symbol}</div><div>Rank: <b>#${rank.indexOf(best.x)+1}</b></div><div>Price: <b>$${best.q.price.toFixed(2)}</b></div><div>Return: <b>${ret>=0?'+':''}${(ret*100).toFixed(2)}%</b></div><div>${new Date(best.q.t).toLocaleString()}${best.q.live?' · LIVE IEX':''}</div>`;
    tip.style.display='block';tip.style.left=`${Math.min(rect.width-240,e.clientX-rect.left+12)}px`;tip.style.top=`${Math.max(8,e.clientY-rect.top-20)}px`;
  });

  svg.addEventListener('pointerleave',()=>{
    tip.style.display='none';svg.querySelector('#cross')?.setAttribute('visibility','hidden');svg.querySelector('#dot')?.setAttribute('visibility','hidden');svg.querySelectorAll('[data-sym]').forEach(l=>{l.setAttribute('opacity',.94);l.setAttribute('stroke-width',l.dataset.w);});
  });

  async function loadToday(force=false){
    if(todayLoading)return;
    if(!force&&todayData.size&&Date.now()-todayLoadedAt<60000){render();return;}
    todayLoading=true;render();
    try{
      const response=await fetch(`/api/intraday-24h-top10?t=${Date.now()}`,{cache:'no-store'});
      if(!response.ok)throw new Error(`HTTP ${response.status}`);
      const payload=await response.json();
      todayData=new Map(Object.entries(payload.series||{}).map(([symbol,rows])=>[symbol,rows.map(x=>({t:Date.parse(x.t),price:Number(x.price)})).filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.price)).sort((a,b)=>a.t-b.t)]));
      todayLoadedAt=Date.now();
    }catch(err){console.warn('[24H INTRADAY]',err);}
    finally{todayLoading=false;render();}
  }

  card.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.r){
      range=b.dataset.r;zoom=1;pan=1;
      if(range==='TODAY'){loadToday();return;}
    }else if(b.dataset.m)mode=b.dataset.m;
    else if(b.dataset.s){active.has(b.dataset.s)?active.delete(b.dataset.s):active.add(b.dataset.s);}
    else if(b.dataset.a){
      if(b.dataset.a==='in')zoom=Math.min(8,zoom*1.5);
      if(b.dataset.a==='out')zoom=Math.max(1,zoom/1.5);
      if(b.dataset.a==='left')pan=Math.max(0,pan-.2);
      if(b.dataset.a==='right')pan=Math.min(1,pan+.2);
      if(b.dataset.a==='reset'){zoom=1;pan=1;}
    }
    render();
  });

  window.addEventListener('ds:all-live-stock-quotes',e=>{
    quotes=e.detail?.quotes||{};
    if(range==='TODAY'&&Date.now()-todayLoadedAt>60000&&!todayLoading)loadToday(true);
    else if(data.size||todayData.size)render();
  });

  async function load(){
    try{
      const response=await fetch('/api/local-history-bulk?limit=1300');
      const payload=await response.json();
      data=new Map(Object.entries(payload.series||{}).map(([symbol,rows])=>[symbol,rows.map(x=>({t:Date.parse(x.t),price:Number(x.price)})).filter(x=>Number.isFinite(x.t)&&Number.isFinite(x.price))]));
      render();
    }catch(err){console.warn(err);stamp.textContent='HISTORY UNAVAILABLE';}
  }
  ('requestIdleCallback'in window)?requestIdleCallback(load,{timeout:1200}):setTimeout(load,400);
})();
