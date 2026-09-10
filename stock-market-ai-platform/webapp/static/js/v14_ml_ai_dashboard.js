(() => {
  const panelId = 'v14-ml-ai-dashboard';
  const API = '/api/v14/ml-ai';
  const STARTING_EQUITY = 100000;
  let refreshTimer = null;

  const escapeHtml = value => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const statusText = value => String(value || 'UNKNOWN').replaceAll('_', ' ');
  const number = value => value == null || !Number.isFinite(Number(value)) ? null : Number(value);
  const integer = value => number(value) == null ? '—' : Math.round(Number(value)).toLocaleString();
  const pct = (value, digits=2) => number(value) == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(digits)}%`;
  const plainPct = (value, digits=2) => number(value) == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`;
  const money = value => number(value) == null ? '—' : Number(value).toLocaleString(undefined, {style:'currency', currency:'USD', minimumFractionDigits:2, maximumFractionDigits:2});
  const decimal = (value, digits=4) => number(value) == null ? '—' : Number(value).toFixed(digits);
  const shortSha = value => value ? `${String(value).slice(0,12)}…${String(value).slice(-8)}` : 'Not recorded yet';
  const dateOnly = value => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric', timeZone:'UTC'});
  };
  const dateTime = value => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZone:'America/Los_Angeles', timeZoneName:'short'});
  };

  function mount(attempt=0) {
    if (document.getElementById(panelId)) return;
    const target = document.querySelector('[data-research-content="v14"]');
    if (!target) {
      if (attempt < 20) window.setTimeout(() => mount(attempt + 1), 50);
      return;
    }
    const section = document.createElement('section');
    section.id = panelId;
    section.className = 'v14-lab';
    section.innerHTML = `
      <style>
        #${panelId}{--v14-cyan:#36d8ff;--v14-green:#39e3a1;--v14-purple:#a78bfa;--v14-pink:#ff7ad9;--v14-gold:#efc56b;--v14-red:#ff758f;display:flex;flex-direction:column;gap:16px;min-width:0}
        #${panelId} .v14-card{border:1px solid rgba(120,155,205,.19);border-radius:18px;background:linear-gradient(145deg,rgba(12,29,50,.92),rgba(6,17,32,.94));padding:18px;min-width:0;box-shadow:0 16px 38px rgba(0,0,0,.13)}
        #${panelId} .v14-hero{position:relative;overflow:hidden;border-color:rgba(54,216,255,.29);background:radial-gradient(circle at 88% -18%,rgba(167,139,250,.24),transparent 42%),radial-gradient(circle at 12% 112%,rgba(57,227,161,.16),transparent 38%),linear-gradient(145deg,rgba(10,37,56,.98),rgba(7,16,31,.97))}
        #${panelId} .v14-hero:after{content:'';position:absolute;inset:0;pointer-events:none;background:linear-gradient(110deg,transparent 0 57%,rgba(54,216,255,.045) 57% 58%,transparent 58% 64%,rgba(167,139,250,.045) 64% 65%,transparent 65%)}
        #${panelId} .v14-head{position:relative;z-index:1;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
        #${panelId} h2,#${panelId} h3{margin:5px 0 7px}#${panelId} p{line-height:1.55}
        #${panelId} .v14-badge{max-width:300px;padding:9px 13px;border:1px solid rgba(57,227,161,.42);border-radius:999px;background:rgba(57,227,161,.07);color:var(--v14-green);font-size:.75rem;font-weight:900;text-align:center;overflow-wrap:anywhere}
        #${panelId} .v14-badge.waiting{color:var(--v14-gold);border-color:rgba(239,197,107,.4);background:rgba(239,197,107,.07)}
        #${panelId} .v14-badge.alert{color:var(--v14-red);border-color:rgba(255,117,143,.45);background:rgba(255,117,143,.07)}
        #${panelId} .v14-flow{position:relative;z-index:1;display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:15px}
        #${panelId} .v14-flow span{padding:7px 10px;border:1px solid rgba(54,216,255,.2);border-radius:999px;background:rgba(54,216,255,.055);font-size:.7rem;font-weight:850;letter-spacing:.035em}
        #${panelId} .v14-flow i{color:#7890ad;font-style:normal}
        #${panelId} .v14-grid{display:grid;gap:12px;min-width:0}#${panelId} .v14-metrics{grid-template-columns:repeat(6,minmax(0,1fr))}
        #${panelId} .v14-metric{padding:13px;border:1px solid rgba(120,155,205,.15);border-radius:13px;background:rgba(4,13,25,.36);min-width:0}
        #${panelId} .v14-metric span{display:block;color:#91a6c2;font-size:.65rem;font-weight:850;letter-spacing:.065em;text-transform:uppercase;line-height:1.4}
        #${panelId} .v14-metric strong{display:block;margin-top:6px;font-size:1rem;line-height:1.35;overflow-wrap:anywhere}
        #${panelId} .positive{color:var(--v14-green)}#${panelId} .negative{color:var(--v14-red)}
        #${panelId} .v14-split{display:grid;grid-template-columns:minmax(270px,.46fr) minmax(0,1.54fr);gap:14px}
        #${panelId} .v14-equity{font-size:clamp(2.15rem,4vw,3.4rem);font-weight:950;letter-spacing:-.04em;margin-top:8px}
        #${panelId} .v14-return{font-size:1.05rem;font-weight:900;margin-top:2px}
        #${panelId} .v14-sub{color:#91a6c2;font-size:.76rem;line-height:1.55;margin-top:8px}
        #${panelId} .v14-mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}
        #${panelId} .v14-chart-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
        #${panelId} .v14-chart-title{font-size:.78rem;font-weight:900;letter-spacing:.055em;text-transform:uppercase}
        #${panelId} .v14-chart-sub{margin-top:4px;color:#91a6c2;font-size:.72rem;line-height:1.45}
        #${panelId} .v14-legend{display:flex;gap:12px;flex-wrap:wrap;color:#91a6c2;font-size:.7rem}
        #${panelId} .v14-legend span{display:flex;align-items:center;gap:5px}#${panelId} .v14-legend i{display:block;width:16px;height:3px;border-radius:3px}
        #${panelId} .v14-chart-stage{position:relative;height:315px;margin-top:7px}#${panelId} .v14-chart-host,#${panelId} .v14-chart-host svg{display:block;width:100%;height:100%}
        #${panelId} .v14-tooltip{position:absolute;display:none;pointer-events:none;min-width:205px;padding:10px 12px;border:1px solid rgba(54,216,255,.32);border-radius:10px;background:#071525;box-shadow:0 12px 30px rgba(0,0,0,.4);font-size:.7rem;z-index:5;transform:translate(-50%,-100%)}
        #${panelId} .v14-tooltip.show{display:block}#${panelId} .v14-tooltip strong{display:block;margin-bottom:5px}#${panelId} .v14-tooltip div{display:flex;justify-content:space-between;gap:18px;margin-top:3px}
        #${panelId} .v14-progress-grid{grid-template-columns:1fr 1fr}#${panelId} .v14-progress{height:8px;margin-top:9px;border-radius:99px;background:rgba(120,155,205,.14);overflow:hidden}
        #${panelId} .v14-progress i{display:block;width:0;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--v14-purple),var(--v14-cyan),var(--v14-green));transition:width .3s ease}
        #${panelId} .v14-charts{grid-template-columns:1fr 1fr}#${panelId} .v14-chart-box{min-width:0}#${panelId} .v14-small-chart{min-height:285px;margin-top:10px;display:flex;align-items:center;justify-content:center;overflow-x:auto}
        #${panelId} .v14-small-chart svg{display:block;width:100%;height:auto;min-width:520px}
        #${panelId} .v14-empty{width:100%;padding:34px 18px;color:#91a6c2;text-align:center;font-size:.78rem;line-height:1.6;border:1px dashed rgba(120,155,205,.2);border-radius:13px;background:rgba(4,13,25,.2)}
        #${panelId} .v14-table-wrap{overflow:auto;max-height:500px;margin-top:12px;border:1px solid rgba(120,155,205,.13);border-radius:12px}
        #${panelId} table{min-width:720px}#${panelId} th{position:sticky;top:0;z-index:2;background:#0b1c31}#${panelId} td,#${panelId} th{font-size:.75rem}
        #${panelId} tr.selected{background:rgba(57,227,161,.055)}#${panelId} .v14-prob{font-weight:900;color:var(--v14-cyan)}
        #${panelId} .v14-pill{display:inline-block;padding:4px 7px;border-radius:999px;border:1px solid rgba(120,155,205,.2);font-size:.64rem;font-weight:900;white-space:nowrap}
        #${panelId} .v14-pill.top{color:var(--v14-green);border-color:rgba(57,227,161,.3);background:rgba(57,227,161,.06)}
        #${panelId} .v14-section-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-end}#${panelId} .v14-section-head p{margin:0;max-width:720px}
        #${panelId} .v14-integrity{border:1px solid rgba(120,155,205,.17);border-radius:13px;background:rgba(4,13,25,.25)}
        #${panelId} .v14-integrity summary{cursor:pointer;padding:13px 15px;font-size:.76rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase}
        #${panelId} .v14-integrity .v14-grid{padding:0 14px 14px;grid-template-columns:repeat(4,minmax(0,1fr))}
        #${panelId} .v14-method{padding:14px;border-left:3px solid var(--v14-purple);border-radius:0 11px 11px 0;background:rgba(167,139,250,.06);color:#b8c7da;font-size:.78rem;line-height:1.65}
        @media(max-width:1100px){#${panelId} .v14-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}#${panelId} .v14-split,#${panelId} .v14-charts{grid-template-columns:1fr}}
        @media(max-width:700px){#${panelId} .v14-head,#${panelId} .v14-chart-head,#${panelId} .v14-section-head{flex-direction:column;align-items:flex-start}#${panelId} .v14-metrics,#${panelId} .v14-progress-grid,#${panelId} .v14-integrity .v14-grid{grid-template-columns:1fr 1fr}#${panelId} .v14-mini-grid{grid-template-columns:1fr}#${panelId} .v14-chart-stage{height:280px}}
        @media(max-width:440px){#${panelId} .v14-metrics,#${panelId} .v14-progress-grid,#${panelId} .v14-integrity .v14-grid{grid-template-columns:1fr}}
      </style>
      <section class="v14-card v14-hero">
        <div class="v14-head"><div><div class="label">GENUINE TRAINED MACHINE LEARNING · ISOLATED PAPER-FORWARD LANE</div><h2>V14 Logistic Regression Intelligence</h2><p class="muted">Every eligible session retrains from historical labels, records the learned model, ranks the frozen 100-stock universe, and follows an auditable Top-10 paper portfolio.</p></div><div class="v14-badge waiting" data-v14-state>LOADING MODEL STATE</div></div>
        <div class="v14-flow" aria-label="V14 machine learning lifecycle"><span>101 synchronized datasets</span><i>→</i><span>5-session purge</span><i>→</i><span>logistic training</span><i>→</i><span>100 probabilities</span><i>→</i><span>Top 10 paper portfolio</span><i>→</i><span>5-session outcome</span></div>
      </section>
      <section class="v14-grid v14-metrics">
        <div class="v14-metric"><span>Model class</span><strong data-v14-model>—</strong></div><div class="v14-metric"><span>Target</span><strong data-v14-target>—</strong></div><div class="v14-metric"><span>Features</span><strong data-v14-features>—</strong></div><div class="v14-metric"><span>Universe</span><strong data-v14-universe>—</strong></div><div class="v14-metric"><span>Forward boundary</span><strong data-v14-boundary>—</strong></div><div class="v14-metric"><span>Next lifecycle event</span><strong data-v14-next>—</strong></div>
      </section>
      <section class="v14-card v14-split">
        <div><div class="label">CURRENT V14 PAPER EQUITY</div><div class="v14-equity" data-v14-equity>$100,000.00</div><div class="v14-return" data-v14-return>WAITING FOR FIRST POSITION</div><div class="v14-sub" data-v14-equity-note>Fresh forward results only. No reconstructed history is mixed into this value.</div><div class="v14-mini-grid"><div class="v14-metric"><span>SPY equivalent</span><strong data-v14-spy-equity>—</strong></div><div class="v14-metric"><span>Excess vs SPY</span><strong data-v14-excess>—</strong></div><div class="v14-metric"><span>Open cohorts</span><strong data-v14-open>—</strong></div><div class="v14-metric"><span>Priced cohorts</span><strong data-v14-priced>—</strong></div></div></div>
        <div><div class="v14-chart-head"><div><div class="v14-chart-title">Interactive paper-forward performance</div><div class="v14-chart-sub">V14 and SPY share a normalized $100,000 starting basis. Current marks are labeled separately from completed evidence.</div></div><div class="v14-legend"><span><i style="background:#36d8ff"></i>V14 ML</span><span><i style="background:#a78bfa"></i>SPY</span></div></div><div class="v14-chart-stage"><div class="v14-chart-host" data-v14-equity-chart></div><div class="v14-tooltip" data-v14-tooltip></div></div></div>
      </section>
      <section class="v14-grid v14-progress-grid">
        <div class="v14-card v14-metric"><span>Next complete five-sleeve block</span><strong data-v14-progress-block>0 / 5 sleeves</strong><div class="v14-progress" data-v14-bar-block role="progressbar" aria-valuemin="0" aria-valuemax="5" aria-valuenow="0"><i></i></div><div class="v14-sub" data-v14-blocks>0 complete blocks recorded</div></div>
        <div class="v14-card v14-metric"><span>Decision authority</span><strong>HUMAN REVIEW REQUIRED</strong><div class="v14-sub">No evidence count can automatically promote V14 or enable brokerage orders.</div></div>
      </section>
      <section class="v14-grid v14-metrics">
        <div class="v14-metric"><span>Decisions</span><strong data-v14-decisions>—</strong></div><div class="v14-metric"><span>Entries</span><strong data-v14-entries>—</strong></div><div class="v14-metric"><span>Completed exits</span><strong data-v14-exits>—</strong></div><div class="v14-metric"><span>Relative hit rate</span><strong data-v14-hit>—</strong></div><div class="v14-metric"><span>Maximum drawdown</span><strong data-v14-drawdown>—</strong></div><div class="v14-metric"><span>Diagnostic Sharpe</span><strong data-v14-sharpe>—</strong></div>
      </section>
      <section class="v14-grid v14-charts">
        <article class="v14-card v14-chart-box"><div class="v14-chart-title">Learned standardized coefficients</div><div class="v14-chart-sub">Positive weights increase the modeled probability of a higher close five sessions later; negative weights decrease it. Magnitude shows influence after standardization.</div><div class="v14-small-chart" data-v14-coefficients></div></article>
        <article class="v14-card v14-chart-box"><div class="v14-chart-title">Latest prediction ranking</div><div class="v14-chart-sub">Highest modeled five-session up probabilities. Probabilities rank candidates; they do not guarantee returns.</div><div class="v14-small-chart" data-v14-probabilities></div></article>
      </section>
      <section class="v14-card"><div class="v14-section-head"><div><div class="label">LATEST TRAINING SNAPSHOT</div><h3>What the model learned and when</h3></div><p class="muted">The recorded cutoff and purge gap prove that future labels were unavailable during training.</p></div><div class="v14-grid v14-metrics" style="margin-top:13px"><div class="v14-metric"><span>Training rows</span><strong data-v14-training-rows>—</strong></div><div class="v14-metric"><span>Positive-label rate</span><strong data-v14-positive-rate>—</strong></div><div class="v14-metric"><span>Training start</span><strong data-v14-training-start>—</strong></div><div class="v14-metric"><span>Training cutoff</span><strong data-v14-training-cutoff>—</strong></div><div class="v14-metric"><span>Purge gap</span><strong data-v14-purge>—</strong></div><div class="v14-metric"><span>Model snapshot</span><strong data-v14-model-sha>—</strong></div></div></section>
      <section class="v14-card"><div class="v14-section-head"><div><div class="label">100-STOCK ML RANKING BOARD</div><h3>Predicted five-session direction probabilities</h3></div><p class="muted" data-v14-ranking-note>Waiting for the first prospectively trained model.</p></div><div class="v14-table-wrap" data-v14-rankings></div></section>
      <section class="v14-card"><div class="v14-section-head"><div><div class="label">OPEN PAPER POSITIONS</div><h3>Entry-to-current mark</h3></div><p class="muted">Read-only marks never create or modify evidence.</p></div><div class="v14-table-wrap" data-v14-positions></div></section>
      <section class="v14-card"><div class="v14-section-head"><div><div class="label">APPEND-ONLY LIFECYCLE</div><h3>Decision, entry, and exit journal</h3></div><p class="muted">Each event remains tied to its decision session, cohort sleeve, contract, and learned model identity.</p></div><div class="v14-table-wrap" data-v14-events></div></section>
      <details class="v14-integrity" open><summary>Data integrity, model lineage &amp; authority</summary><div class="v14-grid"><div class="v14-metric"><span>Data readiness</span><strong data-v14-readiness>—</strong></div><div class="v14-metric"><span>Feature backend</span><strong data-v14-backend>—</strong></div><div class="v14-metric"><span>Feature session</span><strong data-v14-feature-session>—</strong></div><div class="v14-metric"><span>Required symbols</span><strong data-v14-required>—</strong></div><div class="v14-metric"><span>Contract SHA-256</span><strong data-v14-contract-sha>—</strong></div><div class="v14-metric"><span>Paper trading only</span><strong data-v14-paper>YES</strong></div><div class="v14-metric"><span>Brokerage orders</span><strong data-v14-brokerage>OFF</strong></div><div class="v14-metric"><span>Automatic promotion</span><strong data-v14-promotion>NO</strong></div><div class="v14-metric"><span>Human review</span><strong data-v14-review>YES</strong></div><div class="v14-metric"><span>Dashboard invoked runner</span><strong data-v14-runner>NO</strong></div><div class="v14-metric"><span>V8 / V10 modified</span><strong data-v14-isolation>NO / NO</strong></div><div class="v14-metric"><span>Scheduled network requests</span><strong data-v14-network>0</strong></div></div></details>
      <div class="v14-method" data-v14-method>Loading the frozen V14 research contract.</div>
    `;
    target.appendChild(section);
    wireChartPointer(section);
    load(section);
  }

  function set(section, selector, value) {
    const node = section.querySelector(selector);
    if (node) node.textContent = value;
  }
  function tone(section, selector, value) {
    const node = section.querySelector(selector);
    if (!node) return;
    node.classList.remove('positive','negative');
    if (number(value) != null) node.classList.add(Number(value) < 0 ? 'negative' : 'positive');
  }
  function progress(section, selector, value, goal) {
    const node = section.querySelector(selector);
    if (!node) return;
    const completed = Math.max(0, Number(value) || 0);
    node.setAttribute('aria-valuenow', String(Math.min(goal, completed)));
    const bar = node.querySelector('i');
    if (bar) bar.style.width = `${Math.min(100, completed / goal * 100)}%`;
  }

  function renderEquity(section, payload) {
    const host = section.querySelector('[data-v14-equity-chart]');
    const raw = Array.isArray(payload.curve) ? payload.curve : [];
    const rows = raw.filter(row => number(row.v14_normalized) != null);
    if (!rows.length) {
      host.innerHTML = '<div class="v14-empty">The chart begins with the first paper entry. Completed exits remain the official evidence; live marks are provisional and clearly labeled.</div>';
      host.dataset.points = '[]';
      return;
    }
    const baselineTime = new Date(payload.paper_forward_start_utc || Date.now()).getTime();
    const points = [{timestamp_utc:payload.paper_forward_start_utc, time:baselineTime, v14:STARTING_EQUITY, spy:STARTING_EQUITY, event:'FORWARD_BOUNDARY'}];
    rows.forEach(row => {
      const time = new Date(row.timestamp_utc || Date.now()).getTime();
      const v14 = number(row.v14_normalized), spy = number(row.spy_normalized);
      if (Number.isFinite(time) && v14 != null) points.push({timestamp_utc:row.timestamp_utc,time,v14,spy,event:row.event || 'EVIDENCE'});
    });
    const W=940,H=315,p={l:70,r:24,t:20,b:39};
    const values=points.flatMap(row=>[row.v14,row.spy].filter(value=>value!=null));
    let lo=Math.min(STARTING_EQUITY,...values),hi=Math.max(STARTING_EQUITY,...values);const span=Math.max(hi-lo,250);lo-=span*.14;hi+=span*.14;
    const minTime=Math.min(...points.map(row=>row.time)),maxTime=Math.max(...points.map(row=>row.time));
    const x=value=>p.l+(W-p.l-p.r)*(maxTime===minTime?0:(value-minTime)/(maxTime-minTime));
    const y=value=>p.t+(H-p.t-p.b)*(1-(value-lo)/(hi-lo));
    const grid=[0,.25,.5,.75,1].map(ratio=>{const value=hi-(hi-lo)*ratio,yy=p.t+(H-p.t-p.b)*ratio;return `<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="#60708a" opacity=".2"/><text x="${p.l-8}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value/1000)}k</text>`}).join('');
    const line=key=>points.filter(row=>row[key]!=null).map(row=>`${x(row.time)},${y(row[key])}`).join(' ');
    const dots=points.map((row,index)=>`<circle cx="${x(row.time)}" cy="${y(row.v14)}" r="${index===points.length-1?4.5:3}" fill="#36d8ff" data-v14-point="${index}"/><circle cx="${x(row.time)}" cy="${y(row.spy ?? STARTING_EQUITY)}" r="3" fill="#a78bfa" data-v14-point="${index}" opacity=".9"/>`).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="V14 paper-forward equity compared with SPY">${grid}<line x1="${p.l}" y1="${y(STARTING_EQUITY)}" x2="${W-p.r}" y2="${y(STARTING_EQUITY)}" stroke="#91a6c2" stroke-dasharray="5 5" opacity=".55"/><polyline points="${line('v14')}" fill="none" stroke="#36d8ff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="${line('spy')}" fill="none" stroke="#a78bfa" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"/>${dots}<text x="${(p.l+W-p.r)/2}" y="${H-4}" fill="#91a6c2" font-size="10" text-anchor="middle">Fresh paper-forward lifecycle</text></svg>`;
    host.dataset.points=JSON.stringify(points.map(row=>({...row,x:x(row.time),y:y(row.v14)})));
  }

  function wireChartPointer(section) {
    const stage=section.querySelector('.v14-chart-stage');
    stage.addEventListener('pointermove', event=>{
      const host=section.querySelector('[data-v14-equity-chart]');
      let points=[];try{points=JSON.parse(host.dataset.points||'[]')}catch(_){return}
      if(!points.length)return;
      const rect=host.getBoundingClientRect(),W=940,H=315;
      const px=(event.clientX-rect.left)/rect.width*W;
      const point=points.reduce((best,row)=>Math.abs(row.x-px)<Math.abs(best.x-px)?row:best,points[0]);
      const tip=section.querySelector('[data-v14-tooltip]');
      tip.innerHTML=`<strong>${escapeHtml(dateTime(point.timestamp_utc))} · ${escapeHtml(statusText(point.event))}</strong><div><span>V14</span><b>${money(point.v14)}</b></div><div><span>SPY</span><b>${money(point.spy)}</b></div><div><span>Difference</span><b>${money((point.v14||0)-(point.spy||0))}</b></div>`;
      tip.style.left=`${Math.max(110,Math.min(rect.width-110,point.x/W*rect.width))}px`;tip.style.top=`${Math.max(105,point.y/H*rect.height)}px`;tip.classList.add('show');
    });
    stage.addEventListener('pointerleave',()=>section.querySelector('[data-v14-tooltip]').classList.remove('show'));
  }

  function renderCoefficients(section, rows) {
    const host=section.querySelector('[data-v14-coefficients]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v14-empty">Learned coefficients appear after the first eligible September 11 decision is trained and recorded.</div>';return}
    const W=720,H=44+rows.length*38,p={l:190,r:54,t:22,b:20};
    const max=Math.max(.0001,...rows.map(row=>Math.abs(Number(row.coefficient)||0)));const center=p.l+(W-p.l-p.r)/2;const half=(W-p.l-p.r)/2;
    const bars=rows.map((row,index)=>{const value=Number(row.coefficient),width=Math.abs(value)/max*half,yy=p.t+index*38,x=value>=0?center:center-width,color=value>=0?'#39e3a1':'#ff7ad9';return `<text x="${p.l-10}" y="${yy+15}" fill="#c5d4e8" font-size="12" text-anchor="end">${escapeHtml(statusText(row.feature))}</text><rect x="${x}" y="${yy}" width="${Math.max(1,width)}" height="22" rx="5" fill="${color}" opacity=".86"><title>${escapeHtml(row.feature)}: ${value.toFixed(6)} · odds ×${Number(row.odds_multiplier_per_standard_deviation).toFixed(3)} per standard deviation</title></rect><text x="${value>=0?x+width+6:x-6}" y="${yy+15}" fill="${color}" font-size="10" text-anchor="${value>=0?'start':'end'}">${value>=0?'+':''}${value.toFixed(4)}</text>`}).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Learned standardized logistic regression coefficients"><line x1="${center}" y1="8" x2="${center}" y2="${H-10}" stroke="#91a6c2" opacity=".55"/>${bars}</svg>`;
  }

  function renderProbabilities(section, rows) {
    const host=section.querySelector('[data-v14-probabilities]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v14-empty">The latest Top-10 probability chart will appear after V14 creates its first paper-forward decision.</div>';return}
    const top=rows.slice(0,10),W=720,H=44+top.length*32,p={l:82,r:68,t:18,b:22};const min=Math.min(.5,...top.map(row=>Number(row.predicted_probability))),max=Math.max(.51,...top.map(row=>Number(row.predicted_probability)));const span=Math.max(.01,max-min);
    const bars=top.map((row,index)=>{const value=Number(row.predicted_probability),width=(value-min)/span*(W-p.l-p.r),yy=p.t+index*32;return `<text x="${p.l-9}" y="${yy+14}" fill="#c5d4e8" font-size="12" text-anchor="end">#${row.rank} ${escapeHtml(row.symbol)}</text><rect x="${p.l}" y="${yy}" width="${Math.max(3,width)}" height="20" rx="5" fill="url(#v14Prob)" opacity=".9"><title>${escapeHtml(row.symbol)}: ${(value*100).toFixed(2)}%</title></rect><text x="${Math.min(W-p.r+8,p.l+width+7)}" y="${yy+14}" fill="#36d8ff" font-size="10">${(value*100).toFixed(2)}%</text>`}).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Latest V14 prediction probabilities"><defs><linearGradient id="v14Prob"><stop stop-color="#a78bfa"/><stop offset=".52" stop-color="#36d8ff"/><stop offset="1" stop-color="#39e3a1"/></linearGradient></defs>${bars}</svg>`;
  }

  function renderRankings(section, rows, payload) {
    const host=section.querySelector('[data-v14-rankings]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v14-empty">No ranking snapshot exists yet. V14 will record all 100 probabilities with the first eligible decision.</div>';return}
    set(section,'[data-v14-ranking-note]',`${rows.length} recorded probabilities · decision ${dateOnly(payload.latest_decision_session_utc)}`);
    host.innerHTML=`<table><thead><tr><th>Rank</th><th>Symbol</th><th>Predicted up probability</th><th>Selection</th><th>Decision session</th></tr></thead><tbody>${rows.map(row=>`<tr class="${row.selected_top10?'selected':''}"><td>#${integer(row.rank)}</td><td><strong>${escapeHtml(row.symbol)}</strong></td><td class="v14-prob">${plainPct(row.predicted_probability)}</td><td><span class="v14-pill ${row.selected_top10?'top':''}">${row.selected_top10?'TOP 10':'NOT SELECTED'}</span></td><td>${escapeHtml(dateOnly(payload.latest_decision_session_utc))}</td></tr>`).join('')}</tbody></table>`;
  }

  function renderPositions(section, rows) {
    const host=section.querySelector('[data-v14-positions]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v14-empty">Open paper positions appear after the first Top-10 basket enters at the next market open.</div>';return}
    host.innerHTML=`<table><thead><tr><th>Cohort</th><th>Symbol</th><th>Entry</th><th>Current mark</th><th>Return</th><th>Mark time</th><th>Source</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${integer(row.cohort_offset)}</td><td><strong>${escapeHtml(row.symbol)}</strong></td><td>${money(row.entry_price)}</td><td>${money(row.current_price)}</td><td class="${number(row.current_return)!=null&&Number(row.current_return)<0?'negative':'positive'}">${pct(row.current_return)}</td><td>${escapeHtml(dateTime(row.mark_timestamp_utc))}</td><td>${escapeHtml(statusText(row.mark_source))}</td></tr>`).join('')}</tbody></table>`;
  }

  function renderEvents(section, rows) {
    const host=section.querySelector('[data-v14-events]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v14-empty">The append-only journal is empty because the clean paper-forward boundary has not produced its first decision.</div>';return}
    host.innerHTML=`<table><thead><tr><th>Event</th><th>Time</th><th>Cohort</th><th>Basket</th><th>V14 net return</th><th>SPY return</th><th>Relative edge</th><th>Model</th></tr></thead><tbody>${rows.map(row=>`<tr><td><span class="v14-pill ${row.event_type==='DECISION'?'top':''}">${escapeHtml(row.event_type)}</span></td><td>${escapeHtml(dateTime(row.timestamp_utc))}</td><td>${integer(row.cohort_offset)}</td><td>${escapeHtml((row.symbols||[]).join(', ')||'—')}</td><td>${pct(row.net_portfolio_return)}</td><td>${pct(row.spy_return)}</td><td class="${number(row.net_relative_return)!=null&&Number(row.net_relative_return)<0?'negative':'positive'}">${pct(row.net_relative_return)}</td><td>${escapeHtml(shortSha(row.model_sha256))}</td></tr>`).join('')}</tbody></table>`;
  }

  function render(section, payload) {
    const state=statusText(payload.state),badge=section.querySelector('[data-v14-state]');badge.textContent=state;badge.classList.toggle('waiting',/WAITING/.test(state));badge.classList.toggle('alert',/ERROR|CORRUPT|BLOCKED/.test(state));
    set(section,'[data-v14-model]',statusText(payload.model_type));set(section,'[data-v14-target]',statusText(payload.target));set(section,'[data-v14-features]',`${integer((payload.features||[]).length)} learned inputs`);set(section,'[data-v14-universe]',`${integer(payload.required_symbols)} symbols`);set(section,'[data-v14-boundary]',dateOnly(payload.paper_forward_start_utc));set(section,'[data-v14-next]',statusText(payload.next_lifecycle_event));
    set(section,'[data-v14-equity]',money(payload.current_equity));set(section,'[data-v14-return]',`${pct(payload.current_return)} V14 · ${statusText(payload.equity_basis)}`);set(section,'[data-v14-equity-note]',`${money(payload.starting_equity)} start · updated ${dateTime(payload.valuation_timestamp_utc||payload.checked_at_utc)} · current marks are not completed evidence`);set(section,'[data-v14-spy-equity]',money(payload.current_spy_equity));set(section,'[data-v14-excess]',pct(payload.current_excess_return));set(section,'[data-v14-open]',integer(payload.open_cohorts));set(section,'[data-v14-priced]',`${integer(payload.priced_open_cohorts)} / ${integer(payload.open_cohorts)}`);tone(section,'[data-v14-return]',payload.current_return);tone(section,'[data-v14-excess]',payload.current_excess_return);
    const blocks=Number(payload.complete_five_sleeve_blocks)||0,sleeves=Number(payload.sleeves_toward_next_block)||0;set(section,'[data-v14-progress-block]',`${sleeves} / 5 sleeves`);set(section,'[data-v14-blocks]',`${blocks} complete block${blocks===1?'':'s'} recorded`);progress(section,'[data-v14-bar-block]',sleeves,5);
    set(section,'[data-v14-decisions]',integer(payload.decisions));set(section,'[data-v14-entries]',integer(payload.entries));set(section,'[data-v14-exits]',integer(payload.completed_exits));set(section,'[data-v14-hit]',plainPct(payload.relative_hit_rate));set(section,'[data-v14-drawdown]',pct(payload.max_drawdown));set(section,'[data-v14-sharpe]',decimal(payload.diagnostic_annualized_sharpe,2));
    set(section,'[data-v14-training-rows]',integer(payload.training_rows));set(section,'[data-v14-positive-rate]',plainPct(payload.training_positive_rate));set(section,'[data-v14-training-start]',dateOnly(payload.training_start_utc));set(section,'[data-v14-training-cutoff]',dateOnly(payload.training_cutoff_utc));set(section,'[data-v14-purge]',`${integer(payload.purge_gap_sessions)} sessions`);set(section,'[data-v14-model-sha]',shortSha(payload.latest_model_sha256));
    set(section,'[data-v14-readiness]',statusText(payload.refresh_status));set(section,'[data-v14-backend]',String(payload.feature_backend||'—').toUpperCase());set(section,'[data-v14-feature-session]',dateOnly(payload.feature_timestamp_utc));set(section,'[data-v14-required]',integer(payload.required_symbols));set(section,'[data-v14-contract-sha]',shortSha(payload.contract_sha256));set(section,'[data-v14-paper]',payload.paper_trading_only?'YES':'NO');set(section,'[data-v14-brokerage]',payload.brokerage_orders?'ON':'OFF');set(section,'[data-v14-promotion]',payload.automatic_promotion?'YES':'NO');set(section,'[data-v14-review]',payload.human_review_required?'YES':'NO');set(section,'[data-v14-runner]',payload.runner_invoked?'YES':'NO');set(section,'[data-v14-isolation]',`${payload.v8_modified?'YES':'NO'} / ${payload.v10_modified?'YES':'NO'}`);set(section,'[data-v14-network]',integer(payload.scheduled_network_requests));set(section,'[data-v14-method]',payload.method_note||'V14 methodology unavailable.');
    renderEquity(section,payload);renderCoefficients(section,payload.coefficients);renderProbabilities(section,payload.rankings);renderRankings(section,payload.rankings,payload);renderPositions(section,payload.open_positions);renderEvents(section,payload.event_history);
  }

  async function load(section) {
    try {
      const response=await fetch(API,{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw new Error(`HTTP ${response.status}`);const payload=await response.json();render(section,payload);
    } catch(error) {
      const badge=section.querySelector('[data-v14-state]');badge.textContent='DASHBOARD DATA UNAVAILABLE';badge.classList.add('alert');set(section,'[data-v14-method]',`The read-only V14 endpoint could not be loaded: ${error.message}`);
    }
    window.clearTimeout(refreshTimer);refreshTimer=window.setTimeout(()=>{if(!document.hidden)load(section)},15000);
  }

  document.addEventListener('visibilitychange',()=>{const section=document.getElementById(panelId);if(section&&!document.hidden)load(section)});
  mount();
})();
