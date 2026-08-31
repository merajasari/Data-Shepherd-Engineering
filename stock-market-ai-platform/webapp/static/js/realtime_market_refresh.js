(() => {
  const LIVE_REFRESH_MS = 2000;
  const EOD_REFRESH_MS = 60000;
  let liveTimer = null;
  let eodTimer = null;
  let completedRows = [];
  let lastLiveQuote = null;
  let regularSessionOpen = null;
  const positivePrice = value => {
    if (value == null || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  };
  const normalizeLiveQuote = quote => {
    if (!quote) return null;
    const price = positivePrice(quote.reference_price);
    const timestamp = quote.timestamp || quote.received_at;
    if (price == null || !timestamp || !Number.isFinite(new Date(timestamp).getTime())) return null;
    return {...quote, reference_price: price, timestamp};
  };
  const money = value => { const n=positivePrice(value); return n!=null?`$${n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`:'—'; };
  const pct = value => Number.isFinite(Number(value))?`${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(2)}%`:'—';
  const fmtNum=(value,digits=2)=>Number.isFinite(Number(value))?Number(value).toFixed(digits):'—';
  const selectedSymbol=()=>(new URLSearchParams(location.search).get('symbol')||document.getElementById('stock-select')?.value||'AAPL').toUpperCase();
  const isLiveView=()=>location.pathname==='/dashboard'&&new URLSearchParams(location.search).get('view')==='live';
  function renderStockHealth(h){regularSessionOpen=typeof h.regular_session_expected_open==='boolean'?h.regular_session_expected_open:null;window.dispatchEvent(new CustomEvent('ds:stock-market-session-state',{detail:{marketOpen:regularSessionOpen}}));const status=document.getElementById('stock-stream-health-status');if(!status)return;status.textContent=h.status||'UNKNOWN';status.style.color=h.status==='LIVE'?'var(--green)':(h.status==='ERROR'||h.status==='STALE'?'var(--red)':'var(--gold)');const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};set('stock-stream-agent',h.launchagent_running?'RUNNING':'NOT RUNNING');set('stock-stream-live-count',String(h.live_symbol_count??0));set('stock-stream-configured-count',String(h.configured_symbol_count??0));set('stock-stream-cache-age',h.cache_age_seconds==null?'—':`${Math.max(0,h.cache_age_seconds).toFixed(1)}s`);set('stock-stream-session',h.regular_session_expected_open?'REGULAR OPEN':'CLOSED');set('stock-stream-health-detail',h.detail||'');}
  async function refreshStockHealth(){if(location.pathname!=='/dashboard')return;try{renderStockHealth(await fetch(`/api/stock-stream-health?t=${Date.now()}`,{cache:'no-store'}).then(r=>r.json()));}catch(error){console.warn('[STOCK HEALTH REFRESH]',error);}}
  function findMarketCard(){return Array.from(document.querySelectorAll('.card')).find(card=>card.querySelector(':scope > .label')?.textContent?.trim()==='MARKET');}
  function technicalSection(){return Array.from(document.querySelectorAll('section.grid.metrics')).find(section=>Array.from(section.querySelectorAll('.metric span')).some(span=>span.textContent.trim()==='RSI 14'));}
  function calcTechnicals(rows,livePrice){const ordered=rows.slice().sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));const latestCompleted=ordered[ordered.length-1]||{};const closes=ordered.map(r=>positivePrice(r.close)).filter(v=>v!=null);const current=positivePrice(livePrice);if(current!=null)closes.push(current);if(!closes.length)return null;const meanTail=n=>{const a=closes.slice(-n);return a.reduce((s,v)=>s+v,0)/a.length;};const returns=[];for(let i=1;i<closes.length;i++)returns.push(closes[i-1]?closes[i]/closes[i-1]-1:0);const vt=returns.slice(-20),vm=vt.length?vt.reduce((a,b)=>a+b,0)/vt.length:0;const vol=vt.length>1?Math.sqrt(vt.reduce((s,v)=>s+Math.pow(v-vm,2),0)/(vt.length-1)):null;const diffs=[];for(let i=1;i<closes.length;i++)diffs.push(closes[i]-closes[i-1]);const d14=diffs.slice(-14),ag=d14.length?d14.reduce((s,v)=>s+Math.max(v,0),0)/d14.length:0,al=d14.length?d14.reduce((s,v)=>s+Math.max(-v,0),0)/d14.length:0;const rsi=d14.length<14?null:al===0?100:100-(100/(1+ag/al));return{rsi_14:rsi,sma_20:meanTail(20),sma_50:meanTail(50),sma_200:Number(latestCompleted.sma_200),volatility_20d:vol,volume_ratio:Number(latestCompleted.volume_ratio)};}
  function renderTechnicals(tech,hasLive){const section=technicalSection();if(!section||!tech)return;const values={'RSI 14':fmtNum(tech.rsi_14,2),'SMA 20':money(tech.sma_20),'SMA 50':money(tech.sma_50),'SMA 200':money(tech.sma_200),'20D VOL':Number.isFinite(Number(tech.volatility_20d))?`${(Number(tech.volatility_20d)*100).toFixed(2)}%`:'—','VOLUME RATIO':Number.isFinite(Number(tech.volume_ratio))?`${Number(tech.volume_ratio).toFixed(2)}x`:'—'};section.querySelectorAll('.metric').forEach(m=>{const l=m.querySelector('span')?.textContent?.trim(),s=m.querySelector('strong');if(s&&l in values)s.textContent=values[l];});let note=section.querySelector('.ds-live-tech-note');if(!note){note=document.createElement('div');note.className='ds-live-tech-note muted';note.style.cssText='grid-column:1/-1;font-size:.75rem;margin-top:-6px';section.appendChild(note);}note.textContent=hasLive?'LIVE / PROVISIONAL · RSI, SMA20, SMA50 and 20D volatility include the current IEX reference price. SMA200 and Volume Ratio remain latest-completed-session values because the live reference feed does not carry enough history/volume to update them honestly.':'COMPLETED SESSION · Waiting for a current IEX quote.';}
  function renderMarket(symbol,quote){
    const card=findMarketCard();
    if(!card)return;
    const validQuote=normalizeLiveQuote(quote);
    const latest=completedRows.slice().sort((a,b)=>new Date(b.timestamp)-new Date(a.timestamp))[0]||null;
    const hero=card.querySelector('.hero-value');
    const muted=card.querySelector('.muted');
    const changeEl=hero?.nextElementSibling;
    if(validQuote){
      const price=validQuote.reference_price;
      const prior=positivePrice(latest?.close);
      const change=prior!=null?price-prior:null;
      const changePct=prior!=null?price/prior-1:null;
      if(hero)hero.textContent=money(price);
      if(muted)muted.textContent=`${validQuote.timestamp} · LIVE IEX`;
      if(changeEl&&Number.isFinite(change)){
        changeEl.textContent=`${change>=0?'+':''}${change.toFixed(2)} (${pct(changePct)}) vs latest completed close`;
        changeEl.className=change>=0?'positive':'negative';
      }
      return;
    }
    if(!latest)return;
    const session=String(latest.session_date||latest.timestamp||'').slice(0,10);
    if(hero)hero.textContent=money(latest.close);
    if(muted)muted.textContent=`${regularSessionOpen===false?'MARKET CLOSED':'LIVE QUOTE UNAVAILABLE'} · LAST COMPLETED SESSION ${session}`;
    if(changeEl){
      changeEl.textContent='Last completed close · not a live quote';
      changeEl.className='muted';
    }
  }
  function renderRecentMarketData(symbol,quote){
    const section=Array.from(document.querySelectorAll('section.card')).find(s=>s.querySelector(':scope > .label')?.textContent?.trim()==='RECENT MARKET DATA');
    if(!section)return;
    const heading=section.querySelector('h2');
    if(heading)heading.textContent=`Live + Latest ${symbol} Trading Sessions`;
    let status=section.querySelector('.ds-recent-live-status');
    if(!status){
      status=document.createElement('div');
      status.className='ds-recent-live-status muted';
      status.style.cssText='margin:-4px 0 12px;font-size:.76rem';
      heading?.insertAdjacentElement('afterend',status);
    }
    const validQuote=normalizeLiveQuote(quote);
    const ordered=completedRows.slice().sort((a,b)=>new Date(b.timestamp)-new Date(a.timestamp));
    const latest=ordered[0]||null;
    if(validQuote){
      status.textContent='Completed sessions refresh automatically · live reference price updates every 2 seconds';
    }else if(latest){
      const session=String(latest.session_date||latest.timestamp||'').slice(0,10);
      status.textContent=`Showing completed sessions · ${regularSessionOpen===false?'market closed':'live quote unavailable'} · last completed close ${money(latest.close)} (${session})`;
    }else{
      status.textContent='Live quote unavailable · no completed session is available';
    }
    const tbody=section.querySelector('tbody');
    if(!tbody)return;
    const rows=[];
    if(validQuote){
      const lp=validQuote.reference_price;
      const prior=positivePrice(latest?.close);
      const livePct=prior!=null?lp/prior-1:null;
      rows.push(`<tr style="background:rgba(57,227,161,.055)"><td><strong class="positive">LIVE NOW</strong><div class="muted" style="font-size:.68rem">${String(validQuote.timestamp).replace('T',' ').slice(0,19)}</div></td><td>—</td><td>—</td><td>—</td><td class="positive"><strong>${money(lp)}</strong></td><td class="${Number(livePct)>=0?'positive':'negative'}">${pct(livePct)}</td><td>—</td></tr>`);
    }
    ordered.slice(0,validQuote?9:10).forEach(r=>rows.push(`<tr><td>${String(r.session_date||r.timestamp).slice(0,10)}</td><td>${money(r.open)}</td><td>${money(r.high)}</td><td>${money(r.low)}</td><td>${money(r.close)}</td><td class="${Number(r.daily_change_pct)>=0?'positive':'negative'}">${pct(r.daily_change_pct)}</td><td>${Number.isFinite(Number(r.volume))?Math.round(Number(r.volume)).toLocaleString():'—'}</td></tr>`));
    tbody.innerHTML=rows.join('');
  }
  function dispatchHistory(symbol,quote){
    const ordered=completedRows.slice().sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
    const validQuote=normalizeLiveQuote(quote);
    const tech=calcTechnicals(ordered,validQuote?.reference_price);
    let livePoint=null;
    if(validQuote){
      const latest=ordered[ordered.length-1];
      const prior=positivePrice(latest?.close);
      livePoint={timestamp:validQuote.timestamp,close:validQuote.reference_price,sma_20:tech?.sma_20,sma_50:tech?.sma_50,sma_200:tech?.sma_200,live:true,daily_change_pct:prior!=null?validQuote.reference_price/prior-1:null};
    }
    window.dispatchEvent(new CustomEvent('ds:live-market-update',{detail:{symbol,completed:ordered,livePoint}}));
    renderTechnicals(tech,Boolean(livePoint));
  }
  async function refreshCompleted(){if(!isLiveView())return;const symbol=selectedSymbol();try{const response=await fetch(`/api/prices/${encodeURIComponent(symbol)}?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);completedRows=await response.json();renderRecentMarketData(symbol,lastLiveQuote);dispatchHistory(symbol,lastLiveQuote);}catch(error){console.warn('[LIVE EOD REFRESH]',error);}}
  async function refreshStocks(){
    if(location.pathname!=='/dashboard')return;
    try{
      const payload=await fetch(`/api/live-prices?t=${Date.now()}`,{cache:'no-store'}).then(r=>r.json());
      const stocks=payload.stocks||{},quotes=stocks.quotes||{},symbol=selectedSymbol();
      const quote=normalizeLiveQuote(quotes[symbol]||null);
      lastLiveQuote=quote;
      document.querySelectorAll('[data-live-price-symbol]').forEach(cell=>{
        const q=normalizeLiveQuote(quotes[cell.dataset.livePriceSymbol]||null);
        if(q){
          cell.textContent=money(q.reference_price);
          cell.title=`LIVE IEX · ${q.timestamp}`;
          cell.style.color='var(--green)';
        }else{
          cell.textContent='—';
          cell.title='Live quote unavailable';
          cell.style.color='var(--muted)';
        }
      });
      if(isLiveView()){
        window.dispatchEvent(new CustomEvent('ds:all-live-stock-quotes',{detail:{quotes,marketOpen:regularSessionOpen,updatedAt:stocks.updated_at||new Date().toISOString()}}));
        renderMarket(symbol,quote);
        renderRecentMarketData(symbol,quote);
        dispatchHistory(symbol,quote);
      }
      if(typeof window.loadV4==='function')window.loadV4();
    }catch(error){console.warn('[LIVE STOCK REFRESH]',error);}
  }
  function renderCrypto(payload){const root=document.getElementById('crypto-live-ticker-grid'),stamp=document.getElementById('crypto-live-ticker-stamp');if(!root)return;const quotes=Object.values(payload.quotes||{}).sort((a,b)=>a.product_id.localeCompare(b.product_id));if(stamp)stamp.textContent=payload.updated_at?`LIVE CACHE · ${payload.updated_at}`:'WAITING FOR LIVE TICKS';root.innerHTML=quotes.length?quotes.map(q=>{const p=Number(q.price_percent_chg_24_h),cls=Number.isFinite(p)?(p>=0?'positive':'negative'):'',ptxt=Number.isFinite(p)?`${p>=0?'+':''}${p.toFixed(2)}%`:'—';return `<div class="metric"><span>${q.product_id}</span><strong>${money(q.price)}</strong><div class="${cls}" style="margin-top:5px;font-weight:800">24H ${ptxt}</div></div>`;}).join(''):'<div class="warning">Waiting for Coinbase real-time ticker data…</div>';}
  async function refreshCrypto(){if(location.pathname!=='/crypto')return;try{const payload=await fetch(`/api/crypto-live?t=${Date.now()}`,{cache:'no-store'}).then(r=>r.json());renderCrypto(payload.crypto||payload);}catch(error){console.warn('[CRYPTO LIVE REFRESH]',error);}}
  function start(){clearInterval(liveTimer);clearInterval(eodTimer);refreshStocks();refreshStockHealth();refreshCrypto();refreshCompleted();liveTimer=setInterval(()=>{if(document.visibilityState==='visible'){refreshStocks();refreshStockHealth();refreshCrypto();}},LIVE_REFRESH_MS);eodTimer=setInterval(()=>{if(document.visibilityState==='visible')refreshCompleted();},EOD_REFRESH_MS);}
  document.addEventListener('visibilitychange',()=>document.visibilityState==='visible'?start():(clearInterval(liveTimer),clearInterval(eodTimer)));document.addEventListener('DOMContentLoaded',()=>requestAnimationFrame(()=>requestAnimationFrame(start)));
})();

// Crypto forward-model monitor uses a separate 60-second cadence. Load it only
// on the Crypto page so the existing 2-second market ticker loop stays lean.
if (location.pathname === '/crypto' && !document.querySelector('script[data-crypto-forward-monitor]')) {
  const script = document.createElement('script');
  script.src = '/static/js/crypto_forward_monitor.js';
  script.defer = true;
  script.dataset.cryptoForwardMonitor = '1';
  document.head.appendChild(script);
}
