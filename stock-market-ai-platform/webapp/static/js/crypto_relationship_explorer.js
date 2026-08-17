(() => {
  const assetNames = {
    'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'
  };
  const defaultSymbols = ['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD','DOGE-USD','LINK-USD','AVAX-USD'];
  let payload = null;
  let windowDays = 90;
  let selected = new Set(defaultSymbols);

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short = s => s.replace('-USD','');
  const pct = v => Number.isFinite(v) ? `${v >= 0 ? '+' : ''}${(v*100).toFixed(2)}%` : '—';

  function seriesRows(symbol) {
    const src = payload?.series?.[symbol];
    if (!src?.available || !Array.isArray(src.points)) return [];
    const rows = src.points.map(p => ({
      day: String(p.t || '').slice(0,10),
      t: Date.parse(p.t),
      close: Number(p.close)
    })).filter(r => r.day && Number.isFinite(r.t) && Number.isFinite(r.close) && r.close > 0);
    if (!rows.length) return [];
    rows.sort((a,b)=>a.t-b.t);
    const maxT = rows[rows.length-1].t;
    const minT = maxT - windowDays*86400000;
    return rows.filter(r => r.t >= minT);
  }

  function returnsMap(symbol) {
    const rows = seriesRows(symbol);
    const out = new Map();
    for (let i=1;i<rows.length;i++) {
      const prev = rows[i-1].close;
      const cur = rows[i].close;
      if (prev > 0 && cur > 0) out.set(rows[i].day, cur/prev - 1);
    }
    return out;
  }

  function pearson(aMap,bMap) {
    const xs=[],ys=[];
    aMap.forEach((v,k)=>{ if (bMap.has(k) && Number.isFinite(v) && Number.isFinite(bMap.get(k))) { xs.push(v); ys.push(bMap.get(k)); } });
    const n=xs.length;
    if(n<5) return {r:null,n};
    const mx=xs.reduce((a,b)=>a+b,0)/n, my=ys.reduce((a,b)=>a+b,0)/n;
    let num=0,dx=0,dy=0;
    for(let i=0;i<n;i++){ const x=xs[i]-mx,y=ys[i]-my; num+=x*y; dx+=x*x; dy+=y*y; }
    const den=Math.sqrt(dx*dy);
    return {r:den?num/den:null,n};
  }

  function periodReturn(symbol) {
    const rows=seriesRows(symbol);
    if(rows.length<2) return null;
    return rows[rows.length-1].close/rows[0].close-1;
  }

  function cellStyle(r) {
    if(!Number.isFinite(r)) return 'background:rgba(145,166,194,.08);color:#91a6c2';
    const mag=Math.min(1,Math.abs(r));
    if(r>=0) return `background:rgba(57,227,161,${0.12+mag*0.70});color:${mag>.48?'#04150f':'#dffcf1'};box-shadow:inset 0 0 0 1px rgba(57,227,161,${0.10+mag*0.24})`;
    return `background:rgba(255,102,128,${0.12+mag*0.70});color:${mag>.48?'#1b0509':'#ffe9ed'};box-shadow:inset 0 0 0 1px rgba(255,102,128,${0.10+mag*0.24})`;
  }

  function activeSymbols() {
    return [...selected].filter(s=>payload?.series?.[s]?.available).sort((a,b)=>defaultSymbols.indexOf(a)-defaultSymbols.indexOf(b) || a.localeCompare(b));
  }

  function renderSummary() {
    const syms=activeSymbols();
    const set=(id,v)=>{const n=document.getElementById(id);if(n)n.textContent=v;};
    set('relationship-selected-count',`${syms.length} / ${Object.keys(payload?.series||{}).length}`);
    set('relationship-window',`${windowDays} DAYS`);
    const pairs=syms.length*(syms.length-1)/2;
    set('relationship-pair-count',pairs.toLocaleString());
    const btc=periodReturn('BTC-USD');
    set('relationship-btc-return',pct(btc));
  }

  function renderChips() {
    const root=document.getElementById('relationship-chips'); if(!root||!payload) return;
    const symbols=Object.keys(payload.series||{}).filter(s=>payload.series[s]?.available).sort();
    root.innerHTML=symbols.map(s=>`<button type="button" class="relationship-chip${selected.has(s)?' active':''}" data-symbol="${esc(s)}" aria-pressed="${selected.has(s)?'true':'false'}"><strong>${esc(short(s))}</strong><span>${esc(assetNames[s]||'')}</span></button>`).join('');
    root.querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>{
      const s=btn.dataset.symbol;
      if(selected.has(s)) selected.delete(s); else selected.add(s);
      renderAll();
    }));
  }


  function renderPairHighlights() {
    const syms=activeSymbols();
    const mostPair=document.getElementById('relationship-most-pair');
    const mostValue=document.getElementById('relationship-most-value');
    const leastPair=document.getElementById('relationship-least-pair');
    const leastValue=document.getElementById('relationship-least-value');
    if(!mostPair||!mostValue||!leastPair||!leastValue) return;
    if(syms.length<2){
      mostPair.textContent='—'; mostValue.textContent='Select at least two assets';
      leastPair.textContent='—'; leastValue.textContent='Select at least two assets';
      return;
    }
    const maps=Object.fromEntries(syms.map(s=>[s,returnsMap(s)]));
    const pairs=[];
    for(let i=0;i<syms.length;i++) for(let j=i+1;j<syms.length;j++) {
      const result=pearson(maps[syms[i]],maps[syms[j]]);
      if(Number.isFinite(result.r)) pairs.push({a:syms[i],b:syms[j],r:result.r,n:result.n});
    }
    if(!pairs.length){
      mostPair.textContent='—'; mostValue.textContent='Not enough overlapping observations';
      leastPair.textContent='—'; leastValue.textContent='Not enough overlapping observations';
      return;
    }
    pairs.sort((a,b)=>b.r-a.r);
    const most=pairs[0], least=pairs[pairs.length-1];
    mostPair.textContent=`${short(most.a)} + ${short(most.b)}`;
    mostValue.textContent=`${most.r.toFixed(2)} correlation · ${most.n} overlapping daily returns`;
    leastPair.textContent=`${short(least.a)} + ${short(least.b)}`;
    leastValue.textContent=`${least.r.toFixed(2)} correlation · ${least.n} overlapping daily returns`;
  }

  function renderHeatmap() {
    const root=document.getElementById('relationship-heatmap'); if(!root||!payload) return;
    const syms=activeSymbols();
    if(!syms.length){root.innerHTML='<div class="relationship-empty">Select at least one crypto to build the heatmap.</div>';return;}
    const maps=Object.fromEntries(syms.map(s=>[s,returnsMap(s)]));
    let html='<table><thead><tr><th></th>'+syms.map(s=>`<th title="${esc(assetNames[s]||'')}">${esc(short(s))}</th>`).join('')+'</tr></thead><tbody>';
    syms.forEach(a=>{
      html+=`<tr><th title="${esc(assetNames[a]||'')}">${esc(short(a))}</th>`;
      syms.forEach(b=>{
        const result=a===b?{r:1,n:maps[a].size}:pearson(maps[a],maps[b]);
        const label=Number.isFinite(result.r)?result.r.toFixed(2):'—';
        html+=`<td style="${cellStyle(result.r)}" title="${esc(short(a))} vs ${esc(short(b))} · correlation ${label} · ${result.n} overlapping daily returns"><strong>${label}</strong></td>`;
      });
      html+='</tr>';
    });
    html+='</tbody></table>';
    root.innerHTML=html;
  }

  function renderRelative() {
    const root=document.getElementById('relationship-relative'); if(!root||!payload) return;
    const syms=activeSymbols();
    const btc=periodReturn('BTC-USD');
    const rows=syms.map(s=>({symbol:s,ret:periodReturn(s)})).filter(r=>Number.isFinite(r.ret)).map(r=>({...r,excess:Number.isFinite(btc)?r.ret-btc:null})).sort((a,b)=>(b.excess??-Infinity)-(a.excess??-Infinity));
    if(!rows.length){root.innerHTML='<div class="relationship-empty">Select assets to see BTC-relative performance.</div>';return;}
    const maxAbs=Math.max(.000001,...rows.map(r=>Math.abs(r.excess||0)));
    root.innerHTML=rows.map((r,i)=>{
      const w=Math.max(2,Math.abs(r.excess||0)/maxAbs*48);
      const right=(r.excess||0)>=0;
      return `<div class="relationship-bar-row"><div class="relationship-rank">${i+1}</div><div class="relationship-symbol"><strong>${esc(short(r.symbol))}</strong><span>${esc(assetNames[r.symbol]||'')}</span></div><div class="relationship-bar-track"><i class="${right?'up':'down'}" style="width:${w}%;${right?'left:50%':'right:50%'}"></i><b></b></div><div class="relationship-values"><strong class="${right?'positive':'negative'}">${pct(r.excess)}</strong><small>asset ${pct(r.ret)}</small></div></div>`;
    }).join('');
  }

  function renderAll(){renderSummary();renderChips();renderPairHighlights();renderHeatmap();renderRelative();}

  function bind() {
    document.querySelectorAll('[data-relationship-window]').forEach(btn=>btn.addEventListener('click',()=>{
      windowDays=Number(btn.dataset.relationshipWindow)||90;
      document.querySelectorAll('[data-relationship-window]').forEach(b=>b.classList.toggle('active',b===btn));
      renderAll();
    }));
    document.getElementById('relationship-select-default')?.addEventListener('click',()=>{selected=new Set(defaultSymbols);renderAll();});
    document.getElementById('relationship-select-all')?.addEventListener('click',()=>{selected=new Set(Object.keys(payload?.series||{}).filter(s=>payload.series[s]?.available));renderAll();});
    document.getElementById('relationship-clear')?.addEventListener('click',()=>{selected.clear();renderAll();});
    const input=document.getElementById('relationship-search');
    input?.addEventListener('input',()=>{
      const q=input.value.trim().toLowerCase();
      document.querySelectorAll('#relationship-chips .relationship-chip').forEach(btn=>{
        const s=btn.dataset.symbol, text=`${s} ${assetNames[s]||''}`.toLowerCase();
        btn.style.display=!q||text.includes(q)?'':'none';
      });
    });
  }

  async function init() {
    const root=document.getElementById('crypto-relationship-explorer'); if(!root) return;
    try {
      payload=await window.DataShepherdCryptoHistory.load('90D');
      const available=Object.keys(payload?.series||{}).filter(s=>payload.series[s]?.available);
      selected=new Set(defaultSymbols.filter(s=>available.includes(s)));
      bind(); renderAll();
      const status=document.getElementById('relationship-load-status'); if(status) status.textContent='RELATIONSHIPS READY';
    } catch(err) {
      console.error('crypto relationship explorer',err);
      const status=document.getElementById('relationship-load-status'); if(status) status.textContent='RELATIONSHIP DATA ERROR';
    }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
