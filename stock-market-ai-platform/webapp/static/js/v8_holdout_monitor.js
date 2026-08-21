(() => {
  const loadScript = src => new Promise((resolve,reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve();
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`Unable to load ${src}`));
    document.head.appendChild(s);
  });

  const core = document.createElement('script');
  core.src = '/static/js/v8_holdout_monitor_core.js';
  core.onload = async () => {
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

    try {
      await loadScript('/static/js/v8_pnl_visual.js');
      await loadScript('/static/js/v8_leaders.js');
      await loadScript('/static/js/v8_ranking_board.js');
      await loadScript('/static/js/v8_contract_cleanup.js');
      await loadScript('/static/js/v8_dashboard_fixes.js');
      await loadScript('/static/js/v8_dashboard_final_polish.js');
      await loadScript('/static/js/v8_launch_readiness.js');
      await loadScript('/static/js/v10_confirmation_dashboard.js');
    } catch (e) {
      console.error('Unable to load one or more V8/V10 dashboard enhancements.', e);
    }
  };
  core.onerror = () => console.error('Unable to load V8 dashboard core.');
  document.head.appendChild(core);
})();
