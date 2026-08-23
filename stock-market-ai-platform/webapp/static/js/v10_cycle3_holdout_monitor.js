(() => {
  const money = value => value == null ? '—' : '$' + Number(value).toLocaleString(undefined,{maximumFractionDigits:0});
  const pct = value => value == null ? '—' : (Number(value) >= 0 ? '+' : '') + (Number(value) * 100).toFixed(2) + '%';
  const root = document.querySelector('#v10-confirmation-card') ||
    document.querySelector('#v8-launch-readiness-card') ||
    document.querySelector('#v8-holdout-monitor') ||
    document.querySelector('footer');
  if (!root || document.querySelector('#v10-cycle3-holdout-monitor')) return;

  const section = document.createElement('section');
  section.id = 'v10-cycle3-holdout-monitor';
  section.className = 'panel';
  section.style.marginTop = '18px';
  section.innerHTML = `
    <style>
      #v10-cycle3-holdout-monitor .c3-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}
      #v10-cycle3-holdout-monitor .c3-badge{border:1px solid rgba(54,216,255,.38);border-radius:999px;padding:8px 12px;color:#36d8ff;font-size:12px;font-weight:800;white-space:nowrap}
      #v10-cycle3-holdout-monitor .c3-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-top:16px}
      #v10-cycle3-holdout-monitor .c3-metric{padding:12px;border:1px solid rgba(145,166,194,.16);border-radius:10px;background:rgba(7,16,31,.38)}
      #v10-cycle3-holdout-monitor .c3-metric span{display:block;color:#91a6c2;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
      #v10-cycle3-holdout-monitor .c3-metric strong{display:block;margin-top:6px;font-size:16px}
      #v10-cycle3-holdout-monitor .c3-note{margin-top:14px;color:#91a6c2;font-size:12px;line-height:1.55}
      #v10-cycle3-holdout-monitor svg{display:block;width:100%;height:210px;margin-top:14px}
      @media(max-width:900px){#v10-cycle3-holdout-monitor .c3-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.c3-head{flex-direction:column}}
    </style>
    <div class="c3-head"><div><div class="label">FROZEN FUTURE EVIDENCE — SEPARATE FROM RECONSTRUCTION</div><h2>V10 Cycle 3 Fresh Forward Holdout</h2><p class="muted">The selected Cycle 3 candidate is frozen now; genuine observations begin January 4, 2027.</p></div><div class="c3-badge" data-c3-state>LOADING</div></div>
    <div class="c3-grid">
      <div class="c3-metric"><span>Evidence</span><strong data-c3-evidence>—</strong></div>
      <div class="c3-metric"><span>Decisions</span><strong data-c3-decisions>—</strong></div>
      <div class="c3-metric"><span>Entries</span><strong data-c3-entries>—</strong></div>
      <div class="c3-metric"><span>Completed</span><strong data-c3-exits>—</strong></div>
      <div class="c3-metric"><span>Cycle 3 Return</span><strong data-c3-return>—</strong></div>
      <div class="c3-metric"><span>SPY Return</span><strong data-c3-spy>—</strong></div>
      <div class="c3-metric"><span>Operations</span><strong data-c3-operations>—</strong></div>
      <div class="c3-metric"><span>Last Health Check</span><strong data-c3-health-time>—</strong></div>
    </div>
    <div data-c3-chart></div>
    <div class="c3-note" data-c3-note>Loading frozen holdout status…</div>
  `;
  root.insertAdjacentElement('afterend', section);

  const set = (selector, value) => { const node=section.querySelector(selector); if(node) node.textContent=value; };
  const renderChart = curve => {
    const host=section.querySelector('[data-c3-chart]');
    if (!curve || curve.length < 2) { host.innerHTML=''; return; }
    const W=900,H=210,p={l:60,r:24,t:20,b:30};
    const values=curve.flatMap(d=>[Number(d.strategy_normalized),Number(d.spy_normalized)]);
    let lo=Math.min(...values,100000),hi=Math.max(...values,100000),span=Math.max(hi-lo,100);
    lo-=span*.12;hi+=span*.12;
    const x=i=>p.l+(W-p.l-p.r)*i/(curve.length-1),y=v=>p.t+(H-p.t-p.b)*(1-(v-lo)/(hi-lo));
    const points=key=>curve.map((d,i)=>x(i)+','+y(Number(d[key]))).join(' ');
    host.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="V10 Cycle 3 forward equity compared with SPY"><line x1="${p.l}" y1="${y(100000)}" x2="${W-p.r}" y2="${y(100000)}" stroke="#60708a" stroke-dasharray="5 5"/><polyline points="${points('strategy_normalized')}" fill="none" stroke="#36d8ff" stroke-width="3"/><polyline points="${points('spy_normalized')}" fill="none" stroke="#f5c451" stroke-width="2.5"/></svg>`;
  };

  fetch('/api/v10/cycle3/holdout',{credentials:'same-origin'})
    .then(response => { if(!response.ok) throw new Error('HTTP '+response.status); return response.json(); })
    .then(data => {
      set('[data-c3-state]', String(data.state||'UNKNOWN').replaceAll('_',' '));
      set('[data-c3-evidence]', String(data.evidence_status||'UNKNOWN').replaceAll('_',' '));
      set('[data-c3-decisions]', data.decisions ?? 0);
      set('[data-c3-entries]', data.entries ?? 0);
      set('[data-c3-exits]', data.completed_cohorts ?? 0);
      set('[data-c3-return]', pct(data.strategy_total_return));
      set('[data-c3-spy]', pct(data.spy_total_return));
      set('[data-c3-operations]', String(data.operational_status||'UNKNOWN').replaceAll('_',' '));
      const healthTime=data.operational_checked_at_utc ? new Date(data.operational_checked_at_utc).toLocaleString() : '—';
      set('[data-c3-health-time]', healthTime);
      const failures=(data.operational_failures||[]).length;
      set('[data-c3-note]', `${data.method_note} Operations: ${data.operational_status||'UNKNOWN'}${failures ? ` · ${failures} active alert(s)` : ''} · scheduler every 5 minutes. Frozen SHA: ${data.frozen_sha256}. Brokerage orders: OFF.`);
      renderChart(data.curve);
    })
    .catch(error => {
      set('[data-c3-state]','STATUS UNAVAILABLE');
      set('[data-c3-note]','The lightweight Cycle 3 status endpoint could not be reached. No runner was invoked. '+error.message);
    });
})();
