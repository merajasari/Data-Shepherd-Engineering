(() => {
  const LIVE_REFRESH_MS = 2000;
  const EOD_REFRESH_MS = 60000;
  let liveTimer = null;
  let eodTimer = null;
  let completedRows = [];
  let lastLiveQuote = null;

  const money = value => {
    const n = Number(value);
    return Number.isFinite(n) ? `$${n.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}` : '—';
  };
  const pct = value => Number.isFinite(Number(value)) ? `${Number(value) >= 0 ? '+' : ''}${(Number(value)*100).toFixed(2)}%` : '—';
  const fmtNum = (value, digits=2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
  const selectedSymbol = () => (new URLSearchParams(location.search).get('symbol') || document.getElementById('stock-select')?.value || 'AAPL').toUpperCase();
  const isLiveView = () => location.pathname === '/dashboard' && new URLSearchParams(location.search).get('view') === 'live';

  function renderStockHealth(h) {
    const status = document.getElementById('stock-stream-health-status');
    if (!status) return;
    status.textContent = h.status || 'UNKNOWN';
    status.style.color = h.status === 'LIVE' ? 'var(--green)' : (h.status === 'ERROR' || h.status === 'STALE' ? 'var(--red)' : 'var(--gold)');
    const set = (id, value) => { const el=document.getElementById(id); if (el) el.textContent=value; };
    set('stock-stream-agent', h.launchagent_running ? 'RUNNING' : 'NOT RUNNING');
    set('stock-stream-live-count', String(h.live_symbol_count ?? 0));
    set('stock-stream-configured-count', String(h.configured_symbol_count ?? 0));
    set('stock-stream-cache-age', h.cache_age_seconds == null ? '—' : `${Math.max(0,h.cache_age_seconds).toFixed(1)}s`);
    set('stock-stream-session', h.regular_session_expected_open ? 'REGULAR OPEN' : 'CLOSED');
    set('stock-stream-health-detail', h.detail || '');
  }

  async function refreshStockHealth() {
    if (location.pathname !== '/dashboard') return;
    try {
      const h = await fetch(`/api/stock-stream-health?t=${Date.now()}`, {cache:'no-store'}).then(r => r.json());
      renderStockHealth(h);
    } catch (error) {
      console.warn('[STOCK HEALTH REFRESH]', error);
    }
  }

  function findMarketCard() {
    return Array.from(document.querySelectorAll('.card')).find(card =>
      card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET'
    );
  }

  function technicalSection() {
    return Array.from(document.querySelectorAll('section.grid.metrics')).find(section =>
      Array.from(section.querySelectorAll('.metric span')).some(span => span.textContent.trim() === 'RSI 14')
    );
  }

  function calcTechnicals(rows, livePrice) {
    const ordered = rows.slice().sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
    const closes = ordered.map(r => Number(r.close)).filter(Number.isFinite);
    if (Number.isFinite(Number(livePrice))) closes.push(Number(livePrice));
    if (!closes.length) return null;
    const meanTail = n => {
      const a=closes.slice(-n); return a.reduce((s,v)=>s+v,0)/a.length;
    };
    const returns=[];
    for(let i=1;i<closes.length;i++) returns.push(closes[i-1] ? closes[i]/closes[i-1]-1 : 0);
    const volTail=returns.slice(-20);
    const vol = volTail.length > 1 ? Math.sqrt(volTail.reduce((s,v)=>s+Math.pow(v-(volTail.reduce((a,b)=>a+b,0)/volTail.length),2),0)/(volTail.length-1)) : null;
    const diffs=[];
    for(let i=1;i<closes.length;i++) diffs.push(closes[i]-closes[i-1]);
    const d14=diffs.slice(-14);
    const avgGain=d14.length ? d14.reduce((s,v)=>s+Math.max(v,0),0)/d14.length : 0;
    const avgLoss=d14.length ? d14.reduce((s,v)=>s+Math.max(-v,0),0)/d14.length : 0;
    const rsi = d14.length < 14 ? null : avgLoss === 0 ? 100 : 100-(100/(1+avgGain/avgLoss));
    const latestCompleted=ordered[ordered.length-1] || {};
    return {
      rsi_14:rsi,
      sma_20:meanTail(20),
      sma_50:meanTail(50),
      sma_200:meanTail(200),
      volatility_20d:vol,
      volume_ratio:Number(latestCompleted.volume_ratio),
    };
  }

  function renderTechnicals(tech, hasLive) {
    const section=technicalSection();
    if (!section || !tech) return;
    const values={
      'RSI 14':fmtNum(tech.rsi_14,2),
      'SMA 20':money(tech.sma_20),
      'SMA 50':money(tech.sma_50),
      'SMA 200':money(tech.sma_200),
      '20D VOL':Number.isFinite(Number(tech.volatility_20d))?`${(Number(tech.volatility_20d)*100).toFixed(2)}%`:'—',
      'VOLUME RATIO':Number.isFinite(Number(tech.volume_ratio))?`${Number(tech.volume_ratio).toFixed(2)}x`:'—'
    };
    section.querySelectorAll('.metric').forEach(metric=>{
      const label=metric.querySelector('span')?.textContent?.trim();
      const strong=metric.querySelector('strong');
      if (strong && label in values) strong.textContent=values[label];
    });
    let note=section.querySelector('.ds-live-tech-note');
    if(!note){note=document.createElement('div');note.className='ds-live-tech-note muted';note.style.cssText='grid-column:1/-1;font-size:.75rem;margin-top:-6px';section.appendChild(note);}
    note.textContent=hasLive?'LIVE / PROVISIONAL · RSI, SMAs and volatility include the current IEX reference price. Volume Ratio uses the latest completed session.':'COMPLETED SESSION · Waiting for a current IEX quote.';
  }

  function renderMarket(symbol, quote) {
    const card=findMarketCard();
    if(!card || !quote || quote.reference_price==null) return;
    const price=Number(quote.reference_price);
    const latest=completedRows.slice().sort((a,b)=>new Date(b.timestamp)-new Date(a.timestamp))[0];
    const prior=latest ? Number(latest.close) : null;
    const change=Number.isFinite(prior)&&prior!==0 ? price-prior : null;
    const changePct=Number.isFinite(prior)&&prior!==0 ? price/prior-1 : null;
    const hero=card.querySelector('.hero-value');
    if(hero) hero.textContent=money(price);
    const muted=card.querySelector('.muted');
    if(muted) muted.textContent=`${quote.timestamp || quote.received_at || 'LIVE'} · LIVE IEX`;
    const changeEl=hero?.nextElementSibling;
    if(changeEl && Number.isFinite(change)){
      changeEl.textContent=`${change>=0?'+':''}${change.toFixed(2)} (${pct(changePct)}) vs latest completed close`;
      changeEl.className=change>=0?'positive':'negative';
    }
  }

  function renderRecentMarketData(symbol, quote) {
    const section=Array.from(document.querySelectorAll('section.card')).find(s=>s.querySelector(':scope > .label')?.textContent?.trim()==='RECENT MARKET DATA');
    if(!section) return;
    const heading=section.querySelector('h2');
    if(heading) heading.textContent=`Live + Latest ${symbol} Trading Sessions`;
    let status=section.querySelector('.ds-recent-live-status');
    if(!status){status=document.createElement('div');status.className='ds-recent-live-status muted';status.style.cssText='margin:-4px 0 12px;font-size:.76rem';heading?.insertAdjacentElement('afterend',status);}
    status.textContent=`Completed sessions refresh automatically · live reference price ${quote ? 'updates every 2 seconds' : 'currently unavailable'}`;
    const tbody=section.querySelector('tbody');
    if(!tbody) return;
    const ordered=completedRows.slice().sort((a,b)=>new Date(b.timestamp)-new Date(a.timestamp));
    const rows=[];
    if(quote && quote.reference_price!=null){
      const livePrice=Number(quote.reference_price), prior=ordered[0]?Number(ordered[0].close):null;
      const livePct=Number.isFinite(prior)&&prior!==0?livePrice/prior-1:null;
      rows.push(`<tr style="background:rgba(57,227,161,.055)"><td><strong class="positive">LIVE NOW</strong><div class="muted" style="font-size:.68rem">${String(quote.timestamp||quote.received_at||'').replace('T',' ').slice(0,19)}</div></td><td>—</td><td>—</td><td>—</td><td class="positive"><strong>${money(livePrice)}</strong></td><td class="${Number(livePct)>=0?'positive':'negative'}">${pct(livePct)}</td><td>—</td></tr>`);
    }
    ordered.slice(0, quote?9:10).forEach(r=>{
      rows.push(`<tr><td>${String(r.session_date||r.timestamp).slice(0,10)}</td><td>${money(r.open)}</td><td>${money(r.high)}</td><td>${money(r.low)}</td><td>${money(r.close)}</td><td class="${Number(r.daily_change_pct)>=0?'positive':'negative'}">${pct(r.daily_change_pct)}</td><td>${Number.isFinite(Number(r.volume))?Math.round(Number(r.volume)).toLocaleString():'—'}</td></tr>`);
    });
    tbody.innerHTML=rows.join('');
  }

  function dispatchHistory(symbol, quote) {
    const ordered=completedRows.slice().sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
    const tech=calcTechnicals(ordered, quote?.reference_price);
    let livePoint=null;
    if(quote && quote.reference_price!=null){
      const latest=ordered[ordered.length-1];
      const prior=latest?Number(latest.close):null;
      livePoint={
        timestamp:quote.timestamp||quote.received_at||new Date().toISOString(),
        close:Number(quote.reference_price),
        sma_20:tech?.sma_20,
        sma_50:tech?.sma_50,
        sma_200:tech?.sma_200,
        live:true,
        daily_change_pct:Number.isFinite(prior)&&prior!==0?Number(quote.reference_price)/prior-1:null
      };
    }
    window.dispatchEvent(new CustomEvent('ds:live-market-update',{detail:{symbol,completed:ordered,livePoint}}));
    renderTechnicals(tech,Boolean(livePoint));
  }

  async function refreshCompleted() {
    if(!isLiveView()) return;
    const symbol=selectedSymbol();
    try{
      const response=await fetch(`/api/prices/${encodeURIComponent(symbol)}?t=${Date.now()}`,{cache:'no-store'});
      if(!response.ok) throw new Error(`HTTP ${response.status}`);
      completedRows=await response.json();
      renderRecentMarketData(symbol,lastLiveQuote);
      dispatchHistory(symbol,lastLiveQuote);
    }catch(error){console.warn('[LIVE EOD REFRESH]',error);}
  }

  async function refreshStocks() {
    if(location.pathname!=='/dashboard') return;
    try{
      const payload=await fetch(`/api/live-prices?t=${Date.now()}`,{cache:'no-store'}).then(r=>r.json());
      const stocks=payload.stocks||{};
      const quotes=stocks.quotes||{};
      const symbol=selectedSymbol();
      const quote=quotes[symbol]||null;
      lastLiveQuote=quote;
      document.querySelectorAll('[data-live-price-symbol]').forEach(cell=>{
        const q=quotes[cell.dataset.livePriceSymbol];
        if(q&&q.reference_price!=null){cell.textContent=money(q.reference_price);cell.title=`LIVE IEX · ${q.received_at||''}`;cell.style.color='var(--green)';}
      });
      if(isLiveView()){
        renderMarket(symbol,quote);
        renderRecentMarketData(symbol,quote);
        dispatchHistory(symbol,quote);
      }
      if(typeof window.loadV4==='function') window.loadV4();
    }catch(error){console.warn('[LIVE STOCK REFRESH]',error);}
  }

  function renderCrypto(payload) {
    const root=document.getElementById('crypto-live-ticker-grid');
    const stamp=document.getElementById('crypto-live-ticker-stamp');
    if(!root)return;
    const quotes=Object.values(payload.quotes||{}).sort((a,b)=>a.product_id.localeCompare(b.product_id));
    if(stamp)stamp.textContent=payload.updated_at?`LIVE CACHE · ${payload.updated_at}`:'WAITING FOR LIVE TICKS';
    root.innerHTML=quotes.length?quotes.map(q=>{const p=Number(q.price_percent_chg_24_h);const cls=Number.isFinite(p)?(p>=0?'positive':'negative'):'';const ptxt=Number.isFinite(p)?`${p>=0?'+':''}${p.toFixed(2)}%`:'—';return `<div class="metric"><span>${q.product_id}</span><strong>${money(q.price)}</strong><div class="${cls}" style="margin-top:5px;font-weight:800">24H ${ptxt}</div></div>`;}).join(''):'<div class="warning">Waiting for Coinbase real-time ticker data…</div>';
  }

  async function refreshCrypto(){if(location.pathname!=='/crypto')return;try{const payload=await fetch(`/api/crypto-live?t=${Date.now()}`,{cache:'no-store'}).then(r=>r.json());renderCrypto(payload.crypto||payload);}catch(error){console.warn('[CRYPTO LIVE REFRESH]',error);}}

  function start(){
    clearInterval(liveTimer);clearInterval(eodTimer);
    refreshStocks();refreshStockHealth();refreshCrypto();refreshCompleted();
    liveTimer=setInterval(()=>{if(document.visibilityState==='visible'){refreshStocks();refreshStockHealth();refreshCrypto();}},LIVE_REFRESH_MS);
    eodTimer=setInterval(()=>{if(document.visibilityState==='visible')refreshCompleted();},EOD_REFRESH_MS);
  }
  document.addEventListener('visibilitychange',()=>document.visibilityState==='visible'?start():(clearInterval(liveTimer),clearInterval(eodTimer)));
  document.addEventListener('DOMContentLoaded',()=>requestAnimationFrame(()=>requestAnimationFrame(start)));
})();
