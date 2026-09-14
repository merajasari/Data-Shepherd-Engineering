(() => {
  const panelId = 'v15-intraday-v7-dashboard';
  const API = '/api/v15/intraday-v7';
  const STARTING_EQUITY = 100000;
  let refreshTimer = null;

  const escapeHtml = value => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const statusText = value => String(value || 'UNKNOWN').replaceAll('_', ' ');
  const number = value => value == null || !Number.isFinite(Number(value)) ? null : Number(value);
  const integer = value => number(value) == null ? '—' : Math.round(Number(value)).toLocaleString();
  const pct = (value, digits=2) => number(value) == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(digits)}%`;
  const plainPct = (value, digits=1) => number(value) == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`;
  const money = value => number(value) == null ? '—' : Number(value).toLocaleString(undefined, {style:'currency', currency:'USD', minimumFractionDigits:2, maximumFractionDigits:2});
  const shortSha = value => value ? `${String(value).slice(0,12)}…${String(value).slice(-8)}` : 'Not recorded';
  const dateOnly = value => {
    if (!value) return '—';
    const parsed = new Date(`${String(value).slice(0,10)}T12:00:00Z`);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric', timeZone:'UTC'});
  };
  const dateTime = value => {
    if (!value) return '—';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZone:'America/Los_Angeles', timeZoneName:'short'});
  };

  function mount(attempt=0) {
    if (document.getElementById(panelId)) return;
    const target = document.querySelector('[data-research-content="v15"]');
    if (!target) {
      if (attempt < 30) window.setTimeout(() => mount(attempt + 1), 50);
      return;
    }
    const section = document.createElement('section');
    section.id = panelId;
    section.className = 'v15-lab';
    section.innerHTML = `
      <style>
        #${panelId}{--v15-cyan:#36d8ff;--v15-green:#39e3a1;--v15-purple:#a78bfa;--v15-gold:#efc56b;--v15-red:#ff758f;display:flex;flex-direction:column;gap:16px;min-width:0}
        #${panelId} .v15-card{border:1px solid rgba(120,155,205,.19);border-radius:18px;background:linear-gradient(145deg,rgba(12,29,50,.92),rgba(6,17,32,.94));padding:18px;min-width:0;box-shadow:0 16px 38px rgba(0,0,0,.13)}
        #${panelId} .v15-hero{position:relative;overflow:hidden;border-color:rgba(167,139,250,.34);background:radial-gradient(circle at 87% -15%,rgba(54,216,255,.23),transparent 40%),radial-gradient(circle at 9% 115%,rgba(57,227,161,.17),transparent 38%),linear-gradient(145deg,rgba(20,24,61,.98),rgba(6,18,34,.98))}
        #${panelId} .v15-hero:after{content:'';position:absolute;inset:0;pointer-events:none;background:linear-gradient(112deg,transparent 0 55%,rgba(167,139,250,.05) 55% 56%,transparent 56% 63%,rgba(54,216,255,.05) 63% 64%,transparent 64%)}
        #${panelId} .v15-head{position:relative;z-index:1;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
        #${panelId} h2,#${panelId} h3{margin:5px 0 7px}#${panelId} p{line-height:1.55}
        #${panelId} .v15-badge{max-width:330px;padding:9px 13px;border:1px solid rgba(57,227,161,.42);border-radius:999px;background:rgba(57,227,161,.07);color:var(--v15-green);font-size:.73rem;font-weight:900;text-align:center;overflow-wrap:anywhere}
        #${panelId} .v15-badge.waiting{color:var(--v15-gold);border-color:rgba(239,197,107,.4);background:rgba(239,197,107,.07)}
        #${panelId} .v15-badge.alert{color:var(--v15-red);border-color:rgba(255,117,143,.45);background:rgba(255,117,143,.07)}
        #${panelId} .v15-flow{position:relative;z-index:1;display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:15px}
        #${panelId} .v15-flow span{padding:7px 10px;border:1px solid rgba(167,139,250,.23);border-radius:999px;background:rgba(167,139,250,.06);font-size:.69rem;font-weight:850;letter-spacing:.03em}
        #${panelId} .v15-flow i{color:#7890ad;font-style:normal}
        #${panelId} .v15-grid{display:grid;gap:12px;min-width:0}#${panelId} .v15-metrics{grid-template-columns:repeat(6,minmax(0,1fr))}
        #${panelId} .v15-metric{padding:13px;border:1px solid rgba(120,155,205,.15);border-radius:13px;background:rgba(4,13,25,.36);min-width:0}
        #${panelId} .v15-metric span{display:block;color:#91a6c2;font-size:.64rem;font-weight:850;letter-spacing:.065em;text-transform:uppercase;line-height:1.4}
        #${panelId} .v15-metric strong{display:block;margin-top:6px;font-size:.97rem;line-height:1.35;overflow-wrap:anywhere}
        #${panelId} .positive{color:var(--v15-green)}#${panelId} .negative{color:var(--v15-red)}
        #${panelId} .v15-split{display:grid;grid-template-columns:minmax(290px,.54fr) minmax(0,1.46fr);gap:14px}
        #${panelId} .v15-equity{font-size:clamp(2rem,3.7vw,3.35rem);font-weight:950;line-height:1.05;letter-spacing:-.04em;margin-top:8px;white-space:nowrap;font-variant-numeric:tabular-nums}
        #${panelId} .v15-return{font-size:1.02rem;font-weight:900;margin-top:4px}
        #${panelId} .v15-sub{color:#91a6c2;font-size:.75rem;line-height:1.55;margin-top:8px}
        #${panelId} .v15-mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}
        #${panelId} .v15-chart-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
        #${panelId} .v15-chart-title{font-size:.78rem;font-weight:900;letter-spacing:.055em;text-transform:uppercase}
        #${panelId} .v15-chart-sub{margin-top:4px;color:#91a6c2;font-size:.72rem;line-height:1.45}
        #${panelId} .v15-legend{display:flex;gap:11px;flex-wrap:wrap;color:#91a6c2;font-size:.68rem}
        #${panelId} .v15-legend span{display:flex;align-items:center;gap:5px}#${panelId} .v15-legend i{display:block;width:15px;height:3px;border-radius:3px}
        #${panelId} .v15-chart-stage{position:relative;height:325px;margin-top:7px}#${panelId} .v15-chart-host,#${panelId} .v15-chart-host svg{display:block;width:100%;height:100%}
        #${panelId} .v15-tooltip{position:absolute;display:none;pointer-events:none;min-width:230px;padding:10px 12px;border:1px solid rgba(54,216,255,.32);border-radius:10px;background:#071525;box-shadow:0 12px 30px rgba(0,0,0,.4);font-size:.7rem;z-index:5;transform:translate(-50%,-100%)}
        #${panelId} .v15-tooltip.show{display:block}#${panelId} .v15-tooltip strong{display:block;margin-bottom:5px}#${panelId} .v15-tooltip div{display:flex;justify-content:space-between;gap:18px;margin-top:3px}
        #${panelId} .v15-progress-grid{grid-template-columns:repeat(3,minmax(0,1fr))}#${panelId} .v15-progress{height:8px;margin-top:9px;border-radius:99px;background:rgba(120,155,205,.14);overflow:hidden}
        #${panelId} .v15-progress i{display:block;width:0;height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--v15-purple),var(--v15-cyan),var(--v15-green));transition:width .3s ease}
        #${panelId} .v15-charts{grid-template-columns:1fr 1fr}#${panelId} .v15-chart-box{min-width:0}#${panelId} .v15-small-chart{min-height:285px;margin-top:10px;display:flex;align-items:center;justify-content:center;overflow-x:auto}
        #${panelId} .v15-small-chart svg{display:block;width:100%;height:auto;min-width:560px}
        #${panelId} .v15-empty{width:100%;padding:32px 18px;color:#91a6c2;text-align:center;font-size:.78rem;line-height:1.6;border:1px dashed rgba(120,155,205,.2);border-radius:13px;background:rgba(4,13,25,.2)}
        #${panelId} .v15-table-wrap{overflow:auto;max-height:500px;margin-top:12px;border:1px solid rgba(120,155,205,.13);border-radius:12px}
        #${panelId} table{min-width:820px}#${panelId} th{position:sticky;top:0;z-index:2;background:#0b1c31}#${panelId} td,#${panelId} th{font-size:.74rem}
        #${panelId} .v15-pill{display:inline-block;padding:4px 7px;border-radius:999px;border:1px solid rgba(120,155,205,.2);font-size:.63rem;font-weight:900;white-space:nowrap}
        #${panelId} .v15-pill.trade,#${panelId} .v15-pill.pass{color:var(--v15-green);border-color:rgba(57,227,161,.3);background:rgba(57,227,161,.06)}
        #${panelId} .v15-pill.wait{color:var(--v15-gold);border-color:rgba(239,197,107,.3);background:rgba(239,197,107,.06)}
        #${panelId} .v15-pill.fail{color:var(--v15-red);border-color:rgba(255,117,143,.3);background:rgba(255,117,143,.06)}
        #${panelId} .v15-section-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-end}#${panelId} .v15-section-head p{margin:0;max-width:760px}
        #${panelId} .v15-gates{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:13px}
        #${panelId} .v15-gate{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px 11px;border:1px solid rgba(120,155,205,.14);border-radius:11px;background:rgba(4,13,25,.28);font-size:.72rem}
        #${panelId} .v15-integrity{border:1px solid rgba(120,155,205,.17);border-radius:13px;background:rgba(4,13,25,.25)}
        #${panelId} .v15-integrity summary{cursor:pointer;padding:13px 15px;font-size:.76rem;font-weight:900;letter-spacing:.04em;text-transform:uppercase}
        #${panelId} .v15-integrity .v15-grid{padding:0 14px 14px;grid-template-columns:repeat(4,minmax(0,1fr))}
        #${panelId} .v15-method{padding:14px;border-left:3px solid var(--v15-purple);border-radius:0 11px 11px 0;background:rgba(167,139,250,.06);color:#b8c7da;font-size:.78rem;line-height:1.65}
        @media(max-width:1100px){#${panelId} .v15-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}#${panelId} .v15-split,#${panelId} .v15-charts{grid-template-columns:1fr}}
        @media(max-width:760px){#${panelId} .v15-head,#${panelId} .v15-chart-head,#${panelId} .v15-section-head{flex-direction:column;align-items:flex-start}#${panelId} .v15-metrics,#${panelId} .v15-progress-grid,#${panelId} .v15-integrity .v15-grid,#${panelId} .v15-gates{grid-template-columns:1fr 1fr}#${panelId} .v15-mini-grid{grid-template-columns:1fr}#${panelId} .v15-chart-stage{height:290px}}
        @media(max-width:480px){#${panelId} .v15-metrics,#${panelId} .v15-progress-grid,#${panelId} .v15-integrity .v15-grid,#${panelId} .v15-gates{grid-template-columns:1fr}#${panelId} .v15-equity{font-size:clamp(1.8rem,10vw,2.55rem)}}
      </style>
      <section class="v15-card v15-hero">
        <div class="v15-head"><div><div class="label">PREREGISTERED INTRADAY MACHINE LEARNING · PROSPECTIVE PAPER SHADOW</div><h2>V15 V7 Intraday Hybrid Intelligence</h2><p class="muted">An immutable return-regression model combines completed V11 five-minute market structure with prior-close V14 context, then selectively follows a risk-scaled two-hour paper lifecycle.</p></div><div class="v15-badge waiting" data-v15-state>LOADING V15 STATE</div></div>
        <div class="v15-flow" aria-label="V15 intraday machine learning lifecycle"><span>V11 completed 5-minute bars</span><i>→</i><span>prior-close V14 context</span><i>→</i><span>ridge return model</span><i>→</i><span>selective top-k signal</span><i>→</i><span>60% risk budget</span><i>→</i><span>120-minute exit</span></div>
      </section>
      <section class="v15-grid v15-metrics">
        <div class="v15-metric"><span>Model class</span><strong data-v15-model>—</strong></div><div class="v15-metric"><span>Decision checkpoint</span><strong data-v15-decision-time>—</strong></div><div class="v15-metric"><span>Holding period</span><strong data-v15-horizon>—</strong></div><div class="v15-metric"><span>Maximum exposure</span><strong data-v15-exposure>—</strong></div><div class="v15-metric"><span>Fresh boundary</span><strong data-v15-boundary>—</strong></div><div class="v15-metric"><span>Next lifecycle event</span><strong data-v15-next>—</strong></div>
      </section>
      <section class="v15-card v15-split">
        <div><div class="label">NORMALIZED V15 PAPER-SHADOW EQUITY</div><div class="v15-equity" data-v15-equity>$100,000.00</div><div class="v15-return" data-v15-return>WAITING FOR FIRST COMPLETED SESSION</div><div class="v15-sub" data-v15-equity-note>Hypothetical display basis only. No historical V5 result is mixed into V7.</div><div class="v15-mini-grid"><div class="v15-metric"><span>Matched V11</span><strong data-v15-v11>—</strong></div><div class="v15-metric"><span>V14 context control</span><strong data-v15-v14>—</strong></div><div class="v15-metric"><span>Matched SPY</span><strong data-v15-spy>—</strong></div><div class="v15-metric"><span>Excess vs SPY</span><strong data-v15-excess>—</strong></div></div></div>
        <div><div class="v15-chart-head"><div><div class="v15-chart-title">Interactive prospective performance</div><div class="v15-chart-sub">V15, matched V11, V14-context, and SPY share the same hypothetical $100,000 basis and 60% exposure.</div></div><div class="v15-legend"><span><i style="background:#36d8ff"></i>V15</span><span><i style="background:#efc56b"></i>V11</span><span><i style="background:#39e3a1"></i>V14</span><span><i style="background:#a78bfa"></i>SPY</span></div></div><div class="v15-chart-stage"><div class="v15-chart-host" data-v15-equity-chart></div><div class="v15-tooltip" data-v15-tooltip></div></div></div>
      </section>
      <section class="v15-grid v15-progress-grid">
        <div class="v15-card v15-metric"><span>Completed trades</span><strong data-v15-trade-progress>0 / 30</strong><div class="v15-progress" data-v15-trade-bar role="progressbar" aria-valuemin="0" aria-valuemax="30" aria-valuenow="0"><i></i></div><div class="v15-sub">Minimum evidence count before human review.</div></div>
        <div class="v15-card v15-metric"><span>Active 20-session blocks</span><strong data-v15-block-progress>0 / 6</strong><div class="v15-progress" data-v15-block-bar role="progressbar" aria-valuemin="0" aria-valuemax="6" aria-valuenow="0"><i></i></div><div class="v15-sub">Cash-only blocks do not satisfy the activity minimum.</div></div>
        <div class="v15-card v15-metric"><span>Next complete block</span><strong data-v15-session-progress>0 / 20 sessions</strong><div class="v15-progress" data-v15-session-bar role="progressbar" aria-valuemin="0" aria-valuemax="20" aria-valuenow="0"><i></i></div><div class="v15-sub">Only completed prospective sessions enter block gates.</div></div>
      </section>
      <section class="v15-grid v15-metrics">
        <div class="v15-metric"><span>Decisions</span><strong data-v15-decisions>—</strong></div><div class="v15-metric"><span>Trade decisions</span><strong data-v15-trades>—</strong></div><div class="v15-metric"><span>Cash decisions</span><strong data-v15-cash>—</strong></div><div class="v15-metric"><span>Completed exits</span><strong data-v15-exits>—</strong></div><div class="v15-metric"><span>Profitable trade rate</span><strong data-v15-win-rate>—</strong></div><div class="v15-metric"><span>Maximum drawdown</span><strong data-v15-drawdown>—</strong></div>
      </section>
      <section class="v15-grid v15-charts">
        <article class="v15-card v15-chart-box"><div class="v15-chart-title">Immutable hybrid model coefficients</div><div class="v15-chart-sub">Standardized weights show how V11 intraday signals, prior-close V14 probability, and their interactions influence predicted two-hour net return.</div><div class="v15-small-chart" data-v15-coefficients></div></article>
        <article class="v15-card v15-chart-box"><div class="v15-chart-title">Complete 20-session evidence blocks</div><div class="v15-chart-sub">Only finished prospective blocks are shown. Bars compare V15 with matched SPY; cash sessions remain legitimate zero-return observations.</div><div class="v15-small-chart" data-v15-blocks></div></article>
      </section>
      <section class="v15-card"><div class="v15-section-head"><div><div class="label">LATEST PROSPECTIVE DECISION</div><h3>Signal, threshold, and matched controls</h3></div><p class="muted">The model can explicitly choose cash. A cash decision creates no synthetic entry and incurs no modeled cost.</p></div><div class="v15-grid v15-metrics" style="margin-top:13px"><div class="v15-metric"><span>Session</span><strong data-v15-latest-session>—</strong></div><div class="v15-metric"><span>Decision</span><strong data-v15-latest-action>AWAITING FIRST DECISION</strong></div><div class="v15-metric"><span>Predicted top-k net</span><strong data-v15-predicted>—</strong></div><div class="v15-metric"><span>Applied threshold</span><strong data-v15-threshold>—</strong></div><div class="v15-metric"><span>Selected basket</span><strong data-v15-selected>—</strong></div><div class="v15-metric"><span>Daily context</span><strong data-v15-context>—</strong></div></div></section>
      <section class="v15-card"><div class="v15-section-head"><div><div class="label">PREREGISTERED HUMAN-REVIEW GATES</div><h3>Prospective qualification—not automatic promotion</h3></div><p class="muted" data-v15-review-note>Waiting for sufficient fresh evidence.</p></div><div class="v15-gates" data-v15-gates></div></section>
      <section class="v15-card"><div class="v15-section-head"><div><div class="label">OPEN PAPER-SHADOW POSITIONS</div><h3>Entry awaiting the scheduled exit</h3></div><p class="muted">The dashboard reads stored entry prices only and never requests a market quote or changes evidence.</p></div><div class="v15-table-wrap" data-v15-positions></div></section>
      <section class="v15-card"><div class="v15-section-head"><div><div class="label">TAMPER-EVIDENT APPEND-ONLY LIFECYCLE</div><h3>Decision, entry, and exit journal</h3></div><p class="muted">Every event is chained to the prior event and bound to the V15 candidate and contract.</p></div><div class="v15-table-wrap" data-v15-events></div></section>
      <details class="v15-integrity" open><summary>Data integrity, model lineage &amp; authority</summary><div class="v15-grid"><div class="v15-metric"><span>Current run health</span><strong data-v15-health>—</strong></div><div class="v15-metric"><span>Journal integrity</span><strong data-v15-integrity>—</strong></div><div class="v15-metric"><span>Prepared model</span><strong data-v15-prepared>—</strong></div><div class="v15-metric"><span>Training window</span><strong data-v15-training>—</strong></div><div class="v15-metric"><span>Training rows</span><strong data-v15-training-rows>—</strong></div><div class="v15-metric"><span>Model SHA-256</span><strong data-v15-model-sha>—</strong></div><div class="v15-metric"><span>Contract SHA-256</span><strong data-v15-contract-sha>—</strong></div><div class="v15-metric"><span>Historical V5 evidence included</span><strong data-v15-history>NO</strong></div><div class="v15-metric"><span>Paper shadow only</span><strong data-v15-paper>YES</strong></div><div class="v15-metric"><span>Brokerage orders</span><strong data-v15-brokerage>OFF</strong></div><div class="v15-metric"><span>Automatic promotion</span><strong data-v15-promotion>NO</strong></div><div class="v15-metric"><span>Dashboard invoked runner</span><strong data-v15-runner>NO</strong></div><div class="v15-metric"><span>Dashboard network requests</span><strong data-v15-network>0</strong></div><div class="v15-metric"><span>Other models modified</span><strong data-v15-isolation>NO</strong></div><div class="v15-metric"><span>Last scheduler check</span><strong data-v15-checked>—</strong></div><div class="v15-metric"><span>Operational failures</span><strong data-v15-failures>NONE</strong></div></div></details>
      <div class="v15-method" data-v15-method>Loading the frozen V15 V7 paper-shadow contract.</div>
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
    const host = section.querySelector('[data-v15-equity-chart]');
    const rows = (Array.isArray(payload.curve) ? payload.curve : []).filter(row => number(row.v15_normalized) != null);
    if (!rows.length) {
      host.innerHTML = '<div class="v15-empty">The prospective curve begins after the first completed V15 V7 session. Historical V5 and backward-robustness returns are intentionally excluded.</div>';
      host.dataset.points = '[]';
      return;
    }
    const baseline = String(payload.first_eligible_session || rows[0].session_date);
    const points = [{session_date:baseline,event:'V7 BOUNDARY',v15:STARTING_EQUITY,v11:STARTING_EQUITY,v14:STARTING_EQUITY,spy:STARTING_EQUITY}, ...rows.map(row => ({session_date:row.session_date,event:row.event,v15:number(row.v15_normalized),v11:number(row.v11_normalized),v14:number(row.v14_normalized),spy:number(row.spy_normalized)}))];
    const W=960,H=325,p={l:72,r:25,t:22,b:39};
    const values=points.flatMap(row=>[row.v15,row.v11,row.v14,row.spy].filter(value=>value!=null));
    let lo=Math.min(STARTING_EQUITY,...values),hi=Math.max(STARTING_EQUITY,...values);const span=Math.max(hi-lo,250);lo-=span*.14;hi+=span*.14;
    const x=index=>p.l+(W-p.l-p.r)*(points.length===1?0:index/(points.length-1));
    const y=value=>p.t+(H-p.t-p.b)*(1-(value-lo)/(hi-lo));
    const grid=[0,.25,.5,.75,1].map(ratio=>{const value=hi-(hi-lo)*ratio,yy=p.t+(H-p.t-p.b)*ratio;return `<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="#60708a" opacity=".2"/><text x="${p.l-8}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value/1000)}k</text>`}).join('');
    const line=key=>points.filter(row=>row[key]!=null).map((row,index)=>`${x(index)},${y(row[key])}`).join(' ');
    const colors={v15:'#36d8ff',v11:'#efc56b',v14:'#39e3a1',spy:'#a78bfa'};
    const paths=Object.entries(colors).map(([key,color])=>`<polyline points="${line(key)}" fill="none" stroke="${color}" stroke-width="${key==='v15'?3.3:2.35}" stroke-linecap="round" stroke-linejoin="round" opacity="${key==='v15'?1:.88}"/>`).join('');
    const dots=points.map((row,index)=>`<circle cx="${x(index)}" cy="${y(row.v15)}" r="${index===points.length-1?4.5:3}" fill="#36d8ff" data-v15-point="${index}"/>`).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="V15 prospective paper-shadow equity against matched V11, V14-context, and SPY controls">${grid}<line x1="${p.l}" y1="${y(STARTING_EQUITY)}" x2="${W-p.r}" y2="${y(STARTING_EQUITY)}" stroke="#91a6c2" stroke-dasharray="5 5" opacity=".55"/>${paths}${dots}<text x="${(p.l+W-p.r)/2}" y="${H-4}" fill="#91a6c2" font-size="10" text-anchor="middle">Completed prospective intraday sessions</text></svg>`;
    host.dataset.points=JSON.stringify(points.map((row,index)=>({...row,x:x(index),y:y(row.v15)})));
  }

  function wireChartPointer(section) {
    const stage=section.querySelector('.v15-chart-stage');
    stage.addEventListener('pointermove', event=>{
      const host=section.querySelector('[data-v15-equity-chart]');
      let points=[];try{points=JSON.parse(host.dataset.points||'[]')}catch(_){return}
      if(!points.length)return;
      const rect=host.getBoundingClientRect(),W=960,H=325,px=(event.clientX-rect.left)/rect.width*W;
      const point=points.reduce((best,row)=>Math.abs(row.x-px)<Math.abs(best.x-px)?row:best,points[0]);
      const tip=section.querySelector('[data-v15-tooltip]');
      tip.innerHTML=`<strong>${escapeHtml(dateOnly(point.session_date))} · ${escapeHtml(statusText(point.event))}</strong><div><span>V15</span><b>${money(point.v15)}</b></div><div><span>V11 matched</span><b>${money(point.v11)}</b></div><div><span>V14 context</span><b>${money(point.v14)}</b></div><div><span>SPY matched</span><b>${money(point.spy)}</b></div>`;
      tip.style.left=`${Math.max(120,Math.min(rect.width-120,point.x/W*rect.width))}px`;tip.style.top=`${Math.max(125,point.y/H*rect.height)}px`;tip.classList.add('show');
    });
    stage.addEventListener('pointerleave',()=>section.querySelector('[data-v15-tooltip]').classList.remove('show'));
  }

  function renderCoefficients(section, rows) {
    const host=section.querySelector('[data-v15-coefficients]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v15-empty">The immutable coefficient snapshot is not available.</div>';return}
    const shown=rows.slice(0,14),W=760,H=42+shown.length*34,p={l:245,r:60,t:18,b:18};
    const max=Math.max(.000001,...shown.map(row=>Math.abs(Number(row.coefficient)||0))),center=p.l+(W-p.l-p.r)/2,half=(W-p.l-p.r)/2;
    const bars=shown.map((row,index)=>{const value=Number(row.coefficient),width=Math.abs(value)/max*half,yy=p.t+index*34,x=value>=0?center:center-width,color=value>=0?'#39e3a1':'#ff7ad9';return `<text x="${p.l-10}" y="${yy+14}" fill="#c5d4e8" font-size="11" text-anchor="end">${escapeHtml(statusText(row.feature))}</text><rect x="${x}" y="${yy}" width="${Math.max(1,width)}" height="20" rx="5" fill="${color}" opacity=".86"><title>${escapeHtml(row.feature)}: ${value.toFixed(7)}</title></rect><text x="${value>=0?x+width+6:x-6}" y="${yy+14}" fill="${color}" font-size="9" text-anchor="${value>=0?'start':'end'}">${value>=0?'+':''}${value.toFixed(5)}</text>`}).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Largest V15 immutable hybrid model coefficients"><line x1="${center}" y1="7" x2="${center}" y2="${H-8}" stroke="#91a6c2" opacity=".55"/>${bars}</svg>`;
  }

  function renderBlocks(section, rows) {
    const host=section.querySelector('[data-v15-blocks]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v15-empty">A block appears after 20 complete prospective sessions. Partial blocks never enter stability gates.</div>';return}
    const W=760,H=330,p={l:58,r:25,t:22,b:48},values=rows.flatMap(row=>[Number(row.v15_return)||0,Number(row.spy_return)||0]),max=Math.max(.005,...values.map(Math.abs)),zero=p.t+(H-p.t-p.b)/2;
    const group=(W-p.l-p.r)/rows.length,scale=(H-p.t-p.b)/2/max*.86;
    const bars=rows.map((row,index)=>{const center=p.l+group*(index+.5),v15=Number(row.v15_return)||0,spy=Number(row.spy_return)||0;const bar=(value,x,color)=>{const h=Math.abs(value)*scale,y=value>=0?zero-h:zero;return `<rect x="${x}" y="${y}" width="${Math.max(5,group*.22)}" height="${Math.max(1,h)}" rx="3" fill="${color}"><title>Block ${row.block}: ${(value*100).toFixed(2)}%</title></rect>`};return `${bar(v15,center-group*.25,'#36d8ff')}${bar(spy,center+group*.03,'#a78bfa')}<text x="${center}" y="${H-24}" fill="#91a6c2" font-size="9" text-anchor="middle">B${row.block}</text><text x="${center}" y="${H-11}" fill="#7890ad" font-size="8" text-anchor="middle">${row.trades} trades</text>`}).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Complete V15 20-session block returns compared with matched SPY"><line x1="${p.l}" y1="${zero}" x2="${W-p.r}" y2="${zero}" stroke="#91a6c2" opacity=".55"/>${bars}</svg>`;
  }

  function renderGates(section, review) {
    const host=section.querySelector('[data-v15-gates]'),results=review?.gate_results||{};
    const labels={positive_net_return:'Positive net return after modeled cost',positive_relative_to_matched_v11:'Positive relative return versus matched V11',positive_relative_to_v14_context:'Positive relative return versus V14 context',positive_relative_to_matched_spy:'Positive relative return versus matched SPY',maximum_drawdown:'Maximum drawdown at or below 10%',worst_portfolio_trade:'Worst portfolio trade at or above −2%',profitable_trade_rate:'Profitable trade rate at or above 50%',positive_active_block_share:'Positive active-block share at or above 60%',non_losing_all_block_share:'Non-losing all-block share at or above 80%',operational_integrity:'Operational integrity'};
    host.innerHTML=Object.entries(labels).map(([key,label])=>{const value=results[key],state=value===true?'PASS':value===false?'FAIL':'WAITING',klass=value===true?'pass':value===false?'fail':'wait';return `<div class="v15-gate"><span>${escapeHtml(label)}</span><strong class="v15-pill ${klass}">${state}</strong></div>`}).join('');
  }

  function renderPositions(section, rows) {
    const host=section.querySelector('[data-v15-positions]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v15-empty">No open V15 paper-shadow position. Positions exist only between the recorded entry and scheduled same-session exit.</div>';return}
    host.innerHTML=`<table><thead><tr><th>Session</th><th>Symbol</th><th>Entry price</th><th>Portfolio exposure</th><th>Status</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${escapeHtml(dateOnly(row.session_date))}</td><td><strong>${escapeHtml(row.symbol)}</strong></td><td>${money(row.entry_price)}</td><td>${plainPct(row.exposure)}</td><td><span class="v15-pill wait">${escapeHtml(statusText(row.status))}</span></td></tr>`).join('')}</tbody></table>`;
  }

  function renderEvents(section, rows) {
    const host=section.querySelector('[data-v15-events]');
    if(!Array.isArray(rows)||!rows.length){host.innerHTML='<div class="v15-empty">The V15 V7 journal is empty because the September 21 prospective boundary has not produced its first eligible decision.</div>';return}
    host.innerHTML=`<table><thead><tr><th>Sequence</th><th>Event</th><th>Session</th><th>Time</th><th>Decision</th><th>Basket</th><th>V15 return</th><th>Stops</th><th>Event identity</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${integer(row.sequence)}</td><td><span class="v15-pill ${row.event_type==='DECISION'?'trade':''}">${escapeHtml(row.event_type)}</span></td><td>${escapeHtml(dateOnly(row.session_date))}</td><td>${escapeHtml(dateTime(row.occurred_at_utc))}</td><td>${row.trade==null?'—':row.trade?'TRADE':'CASH'}</td><td>${escapeHtml((row.selected_symbols||[]).join(', ')||'—')}</td><td class="${number(row.v15_net_return)!=null&&Number(row.v15_net_return)<0?'negative':'positive'}">${pct(row.v15_net_return)}</td><td>${integer(row.stop_triggered_positions)}</td><td>${escapeHtml(shortSha(row.event_sha256))}</td></tr>`).join('')}</tbody></table>`;
  }

  function render(section, payload) {
    const state=statusText(payload.state),badge=section.querySelector('[data-v15-state]');badge.textContent=state;badge.classList.toggle('waiting',/WAITING/.test(state));badge.classList.toggle('alert',/ERROR|CORRUPT|BLOCKED|MISSED/.test(state));
    set(section,'[data-v15-model]',statusText(payload.model_type));set(section,'[data-v15-decision-time]',`${payload.decision_time_eastern||'—'} ET`);set(section,'[data-v15-horizon]',`${integer(payload.holding_minutes)} minutes`);set(section,'[data-v15-exposure]',plainPct(payload.maximum_invested_fraction,0));set(section,'[data-v15-boundary]',dateOnly(payload.first_eligible_session));set(section,'[data-v15-next]',statusText(payload.next_lifecycle_event));
    set(section,'[data-v15-equity]',money(payload.current_equity));set(section,'[data-v15-return]',`${pct(payload.current_return)} V15 · completed prospective sessions`);set(section,'[data-v15-equity-note]',`${money(payload.starting_equity)} hypothetical basis · ${integer(payload.completed_sessions)} completed sessions · historical V5/V6 results excluded`);set(section,'[data-v15-v11]',`${money(payload.current_v11_equity)} · ${pct(payload.current_v11_return)}`);set(section,'[data-v15-v14]',`${money(payload.current_v14_equity)} · ${pct(payload.current_v14_return)}`);set(section,'[data-v15-spy]',`${money(payload.current_spy_equity)} · ${pct(payload.current_spy_return)}`);set(section,'[data-v15-excess]',pct(payload.current_excess_spy));tone(section,'[data-v15-return]',payload.current_return);tone(section,'[data-v15-excess]',payload.current_excess_spy);
    const review=payload.review||{},minimumTrades=Number(review.minimum_completed_trades)||30,minimumBlocks=Number(review.minimum_active_blocks)||6,tradeCount=Number(payload.completed_exits)||0,activeBlocks=Number(review.active_blocks)||0,blockSessions=Number(review.block_sessions)||20,sessionProgress=Number(review.sessions_toward_next_block)||0;
    set(section,'[data-v15-trade-progress]',`${tradeCount} / ${minimumTrades}`);set(section,'[data-v15-block-progress]',`${activeBlocks} / ${minimumBlocks}`);set(section,'[data-v15-session-progress]',`${sessionProgress} / ${blockSessions} sessions`);progress(section,'[data-v15-trade-bar]',tradeCount,minimumTrades);progress(section,'[data-v15-block-bar]',activeBlocks,minimumBlocks);progress(section,'[data-v15-session-bar]',sessionProgress,blockSessions);
    set(section,'[data-v15-decisions]',integer(payload.decisions));set(section,'[data-v15-trades]',integer(payload.trade_decisions));set(section,'[data-v15-cash]',integer(payload.cash_decisions));set(section,'[data-v15-exits]',integer(payload.completed_exits));set(section,'[data-v15-win-rate]',plainPct(payload.profitable_trade_rate));set(section,'[data-v15-drawdown]',plainPct(payload.max_drawdown));
    const latest=payload.latest_decision||{};set(section,'[data-v15-latest-session]',dateOnly(latest.session_date));set(section,'[data-v15-latest-action]',latest.session_date?(latest.trade?'TRADE':'CASH'):'AWAITING FIRST DECISION');set(section,'[data-v15-predicted]',pct(latest.predicted_topk_net_return,3));set(section,'[data-v15-threshold]',pct(latest.applied_threshold,3));set(section,'[data-v15-selected]',(latest.selected_symbols||[]).join(', ')||'—');set(section,'[data-v15-context]',dateOnly(latest.daily_context_session));
    set(section,'[data-v15-review-note]',payload.review_eligible?'All preregistered thresholds are currently satisfied; human review is still mandatory.':`${integer(payload.completed_exits)} / ${integer(review.minimum_completed_trades)} trades · ${integer(review.active_blocks)} / ${integer(review.minimum_active_blocks)} active blocks · automatic promotion disabled`);
    set(section,'[data-v15-health]',payload.current_run_health?'HEALTHY':'ATTENTION REQUIRED');set(section,'[data-v15-integrity]',payload.journal_integrity?'PASS':'FAIL');set(section,'[data-v15-prepared]',payload.prepared_model_verified?'VERIFIED IMMUTABLE':'NOT VERIFIED');set(section,'[data-v15-training]',`${dateOnly(payload.training_start_session)} → ${dateOnly(payload.training_end_session)}`);set(section,'[data-v15-training-rows]',integer(payload.training_rows));set(section,'[data-v15-model-sha]',shortSha(payload.latest_model_sha256));set(section,'[data-v15-contract-sha]',shortSha(payload.contract_sha256));set(section,'[data-v15-history]',payload.historical_results_are_v7_evidence?'YES':'NO');set(section,'[data-v15-paper]',payload.paper_shadow_only?'YES':'NO');set(section,'[data-v15-brokerage]',payload.brokerage_orders?'ON':'OFF');set(section,'[data-v15-promotion]',payload.automatic_promotion?'YES':'NO');set(section,'[data-v15-runner]',payload.runner_invoked?'YES':'NO');set(section,'[data-v15-network]',integer(payload.dashboard_network_requests));set(section,'[data-v15-isolation]',[payload.v8_modified,payload.v10_modified,payload.v11_modified,payload.v13_modified,payload.v14_modified].some(Boolean)?'ATTENTION':'NO');set(section,'[data-v15-checked]',dateTime(payload.checked_at_utc));set(section,'[data-v15-failures]',(payload.operational_failures||[]).map(statusText).join(' · ')||'NONE');set(section,'[data-v15-method]',payload.method_note||'V15 methodology unavailable.');
    renderEquity(section,payload);renderCoefficients(section,payload.coefficients);renderBlocks(section,review.blocks);renderGates(section,review);renderPositions(section,payload.open_positions);renderEvents(section,payload.event_history);
  }

  async function load(section) {
    try {
      const response=await fetch(API,{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw new Error(`HTTP ${response.status}`);render(section,await response.json());
    } catch(error) {
      const badge=section.querySelector('[data-v15-state]');badge.textContent='DASHBOARD DATA UNAVAILABLE';badge.classList.add('alert');set(section,'[data-v15-method]',`The read-only V15 endpoint could not be loaded: ${error.message}`);
    }
    window.clearTimeout(refreshTimer);refreshTimer=window.setTimeout(()=>{if(!document.hidden)load(section)},15000);
  }

  document.addEventListener('visibilitychange',()=>{const section=document.getElementById(panelId);if(section&&!document.hidden)load(section)});
  mount();
})();
