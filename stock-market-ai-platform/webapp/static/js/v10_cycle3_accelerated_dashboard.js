(() => {
  const panelId = 'v10-cycle3-accelerated-monitor';
  if (document.getElementById(panelId)) return;

  const anchor = document.getElementById('v10-confirmation-card') ||
    document.getElementById('v8-launch-readiness-card') ||
    document.getElementById('v8-holdout-monitor') ||
    document.querySelector('footer');
  if (!anchor) return;

  const section = document.createElement('section');
  section.id = panelId;
  section.className = 'panel';
  section.style.marginTop = '18px';
  section.innerHTML = `
    <style>
      #${panelId}{overflow:hidden}
      #${panelId} .a10-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
      #${panelId} .a10-head h2{margin-bottom:7px}
      #${panelId} .a10-badge{border:1px solid rgba(54,216,255,.42);border-radius:999px;padding:8px 12px;color:#36d8ff;font-size:12px;font-weight:900;text-align:center;overflow-wrap:anywhere;max-width:100%}
      #${panelId} .a10-badge.alert{border-color:rgba(255,109,109,.5);color:#ff8d8d}
      #${panelId} .a10-boundaries{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:16px}
      #${panelId} .a10-boundary,#${panelId} .a10-metric,#${panelId} .a10-progress-card,#${panelId} .a10-chart-card,#${panelId} .a10-gates{padding:13px;border:1px solid rgba(145,166,194,.17);border-radius:12px;background:rgba(7,16,31,.42)}
      #${panelId} .a10-boundary span,#${panelId} .a10-metric span,#${panelId} .a10-progress-card span{display:block;color:#91a6c2;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      #${panelId} .a10-boundary strong,#${panelId} .a10-metric strong,#${panelId} .a10-progress-card strong{display:block;margin-top:6px;font-size:16px;overflow-wrap:anywhere}
      #${panelId} .a10-progress-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
      #${panelId} .a10-progress{height:8px;margin-top:10px;border-radius:999px;background:rgba(145,166,194,.15);overflow:hidden}
      #${panelId} .a10-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#36d8ff,#39e3a1);border-radius:inherit;transition:width .3s ease}
      #${panelId} .a10-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin-top:14px}
      #${panelId} .a10-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
      #${panelId} .a10-chart-title{font-size:13px;font-weight:900;letter-spacing:.04em;text-transform:uppercase}
      #${panelId} .a10-chart-subtitle{color:#91a6c2;font-size:11px;line-height:1.45;margin-top:5px}
      #${panelId} .a10-chart-host{min-height:240px;margin-top:8px;display:flex;align-items:center;justify-content:center}
      #${panelId} .a10-chart-host svg{display:block;width:100%;height:auto;overflow:visible}
      #${panelId} .a10-placeholder{color:#91a6c2;text-align:center;font-size:12px;line-height:1.55;padding:28px}
      #${panelId} .a10-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:6px;color:#91a6c2;font-size:11px}
      #${panelId} .a10-legend span{display:flex;align-items:center;gap:6px}
      #${panelId} .a10-swatch{width:18px;height:3px;border-radius:3px}
      #${panelId} .a10-gates{margin-top:14px}
      #${panelId} .a10-gates h3{font-size:14px;margin:0 0 10px}
      #${panelId} .a10-gate-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;list-style:none;padding:0;margin:0}
      #${panelId} .a10-gate{display:grid;grid-template-columns:1fr auto;gap:6px 12px;padding:10px;border-radius:9px;background:rgba(145,166,194,.06)}
      #${panelId} .a10-gate span{font-size:12px;font-weight:700}
      #${panelId} .a10-gate small{color:#91a6c2;font-size:10px}
      #${panelId} .a10-gate strong{grid-row:1/3;grid-column:2;font-size:11px;align-self:center;color:#91a6c2}
      #${panelId} .a10-gate.pass strong{color:#39e3a1}
      #${panelId} .a10-gate.fail strong{color:#ff8d8d}
      #${panelId} .a10-ops{margin-top:14px;color:#91a6c2;font-size:12px;line-height:1.6;word-break:break-word}
      #${panelId} .a10-integrity{margin-top:12px;border:1px solid rgba(145,166,194,.17);border-radius:10px;background:rgba(7,16,31,.28)}
      #${panelId} .a10-integrity summary{cursor:pointer;padding:10px 12px;color:#c5d4e8;font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}
      #${panelId} .a10-integrity-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:0 12px 12px}
      #${panelId} .a10-integrity-grid div{min-width:0}
      #${panelId} .a10-integrity-grid span{display:block;color:#91a6c2;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
      #${panelId} .a10-integrity-grid strong{display:block;margin-top:4px;font-size:11px;overflow-wrap:anywhere}
      #${panelId} .a10-alerts{margin-top:8px;color:#ff8d8d}
      @media(max-width:1050px){#${panelId} .a10-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}#${panelId} .a10-charts{grid-template-columns:1fr}}
      @media(max-width:700px){#${panelId} .a10-head{flex-direction:column}#${panelId} .a10-boundaries,#${panelId} .a10-progress-grid,#${panelId} .a10-gate-list,#${panelId} .a10-integrity-grid{grid-template-columns:1fr}#${panelId} .a10-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
    </style>
    <div class="a10-head">
      <div>
        <div class="label">AUTHORIZED PROSPECTIVE PAPER-FORWARD · SEPARATE EVIDENCE LANE</div>
        <h2>V10 Cycle 3 Accelerated Evidence</h2>
        <p class="muted">Frozen <strong>c3_confirm2_blend50</strong> decisions are collected prospectively before January. This panel is read-only and never invokes either V10 runner.</p>
      </div>
      <div class="a10-badge" data-a10-state>LOADING</div>
    </div>
    <div class="a10-boundaries">
      <div class="a10-boundary"><span>First eligible decision</span><strong data-a10-first>—</strong></div>
      <div class="a10-boundary"><span>Last eligible decision</span><strong data-a10-last>—</strong></div>
      <div class="a10-boundary"><span>Independent confirmation</span><strong data-a10-january>—</strong></div>
    </div>
    <div class="a10-progress-grid">
      <div class="a10-progress-card">
        <span>Provisional paper-champion review</span>
        <strong data-a10-provisional>0 / 8 complete blocks</strong>
        <div class="a10-progress" data-a10-provisional-progress role="progressbar" aria-label="Provisional review progress" aria-valuemin="0" aria-valuemax="8" aria-valuenow="0"><i></i></div>
      </div>
      <div class="a10-progress-card">
        <span>Stronger human-review checkpoint</span>
        <strong data-a10-stronger>0 / 12 complete blocks</strong>
        <div class="a10-progress" data-a10-stronger-progress role="progressbar" aria-label="Stronger review progress" aria-valuemin="0" aria-valuemax="12" aria-valuenow="0"><i></i></div>
      </div>
    </div>
    <div class="a10-metrics">
      <div class="a10-metric"><span>Decisions</span><strong data-a10-decisions>—</strong></div>
      <div class="a10-metric"><span>Entries</span><strong data-a10-entries>—</strong></div>
      <div class="a10-metric"><span>Completed exits</span><strong data-a10-exits>—</strong></div>
      <div class="a10-metric"><span>Promotion-scored exits</span><strong data-a10-scored>—</strong></div>
      <div class="a10-metric"><span>Complete five-sleeve blocks</span><strong data-a10-blocks>—</strong></div>
      <div class="a10-metric"><span>Mean complete-block V10 return after modeled cost</span><strong data-a10-return>—</strong></div>
      <div class="a10-metric"><span>Mean paired V10 − V8 edge</span><strong data-a10-v8-edge>—</strong></div>
      <div class="a10-metric"><span>Mean paired V10 − SPY edge</span><strong data-a10-spy-edge>—</strong></div>
      <div class="a10-metric"><span>Max cohort drawdown · V10 / V8</span><strong data-a10-drawdown>—</strong></div>
      <div class="a10-metric"><span>Completed defensive-regime exits</span><strong data-a10-defensive-exits>—</strong></div>
      <div class="a10-metric"><span>Mean defensive V10 − V8 edge</span><strong data-a10-defensive-edge>—</strong></div>
    </div>
    <div class="a10-charts">
      <figure class="a10-chart-card">
        <figcaption><div class="a10-chart-title">Complete-block normalized comparison</div><div class="a10-chart-subtitle">Diagnostic hypothetical $100,000 starting basis for V10, the same-date frozen V8 control, and SPY. Partial sleeves never enter this chart.</div></figcaption>
        <div class="a10-legend"><span><i class="a10-swatch" style="background:#36d8ff"></i>V10 accelerated</span><span><i class="a10-swatch" style="background:#efc56b"></i>V8 control</span><span><i class="a10-swatch" style="background:#a78bfa"></i>SPY</span></div>
        <div class="a10-chart-host" data-a10-equity-chart></div>
      </figure>
      <figure class="a10-chart-card">
        <figcaption><div class="a10-chart-title">Paired edge by complete block</div><div class="a10-chart-subtitle">Percentage-point return difference. The zero line separates positive and negative paired evidence.</div></figcaption>
        <div class="a10-legend"><span><i class="a10-swatch" style="background:#39e3a1"></i>V10 − V8</span><span><i class="a10-swatch" style="background:#ff7ad9"></i>V10 − SPY</span></div>
        <div class="a10-chart-host" data-a10-edge-chart></div>
      </figure>
    </div>
    <div class="a10-gates">
      <h3>Preregistered promotion gates</h3>
      <ul class="a10-gate-list" data-a10-gates><li class="a10-placeholder">Loading gate status…</li></ul>
    </div>
    <div class="a10-ops" data-a10-method>Loading accelerated evidence integrity…</div>
    <details class="a10-integrity">
      <summary>Data integrity &amp; authority</summary>
      <div class="a10-integrity-grid">
        <div><span>Frozen SHA-256</span><strong data-a10-frozen-sha>—</strong></div>
        <div><span>Contract SHA-256</span><strong data-a10-contract-sha>—</strong></div>
        <div><span>Paper only</span><strong data-a10-paper>YES</strong></div>
        <div><span>Automatic promotion</span><strong data-a10-auto-promotion>NO</strong></div>
        <div><span>Human review</span><strong data-a10-human-review>YES</strong></div>
        <div><span>Brokerage orders</span><strong data-a10-brokerage>OFF</strong></div>
        <div><span>Runner invoked by dashboard</span><strong data-a10-runner>NO</strong></div>
        <div><span>January evidence modified</span><strong data-a10-january-modified>NO</strong></div>
      </div>
    </details>
    <div class="a10-alerts" data-a10-alerts hidden></div>
  `;

  const original = document.getElementById('v10-confirmation-card');
  if (original) original.insertAdjacentElement('beforebegin', section);
  else anchor.insertAdjacentElement('afterend', section);

  const set = (selector, value) => {
    const node = section.querySelector(selector);
    if (node) node.textContent = value;
  };
  const statusText = value => String(value || 'UNKNOWN').replaceAll('_', ' ');
  const pct = value => value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`;
  const unsignedPct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
  const dateOnly = value => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'UTC'});
  };
  const progress = (selector, value, goal) => {
    const node = section.querySelector(selector);
    if (!node) return;
    const completed = Math.max(0, Number(value) || 0);
    node.setAttribute('aria-valuenow', String(Math.min(completed, goal)));
    const bar = node.querySelector('i');
    if (bar) bar.style.width = `${Math.min(100, completed / goal * 100)}%`;
  };
  const svgLine = (points, color, width=3) => `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linejoin="round" stroke-linecap="round"/>`;

  function renderEquity(curve) {
    const host = section.querySelector('[data-a10-equity-chart]');
    if (!host) return;
    const rows = Array.isArray(curve) ? curve.filter(row => Number.isFinite(Number(row.v10_normalized)) && Number.isFinite(Number(row.v8_normalized)) && Number.isFinite(Number(row.spy_normalized))) : [];
    if (rows.length < 2) {
      host.innerHTML = '<div class="a10-placeholder">The first point appears after one exit from each of the five cohort sleeves forms a complete block.</div>';
      return;
    }
    const W=920,H=260,p={l:66,r:24,t:18,b:38};
    const values=rows.flatMap(row=>[Number(row.v10_normalized),Number(row.v8_normalized),Number(row.spy_normalized)]);
    let lo=Math.min(...values,NORMALIZED_BASE),hi=Math.max(...values,NORMALIZED_BASE);
    const span=Math.max(hi-lo,200);lo-=span*.14;hi+=span*.14;
    const x=index=>p.l+(W-p.l-p.r)*index/(rows.length-1);
    const y=value=>p.t+(H-p.t-p.b)*(1-(value-lo)/(hi-lo));
    const points=key=>rows.map((row,index)=>`${x(index)},${y(Number(row[key]))}`).join(' ');
    const grid=[0,.25,.5,.75,1].map(ratio=>{
      const value=lo+(hi-lo)*(1-ratio),yy=p.t+(H-p.t-p.b)*ratio;
      return `<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="#60708a" opacity=".2"/><text x="${p.l-8}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value/1000)}k</text>`;
    }).join('');
    const labels=rows.map((row,index)=>`<text x="${x(index)}" y="${H-12}" fill="#91a6c2" font-size="10" text-anchor="middle">${row.block}</text>`).join('');
    const dots=[
      ['v10_normalized','#36d8ff','V10 accelerated'],
      ['v8_normalized','#efc56b','V8 control'],
      ['spy_normalized','#a78bfa','SPY'],
    ];
    const dotMarkup=dots.map(([key,color,label])=>rows.slice(1).map((row,offset)=>`<circle cx="${x(offset+1)}" cy="${y(Number(row[key]))}" r="3.5" fill="${color}"><title>${label} · Block ${row.block}: $${Math.round(Number(row[key])).toLocaleString()}</title></circle>`).join('')).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Complete-block V10, V8 control and SPY normalized comparison">${grid}<line x1="${p.l}" y1="${y(NORMALIZED_BASE)}" x2="${W-p.r}" y2="${y(NORMALIZED_BASE)}" stroke="#91a6c2" stroke-dasharray="5 5" opacity=".55"/>${svgLine(points('v10_normalized'),'#36d8ff',3.2)}${svgLine(points('v8_normalized'),'#efc56b',2.7)}${svgLine(points('spy_normalized'),'#a78bfa',2.7)}${dotMarkup}${labels}<text x="${(p.l+W-p.r)/2}" y="${H-1}" fill="#91a6c2" font-size="10" text-anchor="middle">Complete five-sleeve block</text></svg>`;
  }

  function renderEdges(edges) {
    const host = section.querySelector('[data-a10-edge-chart]');
    if (!host) return;
    const rows = Array.isArray(edges) ? edges.filter(row => Number.isFinite(Number(row.v10_minus_v8)) && Number.isFinite(Number(row.v10_minus_spy))) : [];
    if (!rows.length) {
      host.innerHTML = '<div class="a10-placeholder">Paired V10−V8 and V10−SPY bars appear when the first complete block closes.</div>';
      return;
    }
    const W=920,H=260,p={l:64,r:22,t:18,b:40};
    const maxAbs=Math.max(.001,...rows.flatMap(row=>[Math.abs(Number(row.v10_minus_v8)),Math.abs(Number(row.v10_minus_spy))]));
    const y=value=>p.t+(H-p.t-p.b)*(maxAbs-value)/(2*maxAbs);
    const zero=y(0),group=(W-p.l-p.r)/rows.length,barWidth=Math.min(24,group*.28);
    const ticks=[maxAbs,maxAbs/2,0,-maxAbs/2,-maxAbs].map(value=>`<line x1="${p.l}" y1="${y(value)}" x2="${W-p.r}" y2="${y(value)}" stroke="#60708a" opacity="${value === 0 ? .65 : .2}" ${value===0?'stroke-width="1.5"':''}/><text x="${p.l-8}" y="${y(value)+4}" fill="#91a6c2" font-size="10" text-anchor="end">${(value*100).toFixed(1)}%</text>`).join('');
    const bars=rows.map((row,index)=>{
      const center=p.l+group*(index+.5),values=[[Number(row.v10_minus_v8),'#39e3a1','V10 − V8'],[Number(row.v10_minus_spy),'#ff7ad9','V10 − SPY']];
      const rects=values.map(([value,color,label],seriesIndex)=>{
        const top=Math.min(zero,y(value)),height=Math.max(1,Math.abs(zero-y(value))),x=center+(seriesIndex===0?-barWidth-2:2);
        return `<rect x="${x}" y="${top}" width="${barWidth}" height="${height}" rx="2" fill="${color}"><title>${label} · Block ${row.block}: ${(value*100).toFixed(2)} percentage points</title></rect>`;
      }).join('');
      return `${rects}<text x="${center}" y="${H-14}" fill="#91a6c2" font-size="10" text-anchor="middle">${row.block}</text>`;
    }).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Paired V10 edge versus V8 and SPY by complete block">${ticks}${bars}<text x="${(p.l+W-p.r)/2}" y="${H-1}" fill="#91a6c2" font-size="10" text-anchor="middle">Complete five-sleeve block</text></svg>`;
  }

  function renderGates(gates) {
    const list = section.querySelector('[data-a10-gates]');
    if (!list) return;
    list.replaceChildren();
    (Array.isArray(gates) ? gates : []).forEach(gate => {
      const item=document.createElement('li');
      item.className=`a10-gate ${gate.passed===true?'pass':gate.passed===false?'fail':'waiting'}`;
      const label=document.createElement('span');label.textContent=gate.label || gate.id;
      const detail=document.createElement('small');
      let observed='Awaiting eligible evidence';
      if (gate.id==='operations') observed=gate.observed===true?'PASS':'ALERT';
      else if (gate.id==='defensive_count') observed=`${Number(gate.observed)||0} observed`;
      else if (gate.observed!=null) observed=pct(gate.observed);
      detail.textContent=`${gate.requirement} · ${observed} · target ${gate.target}`;
      const state=document.createElement('strong');state.textContent=gate.passed===true?'PASS':gate.passed===false?'BLOCKED':'WAITING';
      item.append(label,detail,state);list.appendChild(item);
    });
    if (!list.children.length) list.innerHTML='<li class="a10-placeholder">Gate status unavailable.</li>';
  }

  const NORMALIZED_BASE=100000;
  fetch('/api/v10/cycle3/accelerated',{credentials:'same-origin'})
    .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();})
    .then(data=>{
      const blocks=Number(data.complete_five_sleeve_blocks)||0;
      const provisional=Number(data.minimum_blocks_for_provisional_review)||8;
      const stronger=Number(data.minimum_blocks_for_stronger_review)||12;
      const badge=section.querySelector('[data-a10-state]');
      if (badge) {
        badge.textContent=statusText(data.status);
        badge.classList.toggle('alert',data.operational_integrity!==true);
      }
      set('[data-a10-first]',dateOnly(data.first_decision_session_utc));
      set('[data-a10-last]',dateOnly(data.last_decision_session_utc));
      set('[data-a10-january]',`${dateOnly(data.independent_confirmation_start_utc)} · unchanged`);
      set('[data-a10-provisional]',`${blocks} / ${provisional} complete blocks${data.provisional_review_eligible?' · REVIEW ELIGIBLE':''}`);
      set('[data-a10-stronger]',`${blocks} / ${stronger} complete blocks${data.stronger_review_eligible?' · REVIEW ELIGIBLE':''}`);
      progress('[data-a10-provisional-progress]',blocks,provisional);
      progress('[data-a10-stronger-progress]',blocks,stronger);
      set('[data-a10-decisions]',data.decisions ?? 0);
      set('[data-a10-entries]',data.entries ?? 0);
      set('[data-a10-exits]',data.completed_exits ?? 0);
      set('[data-a10-scored]',data.promotion_scored_exits ?? 0);
      set('[data-a10-blocks]',blocks);
      set('[data-a10-return]',pct(data.mean_net_return_after_cost));
      set('[data-a10-v8-edge]',pct(data.mean_v10_minus_v8_net_return));
      set('[data-a10-spy-edge]',pct(data.mean_v10_minus_spy_return));
      set('[data-a10-drawdown]',data.v10_max_cohort_drawdown==null?'—':`${unsignedPct(data.v10_max_cohort_drawdown)} / ${unsignedPct(data.v8_max_cohort_drawdown)}`);
      set('[data-a10-defensive-exits]',data.completed_defensive_exits ?? 0);
      set('[data-a10-defensive-edge]',pct(data.mean_defensive_v10_minus_v8_net_return));
      renderEquity(data.block_curve);
      renderEdges(data.block_edges);
      renderGates(data.promotion_gates);
      const checked=data.operational_checked_at_utc?new Date(data.operational_checked_at_utc).toLocaleString():'not yet published';
      set('[data-a10-method]',`${data.method_note} Evidence: ${statusText(data.evidence_status)}. Operations: ${statusText(data.operational_status)} · checked ${checked} · scheduler every ${Math.round((Number(data.scheduler_interval_seconds)||300)/60)} minutes.`);
      set('[data-a10-frozen-sha]',data.frozen_sha256 || '—');
      set('[data-a10-contract-sha]',data.contract_sha256 || '—');
      set('[data-a10-paper]',data.paper_trading_only === true ? 'YES' : 'NO');
      set('[data-a10-auto-promotion]',data.automatic_promotion === true ? 'YES' : 'NO');
      set('[data-a10-human-review]',data.human_review_required === true ? 'YES' : 'NO');
      set('[data-a10-brokerage]',data.brokerage_orders === true ? 'ON' : 'OFF');
      set('[data-a10-runner]',data.runner_invoked === true ? 'YES' : 'NO');
      set('[data-a10-january-modified]',data.january_confirmation_modified === true ? 'YES' : 'NO');
      const alerts=section.querySelector('[data-a10-alerts]');
      const failures=Array.isArray(data.operational_failures)?data.operational_failures:[];
      if (alerts) { alerts.hidden=!failures.length; alerts.textContent=failures.length?`Active integrity alerts: ${failures.join(' · ')}`:''; }
    })
    .catch(error=>{
      set('[data-a10-state]','STATUS UNAVAILABLE');
      const badge=section.querySelector('[data-a10-state]');if(badge)badge.classList.add('alert');
      set('[data-a10-method]',`The accelerated read-only endpoint could not be reached. No runner was invoked. ${error.message}`);
    });
})();
