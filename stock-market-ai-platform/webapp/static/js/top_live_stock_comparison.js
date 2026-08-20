(() => {
  if (location.pathname !== '/dashboard' || new URLSearchParams(location.search).get('view') !== 'live') return;

  const marketCard = Array.from(document.querySelectorAll('.card')).find(card =>
    card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET'
  );
  if (!marketCard || document.getElementById('ds-top-live-comparison')) return;

  const parent = marketCard.parentElement;
  if (parent) parent.classList.add('ds-market-comparison-grid');

  const card = document.createElement('div');
  card.id = 'ds-top-live-comparison';
  card.className = 'card ds-live-stock-keep';
  card.innerHTML = `
    <div class="ds-top-live-head">
      <div><div class="label">TOP LIVE STOCK COMPARISON</div><h2>Top 10 Performing Stocks</h2><div class="muted">Live session performance, normalized to 0% at first observation.</div></div>
      <div id="ds-top-live-stamp" class="mode">WAITING FOR LIVE DATA</div>
    </div>
    <div id="ds-top-live-legend" class="ds-top-live-legend"></div>
    <div class="ds-top-live-chart-wrap"><svg id="ds-top-live-chart" viewBox="0 0 1000 330" preserveAspectRatio="none" aria-label="Top 10 live stock performance comparison over time"></svg></div>
    <div class="muted ds-top-live-note">Ranked by performance since each symbol's first live observation in this browser session. The top 10 can change as prices update.</div>`;
  marketCard.insertAdjacentElement('afterend', card);

  const style = document.createElement('style');
  style.textContent = `
    body.ds-live-stock-view .ds-market-comparison-grid{display:grid!important;grid-template-columns:minmax(300px,.72fr) minmax(520px,1.28fr)!important;gap:22px;align-items:stretch}
    #ds-top-live-comparison{min-width:0;overflow:hidden}
    .ds-top-live-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
    .ds-top-live-head h2{margin-bottom:5px}
    .ds-top-live-chart-wrap{height:330px;margin-top:12px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.5);overflow:hidden}
    #ds-top-live-chart{width:100%;height:100%;display:block}
    .ds-top-live-legend{display:flex;gap:7px 12px;flex-wrap:wrap;margin-top:12px;font-size:.72rem;color:var(--muted)}
    .ds-top-live-legend span{display:inline-flex;align-items:center;gap:5px;font-weight:800}
    .ds-top-live-swatch{width:9px;height:9px;border-radius:50%;display:inline-block}
    .ds-top-live-note{font-size:.72rem;margin-top:8px}
    @media(max-width:1050px){body.ds-live-stock-view .ds-market-comparison-grid{grid-template-columns:1fr!important}.ds-top-live-chart-wrap{height:300px}}
  `;
  document.head.appendChild(style);

  const svg = document.getElementById('ds-top-live-chart');
  const legend = document.getElementById('ds-top-live-legend');
  const stamp = document.getElementById('ds-top-live-stamp');
  const history = new Map();
  const MAX_POINTS = 240;
  const colors = ['#36d8ff','#39e3a1','#efc56b','#9b65ff','#ff6680','#58a6ff','#f778ba','#a5d6ff','#d2a8ff','#7ee787'];

  const ns = (tag, attrs={}, parent=svg) => {
    const el=document.createElementNS('http://www.w3.org/2000/svg',tag);
    Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));
    parent.appendChild(el); return el;
  };

  function ingest(quotes) {
    const now = Date.now();
    Object.entries(quotes || {}).forEach(([symbol,q]) => {
      const price=Number(q?.reference_price);
      if(!Number.isFinite(price) || price<=0) return;
      let series=history.get(symbol);
      if(!series){series={base:price,points:[]};history.set(symbol,series);}
      const perf=price/series.base-1;
      series.points.push({t:now,p:perf,price});
      if(series.points.length>MAX_POINTS) series.points.splice(0,series.points.length-MAX_POINTS);
    });
  }

  function render() {
    const ranked=[...history.entries()]
      .filter(([,s])=>s.points.length)
      .map(([symbol,s])=>({symbol,series:s,perf:s.points[s.points.length-1].p}))
      .sort((a,b)=>b.perf-a.perf).slice(0,10);
    svg.innerHTML='';
    if(!ranked.length){const t=ns('text',{x:500,y:165,'text-anchor':'middle',fill:'#91a6c2','font-size':'15'});t.textContent='Waiting for live stock observations…';return;}

    const W=1000,H=330,p={l:64,r:24,t:22,b:38};
    const all=ranked.flatMap(r=>r.series.points.map(x=>x.p));
    let min=Math.min(0,...all),max=Math.max(0,...all);
    const span=Math.max(max-min,.002); min-=span*.12; max+=span*.12;
    const starts=ranked.map(r=>r.series.points[0].t), ends=ranked.map(r=>r.series.points[r.series.points.length-1].t);
    const t0=Math.min(...starts),t1=Math.max(...ends); const td=Math.max(1,t1-t0);
    const x=t=>p.l+(W-p.l-p.r)*((t-t0)/td);
    const y=v=>p.t+(H-p.t-p.b)*(1-(v-min)/(max-min));

    for(let i=0;i<5;i++){
      const v=min+(max-min)*i/4, yy=y(v);
      ns('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.14)','stroke-width':'1'});
      const label=ns('text',{x:p.l-8,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':'11'});label.textContent=`${v>=0?'+':''}${(v*100).toFixed(2)}%`;
    }
    const zero=y(0);ns('line',{x1:p.l,y1:zero,x2:W-p.r,y2:zero,stroke:'rgba(242,246,255,.38)','stroke-width':'1.2','stroke-dasharray':'4 4'});

    ranked.forEach((r,i)=>{
      const pts=r.series.points.map(pt=>`${x(pt.t)},${y(pt.p)}`).join(' ');
      ns('polyline',{points:pts,fill:'none',stroke:colors[i], 'stroke-width':i<3?'3':'2','stroke-linejoin':'round','stroke-linecap':'round',opacity:'.94'});
      const last=r.series.points[r.series.points.length-1];
      ns('circle',{cx:x(last.t),cy:y(last.p),r:i<3?'4.5':'3.5',fill:colors[i],stroke:'#07101f','stroke-width':'1.5'});
    });

    const timeLabel=ms=>new Date(ms).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
    [t0,t0+td/2,t1].forEach((t,i)=>{const lab=ns('text',{x:x(t),y:H-13,'text-anchor':i===0?'start':i===2?'end':'middle',fill:'#91a6c2','font-size':'11'});lab.textContent=timeLabel(t);});
    legend.innerHTML=ranked.map((r,i)=>`<span title="Latest ${r.symbol} performance"><i class="ds-top-live-swatch" style="background:${colors[i]}"></i>${i+1}. ${r.symbol} <b class="${r.perf>=0?'positive':'negative'}">${r.perf>=0?'+':''}${(r.perf*100).toFixed(2)}%</b></span>`).join('');
    stamp.textContent=`LIVE · ${new Date().toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit',second:'2-digit'})}`;
  }

  window.addEventListener('ds:all-live-stock-quotes', event => { ingest(event.detail?.quotes); render(); });
  render();
})();
