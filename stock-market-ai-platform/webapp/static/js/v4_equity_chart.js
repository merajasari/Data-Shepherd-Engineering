(() => {
  const svg = document.getElementById('v4-equity-chart');
  const wrap = svg?.closest('.v4-chart-wrap');
  const tooltip = document.getElementById('v4-chart-tooltip');
  if (!svg || !wrap || !tooltip) return;

  const style = document.createElement('style');
  style.id = 'v4-equity-interactive-history-style';
  style.textContent = `
    .v4-chart-wrap{position:relative;height:390px;min-height:300px;border:1px solid rgba(120,155,205,.14);border-radius:16px;background:rgba(7,16,31,.52);overflow:hidden}
    .v4-chart-wrap svg{width:100%;height:100%;display:block;touch-action:none;cursor:crosshair}
    .v4-eq-tooltip{position:absolute;display:none;pointer-events:none;z-index:25;min-width:205px;padding:11px 13px;border:1px solid var(--border);border-radius:11px;background:rgba(7,21,37,.97);box-shadow:0 10px 28px rgba(0,0,0,.38);font-size:.78rem;line-height:1.45;color:var(--text)}
    .v4-eq-tooltip strong{display:block;margin-bottom:5px;font-size:.82rem}
    .v4-eq-tooltip-row{display:flex;justify-content:space-between;gap:18px;white-space:nowrap}.v4-eq-tooltip-row span:first-child{color:var(--muted)}
    .v4-eq-slider{width:100%;margin-top:13px;accent-color:var(--cyan)}
    .v4-eq-help{margin-top:7px;color:var(--muted);font-size:.78rem}
    .v4-eq-readout{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:14px}
    .v4-eq-readout .metric{padding:14px}.v4-eq-readout .metric strong{font-size:1rem}
    @media(max-width:650px){.v4-chart-wrap{height:300px}.v4-eq-readout{grid-template-columns:1fr}.v4-eq-tooltip{min-width:175px;font-size:.72rem}}
  `;
  document.getElementById(style.id)?.remove();
  document.head.appendChild(style);
  tooltip.className = 'v4-eq-tooltip';

  let slider = document.getElementById('v4-eq-slider');
  if (!slider) {
    slider = document.createElement('input');
    slider.id = 'v4-eq-slider';
    slider.className = 'v4-eq-slider';
    slider.type = 'range';
    slider.step = '1';
    slider.setAttribute('aria-label', 'Portfolio equity observation selector');
    wrap.insertAdjacentElement('afterend', slider);
  }

  let help = document.getElementById('v4-eq-help');
  if (!help) {
    help = document.createElement('div');
    help.id = 'v4-eq-help';
    help.className = 'v4-eq-help';
    help.textContent = 'The vertical guide follows your pointer. Equity and time labels move with the guide; the floating panel and boxes below show the selected observation.';
    slider.insertAdjacentElement('afterend', help);
  } else {
    help.textContent = 'The vertical guide follows your pointer. Equity and time labels move with the guide; the floating panel and boxes below show the selected observation.';
  }

  let readout = document.getElementById('v4-eq-readout');
  if (!readout) {
    readout = document.createElement('div');
    readout.id = 'v4-eq-readout';
    readout.className = 'v4-eq-readout';
    readout.innerHTML = `
      <div class="metric"><span>SELECTED TIME</span><strong id="v4-eq-selected-time">—</strong></div>
      <div class="metric"><span>PORTFOLIO EQUITY</span><strong id="v4-eq-selected-equity">—</strong></div>
      <div class="metric"><span>CHANGE VS START</span><strong id="v4-eq-selected-change">—</strong></div>`;
    help.insertAdjacentElement('afterend', readout);
  }

  const selectedTime = document.getElementById('v4-eq-selected-time');
  const selectedEquity = document.getElementById('v4-eq-selected-equity');
  const selectedChange = document.getElementById('v4-eq-selected-change');
  const ns = 'http://www.w3.org/2000/svg';
  const money = v => '$' + Number(v || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const signedMoney = v => `${Number(v) >= 0 ? '+' : '-'}$${Math.abs(Number(v || 0)).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
  const fullStamp = row => row?.label || new Date(row.timestamp).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'});
  const shortStamp = row => row?.label || new Date(row.timestamp).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});

  let rows = [];
  let startingEquity = 100000;
  let geometry = null;
  let pointerActive = false;

  function node(tag, attrs = {}, parent = svg) {
    const n = document.createElementNS(ns, tag);
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k,v);
    parent.appendChild(n);
    return n;
  }

  function setTag(id, x, y, text, opts = {}) {
    const group = svg.querySelector(`#${id}`);
    if (!group || !geometry) return;
    const rect = group.querySelector('rect');
    const label = group.querySelector('text');
    const width = Math.max(opts.minWidth || 78, String(text).length * (opts.charWidth || 7) + 18);
    let left = x + 11;
    if (opts.center) left = x - width / 2;
    else if (x + width + 18 > geometry.W - geometry.p.r) left = x - width - 11;
    left = Math.max(geometry.p.l + 2, Math.min(left, geometry.W - geometry.p.r - width - 2));
    const top = Math.max(geometry.p.t + 2, Math.min(y, geometry.H - geometry.p.b - 27));
    rect.setAttribute('x', left); rect.setAttribute('y', top); rect.setAttribute('width', width); rect.setAttribute('height', 25);
    label.setAttribute('x', left + width/2); label.setAttribute('y', top + 17); label.textContent = text;
    group.setAttribute('visibility','visible');
  }

  function showTooltip(index, clientX = null, clientY = null) {
    const row = rows[index];
    if (!row || !geometry) return;
    const equity = Number(row.equity);
    const change = equity - startingEquity;
    tooltip.innerHTML = `<strong>${fullStamp(row)}</strong><div class="v4-eq-tooltip-row"><span>Portfolio equity</span><b>${money(equity)}</b></div><div class="v4-eq-tooltip-row"><span>Vs start</span><b class="${change >= 0 ? 'positive' : 'negative'}">${signedMoney(change)}</b></div>`;
    tooltip.style.display = 'block';
    const wr = wrap.getBoundingClientRect();
    const localX = clientX == null ? wr.width * (geometry.x(index)/geometry.W) : clientX - wr.left;
    const localY = clientY == null ? 70 : clientY - wr.top;
    const tw = tooltip.offsetWidth || 205, th = tooltip.offsetHeight || 95;
    let left = localX + 18;
    if (left + tw > wr.width - 8) left = localX - tw - 18;
    tooltip.style.left = Math.max(8,left) + 'px';
    tooltip.style.top = Math.max(8,Math.min(localY-th/2,wr.height-th-8)) + 'px';
  }

  function updateSelection(index, clientX = null, clientY = null, showTip = true) {
    if (!rows.length || !geometry) return;
    index = Math.max(0,Math.min(rows.length-1,Number(index)));
    slider.value = index;
    const row = rows[index], equity = Number(row.equity), change = equity-startingEquity;
    const x = geometry.x(index), y = geometry.y(equity);
    const guide = svg.querySelector('#v4-equity-guide');
    const dot = svg.querySelector('#v4-equity-guide-dot');
    if (guide) { guide.setAttribute('x1',x); guide.setAttribute('x2',x); guide.setAttribute('opacity','.92'); }
    if (dot) { dot.setAttribute('cx',x); dot.setAttribute('cy',y); }
    setTag('v4-equity-value-tag',x,y-34,money(equity),{minWidth:90});
    setTag('v4-equity-date-tag',x,geometry.H-geometry.p.b-29,fullStamp(row),{center:true,minWidth:126,charWidth:6.2});
    selectedTime.textContent = fullStamp(row);
    selectedEquity.textContent = money(equity);
    selectedChange.textContent = signedMoney(change);
    selectedChange.className = change >= 0 ? 'positive' : 'negative';
    if (showTip) showTooltip(index,clientX,clientY);
  }

  function render() {
    svg.innerHTML = '';
    const W=1000,H=390,p={l:78,r:34,t:24,b:48};
    if (!rows.length) {
      const t=node('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#91a6c2','font-size':'15'}); t.textContent='No portfolio observations available.'; return;
    }
    const vals=rows.map(r=>Number(r.equity)).filter(Number.isFinite);
    let min=Math.min(...vals,startingEquity),max=Math.max(...vals,startingEquity);
    const span=Math.max(max-min,Math.max(100,startingEquity*.002)); min-=span*.16; max+=span*.16;
    const x=i=>rows.length===1?(p.l+(W-p.l-p.r)/2):p.l+(W-p.l-p.r)*(i/(rows.length-1));
    const y=v=>p.t+(H-p.t-p.b)*(1-(v-min)/(max-min));
    geometry={W,H,p,x,y};

    for(let i=0;i<5;i++){
      const v=min+(max-min)*i/4, yy=y(v);
      node('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.15)','stroke-width':'1'});
      const t=node('text',{x:p.l-9,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':'11'}); t.textContent='$'+Math.round(v).toLocaleString();
    }
    const baselineY=y(startingEquity);
    node('line',{x1:p.l,y1:baselineY,x2:W-p.r,y2:baselineY,stroke:'#91a6c2','stroke-width':'1.15','stroke-dasharray':'6 5',opacity:'.75'});
    const base=node('text',{x:p.l+8,y:baselineY-7,fill:'#91a6c2','font-size':'11','font-weight':'700'}); base.textContent=money(startingEquity)+' baseline';

    if(rows.length>1){
      const points=rows.map((r,i)=>[x(i),y(Number(r.equity))]);
      node('path',{d:`M ${points[0][0]} ${H-p.b} L ${points.map(q=>q.join(' ')).join(' L ')} L ${points.at(-1)[0]} ${H-p.b} Z`,fill:'rgba(57,227,161,.09)'});
      node('polyline',{points:points.map(q=>q.join(',')).join(' '),fill:'none',stroke:'#39e3a1','stroke-width':'3','stroke-linejoin':'round','stroke-linecap':'round'});
    }

    const labelIndexes=rows.length===1?[0]:[0,Math.floor((rows.length-1)/3),Math.floor((rows.length-1)*2/3),rows.length-1];
    [...new Set(labelIndexes)].forEach(i=>{const t=node('text',{x:x(i),y:H-16,'text-anchor':'middle',fill:rows[i].label==='Current'?'#36d8ff':'#91a6c2','font-size':'11'});t.textContent=shortStamp(rows[i]);});

    const last=Math.max(0,rows.length-1);
    node('line',{id:'v4-equity-guide',x1:x(last),x2:x(last),y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-width':'1.5','stroke-dasharray':'5 4',opacity:'.92'});
    node('circle',{id:'v4-equity-guide-dot',cx:x(last),cy:y(Number(rows[last].equity)),r:'5.5',fill:'#39e3a1',stroke:'#07101f','stroke-width':'2'});
    const valueTag=node('g',{id:'v4-equity-value-tag',visibility:'hidden'}); node('rect',{rx:'6',ry:'6',fill:'#0b2940',stroke:'#39e3a1','stroke-width':'1.2'},valueTag); node('text',{'text-anchor':'middle',fill:'#f2f6ff','font-size':'12','font-weight':'900'},valueTag);
    const dateTag=node('g',{id:'v4-equity-date-tag',visibility:'hidden'}); node('rect',{rx:'6',ry:'6',fill:'#111d31',stroke:'#91a6c2','stroke-width':'1.1'},dateTag); node('text',{'text-anchor':'middle',fill:'#f2f6ff','font-size':'11','font-weight':'800'},dateTag);

    const overlay=node('rect',{
      x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,
      fill:'rgba(0,0,0,0.001)',
      'pointer-events':'all',
      style:'cursor:crosshair;touch-action:none'
    });

    const selectFromEvent=event=>{
      const rect=svg.getBoundingClientRect();
      const px=(event.clientX-rect.left)*W/rect.width;
      const plotLeft=p.l;
      const plotRight=W-p.r;
      const guideX=Math.max(plotLeft,Math.min(plotRight,px));
      const ratio=(guideX-plotLeft)/(plotRight-plotLeft);
      const idx=rows.length===1?0:Math.round(ratio*(rows.length-1));

      // Update the selected observation/readouts first.
      updateSelection(idx,event.clientX,event.clientY,true);

      // Then keep the vertical guide physically under the pointer instead of
      // snapping it to the sparse journal observation.  This makes the V4
      // chart feel like Interactive Market History even when only a handful
      // of V4 journal observations exist.
      const guide=svg.querySelector('#v4-equity-guide');
      if(guide){
        guide.setAttribute('x1',guideX);
        guide.setAttribute('x2',guideX);
        guide.setAttribute('opacity','.98');
      }
    };

    overlay.addEventListener('pointerenter',()=>{pointerActive=true;});
    overlay.addEventListener('pointermove',selectFromEvent);
    overlay.addEventListener('pointerdown',event=>{
      overlay.setPointerCapture?.(event.pointerId);
      selectFromEvent(event);
    });
    overlay.addEventListener('pointerleave',()=>{pointerActive=false;tooltip.style.display='none';});
    updateSelection(last,null,null,false);
  }

  async function load() {
    const response=await fetch('/api/v4-forward',{credentials:'same-origin',cache:'no-store'});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const d=await response.json();
    rows=(d.forward?.chart_history||[]).map(row=>({...row,equity:Number(row.equity)}));
    startingEquity=Number(d.portfolio?.starting_cash||100000);
    slider.min='0'; slider.max=String(Math.max(0,rows.length-1)); slider.value=slider.max;
    render();
  }

  slider.addEventListener('input',()=>updateSelection(slider.value,null,null,true));
  slider.addEventListener('change',()=>setTimeout(()=>tooltip.style.display='none',900));
  const startLoad=()=>load().catch(err=>console.error('V4 interactive equity chart:',err));
  if('requestIdleCallback' in window) requestIdleCallback(startLoad,{timeout:700}); else setTimeout(startLoad,80);
  window.setInterval(()=>{if(!pointerActive) startLoad();},5000);
})();
