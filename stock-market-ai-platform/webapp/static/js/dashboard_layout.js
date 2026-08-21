(() => {
  // Move the selected-stock technical indicators (RSI, moving averages,
  // volatility and volume ratio) out of Model Research and into Live Stock Viewer.
  const technicalIndicators = Array.from(document.querySelectorAll('section.grid.metrics')).find(section => {
    const labels = Array.from(section.querySelectorAll('.metric > span')).map(node => node.textContent.trim());
    return ['RSI 14','SMA 20','SMA 50','SMA 200','20D VOL','VOLUME RATIO'].every(label => labels.includes(label));
  });

  if (technicalIndicators) {
    technicalIndicators.classList.add('ds-technical-indicators', 'ds-live-stock-keep');
    technicalIndicators.setAttribute('data-selected-stock-indicators', 'true');

    // Keep the indicator strip beside the selected-stock market context on the
    // Live Stock Viewer. The server-rendered values are tied to the symbol in
    // /dashboard?view=live&symbol=..., so every search/dropdown selection reloads
    // this strip with the newly selected stock's values.
    const marketSection = document.querySelector('.ds-market-section');
    if (marketSection && marketSection.nextElementSibling !== technicalIndicators) {
      marketSection.insertAdjacentElement('afterend', technicalIndicators);
    }
  }

  const technicalStyle = document.createElement('style');
  technicalStyle.id = 'ds-technical-indicators-placement';
  technicalStyle.textContent = `
    body.ds-model-research-view .ds-technical-indicators{display:none!important}
    body.ds-live-stock-view .ds-technical-indicators{display:grid!important}
    body.ds-live-stock-view .ds-live-comparison-stack{display:grid!important;grid-template-columns:1fr!important;gap:22px!important}
    body.ds-live-stock-view .ds-live-comparison-stack > #ds-top-live-comparison,
    body.ds-live-stock-view .ds-live-comparison-stack > .ds-live-viewer-card{grid-column:1/-1!important;width:100%!important}
  `;
  document.getElementById(technicalStyle.id)?.remove();
  document.head.appendChild(technicalStyle);

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

  // On Live Stock Viewer, keep the stock selector/search card directly below the
  // Top Live Stock Comparison chart and remove the redundant compact MARKET card.
  // Wait until the comparison chart has been injected before removing MARKET,
  // because the comparison renderer uses that card as its initial insertion anchor.
  const arrangeLiveStockViewer = () => {
    if (!document.body.classList.contains('ds-live-stock-view')) return false;

    const comparison = document.getElementById('ds-top-live-comparison');
    if (!comparison) return false;

    const cards = Array.from(document.querySelectorAll('.card'));
    const liveViewer = cards.find(node => {
      if (node === comparison) return false;
      const label = node.querySelector(':scope > .label')?.textContent?.trim() || '';
      const heading = node.querySelector(':scope > h1,:scope > h2,:scope > h3')?.textContent?.trim() || '';
      return label === 'LIVE STOCK VIEWER' || heading === 'LIVE STOCK VIEWER' || /LIVE STOCK VIEWER/i.test(`${label} ${heading}`);
    });

    const market = cards.find(node => {
      const label = node.querySelector(':scope > .label')?.textContent?.trim() || '';
      return label === 'MARKET' || node.classList.contains('ds-market-section');
    });

    const stack = comparison.parentElement;
    if (stack) {
      stack.classList.remove('ds-market-comparison-grid');
      stack.classList.add('ds-live-comparison-stack');
    }

    if (liveViewer && stack) {
      liveViewer.classList.add('ds-live-viewer-card', 'ds-live-stock-keep');
      if (comparison.nextElementSibling !== liveViewer) {
        comparison.insertAdjacentElement('afterend', liveViewer);
      }
    }

    if (market && market !== liveViewer) market.remove();
    return Boolean(liveViewer || market);
  };

  removeCompactV4Equity();
  moveV8RankSignal();
  arrangeLiveStockViewer();

  // Compact equity cards, the V8 replacement signal, and the live comparison card
  // are injected by other dashboard scripts, so watch briefly for their final DOM
  // state and enforce only these layout rules.
  const layoutObserver = new MutationObserver(() => {
    removeCompactV4Equity();
    moveV8RankSignal();
    arrangeLiveStockViewer();
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
