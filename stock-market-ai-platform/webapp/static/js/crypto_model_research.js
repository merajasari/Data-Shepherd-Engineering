(() => {
  const colors = ['#36d8ff','#39e3a1','#efc56b','#ff6680','#9b65ff','#4d8cff'];
  const money = n => Number.isFinite(+n) ? '$' + (+n).toLocaleString(undefined,{maximumFractionDigits:0}) : '—';
  const pct = n => Number.isFinite(+n) ? `${+n >= 0 ? '+' : ''}${(+n).toFixed(2)}%` : '—';
  const val = n => Number.isFinite(+n) ? (+n).toFixed(2) : '—';
  const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let payload, range='10Y', enabled=new Set();

  function setupModelTabs(){
    const tabs=[...document.querySelectorAll('[data-crypto-tab]')],panels=[...document.querySelectorAll('[data-crypto-panel]')];
    const show=id=>{tabs.forEach(t=>{const on=t.dataset.cryptoTab===id;t.classList.toggle('active',on);t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1});panels.forEach(p=>p.hidden=p.dataset.cryptoPanel!==id);history.replaceState(null,'',id==='overview'?location.pathname:`#${id}`);if(id!=='overview')renderModelChart(id)};
    tabs.forEach((t,i)=>{t.onclick=()=>show(t.dataset.cryptoTab);t.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();show(tabs[n].dataset.cryptoTab)}});
    const initial=location.hash.slice(1);show(tabs.some(t=>t.dataset.cryptoTab===initial)?initial:'overview');
  }
  function renderModelChart(id){
    const map={v1:'CRYPTO_V1',v2:'CRYPTO_V2',v3:'CRYPTO_V3',v4:'CRYPTO_V4'},model=map[id];if(!model||!payload)return;
    const host=document.querySelector(`[data-model-chart="${model}"]`);if(!host||host.dataset.ready)return;host.dataset.ready='1';const s=(payload.series||[]).find(x=>x.model_id===model);if(!s){host.innerHTML='<div class="notice">A scientifically admissible reconstruction is not available in the current generated artifact.</div>';return}host.innerHTML=`<div class="grid2"><div><div class="eyebrow">RECONSTRUCTED ENDING VALUE</div><h2>${money(s.ending_equity)}</h2><p class="muted">Eligible ${esc((s.start_timestamp||'').slice(0,10))} → ${esc((s.end_timestamp||'').slice(0,10))}</p></div><div><div class="eyebrow">RETURN / MAX DRAWDOWN</div><h2>${pct(s.total_return_pct)} / ${pct(s.max_drawdown_pct)}</h2><p class="muted">Normalized hypothetical $100,000 basis</p></div></div>`}

  function cutoff(latest){const y={10:10,5:5,3:3,1:1}[parseInt(range)];return y?latest-y*365.25*864e5:-Infinity}
  function selected(){return (payload?.series||[]).filter(s=>enabled.has(s.model_id))}
  function points(series, drawdown=false){
    const raw=(series.history||[]).map(p=>({t:Date.parse(p.timestamp),v:+p.equity})).filter(p=>Number.isFinite(p.t)&&Number.isFinite(p.v));
    const latest=Math.max(...(payload.series||[]).flatMap(s=>(s.history||[]).map(p=>Date.parse(p.timestamp)).filter(Number.isFinite)));
    if(!drawdown)return raw.filter(p=>p.t>=cutoff(latest));
    let peak=0;return raw.map(p=>{peak=Math.max(peak,p.v);return {t:p.t,v:(p.v/peak-1)*100}}).filter(p=>p.t>=cutoff(latest));
  }
  function chart(id, drawdown=false){
    const svg=document.getElementById(id);if(!svg)return;svg.innerHTML='';
    const series=selected().map((s,i)=>({s,c:colors[(payload.series||[]).indexOf(s)%colors.length],p:points(s,drawdown)})).filter(x=>x.p.length>1);
    if(!series.length){svg.innerHTML='<text x="50%" y="50%" fill="#91a6c2" text-anchor="middle">No eligible series in this range</text>';return}
    const W=1100,H=drawdown?260:430,pad={l:82,r:30,t:28,b:46},all=series.flatMap(x=>x.p),minT=Math.min(...all.map(x=>x.t)),maxT=Math.max(...all.map(x=>x.t));let minV=Math.min(...all.map(x=>x.v)),maxV=Math.max(...all.map(x=>x.v));if(!drawdown){const span=Math.max(1,maxV-minV);minV=Math.max(0,minV-span*.08);maxV+=span*.12}else maxV=0;
    const x=t=>pad.l+(W-pad.l-pad.r)*(t-minT)/Math.max(1,maxT-minT),y=v=>pad.t+(H-pad.t-pad.b)*(1-(v-minV)/Math.max(1e-9,maxV-minV));
    const el=(tag,a)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(a).forEach(([k,v])=>n.setAttribute(k,v));svg.appendChild(n);return n};
    for(let i=0;i<5;i++){const v=minV+(maxV-minV)*i/4;el('line',{x1:pad.l,x2:W-pad.r,y1:y(v),y2:y(v),stroke:'rgba(145,166,194,.16)'});const t=el('text',{x:pad.l-10,y:y(v)+4,fill:'#91a6c2','text-anchor':'end','font-size':12});t.textContent=drawdown?`${v.toFixed(0)}%`:money(v)}
    series.forEach(({s,c,p})=>{el('polyline',{points:p.map(q=>`${x(q.t)},${y(q.v)}`).join(' '),fill:'none',stroke:c,'stroke-width':3,'data-model':s.model_id});const last=p[p.length-1],t=el('text',{x:Math.min(W-pad.r-2,x(last.t)+7),y:y(last.v)-6,fill:c,'font-size':12,'font-weight':800,'text-anchor':x(last.t)>W-pad.r-120?'end':'start'});t.textContent=s.label});
  }
  function render(){
    document.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('active',b.dataset.range===range));
    const legend=document.getElementById('cmr-legend');legend.innerHTML=(payload.series||[]).map((s,i)=>`<button class="cmr-chip ${enabled.has(s.model_id)?'active':''}" data-id="${esc(s.model_id)}"><i style="background:${colors[i%colors.length]}"></i>${esc(s.label)}</button>`).join('');
    legend.querySelectorAll('button').forEach(b=>b.onclick=()=>{enabled.has(b.dataset.id)?enabled.delete(b.dataset.id):enabled.add(b.dataset.id);render()});
    document.getElementById('cmr-table-body').innerHTML=selected().map(s=>`<tr><td><strong>${esc(s.label)}</strong><small>${esc(s.status)}</small></td><td>${esc((s.start_timestamp||'').slice(0,10))}</td><td>${money(s.ending_equity)}</td><td class="${+s.total_return_pct>=0?'up':'down'}">${pct(s.total_return_pct)}</td><td>${pct(s.cagr_pct)}</td><td>${pct(s.max_drawdown_pct)}</td><td>${val(s.sharpe)}</td></tr>`).join('');
    chart('cmr-equity');chart('cmr-drawdown',true);
  }
  async function init(){
    const status=document.getElementById('cmr-status');
    try{const r=await fetch('/api/crypto-model-comparison',{credentials:'same-origin'});payload=await r.json();if(!r.ok||!payload.available)throw new Error(payload.error||`HTTP ${r.status}`);enabled=new Set(payload.series.map(s=>s.model_id));status.textContent=`${payload.series.length} ELIGIBLE SERIES · GENERATED ${(payload.generated_at_utc||'').slice(0,10)}`;document.getElementById('cmr-policy').textContent=payload.common_clock_policy;const unavailable=document.getElementById('cmr-unavailable');if(payload.unavailable_series?.length){unavailable.hidden=false;unavailable.innerHTML='<strong>Not charted:</strong> '+payload.unavailable_series.map(s=>`${esc(s.label)} — ${esc(s.reason)}`).join(' · ')}render();renderModelChart(document.querySelector('[data-crypto-tab].active')?.dataset.cryptoTab)}catch(e){status.textContent='COMPARISON NOT BUILT';document.getElementById('cmr-error').hidden=false;document.getElementById('cmr-error').textContent=`${e.message} Run: python -m ml.build_crypto_model_comparison`}}
  document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{range=b.dataset.range;render()});setupModelTabs();init();
})();
