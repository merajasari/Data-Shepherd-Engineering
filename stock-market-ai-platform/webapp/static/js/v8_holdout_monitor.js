(() => {
  const core = document.createElement('script');
  core.src = '/static/js/v8_holdout_monitor_core.js';
  core.onload = () => {
    const help = document.querySelector('.v4-dashboard .v4-help');
    if (!help) return;
    help.innerHTML = `
      <div class="label">WHAT YOU'RE SEEING — V8</div>
      <ul>
        <li><strong>V8 Frozen</strong> is the selected DISTANCE_ONLY cross-sectional strategy. It ranks the frozen stock universe and selects the Top 10 names for each decision cohort.</li>
        <li>The V8 portfolio contract is <strong>100% stock basket</strong>: 10 selected stocks at a 10% target weight each. SPY is the benchmark, not a permanent portfolio allocation.</li>
        <li>Each cohort enters at the <strong>next market open</strong> after the decision and is held for <strong>5 trading sessions</strong>. Five staggered cohort offsets (0–4) allow overlapping 5-session holding cycles.</li>
        <li>Performance includes the frozen <strong>10-bps modeled trading-cost</strong> assumption. Historical V8 charts are research evidence and remain separate from the genuine forward holdout.</li>
        <li>The formal append-only V8 forward holdout begins <strong>September 1, 2026</strong>. Pre-boundary observations are never retroactively counted as holdout performance. Simulation only — no real brokerage orders are placed.</li>
      </ul>`;
  };
  core.onerror = () => console.error('Unable to load V8 dashboard core.');
  document.head.appendChild(core);
})();
