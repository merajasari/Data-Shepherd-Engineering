(() => {
  const select = document.getElementById('stock-select');
  if (!select) return;

  const style = document.createElement('style');
  style.textContent = `
    .market-history-card{margin-top:22px}
    .market-history-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}
    .market-history-legend{display:flex;gap:15px;flex-wrap:wrap;color:var(--muted);font-size:.8rem}
    .market-history-legend span{display:inline-flex;align-items:center;gap:7px}
    .mh-dot{width:10px;height:10px;border-radius:50%;display:inline-block}
    .market-history-chart{position:relative;height:390px;margin-top:16px;border:1px solid rgba(120,155,205,.14);border-radius:16px;background:rgba(7,16,31,.52);overflow:hidden}
    .market-history-chart svg{width:100%;height:100%;display:block;touch-action:none;cursor:crosshair}
    .mh-tooltip{position:absolute;display:none;pointer-events:none;z-index:20;min-width:190px;padding:11px 13px;border:1px solid var(--border);border-radius:11px;background:rgba(7,21,37,.96);box-shadow:0 10px 28px rgba(0,0,0,.38);font-size:.78rem;line-height:1.45;color:var(--text)}
    .mh-tooltip strong{display:block;margin-bottom:5px;font-size:.82rem;color:var(--text)}
    .mh-tooltip-row{display:flex;justify-content:space-between;gap:18px;white-space:nowrap}
    .mh-tooltip-row span:first-child{color:var(--muted)}
    .market-history-readout{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:14px}
    .market-history-readout .metric{padding:14px}
    .market-history-slider{width:100%;margin-top:13px;accent-color:var(--cyan)}
    .market-history-help{margin-top:7px;color:var(--muted);font-size:.78rem}
    @media(max-width:800px){.market-history-readout{grid-template-columns:repeat(2,1fr)}.market-history-chart{height:320px}}
    @media(max-width:520px){.market-history-readout{grid-template-columns:1fr 1fr}.market-history-chart{height:280px}.mh-tooltip{min-width:165px;font-size:.72rem}}
  `;
  document.head.appendChild(style);

  const technicalMetrics = Array.from(document.querySelectorAll('section.grid.metrics'))
    .find(section => section.querySelector('.metric span')?.textContent?.trim() === 'RSI 14');
  if (!technicalMetrics) return;

  const section = document.createElement('section');
  section.className = 'card market-history-card';
  section.innerHTML = `
    <div class="market-history-head">
      <div>
        <div class="label">INTERACTIVE MARKET HISTORY</div>
        <h2 id="mh-title" style="margin-bottom:5px">Price History</h2>
        <div class="muted">Move across the chart or drag the slider to inspect historical Close and moving averages.</div>
      </div>
      <div class="market-history-legend">
        <span><i class="mh-dot" style="background:#36d8ff"></i>Close</span>
        <span><i class="mh-dot" style="background:#39e3a1"></i>SMA 20</span>
        <span><i class="mh-dot" style="background:#efc56b"></i>SMA 50</span>
        <span><i class="mh-dot" style="background:#9b65ff"></i>SMA 200</span>
      </div>
    </div>
    <div class="market-history-chart" id="market-history-chart-wrap">
      <svg id="market-history-svg" viewBox="0 0 1000 390" preserveAspectRatio="none" aria-label="Interactive historical stock price chart"></svg>
      <div id="mh-tooltip" class="mh-tooltip"></div>
    </div>
    <input id="market-history-slider" class="market-history-slider" type="range" min="0" max="0" value="0" step="1" aria-label="Historical market date selector">
    <div class="market-history-help">The vertical guide follows your pointer. Price and date labels move with the guide; the floating panel and boxes below show the full selected-session detail.</div>
    <div class="market-history-readout">
      <div class="metric"><span>DATE</span><strong id="mh-date">—</strong></div>
      <div class="metric"><span>CLOSE</span><strong id="mh-close">—</strong></div>
      <div class="metric"><span>SMA 20</span><strong id="mh-sma20">—</strong></div>
      <div class="metric"><span>SMA 50</span><strong id="mh-sma50">—</strong></div>
      <div class="metric"><span>SMA 200</span><strong id="mh-sma200">—</strong></div>
    </div>`;
  technicalMetrics.insertAdjacentElement('afterend', section);

  const svg = document.getElementById('market-history-svg');
  const chartWrap = document.getElementById('market-history-chart-wrap');
  const tooltip = document.getElementById('mh-tooltip');
  const slider = document.getElementById('market-history-slider');
  const title = document.getElementById('mh-title');
  const readout = {
    date: document.getElementById('mh-date'),
    close: document.getElementById('mh-close'),
    sma20: document.getElementById('mh-sma20'),
    sma50: document.getElementById('mh-sma50'),
    sma200: document.getElementById('mh-sma200')
  };

  const money = value => value == null || Number.isNaN(Number(value)) ? '—' : '$' + Number(value).toFixed(2);
  const dateLabel = value => new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
  const shortDateLabel = value => new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:'UTC'});
  let rows = [];
  let geometry = null;

  function nsEl(tag, attrs = {}, parent = svg) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    parent.appendChild(node);
    return node;
  }

  function renderSeries(points, color, width = 2.2) {
    const usable = points.filter(p => p[1] != null && Number.isFinite(p[1]));
    if (usable.length < 2) return;
    nsEl('polyline', {
      points: usable.map(([x, y]) => `${x},${geometry.y(y)}`).join(' '),
      fill: 'none', stroke: color, 'stroke-width': width,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity: '.95'
    });
  }

  function showTooltip(index, clientX, clientY) {
    const row = rows[index];
    if (!row) return;
    tooltip.innerHTML = `<strong>${dateLabel(row.timestamp)}</strong>
      <div class="mh-tooltip-row"><span>Close</span><b>${money(row.close)}</b></div>
      <div class="mh-tooltip-row"><span>SMA 20</span><b>${money(row.sma_20)}</b></div>
      <div class="mh-tooltip-row"><span>SMA 50</span><b>${money(row.sma_50)}</b></div>
      <div class="mh-tooltip-row"><span>SMA 200</span><b>${money(row.sma_200)}</b></div>`;
    tooltip.style.display = 'block';
    const wrapRect = chartWrap.getBoundingClientRect();
    const localX = clientX == null ? wrapRect.width * (geometry.x(index) / geometry.W) : clientX - wrapRect.left;
    const localY = clientY == null ? 70 : clientY - wrapRect.top;
    const tw = tooltip.offsetWidth || 190;
    const th = tooltip.offsetHeight || 120;
    let left = localX + 18;
    if (left + tw > wrapRect.width - 8) left = localX - tw - 18;
    let top = Math.max(8, Math.min(localY - th / 2, wrapRect.height - th - 8));
    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${top}px`;
  }

  function setTag(groupId, x, y, text, opts = {}) {
    const group = svg.querySelector(`#${groupId}`);
    if (!group) return;
    const rect = group.querySelector('rect');
    const label = group.querySelector('text');
    const width = Math.max(opts.minWidth || 72, text.length * (opts.charWidth || 7.1) + 18);
    let left = x - width / 2;
    if (opts.anchor === 'right') left = x + 10;
    if (opts.anchor === 'left') left = x - width - 10;
    left = Math.max(geometry.p.l + 2, Math.min(left, geometry.W - geometry.p.r - width - 2));
    const top = Math.max(geometry.p.t + 2, Math.min(y, geometry.H - geometry.p.b - (opts.height || 25) - 2));
    rect.setAttribute('x', left);
    rect.setAttribute('y', top);
    rect.setAttribute('width', width);
    rect.setAttribute('height', opts.height || 25);
    label.setAttribute('x', left + width / 2);
    label.setAttribute('y', top + 17);
    label.textContent = text;
    group.setAttribute('visibility', 'visible');
  }

  function updateSelection(index, clientX = null, clientY = null, show = true) {
    if (!rows.length || !geometry) return;
    index = Math.max(0, Math.min(rows.length - 1, Number(index)));
    slider.value = index;
    const row = rows[index];
    const x = geometry.x(index);
    const closeY = geometry.y(Number(row.close));

    readout.date.textContent = dateLabel(row.timestamp);
    readout.close.textContent = money(row.close);
    readout.sma20.textContent = money(row.sma_20);
    readout.sma50.textContent = money(row.sma_50);
    readout.sma200.textContent = money(row.sma_200);

    const line = svg.querySelector('#mh-crosshair');
    const dot = svg.querySelector('#mh-crosshair-dot');
    if (line) { line.setAttribute('x1', x); line.setAttribute('x2', x); }
    if (dot) { dot.setAttribute('cx', x); dot.setAttribute('cy', closeY); }

    setTag('mh-price-tag', x, closeY - 34, money(row.close), {
      anchor: x > geometry.W * .73 ? 'left' : 'right', minWidth: 78
    });
    setTag('mh-date-tag', x, geometry.H - geometry.p.b - 30, dateLabel(row.timestamp), {
      minWidth: 112, charWidth: 6.5
    });

    if (show) showTooltip(index, clientX, clientY);
  }

  function renderChart() {
    svg.innerHTML = '';
    if (rows.length < 2) {
      const t = nsEl('text',{x:500,y:195,'text-anchor':'middle',fill:'#91a6c2','font-size':'15'});
      t.textContent = 'Not enough market history to render chart.';
      return;
    }

    const W = 1000, H = 390, p = {l:72,r:28,t:24,b:46};
    const values = [];
    rows.forEach(r => ['close','sma_20','sma_50','sma_200'].forEach(k => {
      if (r[k] != null && Number.isFinite(Number(r[k]))) values.push(Number(r[k]));
    }));
    let min = Math.min(...values), max = Math.max(...values);
    const span = Math.max(max - min, Math.max(2, max * .02));
    min -= span * .08;
    max += span * .08;
    const x = i => p.l + (W - p.l - p.r) * (i / (rows.length - 1));
    const y = v => p.t + (H - p.t - p.b) * (1 - (v - min) / (max - min));
    geometry = {W,H,p,x,y};

    for (let i = 0; i < 5; i++) {
      const value = min + (max - min) * i / 4;
      const yy = y(value);
      nsEl('line',{x1:p.l,y1:yy,x2:W-p.r,y2:yy,stroke:'rgba(145,166,194,.15)','stroke-width':'1'});
      const label = nsEl('text',{x:p.l-9,y:yy+4,'text-anchor':'end',fill:'#91a6c2','font-size':'11'});
      label.textContent = '$' + value.toFixed(0);
    }

    const labelIndexes = [0, Math.floor((rows.length-1)/3), Math.floor((rows.length-1)*2/3), rows.length-1];
    [...new Set(labelIndexes)].forEach(i => {
      const label = nsEl('text',{x:x(i),y:H-16,'text-anchor':'middle',fill:'#91a6c2','font-size':'11'});
      label.textContent = shortDateLabel(rows[i].timestamp);
    });

    renderSeries(rows.map((r,i)=>[x(i),Number(r.close)]),'#36d8ff',3);
    renderSeries(rows.map((r,i)=>[x(i),r.sma_20==null?null:Number(r.sma_20)]),'#39e3a1');
    renderSeries(rows.map((r,i)=>[x(i),r.sma_50==null?null:Number(r.sma_50)]),'#efc56b');
    renderSeries(rows.map((r,i)=>[x(i),r.sma_200==null?null:Number(r.sma_200)]),'#9b65ff');

    nsEl('line',{id:'mh-crosshair',x1:x(rows.length-1),x2:x(rows.length-1),y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-width':'1.2','stroke-dasharray':'5 4',opacity:'.82'});
    nsEl('circle',{id:'mh-crosshair-dot',cx:x(rows.length-1),cy:y(Number(rows[rows.length-1].close)),r:'5',fill:'#36d8ff',stroke:'#07101f','stroke-width':'2'});

    const priceTag = nsEl('g',{id:'mh-price-tag',visibility:'hidden'});
    nsEl('rect',{rx:'6',ry:'6',fill:'#0b2940',stroke:'#36d8ff','stroke-width':'1.2'},priceTag);
    nsEl('text',{'text-anchor':'middle',fill:'#f2f6ff','font-size':'12','font-weight':'900'},priceTag);

    const dateTag = nsEl('g',{id:'mh-date-tag',visibility:'hidden'});
    nsEl('rect',{rx:'6',ry:'6',fill:'#111d31',stroke:'#91a6c2','stroke-width':'1.1'},dateTag);
    nsEl('text',{'text-anchor':'middle',fill:'#f2f6ff','font-size':'11','font-weight':'800'},dateTag);

    const overlay = nsEl('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'transparent',style:'cursor:crosshair;touch-action:none'});
    function selectFromEvent(event) {
      const rect = svg.getBoundingClientRect();
      const px = (event.clientX - rect.left) * W / rect.width;
      const ratio = Math.max(0, Math.min(1, (px - p.l) / (W - p.l - p.r)));
      updateSelection(Math.round(ratio * (rows.length - 1)), event.clientX, event.clientY, true);
    }
    overlay.addEventListener('pointermove', selectFromEvent);
    overlay.addEventListener('pointerdown', event => { overlay.setPointerCapture?.(event.pointerId); selectFromEvent(event); });
    overlay.addEventListener('pointerleave', () => { tooltip.style.display = 'none'; });
  }

  async function load() {
    const symbol = select.value;
    title.textContent = `${symbol} Historical Price + Moving Averages`;
    try {
      const response = await fetch(`/api/prices/${encodeURIComponent(symbol)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      rows = payload.slice().reverse();
      slider.max = Math.max(0, rows.length - 1);
      slider.value = Math.max(0, rows.length - 1);
      renderChart();
      updateSelection(rows.length - 1, null, null, false);
    } catch (error) {
      console.error('market history chart:', error);
      svg.innerHTML = '<text x="500" y="195" text-anchor="middle" fill="#ff6680">Unable to load market history.</text>';
    }
  }

  slider.addEventListener('input', () => updateSelection(slider.value, null, null, true));
  slider.addEventListener('change', () => { setTimeout(() => tooltip.style.display='none', 900); });
  load();
})();
