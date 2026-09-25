(() => {
  const API = '/api/stock-eagle/autonomous-ml/prospective-v1';
  const panelId = 'stock-eagle-autonomous-ml-prospective-dashboard';
  const STARTING_EQUITY = 100000;
  let refreshTimer = null;

  const escapeHtml = value => String(value ?? '—')
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;')
    .replaceAll('"','&quot;')
    .replaceAll("'",'&#039;');

  const number = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };
  const money = value => number(value) == null
    ? '—'
    : new Intl.NumberFormat('en-US', {
        style:'currency',
        currency:'USD',
        maximumFractionDigits:2
      }).format(Number(value));
  const pct = value => number(value) == null
    ? '—'
    : `${Number(value) >= 0 ? '+' : ''}${(Number(value) * 100).toFixed(2)}%`;
  const plainPct = value => number(value) == null
    ? '—'
    : `${(Number(value) * 100).toFixed(1)}%`;
  const integer = value => number(value) == null
    ? '—'
    : Math.round(Number(value)).toLocaleString();
  const shortSha = value => value ? `${String(value).slice(0,8)}…${String(value).slice(-6)}` : '—';
  const dateOnly = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime())
      ? String(value)
      : d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
  };
  const dateTime = value => {
    if (!value) return '—';
    const d = new Date(value);
    return Number.isNaN(d.getTime())
      ? String(value)
      : d.toLocaleString(undefined,{
          year:'numeric',month:'short',day:'numeric',
          hour:'numeric',minute:'2-digit'
        });
  };
  const statusText = value => String(value || '—').replaceAll('_',' ');
  const toneClass = value => {
    const parsed = number(value);
    if (parsed == null || parsed === 0) return '';
    return parsed < 0 ? 'negative' : 'positive';
  };

  function installStyle() {
    if (document.getElementById('eagle-forward-style')) return;
    const style = document.createElement('style');
    style.id = 'eagle-forward-style';
    style.textContent = `
      .eagle-forward{display:grid;gap:18px}
      .eagle-hero,.eagle-card{border:1px solid rgba(120,155,205,.2);border-radius:20px;background:linear-gradient(145deg,rgba(13,28,49,.9),rgba(7,17,31,.94));padding:20px}
      .eagle-hero{border-color:rgba(54,216,255,.25)}
      .eagle-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
      .eagle-head h3{margin:5px 0 7px}
      .eagle-badge{flex:0 0 auto;padding:8px 11px;border-radius:999px;border:1px solid rgba(57,227,161,.3);background:rgba(57,227,161,.08);font-size:.7rem;font-weight:900;letter-spacing:.05em}
      .eagle-badge.waiting{border-color:rgba(239,197,107,.35);background:rgba(239,197,107,.08);color:var(--gold)}
      .eagle-badge.alert{border-color:rgba(255,122,217,.35);background:rgba(255,122,217,.08);color:#ff9adf}
      .eagle-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
      .eagle-grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
      .eagle-metric{padding:14px;border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(4,13,25,.36)}
      .eagle-metric span{display:block;color:var(--muted);font-size:.66rem;font-weight:900;letter-spacing:.07em}
      .eagle-metric strong{display:block;margin-top:6px;font-size:1rem;overflow-wrap:anywhere}
      .eagle-progress{height:9px;margin-top:9px;border-radius:99px;overflow:hidden;background:rgba(120,155,205,.14)}
      .eagle-progress i{display:block;height:100%;width:0;border-radius:inherit;background:linear-gradient(90deg,var(--cyan),var(--green))}
      .eagle-candidate{padding:18px;border:1px solid rgba(120,155,205,.18);border-radius:18px;background:rgba(4,13,25,.38)}
      .eagle-candidate h4{margin:5px 0 12px}
      .eagle-candidate .big{font-size:1.8rem;font-weight:950;margin:3px 0}
      .eagle-pair{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:12px}
      .eagle-pair>div{padding:10px;border-radius:11px;background:rgba(120,155,205,.06)}
      .eagle-pair span{display:block;color:var(--muted);font-size:.64rem;font-weight:850;letter-spacing:.05em}
      .eagle-pair strong{display:block;margin-top:4px;font-size:.9rem}
      .eagle-chart-wrap{position:relative;height:330px;margin-top:12px}
      .eagle-chart-wrap svg{display:block;width:100%;height:100%}
      .eagle-empty{height:100%;display:grid;place-items:center;text-align:center;color:var(--muted);padding:28px;border:1px dashed rgba(120,155,205,.22);border-radius:15px}
      .eagle-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;color:var(--muted);font-size:.75rem}
      .eagle-legend i{display:inline-block;width:18px;height:3px;vertical-align:middle;margin-right:5px;border-radius:99px}
      .eagle-table{overflow:auto;margin-top:12px}
      .eagle-table table{width:100%;border-collapse:collapse;min-width:760px}
      .eagle-table th,.eagle-table td{padding:10px 9px;border-bottom:1px solid rgba(120,155,205,.12);text-align:left;font-size:.78rem;vertical-align:top}
      .eagle-table th{color:var(--muted);font-size:.65rem;letter-spacing:.06em;text-transform:uppercase}
      .eagle-pill{display:inline-block;padding:5px 8px;border-radius:999px;border:1px solid rgba(54,216,255,.2);background:rgba(54,216,255,.06);font-size:.66rem;font-weight:900}
      .eagle-note{padding:13px 14px;border-radius:13px;border:1px solid rgba(239,197,107,.22);background:rgba(239,197,107,.06);color:var(--gold);line-height:1.5}
      .eagle-integrity{border:1px solid rgba(120,155,205,.18);border-radius:16px;padding:14px 16px;background:rgba(4,13,25,.28)}
      .eagle-integrity summary{cursor:pointer;font-weight:900}
      .eagle-integrity .eagle-grid{margin-top:14px}
      @media(max-width:1050px){.eagle-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.eagle-grid-3{grid-template-columns:1fr}}
      @media(max-width:650px){.eagle-grid{grid-template-columns:1fr}.eagle-head{display:block}.eagle-badge{display:inline-block;margin-top:9px}.eagle-chart-wrap{height:280px}}
    `;
    document.head.appendChild(style);
  }

  function mount() {
    const target = document.querySelector('[data-research-content="eagle"]');
    if (!target || document.getElementById(panelId)) return;
    installStyle();
    const section = document.createElement('section');
    section.id = panelId;
    section.className = 'eagle-forward';
    section.innerHTML = `
      <section class="eagle-hero">
        <div class="eagle-head">
          <div>
            <div class="label">FIXED-SNAPSHOT PROSPECTIVE EVIDENCE · OCT 1+ ONLY</div>
            <h3>StockEagle250 Autonomous ML V1 / V2 / V3</h3>
            <p class="muted">One shared append-only decision clock compares three immutable learned snapshots. This page is read-only and never invokes the runner.</p>
          </div>
          <div class="eagle-badge waiting" data-eagle-state>LOADING</div>
        </div>
        <div class="eagle-grid" style="margin-top:16px">
          <div class="eagle-metric"><span>PROSPECTIVE START</span><strong data-eagle-start>—</strong></div>
          <div class="eagle-metric"><span>LATEST COMPLETED SESSION</span><strong data-eagle-session>—</strong></div>
          <div class="eagle-metric"><span>FORMAL REVIEW</span><strong data-eagle-review>—</strong></div>
          <div class="eagle-metric"><span>LAST CHECKED</span><strong data-eagle-checked>—</strong></div>
        </div>
      </section>

      <section class="eagle-card">
        <div class="label">FORWARD COLLECTION PROGRESS</div>
        <div class="eagle-grid" style="margin-top:12px">
          <div class="eagle-metric"><span>DECISION BATCHES</span><strong data-eagle-decisions>0</strong></div>
          <div class="eagle-metric"><span>ENTRY BATCHES</span><strong data-eagle-entries>0</strong></div>
          <div class="eagle-metric"><span>EXIT BATCHES</span><strong data-eagle-exits>0</strong></div>
          <div class="eagle-metric"><span>MISSED DECISIONS</span><strong data-eagle-missed>0</strong></div>
        </div>
        <div class="eagle-grid" style="margin-top:12px">
          <div class="eagle-metric">
            <span>COMPLETED COHORTS / MODEL</span>
            <strong data-eagle-cohorts>0 / 60</strong>
            <div class="eagle-progress"><i data-eagle-cohort-bar></i></div>
          </div>
          <div class="eagle-metric">
            <span>COMPLETE FIVE-SLEEVE BLOCKS</span>
            <strong data-eagle-blocks>0 / 12</strong>
            <div class="eagle-progress"><i data-eagle-block-bar></i></div>
          </div>
          <div class="eagle-metric"><span>DECISION STATUS</span><strong data-eagle-decision-status>—</strong></div>
          <div class="eagle-metric"><span>SAME DECISION CLOCK</span><strong>YES · V1 / V2 / V3</strong></div>
        </div>
      </section>

      <section class="eagle-grid-3" data-eagle-candidates></section>

      <section class="eagle-card">
        <div class="eagle-head">
          <div><div class="label">UNSEEN FORWARD EQUITY</div><h3>$100,000 normalized comparison</h3></div>
          <div class="muted">Completed EXIT_BATCH evidence only</div>
        </div>
        <div class="eagle-chart-wrap" data-eagle-chart></div>
        <div class="eagle-legend">
          <span><i style="background:#36d8ff"></i>V1</span>
          <span><i style="background:#39e3a1"></i>V2</span>
          <span><i style="background:#ff7ad9"></i>V3</span>
          <span><i style="background:#a78bfa"></i>SPY</span>
        </div>
      </section>

      <section class="eagle-card">
        <div class="eagle-head">
          <div><div class="label">LATEST SHARED DECISION</div><h3>Top-10 baskets and learned allocation</h3></div>
          <div class="muted" data-eagle-latest-decision>Waiting for Oct. 1+</div>
        </div>
        <div class="eagle-table" data-eagle-latest-table></div>
      </section>

      <section class="eagle-card">
        <div class="eagle-head">
          <div><div class="label">APPEND-ONLY EVIDENCE JOURNAL</div><h3>Decision, entry, exit, and missed-session evidence</h3></div>
          <div class="muted">No historical reconstruction or late decision backfill</div>
        </div>
        <div class="eagle-table" data-eagle-events></div>
      </section>

      <details class="eagle-integrity" open>
        <summary>Snapshot identity, evidence boundary &amp; authority</summary>
        <div class="eagle-grid">
          <div class="eagle-metric"><span>TRAINING ROWS</span><strong data-eagle-training-rows>—</strong></div>
          <div class="eagle-metric"><span>TRAINING DECISION END</span><strong data-eagle-training-end>—</strong></div>
          <div class="eagle-metric"><span>MAX TRAINING TARGET END</span><strong data-eagle-target-end>—</strong></div>
          <div class="eagle-metric"><span>SEALED GUARD BAND</span><strong data-eagle-guard>—</strong></div>
          <div class="eagle-metric"><span>CONTRACT SHA-256</span><strong data-eagle-contract>—</strong></div>
          <div class="eagle-metric"><span>DEVELOPMENT PANEL SHA-256</span><strong data-eagle-panel>—</strong></div>
          <div class="eagle-metric"><span>RETRAINING</span><strong data-eagle-retraining>OFF</strong></div>
          <div class="eagle-metric"><span>AUTOMATIC PROMOTION</span><strong data-eagle-promotion>OFF</strong></div>
          <div class="eagle-metric"><span>BROKERAGE / LIVE</span><strong data-eagle-live>OFF / OFF</strong></div>
          <div class="eagle-metric"><span>DASHBOARD INVOKED RUNNER</span><strong data-eagle-runner>NO</strong></div>
        </div>
        <div class="eagle-note" style="margin-top:14px" data-eagle-method>Loading prospective methodology.</div>
      </details>
    `;
    target.appendChild(section);
    load(section);
  }

  function set(section, selector, value) {
    const node = section.querySelector(selector);
    if (node) node.textContent = value;
  }
  function progress(section, selector, value, goal) {
    const bar = section.querySelector(selector);
    if (!bar) return;
    const current = Math.max(0, Number(value) || 0);
    bar.style.width = `${Math.min(100, current / Math.max(1, goal) * 100)}%`;
  }

  function renderCandidates(section, payload) {
    const host = section.querySelector('[data-eagle-candidates]');
    const rows = Array.isArray(payload.candidates) ? payload.candidates : [];
    if (!rows.length) {
      host.innerHTML = '<div class="eagle-empty">Snapshot metadata is unavailable.</div>';
      return;
    }
    host.innerHTML = rows.map(row => {
      const latestAllocation = row.latest_active_weight == null
        ? 'Waiting for first decision'
        : `Active ${plainPct(row.latest_active_weight)} · SPY ${plainPct(row.latest_spy_weight)} · Cash ${plainPct(row.latest_cash_fraction)}`;
      const basket = Array.isArray(row.latest_selected_symbols) && row.latest_selected_symbols.length
        ? row.latest_selected_symbols.join(', ')
        : 'No prospective basket yet';
      return `
        <article class="eagle-candidate">
          <div class="label">${escapeHtml(row.label)}</div>
          <h4>${escapeHtml(statusText(row.allocation_policy))}</h4>
          <div class="big">${money(row.normalized_equity)}</div>
          <div class="${toneClass(row.total_net_return)}"><strong>${pct(row.total_net_return)}</strong> prospective return</div>
          <div class="eagle-pair">
            <div><span>EXCESS VS SPY</span><strong class="${toneClass(row.excess_vs_spy)}">${pct(row.excess_vs_spy)}</strong></div>
            <div><span>MAX DRAWDOWN</span><strong class="${toneClass(row.maximum_drawdown)}">${pct(row.maximum_drawdown)}</strong></div>
            <div><span>STRESS 20 BPS</span><strong class="${toneClass(row.stress_20bps_total_net_return)}">${pct(row.stress_20bps_total_net_return)}</strong></div>
            <div><span>EXCESS HIT RATE</span><strong>${plainPct(row.positive_excess_vs_spy_cohort_fraction)}</strong></div>
            <div><span>MEAN ACTIVE WEIGHT</span><strong>${plainPct(row.mean_active_weight)}</strong></div>
            <div><span>COMPLETED COHORTS</span><strong>${integer(row.completed_cohorts)}</strong></div>
          </div>
          <div class="eagle-note" style="margin-top:12px"><strong>Latest allocation:</strong> ${escapeHtml(latestAllocation)}<br><strong>Basket:</strong> ${escapeHtml(basket)}</div>
          <div class="muted" style="margin-top:10px;font-size:.75rem">Snapshot ${escapeHtml(shortSha(row.snapshot_sha256))} · ${integer(row.learned_component_count)} learned components · ${integer(row.meta_oos_training_sessions)} inner-OOS meta sessions</div>
        </article>
      `;
    }).join('');
  }

  function renderChart(section, payload) {
    const host = section.querySelector('[data-eagle-chart]');
    const raw = Array.isArray(payload.curve) ? payload.curve : [];
    const startTime = new Date(payload.prospective_start_utc || Date.now()).getTime();
    const rows = raw.map((row,index) => ({
      ...row,
      time: row.timestamp_utc ? new Date(row.timestamp_utc).getTime() : startTime + index
    })).filter(row => Number.isFinite(row.time));

    if (rows.length <= 1) {
      host.innerHTML = `<div class="eagle-empty"><div><strong>Waiting for completed prospective cohorts</strong><br><br>The chart begins after the first Oct. 1+ DECISION_BATCH enters at the next open and completes its fifth-session close. Until then all three fixed snapshots remain at ${money(STARTING_EQUITY)}.</div></div>`;
      return;
    }

    const W=960,H=330,p={l:70,r:24,t:20,b:42};
    const keys=[
      ['autonomous_ml_v1_normalized','#36d8ff'],
      ['autonomous_ml_v2_normalized','#39e3a1'],
      ['autonomous_ml_v3_normalized','#ff7ad9'],
      ['spy_normalized','#a78bfa']
    ];
    const values=rows.flatMap(row=>keys.map(([key])=>number(row[key])).filter(value=>value!=null));
    let lo=Math.min(STARTING_EQUITY,...values),hi=Math.max(STARTING_EQUITY,...values);
    const span=Math.max(250,hi-lo);lo-=span*.15;hi+=span*.15;
    const minTime=Math.min(...rows.map(row=>row.time)),maxTime=Math.max(...rows.map(row=>row.time));
    const x=value=>p.l+(W-p.l-p.r)*(maxTime===minTime?0:(value-minTime)/(maxTime-minTime));
    const y=value=>p.t+(H-p.t-p.b)*(1-(value-lo)/(hi-lo));
    const grid=[0,.25,.5,.75,1].map(ratio=>{
      const value=hi-(hi-lo)*ratio,yy=p.t+(H-p.t-p.b)*ratio;
      return `<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="#60708a" opacity=".2"/><text x="${p.l-8}" y="${yy+4}" fill="#91a6c2" font-size="10" text-anchor="end">$${Math.round(value/1000)}k</text>`;
    }).join('');
    const lines=keys.map(([key,color])=>{
      const points=rows.filter(row=>number(row[key])!=null).map(row=>`${x(row.time)},${y(Number(row[key]))}`).join(' ');
      return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>`;
    }).join('');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Prospective normalized equity for Autonomous ML V1, V2, V3 and SPY">${grid}<line x1="${p.l}" y1="${y(STARTING_EQUITY)}" x2="${W-p.r}" y2="${y(STARTING_EQUITY)}" stroke="#91a6c2" stroke-dasharray="5 5" opacity=".5"/>${lines}<text x="${(p.l+W-p.r)/2}" y="${H-6}" fill="#91a6c2" font-size="10" text-anchor="middle">Completed prospective five-session cohort evidence</text></svg>`;
  }

  function renderLatestDecision(section, payload) {
    set(section,'[data-eagle-latest-decision]',payload.latest_decision_timestamp_utc ? dateTime(payload.latest_decision_timestamp_utc) : 'Waiting for Oct. 1+');
    const host=section.querySelector('[data-eagle-latest-table]');
    const rows=Array.isArray(payload.candidates) ? payload.candidates : [];
    if (!payload.latest_decision_timestamp_utc) {
      host.innerHTML='<div class="eagle-empty" style="min-height:120px">No prospective decision exists yet. The first eligible same-day post-close decision can occur on or after Oct. 1.</div>';
      return;
    }
    host.innerHTML=`<table><thead><tr><th>Candidate</th><th>Active</th><th>SPY</th><th>Cash</th><th>Top-10 basket</th><th>Snapshot</th></tr></thead><tbody>${rows.map(row=>`<tr><td><strong>${escapeHtml(row.label)}</strong></td><td>${plainPct(row.latest_active_weight)}</td><td>${plainPct(row.latest_spy_weight)}</td><td>${plainPct(row.latest_cash_fraction)}</td><td>${escapeHtml((row.latest_selected_symbols||[]).join(', ')||'—')}</td><td>${escapeHtml(shortSha(row.snapshot_sha256))}</td></tr>`).join('')}</tbody></table>`;
  }

  function renderEvents(section, payload) {
    const host=section.querySelector('[data-eagle-events]');
    const rows=Array.isArray(payload.event_history) ? payload.event_history : [];
    if (!rows.length) {
      host.innerHTML='<div class="eagle-empty" style="min-height:120px">The prospective append-only journal is empty. That is expected before the Oct. 1 boundary.</div>';
      return;
    }
    host.innerHTML=`<table><thead><tr><th>Event</th><th>Time</th><th>Cohort</th><th>V1</th><th>V2</th><th>V3</th><th>Evidence note</th></tr></thead><tbody>${rows.map(row=>{
      const candidates=row.candidates||{};
      const cell=id=>{
        const c=candidates[id]||{};
        if(row.event_type==='DECISION_BATCH') return `${plainPct(c.active_weight)} active · ${escapeHtml((c.selected_symbols||[]).slice(0,3).join(', ')||'—')}${(c.selected_symbols||[]).length>3?'…':''}`;
        if(row.event_type==='EXIT_BATCH') return `${pct(c.primary_net_return)} · excess ${pct(c.excess_vs_spy)}`;
        return '—';
      };
      const note=row.event_type==='MISSED_DECISION'
        ? 'Missed window preserved · never backfilled'
        : row.reason || '';
      return `<tr><td><span class="eagle-pill">${escapeHtml(row.event_type)}</span></td><td>${escapeHtml(dateTime(row.timestamp_utc))}</td><td>${escapeHtml(row.cohort_offset ?? '—')}</td><td>${cell('autonomous_ml_v1')}</td><td>${cell('autonomous_ml_v2')}</td><td>${cell('autonomous_ml_v3')}</td><td>${escapeHtml(note)}</td></tr>`;
    }).join('')}</tbody></table>`;
  }

  function render(section, payload) {
    const state = statusText(payload.state);
    const badge = section.querySelector('[data-eagle-state]');
    badge.textContent = state;
    badge.classList.toggle('waiting', /WAITING/.test(state));
    badge.classList.toggle('alert', /ERROR|CORRUPT|BLOCKED/.test(state));

    set(section,'[data-eagle-start]',dateOnly(payload.prospective_start_utc));
    set(section,'[data-eagle-session]',dateOnly(payload.latest_completed_session_utc));
    set(section,'[data-eagle-review]',statusText(payload.formal_review_status));
    set(section,'[data-eagle-checked]',dateTime(payload.checked_at_utc));
    set(section,'[data-eagle-decisions]',integer(payload.decision_batches));
    set(section,'[data-eagle-entries]',integer(payload.entry_batches));
    set(section,'[data-eagle-exits]',integer(payload.exit_batches));
    set(section,'[data-eagle-missed]',integer(payload.missed_decision_count));
    set(section,'[data-eagle-decision-status]',statusText(payload.decision_status));
    set(section,'[data-eagle-cohorts]',`${integer(payload.completed_cohorts_per_candidate)} / ${integer(payload.formal_review_minimum_completed_cohorts)}`);
    set(section,'[data-eagle-blocks]',`${integer(payload.complete_five_sleeve_blocks)} / ${integer(payload.formal_review_minimum_complete_blocks)}`);
    progress(section,'[data-eagle-cohort-bar]',payload.completed_cohorts_per_candidate,payload.formal_review_minimum_completed_cohorts||60);
    progress(section,'[data-eagle-block-bar]',payload.complete_five_sleeve_blocks,payload.formal_review_minimum_complete_blocks||12);

    set(section,'[data-eagle-training-rows]',integer(payload.training_rows));
    set(section,'[data-eagle-training-end]',dateOnly(payload.training_decision_end_utc));
    set(section,'[data-eagle-target-end]',dateOnly(payload.training_target_endpoint_max_utc));
    set(section,'[data-eagle-guard]',`${dateOnly(payload.sealed_guard_band_start_utc)} → ${dateOnly(payload.sealed_guard_band_end_exclusive_utc)}`);
    set(section,'[data-eagle-contract]',shortSha(payload.contract_sha256));
    set(section,'[data-eagle-panel]',shortSha(payload.development_panel_sha256));
    set(section,'[data-eagle-retraining]',payload.retraining_enabled?'ON':'OFF');
    set(section,'[data-eagle-promotion]',payload.automatic_model_promotion?'ON':'OFF');
    set(section,'[data-eagle-live]',`${payload.brokerage_orders?'ON':'OFF'} / ${payload.live_execution_enabled?'ON':'OFF'}`);
    set(section,'[data-eagle-runner]',payload.dashboard_invoked_runner?'YES':'NO');
    set(section,'[data-eagle-method]',payload.method_note || 'Prospective methodology unavailable.');

    renderCandidates(section,payload);
    renderChart(section,payload);
    renderLatestDecision(section,payload);
    renderEvents(section,payload);
  }

  async function load(section) {
    try {
      const response = await fetch(API,{cache:'no-store',credentials:'same-origin'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(section, await response.json());
    } catch (error) {
      const badge = section.querySelector('[data-eagle-state]');
      if (badge) {
        badge.textContent='DASHBOARD DATA UNAVAILABLE';
        badge.classList.add('alert');
      }
      set(section,'[data-eagle-method]',`The read-only prospective endpoint could not be loaded: ${error.message}`);
    }
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      if (!document.hidden) load(section);
    },15000);
  }

  document.addEventListener('visibilitychange',()=>{
    const section=document.getElementById(panelId);
    if(section&&!document.hidden)load(section);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded',mount,{once:true});
  } else {
    mount();
  }
})();
