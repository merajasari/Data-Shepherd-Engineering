(() => {
  const core = document.createElement('script');
  core.src = '/static/js/v8_holdout_monitor_core.js';
  core.onload = () => {
    const help = document.querySelector('.v4-dashboard .v4-help');
    if (help) {
      help.innerHTML = `
        <div class="label">WHAT YOU'RE SEEING — V8</div>
        <ul>
          <li><strong>V8 Frozen</strong> is the selected DISTANCE_ONLY cross-sectional strategy. It ranks the frozen stock universe and selects the Top 10 names for each decision cohort.</li>
          <li>The V8 portfolio contract is <strong>100% stock basket</strong>: 10 selected stocks at a 10% target weight each. SPY is the benchmark, not a permanent portfolio allocation.</li>
          <li>Each cohort enters at the <strong>next market open</strong> after the decision and is held for <strong>5 trading sessions</strong>. Five staggered cohort offsets (0–4) allow overlapping 5-session holding cycles.</li>
          <li>Performance includes the frozen <strong>10-bps modeled trading-cost</strong> assumption. Historical V8 charts are research evidence and remain separate from the genuine forward holdout.</li>
          <li>The formal append-only V8 forward holdout begins <strong>September 1, 2026</strong>. Pre-boundary observations are never retroactively counted as holdout performance. Simulation only — no real brokerage orders are placed.</li>
        </ul>`;
    }

    const pnl = document.getElementById('v4-pnl-attribution');
    if (!pnl) return;
    pnl.id = 'v8-pnl-attribution';
    pnl.innerHTML = `
      <div class="v4-pnl-attribution-head">
        <div>
          <div class="label">V8 P&amp;L ATTRIBUTION</div>
          <h3>What is driving the frozen V8 strategy?</h3>
          <div class="muted">Attributes completed V8 cohort performance to the Top-10 stock basket, SPY-relative market edge, and the frozen 10-bps trading-cost assumption. SPY is benchmark-only — there is no SPY core allocation.</div>
        </div>
        <div><div class="muted" style="font-size:.72rem;font-weight:900;letter-spacing:.08em">COMPLETED COHORTS</div><div id="v8-pnl-completed" class="v4-pnl-total">—</div></div>
      </div>
      <div class="v4-pnl-metrics">
        <div class="metric"><span>MEAN NET RELATIVE RETURN</span><strong id="v8-pnl-edge">—</strong></div>
        <div class="metric"><span>NET RELATIVE HIT RATE</span><strong id="v8-pnl-hit">—</strong></div>
        <div class="metric"><span>DECISIONS</span><strong id="v8-pnl-decisions">—</strong></div>
        <div class="metric"><span>TRADING COST CONTRACT</span><strong>10 bps</strong></div>
        <div class="metric"><span>SPY ROLE</span><strong>BENCHMARK</strong></div>
      </div>
      <div class="v4-pnl-grid">
        <div class="v4-pnl-panel">
          <div class="label">ATTRIBUTION CONTRACT</div>
          <div class="v4-list" style="margin-top:12px">
            <div class="v4-list-row"><div class="v4-rank">10</div><div><strong>Equal-Weight Stocks</strong><div class="v4-company">Top 10 names at 10% target weight each</div></div></div>
            <div class="v4-list-row"><div class="v4-rank">5D</div><div><strong>Holding Horizon</strong><div class="v4-company">Next-open entry and 5-session exit</div></div></div>
            <div class="v4-list-row"><div class="v4-rank">5</div><div><strong>Staggered Cohorts</strong><div class="v4-company">Offsets 0–4 create overlapping holding cycles</div></div></div>
          </div>
        </div>
        <div class="v4-pnl-panel">
          <div class="label">FORWARD EVIDENCE STATUS</div>
          <div class="metric" style="margin-top:12px"><span>STATE</span><strong id="v8-pnl-state">LOADING</strong></div>
          <div class="metric" style="margin-top:10px"><span>HOLDOUT START</span><strong id="v8-pnl-start">SEP 1, 2026</strong></div>
          <div class="metric" style="margin-top:10px"><span>REAL BROKERAGE ORDERS</span><strong class="positive">NO</strong></div>
          <div class="v4-pnl-note">Attribution is reported only from genuine completed V8 forward cohorts once they exist. Historical development-era observations are not retroactively counted as holdout P&amp;L. Until Sep 1, 2026+ cohorts mature, the attribution metrics correctly remain empty rather than borrowing V4 or research-period results.</div>
        </div>
      </div>`;

    const fmtPct = v => v == null ? '—' : `${(Number(v) * 100).toFixed(3)}%`;
    async function refreshV8Pnl(){
      try {
        const r = await fetch('/api/v8/holdout',{cache:'no-store'});
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const d = await r.json();
        pnl.querySelector('#v8-pnl-completed').textContent = d.completed_cohorts ?? '—';
        pnl.querySelector('#v8-pnl-edge').textContent = fmtPct(d.mean_net_relative_return);
        pnl.querySelector('#v8-pnl-hit').textContent = fmtPct(d.net_relative_hit_rate);
        pnl.querySelector('#v8-pnl-decisions').textContent = d.decisions ?? '—';
        pnl.querySelector('#v8-pnl-state').textContent = String(d.state || 'UNKNOWN').replaceAll('_',' ');
        if (d.holdout_start_utc) pnl.querySelector('#v8-pnl-start').textContent = new Date(d.holdout_start_utc).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});
      } catch (e) {
        pnl.querySelector('#v8-pnl-state').textContent = 'DATA UNAVAILABLE';
        console.error('V8 P&L attribution failed:', e);
      }
    }
    refreshV8Pnl();
    setInterval(refreshV8Pnl,15000);
  };
  core.onerror = () => console.error('Unable to load V8 dashboard core.');
  document.head.appendChild(core);
})();
