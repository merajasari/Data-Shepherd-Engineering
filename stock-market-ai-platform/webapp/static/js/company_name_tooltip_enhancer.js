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

  function enhanceTopLiveTooltip() {
    const tip = document.getElementById('tlc-tip');
    if (!tip || tip.dataset.companyEnhancerReady === '1') return;
    tip.dataset.companyEnhancerReady = '1';

    const apply = () => {
      const title = tip.querySelector('.tlc-tip-title');
      if (!title) return;
      const symbol = (title.textContent || '').trim().split(/\s|·/)[0].toUpperCase();
      const company = companyName(symbol);
      tip.querySelector('.ds-tooltip-company')?.remove();
      if (!company || company === symbol) return;
      const node = document.createElement('div');
      node.className = 'ds-tooltip-company';
      node.textContent = company;
      title.insertAdjacentElement('afterend', node);
    };

    new MutationObserver(apply).observe(tip, {childList:true, subtree:true, characterData:true});
    apply();
  }

  function enhanceMarketHistoryTooltip() {
    const tip = document.getElementById('mh-tooltip');
    if (!tip || tip.dataset.companyEnhancerReady === '1') return;
    tip.dataset.companyEnhancerReady = '1';

    const apply = () => {
      const symbol = (select.value || '').toUpperCase();
      const company = companyName(symbol);
      const title = tip.querySelector('.mh-tip-title');
      if (!title) return;
      tip.querySelector('.ds-tooltip-company')?.remove();
      if (!company || company === symbol) return;
      const node = document.createElement('div');
      node.className = 'ds-tooltip-company';
      node.textContent = `${symbol} · ${company}`;
      title.insertAdjacentElement('afterend', node);
    };

    new MutationObserver(apply).observe(tip, {childList:true, subtree:true, characterData:true});
    apply();
  }

  const install = () => {
    enhanceTopLiveTooltip();
    enhanceMarketHistoryTooltip();
  };

  install();
  const observer = new MutationObserver(install);
  observer.observe(document.body, {childList:true, subtree:true});
  setTimeout(() => observer.disconnect(), 15000);
})();
