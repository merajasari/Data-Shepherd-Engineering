(() => {
  if (window.location.pathname !== '/dashboard') return;

  const findCardByLabel = label => Array.from(document.querySelectorAll('section.card, .card')).find(card =>
    card.querySelector(':scope > .label')?.textContent?.trim() === label
  );

  const frozen = findCardByLabel('FROZEN V5 MODEL CONTRACT');
  if (frozen) {
    frozen.innerHTML = `
      <div class="label">FROZEN V8 MODEL CONTRACT</div>
      <h3>V8 DISTANCE_ONLY</h3>
      <div class="muted">Frozen cross-sectional ranking strategy selected before the forward holdout. The production contract is fixed: Top-10 selection, 5-session holding horizon, next-open execution, five staggered cohort offsets, SPY-relative evaluation, and 10-bps modeled trading costs.</div>
      <div class="grid grid-3" style="margin-top:16px">
        <div class="metric"><span>MODEL</span><strong>DISTANCE_ONLY</strong></div>
        <div class="metric"><span>TOP N</span><strong>10</strong></div>
        <div class="metric"><span>HOLD</span><strong>5 SESSIONS</strong></div>
        <div class="metric"><span>EXECUTION</span><strong>NEXT OPEN</strong></div>
        <div class="metric"><span>COHORT OFFSETS</span><strong>0–4</strong></div>
        <div class="metric"><span>TRADING COST</span><strong>10 BPS</strong></div>
      </div>
      <div class="warning" style="margin-top:16px">V8 scores are cross-sectional ranking signals, not calibrated probabilities or guaranteed returns. The frozen contract is not refit or tuned from forward holdout results.</div>`;
  }

  const portfolio = findCardByLabel('PORTFOLIO CONTRACT');
  if (portfolio) {
    portfolio.innerHTML = `
      <div class="label">V8 PORTFOLIO CONTRACT</div>
      <h3>100% Top-10 Stock Basket</h3>
      <div class="muted">The frozen V8 portfolio allocates equally across the selected Top 10 stocks. SPY is used only as the benchmark for relative-performance evaluation and is not a permanent portfolio holding.</div>
      <div class="metric" style="margin-top:16px"><span>SELECTED STOCKS</span><strong>10</strong></div>
      <div class="metric" style="margin-top:10px"><span>EACH SELECTED STOCK</span><strong>10%</strong></div>
      <div class="metric" style="margin-top:10px"><span>SPY PORTFOLIO WEIGHT</span><strong>0%</strong></div>
      <div class="metric" style="margin-top:10px"><span>SPY ROLE</span><strong>BENCHMARK ONLY</strong></div>
      <div class="metric" style="margin-top:10px"><span>HOLDING / EXECUTION</span><strong>5 SESSIONS · NEXT OPEN</strong></div>`;
  }

  // Remove the standalone bottom-of-page V8 holdout summary/curve. Other V8
  // holdout interaction visualizations elsewhere on Model Research remain intact.
  const removeBottomHoldout = () => {
    const root = document.getElementById('v8-holdout-monitor');
    if (root) root.remove();
    for (const section of document.querySelectorAll('.shell > section.card, .shell > section')) {
      const label = section.querySelector(':scope > .label')?.textContent?.trim() || '';
      const heading = section.querySelector(':scope > h2, :scope > h3')?.textContent?.trim() || '';
      if (/V8 FROZEN FORWARD HOLDOUT/i.test(`${label} ${heading}`)) section.remove();
    }
  };

  removeBottomHoldout();
  const observer = new MutationObserver(removeBottomHoldout);
  observer.observe(document.querySelector('.shell') || document.body, {childList:true, subtree:true});
  window.setTimeout(() => observer.disconnect(), 5000);
})();