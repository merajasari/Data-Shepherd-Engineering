(() => {
  if (new URLSearchParams(window.location.search).get('view') === 'live') return;

  const START = 100000;
  const POLL_MS = 15000;
  const CONFIG = {
    v10: {label:'V10 accelerated', short:'V10', color:'#36d8ff'},
    v14: {label:'V14 ML', short:'V14', color:'#9dff2a'},
    v15: {label:'V15 intraday', short:'V15', color:'#ff67c8'},
    v8:  {label:'V8 control', short:'V8', color:'#efc56b'},
    spy: {label:'SPY', short:'SPY', color:'#a78bfa'},
  };
  const visible = new Set(Object.keys(CONFIG));
  let model = null;
  let resizeObserver = null;
  let pollTimer = null;

  const money = value => Number(value).toLocaleString(undefined, {
    style:'currency', currency:'USD', minimumFractionDigits:2, maximumFractionDigits:2,
  });
  const pct = value => value == null || !Number.isFinite(Number(value))
    ? '\u2014'
    : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(4)}%`;
  const when = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '\u2014' : date.toLocaleString(undefined, {
      month:'short', day:'numeric', hour:'numeric', minute:'2-digit',
      timeZone:'America/Los_Angeles', timeZoneName:'short',
    });
  };
  const day = value => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '\u2014' : date.toLocaleDateString(undefined, {
      month:'short', day:'numeric', year:'numeric', timeZone:'America/Los_Angeles',
    });
  };
  const finite = value => Number.isFinite(Number(value));
  const stamp = value => {
    const parsed = new Date(value).getTime();
    return Number.isFinite(parsed) ? parsed : null;
  };
  const statusText = value => String(value || 'waiting').replaceAll('_', ' ');
  const unique = rows => {
    const sorted = rows
      .filter(row => Number.isFinite(row.time) && Number.isFinite(row.value))
      .sort((left, right) => left.time - right.time);
    return sorted.filter((row, index) => !index || row.time !== sorted[index - 1].time);
  };
  const appendCurrent = (rows, payload, value, allow) => {
    const currentTime = stamp(
      payload.valuation_timestamp_utc || payload.operational_checked_at_utc ||
      payload.checked_at_utc || new Date().toISOString()
    );
    if (!allow || currentTime == null || !finite(value)) return rows;
    let time = currentTime;
    if (rows.length && time <= rows.at(-1).time) time = rows.at(-1).time + 1;
    rows.push({time, value:Number(value), kind:'CURRENT MARK'});
    return rows;
  };

  function v10Series(payload) {
    const boundary = stamp(payload.first_decision_session_utc);
    const base = finite(payload.starting_equity) ? Number(payload.starting_equity) : START;
    const make = (key, currentKey, id) => {
      const rows = boundary == null ? [] : [{time:boundary, value:base, kind:'FORWARD BOUNDARY'}];
      (Array.isArray(payload.operational_curve) ? payload.operational_curve : []).forEach(row => {
        const time = stamp(row.timestamp_utc);
        if (time != null && finite(row[key])) rows.push({time, value:Number(row[key]), kind:'COMPLETED EXIT'});
      });
      appendCurrent(rows, payload, payload[currentKey], payload.equity_basis === 'LIVE_MARK_TO_MARKET');
      return {id, ...CONFIG[id], boundary, state:payload.status, basis:payload.equity_basis, points:unique(rows)};
    };
    return [
      make('v10_normalized', 'current_equity', 'v10'),
      make('v8_normalized', 'current_v8_equity', 'v8'),
      make('spy_normalized', 'current_spy_equity', 'spy'),
    ];
  }

  function v14Series(payload) {
    const boundary = stamp(payload.paper_forward_start_utc);
    const rows = boundary == null ? [] : [{time:boundary, value:START, kind:'FORWARD BOUNDARY'}];
    (Array.isArray(payload.curve) ? payload.curve : []).forEach(row => {
      const time = stamp(row.timestamp_utc);
      if (time != null && finite(row.v14_normalized)) {
        rows.push({time, value:Number(row.v14_normalized), kind:statusText(row.event)});
      }
    });
    appendCurrent(
      rows, payload, payload.current_equity,
      ['LIVE_MARK_TO_MARKET', 'PARTIAL_MARK_TO_MARKET'].includes(payload.equity_basis)
    );
    return {
      id:'v14', ...CONFIG.v14, boundary, state:payload.state,
      basis:payload.equity_basis, points:unique(rows),
    };
  }

  function v15Series(payload) {
    const boundary = stamp(payload.first_eligible_session);
    const curve = Array.isArray(payload.curve) ? payload.curve : [];
    const boundaryReached = boundary != null && Date.now() >= boundary;
    const rows = boundaryReached || curve.length
      ? [{time:boundary, value:START, kind:'PROSPECTIVE BOUNDARY'}]
      : [];
    curve.forEach(row => {
      const time = stamp(row.session_date);
      if (time != null && finite(row.v15_normalized)) {
        rows.push({time, value:Number(row.v15_normalized), kind:statusText(row.event)});
      }
    });
    return {
      id:'v15', ...CONFIG.v15, boundary, state:payload.state,
      basis:curve.length ? 'COMPLETED PROSPECTIVE SESSIONS' : 'WAITING FOR FIRST SESSION',
      points:unique(rows),
    };
  }

  function mount() {
    const target = document.querySelector('[data-research-content="overview"]');
    if (!target) return false;
    if (document.getElementById('overview-live-paper-comparison')) return true;
    const card = document.createElement('section');
    card.id = 'overview-live-paper-comparison';
    card.className = 'olp-card';
    card.innerHTML = `
      <style>
        #overview-live-paper-comparison{margin:0 0 20px;padding:22px;border:1px solid rgba(54,216,255,.3);border-radius:22px;background:linear-gradient(145deg,rgba(7,27,45,.98),rgba(8,18,34,.98));box-shadow:0 20px 48px rgba(0,0,0,.2);min-width:0}
        #overview-live-paper-comparison .olp-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}
        #overview-live-paper-comparison h2{margin:6px 0 6px;font-size:clamp(1.35rem,2.4vw,2rem)}
        #overview-live-paper-comparison .olp-note{max-width:920px;line-height:1.55}
        #overview-live-paper-comparison .olp-live{display:flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid rgba(57,227,161,.28);border-radius:999px;color:#39e3a1;font-size:.68rem;font-weight:900;letter-spacing:.06em;white-space:nowrap}
        #overview-live-paper-comparison .olp-live i{width:7px;height:7px;border-radius:50%;background:#39e3a1;box-shadow:0 0 12px #39e3a1}
        #overview-live-paper-comparison .olp-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:11px;margin:18px 0 14px}
        #overview-live-paper-comparison .olp-metric{padding:13px 14px;border:1px solid rgba(120,155,205,.18);border-radius:14px;background:rgba(3,12,24,.42);min-width:0}
        #overview-live-paper-comparison .olp-metric span{display:block;color:#91a6c2;font-size:.65rem;font-weight:900;letter-spacing:.07em;text-transform:uppercase}
        #overview-live-paper-comparison .olp-metric strong{display:block;margin-top:6px;font-size:1.05rem;overflow-wrap:anywhere}
        #overview-live-paper-comparison .olp-metric small{display:block;margin-top:5px;color:#91a6c2;font-size:.7rem;line-height:1.35;text-transform:capitalize}
        #overview-live-paper-comparison .olp-tools{display:flex;justify-content:space-between;gap:12px;align-items:center;margin:12px 0;flex-wrap:wrap}
        #overview-live-paper-comparison .olp-toggles{display:flex;gap:7px;flex-wrap:wrap}
        #overview-live-paper-comparison .olp-toggle{display:flex;gap:7px;align-items:center;padding:7px 9px;border:1px solid rgba(120,155,205,.22);border-radius:999px;background:rgba(5,15,29,.66);color:#dfe9f6;font-size:.7rem;font-weight:850;cursor:pointer}
        #overview-live-paper-comparison .olp-toggle[aria-pressed=false]{opacity:.42}
        #overview-live-paper-comparison .olp-toggle i{width:9px;height:9px;border-radius:50%}
        #overview-live-paper-comparison .olp-updated{color:#91a6c2;font-size:.72rem}
        #overview-live-paper-comparison .olp-stage{position:relative;min-height:360px;border:1px solid rgba(120,155,205,.13);border-radius:17px;background:rgba(2,10,21,.36);overflow:hidden}
        #overview-live-paper-comparison .olp-chart{height:360px;min-width:0}
        #overview-live-paper-comparison .olp-chart svg{display:block;width:100%;height:100%}
        #overview-live-paper-comparison .olp-tooltip{display:none;position:absolute;z-index:3;min-width:230px;transform:translate(-50%,-105%);padding:10px 11px;border:1px solid rgba(120,155,205,.34);border-radius:11px;background:rgba(4,13,25,.97);box-shadow:0 14px 28px rgba(0,0,0,.36);font-size:.72rem;pointer-events:none}
        #overview-live-paper-comparison .olp-tooltip.show{display:block}
        #overview-live-paper-comparison .olp-tooltip strong{display:block;margin-bottom:7px}
        #overview-live-paper-comparison .olp-tooltip div{display:flex;justify-content:space-between;gap:16px;margin-top:4px}
        #overview-live-paper-comparison .olp-disclosure{margin-top:13px;padding:12px 14px;border-left:3px solid #36d8ff;background:rgba(54,216,255,.055);color:#91a6c2;font-size:.75rem;line-height:1.5}
        #overview-live-paper-comparison .positive{color:#39e3a1}#overview-live-paper-comparison .negative{color:#ff6680}
        @media(max-width:780px){#overview-live-paper-comparison{padding:16px}#overview-live-paper-comparison .olp-head{display:block}#overview-live-paper-comparison .olp-live{width:max-content;margin-top:10px}#overview-live-paper-comparison .olp-metrics{grid-template-columns:1fr}#overview-live-paper-comparison .olp-stage,#overview-live-paper-comparison .olp-chart{min-height:315px;height:315px}}
      </style>
      <div class="olp-head">
        <div><div class="label">LIVE PROSPECTIVE MODEL COMPARISON</div><h2>Interactive live paper performance</h2><div class="muted olp-note">V10, V14, and V15 are displayed from their own preregistered boundaries on a common $100,000 basis. V8 and SPY remain reference controls. Hover for exact values and toggle any line.</div></div>
        <div class="olp-live"><i></i>READ-ONLY · 15-SECOND REFRESH</div>
      </div>
      <div class="olp-metrics" data-olp-metrics></div>
      <div class="olp-tools"><div class="olp-toggles" data-olp-toggles></div><div class="olp-updated" data-olp-updated>Loading paper journals…</div></div>
      <div class="olp-stage"><div class="olp-chart" data-olp-chart></div><div class="olp-tooltip" data-olp-tooltip></div></div>
      <div class="olp-disclosure"><strong>Evidence boundary:</strong> this is a read-only visual comparison, not a common-start holdout. Each model enters only at its own authorized boundary; V15 remains visibly pending until September 21, 2026. No historical reconstruction, runner invocation, automatic promotion, or brokerage authority is included.</div>
    `;
    target.prepend(card);
    card.querySelector('[data-olp-toggles]').innerHTML = Object.entries(CONFIG).map(([id, item]) =>
      `<button type="button" class="olp-toggle" data-olp-toggle="${id}" aria-pressed="true"><i style="background:${item.color}"></i>${item.label}</button>`
    ).join('');
    card.querySelector('[data-olp-toggles]').addEventListener('click', event => {
      const button = event.target.closest('[data-olp-toggle]');
      if (!button) return;
      const id = button.dataset.olpToggle;
      if (visible.has(id) && visible.size === 1) return;
      if (visible.has(id)) visible.delete(id); else visible.add(id);
      button.setAttribute('aria-pressed', String(visible.has(id)));
      render();
    });
    const stage = card.querySelector('.olp-stage');
    stage.addEventListener('pointermove', hover);
    stage.addEventListener('pointerleave', () => {
      card.querySelector('[data-olp-tooltip]').classList.remove('show');
      card.querySelector('[data-olp-guide]')?.setAttribute('opacity', '0');
    });
    if (window.ResizeObserver) {
      resizeObserver = new ResizeObserver(() => render());
      resizeObserver.observe(card.querySelector('[data-olp-chart]'));
    }
    return true;
  }

  function renderMetrics(series) {
    const host = document.querySelector('[data-olp-metrics]');
    if (!host) return;
    host.innerHTML = series.filter(item => ['v10','v14','v15'].includes(item.id)).map(item => {
      const last = item.points.at(-1);
      const value = last?.value ?? START;
      const change = value / START - 1;
      const waiting = !item.points.length;
      return `<div class="olp-metric"><span>${item.label}</span><strong class="${change < 0 ? 'negative' : 'positive'}">${money(value)} · ${pct(change)}</strong><small>${waiting ? `Waiting for ${day(item.boundary)} boundary` : statusText(item.basis || item.state)}</small></div>`;
    }).join('');
  }

  function render() {
    const host = document.querySelector('[data-olp-chart]');
    if (!host || !model) return;
    renderMetrics(model.series);
    const active = model.series.filter(item => visible.has(item.id) && item.points.length);
    if (!active.length) {
      host.innerHTML = '<div style="height:100%;display:grid;place-items:center;color:#91a6c2">Waiting for the first prospective paper observation.</div>';
      return;
    }
    const all = active.flatMap(item => item.points);
    const W = Math.max(720, Math.round(host.clientWidth || 1000));
    const H = 360, p = {l:78,r:150,t:25,b:43};
    const minX = Math.min(...all.map(row => row.time));
    const rawMaxX = Math.max(...all.map(row => row.time));
    const maxX = Math.max(rawMaxX, minX + 86400000);
    const values = [...all.map(row => row.value), START];
    const raw = Math.max(...values) - Math.min(...values);
    const padding = Math.max(raw * .2, 50);
    const lo = Math.min(...values) - padding, hi = Math.max(...values) + padding;
    const x = value => p.l + (value - minX) / (maxX - minX) * (W - p.l - p.r);
    const y = value => p.t + (hi - value) / (hi - lo) * (H - p.t - p.b);
    const grid = Array.from({length:5}, (_, index) => {
      const value = hi - (hi - lo) * index / 4, yy = y(value);
      return `<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="rgba(145,166,194,.15)"/><text x="${p.l-9}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value).toLocaleString()}</text>`;
    }).join('');
    const paths = active.map(item => {
      const path = item.points.map((row, index) => `${index ? 'L' : 'M'} ${x(row.time).toFixed(1)} ${y(row.value).toFixed(1)}`).join(' ');
      const dots = item.points.map((row, index) => `<circle cx="${x(row.time)}" cy="${y(row.value)}" r="${index === item.points.length-1 ? 4.3 : 2.6}" fill="${item.color}"/>`).join('');
      return `<path d="${path}" fill="none" stroke="${item.color}" stroke-width="${['v10','v14','v15'].includes(item.id) ? 3.5 : 2.5}" stroke-linecap="round" stroke-linejoin="round"/>${dots}`;
    }).join('');
    const ends = active.map(item => {
      const last = item.points.at(-1);
      return {item, last, rawY:y(last.value), labelY:y(last.value)};
    }).sort((a,b) => a.rawY-b.rawY);
    ends.forEach((row,index) => {
      row.labelY = Math.max(p.t+10, Math.min(H-p.b-6, row.rawY));
      if (index && row.labelY - ends[index-1].labelY < 17) row.labelY = ends[index-1].labelY + 17;
    });
    for (let index=ends.length-2; index>=0; index--) {
      if (ends[index+1].labelY > H-p.b-6) ends[index+1].labelY = H-p.b-6;
      if (ends[index+1].labelY - ends[index].labelY < 17) ends[index].labelY = ends[index+1].labelY - 17;
    }
    const labels = ends.map(({item,last,labelY}) => `<text x="${W-p.r+9}" y="${labelY}" fill="${item.color}" font-size="10.5" font-weight="900">${item.short} ${money(last.value)}</text>`).join('');
    model.geometry = {W,H,p,minX,maxX,x,y,active};
    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Live prospective paper equity for V10, V14, V15, V8 control and SPY">${grid}<line x1="${p.l}" y1="${y(START)}" x2="${W-p.r}" y2="${y(START)}" stroke="rgba(242,246,255,.36)" stroke-dasharray="5 6"/>${paths}${labels}<line data-olp-guide x1="0" y1="${p.t}" x2="0" y2="${H-p.b}" stroke="rgba(242,246,255,.55)" stroke-dasharray="3 4" opacity="0"/><text x="${p.l}" y="${H-11}" fill="#91a6c2" font-size="10">${day(minX)}</text><text x="${W-p.r}" y="${H-11}" fill="#91a6c2" text-anchor="end" font-size="10">${day(rawMaxX)}</text></svg>`;
  }

  function hover(event) {
    const card = document.getElementById('overview-live-paper-comparison');
    const host = card?.querySelector('[data-olp-chart]');
    const tip = card?.querySelector('[data-olp-tooltip]');
    const geometry = model?.geometry;
    if (!host || !tip || !geometry) return;
    const rect = host.getBoundingClientRect();
    const svgX = (event.clientX - rect.left) * geometry.W / rect.width;
    const time = geometry.minX + (svgX - geometry.p.l) / (geometry.W - geometry.p.l - geometry.p.r) * (geometry.maxX - geometry.minX);
    const nearest = geometry.active.map(item => {
      const point = item.points.reduce((left, right) => Math.abs(right.time-time) < Math.abs(left.time-time) ? right : left);
      return {item, point};
    });
    const anchor = nearest.reduce((left, right) => Math.abs(right.point.time-time) < Math.abs(left.point.time-time) ? right : left);
    const guideX = geometry.x(anchor.point.time);
    card.querySelector('[data-olp-guide]')?.setAttribute('x1', guideX);
    card.querySelector('[data-olp-guide]')?.setAttribute('x2', guideX);
    card.querySelector('[data-olp-guide]')?.setAttribute('opacity', '1');
    tip.innerHTML = `<strong>${when(anchor.point.time)} · nearest recorded values</strong>${nearest.map(({item,point}) => `<div><span style="color:${item.color}">${item.label}</span><b>${money(point.value)} (${pct(point.value/START-1)})</b></div>`).join('')}`;
    tip.style.left = `${Math.max(125, Math.min(rect.width-125, guideX/geometry.W*rect.width))}px`;
    tip.style.top = `${Math.max(120, Math.min(rect.height-12, event.clientY-rect.top))}px`;
    tip.classList.add('show');
  }

  async function refresh() {
    if (!mount()) return;
    const requests = [
      fetch('/api/v10/cycle3/accelerated-v2', {credentials:'same-origin', cache:'no-store'}),
      fetch('/api/v14/ml-ai', {credentials:'same-origin', cache:'no-store'}),
      fetch('/api/v15/intraday-v7', {credentials:'same-origin', cache:'no-store'}),
    ];
    const results = await Promise.allSettled(requests);
    const payloads = await Promise.all(results.map(async result => {
      if (result.status !== 'fulfilled' || !result.value.ok) return null;
      try { return await result.value.json(); } catch (_) { return null; }
    }));
    const [v10,v14,v15] = payloads;
    const series = [
      ...(v10 ? v10Series(v10) : []),
      ...(v14 ? [v14Series(v14)] : []),
      ...(v15 ? [v15Series(v15)] : []),
    ];
    const order = ['v10','v14','v15','v8','spy'];
    series.sort((left,right) => order.indexOf(left.id)-order.indexOf(right.id));
    model = {series};
    render();
    const failures = payloads.filter(value => !value).length;
    const updated = document.querySelector('[data-olp-updated]');
    if (updated) updated.textContent = failures
      ? `${failures} read-only source${failures === 1 ? '' : 's'} unavailable · updated ${when(Date.now())}`
      : `All three paper journals read successfully · updated ${when(Date.now())}`;
  }

  function start() {
    let attempts = 0;
    const ready = () => {
      if (mount()) {
        refresh();
        pollTimer = window.setInterval(refresh, POLL_MS);
      } else if (attempts++ < 80) {
        window.setTimeout(ready, 125);
      }
    };
    ready();
  }

  start();
})();
