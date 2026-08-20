(() => {
  // Remove only the compact V4 paper-portfolio chart shown beside the dashboard metrics.
  // Do not touch .v4-chart-card, which is repurposed by v4_equity_chart.js for the
  // MODEL PERFORMANCE COMPARISON panel.
  const removeCompactV4Equity = () => {
    const compact = document.getElementById('v4-compact-equity-card');
    if (compact) {
      compact.remove();
      return true;
    }
    return false;
  };

  // Keep the V8 selected-stock rank signal directly below the compact
  // PORTFOLIO EQUITY OVER TIME — LATEST MODEL card on Model Research.
  const moveV8RankSignal = () => {
    const latestModelEquity = document.getElementById('v8-compact-equity-card');
    if (!latestModelEquity) return false;

    const signal = Array.from(document.querySelectorAll('.card')).find(node => {
      const label = node.querySelector(':scope > .label')?.textContent?.trim() || '';
      return label === 'V8 5-DAY RELATIVE-RANK SIGNAL' || label === 'V5 5-DAY RELATIVE-RANK SIGNAL';
    });
    if (!signal) return false;

    if (latestModelEquity.nextElementSibling !== signal) {
      latestModelEquity.insertAdjacentElement('afterend', signal);
    }
    signal.style.marginTop = '20px';
    return true;
  };

  removeCompactV4Equity();
  moveV8RankSignal();

  // Both compact equity cards and the V8 replacement signal are injected by
  // other dashboard scripts, so watch briefly for their final DOM state and
  // enforce only these two layout rules.
  const layoutObserver = new MutationObserver(() => {
    removeCompactV4Equity();
    moveV8RankSignal();
  });
  layoutObserver.observe(document.documentElement, { childList: true, subtree: true });
  window.setTimeout(() => layoutObserver.disconnect(), 12000);

  const sections = Array.from(document.querySelectorAll('section.card'));

  // The full 100-stock V8 ranking board is no longer part of the Model Research UI.
  // Match both the current V8 label and the legacy V5 label in case another script
  // upgrades the label after initial render.
  const rankingBoard = sections.find(section => {
    const label = section.querySelector('.label')?.textContent?.trim() || '';
    const heading = section.querySelector('h2,h3')?.textContent?.trim() || '';
    return /100[- ]STOCK.*(?:V8|V5).*RANKING BOARD/i.test(`${label} ${heading}`) ||
           /(?:V8|V5).*100[- ]STOCK.*RANKING BOARD/i.test(`${label} ${heading}`);
  });
  if (rankingBoard) rankingBoard.remove();

  const remainingSections = Array.from(document.querySelectorAll('section.card'));
  const recentMarketData = remainingSections.find(section =>
    section.querySelector('.label')?.textContent?.trim() === 'RECENT MARKET DATA'
  );
  const v5Leaders = remainingSections.find(section =>
    section.querySelector('.label')?.textContent?.trim() === 'V5 LEADERS'
  );

  if (recentMarketData && v5Leaders) {
    v5Leaders.parentNode.insertBefore(recentMarketData, v5Leaders);
  }
})();
