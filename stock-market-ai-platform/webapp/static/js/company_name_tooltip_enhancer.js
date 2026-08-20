(() => {
  if (location.pathname !== '/dashboard' || new URLSearchParams(location.search).get('view') !== 'live') return;

  const select = document.getElementById('stock-select');
  if (!select) return;

  const companyBySymbol = new Map(
    Array.from(select.options)
      .filter(option => option.value)
      .map(option => {
        const symbol = option.value.toUpperCase();
        const rawText = option.textContent.trim();
        const company = (option.dataset.company || rawText.replace(new RegExp(`^${symbol}\\s*[—–-]?\\s*`, 'i'), '') || symbol).trim();
        return [symbol, company];
      })
  );

  const style = document.createElement('style');
  style.textContent = `
    .ds-tooltip-company{
      margin:-1px 0 8px 16px;
      color:var(--muted);
      font-size:.72rem;
      line-height:1.3;
      font-weight:700;
      max-width:260px;
      white-space:normal;
    }
    #mh-tooltip .ds-tooltip-company{margin-left:0}
  `;
  document.head.appendChild(style);

  const companyName = symbol => companyBySymbol.get(String(symbol || '').toUpperCase()) || '';

  function ensureCompanyNode(tip, title, text) {
    if (!tip || !title || !text) return;
    let node = tip.querySelector('.ds-tooltip-company');
    if (node && node.textContent === text) return;
    if (!node) {
      node = document.createElement('div');
      node.className = 'ds-tooltip-company';
      title.insertAdjacentElement('afterend', node);
    }
    node.textContent = text;
  }

  function enhanceTopLiveTooltip() {
    const tip = document.getElementById('tlc-tip');
    if (!tip || tip.dataset.companyEnhancerReady === '1') return false;
    tip.dataset.companyEnhancerReady = '1';

    let lastSignature = '';
    const apply = () => {
      const title = tip.querySelector('.tlc-tip-title');
      if (!title) return;
      const symbol = (title.textContent || '').trim().split(/\s|·/)[0].toUpperCase();
      const company = companyName(symbol);
      const signature = `${symbol}|${company}`;
      if (signature === lastSignature) return;
      lastSignature = signature;
      if (company && company !== symbol) ensureCompanyNode(tip, title, company);
    };

    new MutationObserver(apply).observe(tip, {childList:true, subtree:true, characterData:true});
    apply();
    return true;
  }

  function enhanceMarketHistoryTooltip() {
    const tip = document.getElementById('mh-tooltip');
    if (!tip || tip.dataset.companyEnhancerReady === '1') return false;
    tip.dataset.companyEnhancerReady = '1';

    let lastSignature = '';
    const apply = () => {
      const title = tip.querySelector('.mh-tip-title');
      if (!title) return;
      const symbol = (select.value || '').toUpperCase();
      const company = companyName(symbol);
      const display = company && company !== symbol ? `${symbol} · ${company}` : symbol;
      if (display === lastSignature) return;
      lastSignature = display;
      ensureCompanyNode(tip, title, display);
    };

    new MutationObserver(apply).observe(tip, {childList:true, subtree:true, characterData:true});
    apply();
    return true;
  }

  const install = () => {
    const topReady = enhanceTopLiveTooltip();
    const historyReady = enhanceMarketHistoryTooltip();
    return topReady || document.getElementById('tlc-tip')?.dataset.companyEnhancerReady === '1'
      ? (historyReady || document.getElementById('mh-tooltip')?.dataset.companyEnhancerReady === '1')
      : false;
  };

  install();
  // The chart modules are deferred ahead of this script, so tooltips normally
  // already exist. Use only a few cheap retries instead of observing the entire
  // dashboard DOM, which previously amplified every live chart update.
  [250, 750, 1500, 3000].forEach(delay => setTimeout(install, delay));
})();
