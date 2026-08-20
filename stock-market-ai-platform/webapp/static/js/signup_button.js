(() => {
  const makeButton = (className) => {
    const link = document.createElement('a');
    link.href = '/signup';
    link.textContent = 'SIGN UP';
    link.className = className;
    link.style.textDecoration = 'none';
    return link;
  };

  const landingActions = document.querySelector('.landing-header-actions');
  if (landingActions && !landingActions.querySelector('a[href="/signup"]')) {
    const button = makeButton('landing-login-button');
    button.style.borderColor = '#36d8ff';
    button.style.color = '#36d8ff';
    button.style.background = 'rgba(54,216,255,.08)';
    landingActions.insertBefore(button, landingActions.firstChild);
  }

  const dashboardActions = document.querySelector('.actions');
  if (dashboardActions && !dashboardActions.querySelector('a[href="/signup"]')) {
    const button = makeButton('pill');
    button.style.color = '#36d8ff';
    button.style.borderColor = 'rgba(54,216,255,.45)';
    button.style.background = 'rgba(54,216,255,.08)';
    dashboardActions.insertBefore(button, dashboardActions.firstChild);
  }

  const shell = document.querySelector('.shell');
  const header = shell && shell.querySelector('header');
  const existingTabs = shell && shell.querySelector('.tabs');
  const params = new URLSearchParams(window.location.search);
  const liveStockView = window.location.pathname === '/dashboard' && params.get('view') === 'live';
  const modelResearchView = window.location.pathname === '/dashboard' && !liveStockView;

  if (shell && header && !existingTabs && ['/dashboard', '/crypto', '/crypto-visual'].includes(window.location.pathname)) {
    const style = document.createElement('style');
    style.textContent = `
      .ds-dashboard-tabs{display:flex;gap:10px;margin-bottom:22px;flex-wrap:wrap}
      .ds-dashboard-tab{padding:12px 18px;border:1px solid #244261;border-radius:999px;text-decoration:none;color:#91a6c2;font-weight:900;letter-spacing:.04em;background:rgba(13,28,49,.85)}
      .ds-dashboard-tab.active{color:#06151d;background:linear-gradient(90deg,#36d8ff,#39e3a1);border-color:transparent}
      .ds-dashboard-tab:hover{border-color:rgba(54,216,255,.55);color:#f2f6ff}
      body.ds-model-research-view .ds-primary-stock-section{display:none!important}
      body.ds-model-research-view .ds-market-card{display:none!important}
      body.ds-model-research-view .ds-market-section{grid-template-columns:1fr!important}
      body.ds-model-research-view .market-history-card{display:none!important}
      body.ds-live-stock-view .shell>section:not(.ds-live-stock-keep):not(.market-history-card){display:none!important}
      body.ds-live-stock-view .ds-market-section{grid-template-columns:1fr!important}
      body.ds-live-stock-view .ds-model-signal-card{display:none!important}
      body.ds-live-stock-view .market-history-card{display:block!important}
      body.ds-live-stock-view footer{margin-top:24px}
    `;
    document.head.appendChild(style);

    const nav = document.createElement('nav');
    nav.className = 'ds-dashboard-tabs';
    nav.setAttribute('aria-label', 'Dashboard sections');
    nav.innerHTML = `
      <a class="ds-dashboard-tab ${modelResearchView ? 'active' : ''}" href="/dashboard">MODEL RESEARCH</a>
      <a class="ds-dashboard-tab ${liveStockView ? 'active' : ''}" href="/dashboard?view=live">LIVE STOCK VIEWER</a>
      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto' ? 'active' : ''}" href="/crypto">CRYPTO</a>
      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto-visual' ? 'active' : ''}" href="/crypto-visual">CRYPTO VISUAL</a>
    `;
    header.insertAdjacentElement('afterend', nav);
  }

  if (window.location.pathname === '/dashboard') {
    const selector = Array.from(document.querySelectorAll('section.card')).find(section =>
      section.querySelector(':scope .label')?.textContent?.trim() === 'PRIMARY STOCK VIEW'
    );
    if (selector) selector.classList.add('ds-primary-stock-section', 'ds-live-stock-keep');

    const marketCard = Array.from(document.querySelectorAll('section.grid.grid-2 > .card')).find(card =>
      card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET'
    );
    if (marketCard) {
      marketCard.classList.add('ds-market-card');
      const marketSection = marketCard.parentElement;
      marketSection?.classList.add('ds-market-section', 'ds-live-stock-keep');
      const modelSignal = Array.from(marketSection?.children || []).find(card => card !== marketCard);
      modelSignal?.classList.add('ds-model-signal-card');
    }

    document.body.classList.add(liveStockView ? 'ds-live-stock-view' : 'ds-model-research-view');

    if (liveStockView) {
      const brandSubtitle = document.querySelector('.brand .muted');
      if (brandSubtitle) brandSubtitle.textContent = 'Live Stock Viewer · real-time market data + interactive price history';
      const selectorLabel = selector?.querySelector('.label');
      if (selectorLabel) selectorLabel.textContent = 'LIVE STOCK VIEWER';
      const selectorTitle = selector?.querySelector('h3');
      if (selectorTitle) selectorTitle.textContent = 'Search and Inspect Live Stocks';
      const selectorCopy = selector?.querySelector('.muted');
      if (selectorCopy) selectorCopy.textContent = 'Search by ticker or company name, then inspect live market data and interactive history.';
    }

    window.addEventListener('DOMContentLoaded', () => {
      const form = document.getElementById('stock-selector-form');
      if (form && liveStockView) form.action = `/dashboard?view=live#primary-stock-view`;
    });
  }

  // Live Crypto V2 monitor: refresh values in place without reloading the page.
  if (window.location.pathname === '/crypto') {
    const liveCard = document.querySelector('section.card.live');
    if (!liveCard) return;

    const metricStrong = (label) => {
      const spans = [...liveCard.querySelectorAll('.metric span')];
      const span = spans.find((node) => node.textContent.trim() === label);
      return span ? span.parentElement.querySelector('strong') : null;
    };

    const modeBadge = liveCard.querySelector('.mode');
    const refreshBadge = document.createElement('span');
    refreshBadge.style.cssText = 'display:inline-flex;margin-left:10px;padding:7px 12px;border-radius:999px;border:1px solid rgba(57,227,161,.3);background:rgba(57,227,161,.08);color:#39e3a1;font-size:.72rem;font-weight:900;letter-spacing:.06em;vertical-align:middle';
    refreshBadge.textContent = 'AUTO-REFRESH · STARTING';
    if (modeBadge) modeBadge.insertAdjacentElement('afterend', refreshBadge);

    const setProbability = (label, value) => {
      const rows = [...liveCard.querySelectorAll('.prob')];
      for (const bar of rows) {
        const headerRow = bar.previousElementSibling;
        if (!headerRow) continue;
        const strongs = headerRow.querySelectorAll('strong');
        if (strongs.length < 2 || strongs[0].textContent.trim() !== label) continue;
        const pct = Math.max(0, Math.min(100, Number(value || 0) * 100));
        strongs[1].textContent = `${pct.toFixed(2)}%`;
        const fill = bar.querySelector('i');
        if (fill) fill.style.width = `${pct}%`;
      }
    };

    const setChips = (heading, values) => {
      const headings = [...liveCard.querySelectorAll('.muted')];
      const node = headings.find((el) => el.textContent.trim() === heading);
      const chips = node && node.nextElementSibling;
      if (!chips || !chips.classList.contains('chips')) return;
      const items = Array.isArray(values) && values.length ? values : ['None'];
      chips.innerHTML = items.map((x) => `<span class="chip">${String(x).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}</span>`).join('');
    };

    const operationalCard = [...liveCard.querySelectorAll('.lower > .card')][1];
    const operationalParagraph = operationalCard && operationalCard.querySelector('h3 + p');

    const renderLive = (live) => {
      if (!live || !live.available) throw new Error(live && live.message ? live.message : 'Live V2 status unavailable');

      if (modeBadge) modeBadge.textContent = `${live.mode || 'UNKNOWN'} MODE`;
      const executed = metricStrong('EXECUTED SLEEVE');
      const raw = metricStrong('RAW PREDICTION');
      const alts = metricStrong('ELIGIBLE ALTS');
      const decision = metricStrong('DECISION TIME UTC');
      const reconciled = metricStrong('RECONCILED THROUGH');
      if (executed) executed.textContent = live.current_executed_label || '—';
      if (raw) raw.textContent = live.raw_predicted_label || '—';
      if (alts) alts.textContent = String(live.alt_asset_count ?? '—');
      if (decision) decision.textContent = live.decision_timestamp_utc || '—';
      if (reconciled) reconciled.textContent = live.reconcile_boundary || '—';

      setProbability('ALT', live.prob_alt);
      setProbability('CASH', live.prob_cash);
      setProbability('BTC', live.prob_btc);
      setChips('Missing exact-hour ALT candles', live.missing_alts);
      setChips('Feature-ineligible ALTs', live.ineligible_alts);

      if (operationalParagraph) {
        operationalParagraph.innerHTML = `<strong>${live.reconcile_product_count ?? '—'}</strong> products in reconciliation service · <strong>${live.journal_rows ?? 0}</strong> forward journal rows · <strong>${live.realized_rows ?? 0}</strong> realized forward rows.`;
      }

      const now = new Date();
      refreshBadge.textContent = `AUTO-REFRESH · ${now.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})}`;
      refreshBadge.style.color = '#39e3a1';
      refreshBadge.style.borderColor = 'rgba(57,227,161,.3)';
    };

    const refresh = async () => {
      try {
        const response = await fetch('/api/crypto-v1', {
          method: 'GET',
          credentials: 'same-origin',
          cache: 'no-store',
          headers: {'Accept': 'application/json'}
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        renderLive(payload.live_v2);
      } catch (error) {
        refreshBadge.textContent = 'AUTO-REFRESH · RETRYING';
        refreshBadge.style.color = '#efc56b';
        refreshBadge.style.borderColor = 'rgba(239,197,107,.35)';
        console.warn('[CRYPTO LIVE REFRESH]', error);
      }
    };

    refresh();
    window.setInterval(refresh, 60_000);
  }
})();