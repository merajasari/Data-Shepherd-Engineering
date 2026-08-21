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
    body.ds-live-stock-view .ds-live-comparison-stack > .ds-top-live-row,
    body.ds-live-stock-view .ds-live-comparison-stack > .ds-live-viewer-card{grid-column:1/-1!important;width:100%!important}
  `;
  document.getElementById(technicalStyle.id)?.remove();
  document.head.appendChild(technicalStyle);

  const removeCompactV4Equity = () => {
    const compact = document.getElementById('v4-compact-equity-card');
    if (compact) {
      compact.remove();
      return true;
    }
    return false;
  };

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

  const findFullLiveViewer = () => {
    const heading = Array.from(document.querySelectorAll('h1,h2,h3,h4')).find(node =>
      node.textContent.trim() === 'Search and Inspect Live Stocks'
    );

    if (heading) {
      const panel = heading.closest('.card, section, article');
      if (panel) return panel;
    }

    const labeledCandidates = Array.from(document.querySelectorAll('.card, section, article')).filter(node => {
      const text = node.textContent || '';
      return /LIVE STOCK VIEWER/i.test(text) &&
             /Search and Inspect Live Stocks/i.test(text) &&
             (node.querySelector('input') || node.querySelector('select') || node.querySelector('[role="combobox"]'));
    });

    return labeledCandidates.sort((a,b) => a.textContent.length - b.textContent.length)[0] || null;
  };

  // Keep the combined Top-10 list + comparison-chart row first, then place the
  // full LIVE STOCK VIEWER search/selector panel directly below that row.
  const arrangeLiveStockViewer = () => {
    if (!document.body.classList.contains('ds-live-stock-view')) return false;

    const comparison = document.getElementById('ds-top-live-comparison');
    if (!comparison) return false;

    const comparisonRow = comparison.closest('.ds-top-live-row') || comparison;
    const liveViewer = findFullLiveViewer();
    const cards = Array.from(document.querySelectorAll('.card'));
    const market = cards.find(node => {
      const label = node.querySelector(':scope > .label')?.textContent?.trim() || '';
      return label === 'MARKET' || node.classList.contains('ds-market-section');
    });

    const stack = comparisonRow.parentElement;
    if (stack) {
      stack.classList.remove('ds-market-comparison-grid');
      stack.classList.add('ds-live-comparison-stack');
    }

    if (liveViewer && stack) {
      liveViewer.classList.add('ds-live-viewer-card', 'ds-live-stock-keep');
      if (comparisonRow.nextElementSibling !== liveViewer) {
        comparisonRow.insertAdjacentElement('afterend', liveViewer);
      }
    }

    if (market && market !== liveViewer) market.remove();
    return Boolean(liveViewer || market);
  };

  removeCompactV4Equity();
  moveV8RankSignal();
  arrangeLiveStockViewer();

  const layoutObserver = new MutationObserver(() => {
    removeCompactV4Equity();
    moveV8RankSignal();
    arrangeLiveStockViewer();
  });
  layoutObserver.observe(document.documentElement, { childList: true, subtree: true });
  window.setTimeout(() => layoutObserver.disconnect(), 12000);

  const sections = Array.from(document.querySelectorAll('section.card'));

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