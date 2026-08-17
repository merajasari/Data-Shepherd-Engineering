(() => {
  const pollMs = 2000;
  const maxPoints = 180;
  const histories = new Map();
  let selected = 'BTC-USD';
  let latestQuotes = {};

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = (value) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    const digits = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 4 : 8;
    return '$' + n.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: digits});
  };
  const pct = (value) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
  };
  const colorClass = (value) => Number(value) >= 0 ? 'positive' : 'negative';

  function quoteChange(q) {
    const raw = q?.price_percent_chg_24_h;
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  }

  function pushPoint(symbol, q) {
    if (!q || !Number.isFinite(Number(q.price))) return;
    const list = histories.get(symbol) || [];
    const t = Date.parse(q.received_at || new Date().toISOString());
    const last = list[list.length - 1];
    if (!last || t > last.t) list.push({t, price: Number(q.price)});
    if (list.length > maxPoints) list.splice(0, list.length - maxPoints);
    histories.set(symbol, list);
  }

  function populateSelect(symbols) {
    const select = document.getElementById('visual-asset-select');
    if (!select) return;
    const current = select.value || selected;
    select.innerHTML = symbols.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    select.value = symbols.includes(current) ? current : (symbols.includes(selected) ? selected : symbols[0]);
    selected = select.value;
  }

  function renderPulse(quotes, updatedAt) {
    const rows = Object.values(quotes).map(q => ({...q, chg: quoteChange(q)}));
    if (!rows.length) return;
    rows.sort((a,b) => b.chg - a.chg);
    const leader = rows[0], laggard = rows[rows.length - 1];
    const up = rows.filter(r => r.chg > 0).length;
    const down = rows.filter(r => r.chg < 0).length;
    const set = (id, text, cls) => { const n=document.getElementById(id); if(n){n.textContent=text;n.className=cls||'';} };
    set('visual-leader', `${leader.product_id} ${pct(leader.chg)}`, colorClass(leader.chg));
    set('visual-laggard', `${laggard.product_id} ${pct(laggard.chg)}`, colorClass(laggard.chg));
    set('visual-up-count', `${up} / ${rows.length}`, 'positive');
    set('visual-down-count', `${down} / ${rows.length}`, 'negative');
    set('visual-btc-price', money(quotes['BTC-USD']?.price));
    const stamp = document.getElementById('visual-live-stamp');
    if (stamp) stamp.textContent = updatedAt ? new Date(updatedAt).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : 'LIVE';
  }

  function renderMovers(quotes) {
    const root = document.getElementById('visual-movers');
    if (!root) return;
    const rows = Object.values(quotes).map(q => ({...q, chg: quoteChange(q)})).sort((a,b) => b.chg - a.chg);
    const maxAbs = Math.max(0.01, ...rows.map(r => Math.abs(r.chg)));
    root.innerHTML = rows.map(r => {
      const width = Math.max(2, Math.abs(r.chg) / maxAbs * 100);
      return `<button type="button" class="mover ${r.product_id===selected?'active':''}" data-symbol="${esc(r.product_id)}"><strong>${esc(r.product_id.replace('-USD',''))}</strong><div class="mover-track"><div class="mover-fill ${r.chg<0?'down':''}" style="width:${width.toFixed(1)}%"></div></div><strong class="${colorClass(r.chg)}">${pct(r.chg)}</strong></button>`;
    }).join('');
    root.querySelectorAll('.mover').forEach(btn => btn.addEventListener('click', () => {
      selected = btn.dataset.symbol;
      const select = document.getElementById('visual-asset-select');
      if (select) select.value = selected;
      renderSelected();
      renderMovers(latestQuotes);
    }));
  }

  function svgEl(tag, attrs={}) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([k,v]) => node.setAttribute(k, String(v)));
    return node;
  }

  function renderChart(points) {
    const svg = document.getElementById('visual-live-chart');
    if (!svg) return;
    svg.innerHTML = '';
    const W=900,H=360,p={l:78,r:35,t:28,b:48};
    if (!points || points.length < 2) {
      const t=svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2','font-size':'15'});
      t.textContent='Collecting live observations…';svg.appendChild(t);return;
    }
    let min=Math.min(...points.map(d=>d.price)), max=Math.max(...points.map(d=>d.price));
    if (max===min){const pad=Math.max(Math.abs(max)*.0005,.000001);min-=pad;max+=pad;} else {const pad=(max-min)*.18;min-=pad;max+=pad;}
    const minT=points[0].t,maxT=points[points.length-1].t;
    const x=t=>p.l+(W-p.l-p.r)*((t-minT)/Math.max(1,maxT-minT));
    const y=v=>p.t+(H-p.t-p.b)*(1-(v-min)/(max-min));
    for(let i=0;i<4;i++){
      const val=min+(max-min)*i/3, yy=y(val);
      svg.appendChild(svgEl('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.14)','stroke-width':1}));
      const label=svgEl('text',{x:p.l-10,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':11});label.textContent=money(val);svg.appendChild(label);
    }
    const pts=points.map(d=>`${x(d.t)},${y(d.price)}`).join(' ');
    const area=`M ${x(points[0].t)} ${H-p.b} L ${points.map(d=>`${x(d.t)} ${y(d.price)}`).join(' L ')} L ${x(points[points.length-1].t)} ${H-p.b} Z`;
    svg.appendChild(svgEl('path',{d:area,fill:'rgba(54,216,255,.09)'}));
    svg.appendChild(svgEl('polyline',{points:pts,fill:'none',stroke:'#36d8ff','stroke-width':3,'stroke-linejoin':'round','stroke-linecap':'round'}));
    const start=svgEl('text',{x:p.l,y:H-18,fill:'#91a6c2','font-size':11});start.textContent=new Date(minT).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});svg.appendChild(start);
    const end=svgEl('text',{x:W-p.r,y:H-18,'text-anchor':'end',fill:'#91a6c2','font-size':11});end.textContent='NOW';svg.appendChild(end);
    const guide=svgEl('line',{y1:p.t,y2:H-p.b,stroke:'#efc56b','stroke-width':1,'stroke-dasharray':'4 4',visibility:'hidden'});svg.appendChild(guide);
    const dot=svgEl('circle',{r:5,fill:'#efc56b',visibility:'hidden'});svg.appendChild(dot);
    const tip=svgEl('text',{fill:'#f2f6ff','font-size':12,'font-weight':700,visibility:'hidden'});svg.appendChild(tip);
    svg.onmousemove=(event)=>{
      const rect=svg.getBoundingClientRect();const mx=(event.clientX-rect.left)/rect.width*W;
      let best=points[0],dist=Infinity;for(const d of points){const dx=Math.abs(x(d.t)-mx);if(dx<dist){dist=dx;best=d;}}
      const xx=x(best.t),yy=y(best.price);guide.setAttribute('x1',xx);guide.setAttribute('x2',xx);guide.setAttribute('visibility','visible');dot.setAttribute('cx',xx);dot.setAttribute('cy',yy);dot.setAttribute('visibility','visible');tip.setAttribute('x',Math.min(W-p.r-130,xx+10));tip.setAttribute('y',Math.max(p.t+15,yy-12));tip.textContent=`${money(best.price)} · ${new Date(best.t).toLocaleTimeString()}`;tip.setAttribute('visibility','visible');
    };
    svg.onmouseleave=()=>{guide.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');tip.setAttribute('visibility','hidden');};
  }

  function renderSelected() {
    const q=latestQuotes[selected];
    const symbol=document.getElementById('visual-selected-symbol');if(symbol)symbol.textContent=selected;
    const price=document.getElementById('visual-selected-price');if(price)price.textContent=money(q?.price);
    const change=document.getElementById('visual-selected-change');if(change){const c=quoteChange(q);change.textContent=`24H ${pct(c)}`;change.style.color=c>=0?'#39e3a1':'#ff6680';}
    const list=histories.get(selected)||[];
    renderChart(list);
    const note=document.getElementById('visual-chart-note');if(note){note.textContent=list.length<2?'Waiting for a second live observation…':`${list.length} live observations · ${(pollMs/1000).toFixed(0)}-second page sampling · display only`;}
  }

  async function refresh() {
    try {
      const r=await fetch('/api/crypto-live',{credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}});
      if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const data=await r.json();
      latestQuotes=data.quotes||{};
      const symbols=Object.keys(latestQuotes).sort();
      if(!symbols.length)return;
      if(!latestQuotes[selected])selected=symbols.includes('BTC-USD')?'BTC-USD':symbols[0];
      symbols.forEach(s=>pushPoint(s,latestQuotes[s]));
      populateSelect(symbols);
      renderPulse(latestQuotes,data.updated_at);
      renderMovers(latestQuotes);
      renderSelected();
    } catch(err) {
      const stamp=document.getElementById('visual-live-stamp');if(stamp){stamp.textContent='RETRYING';stamp.className='negative';}
      console.warn('[CRYPTO VISUAL]',err);
    }
  }

  document.getElementById('visual-asset-select')?.addEventListener('change',(e)=>{selected=e.target.value;renderMovers(latestQuotes);renderSelected();});
  refresh();
  window.setInterval(refresh,pollMs);
})();
