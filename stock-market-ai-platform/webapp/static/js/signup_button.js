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
  const params = new URLSearchParams(window.location.search);
  const path = window.location.pathname;
  const liveStockView = path === '/dashboard' && params.get('view') === 'live';
  const modelResearchView = path === '/dashboard' && !liveStockView;
  const stockArea = path === '/dashboard';
  const cryptoArea = path === '/crypto' || path === '/crypto-visual';
  const readinessArea = path === '/trading-readiness';

  if (shell && header && ['/dashboard', '/crypto', '/crypto-visual', '/trading-readiness'].includes(path)) {
    shell.querySelectorAll(':scope > nav.tabs, :scope > .ds-dashboard-tabs, :scope > .ds-section-tabs').forEach(nav => nav.remove());

    if (!document.getElementById('ds-navigation-style')) {
      const style = document.createElement('style');
      style.id = 'ds-navigation-style';
      style.textContent = `
        .ds-dashboard-tabs,.ds-section-tabs{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
        .ds-section-tabs{margin-bottom:22px;padding-left:10px;border-left:3px solid rgba(54,216,255,.35)}
        .ds-dashboard-tab,.ds-section-tab{padding:12px 18px;border:1px solid #244261;border-radius:999px;text-decoration:none;color:#91a6c2;font-weight:900;letter-spacing:.04em;background:rgba(13,28,49,.85)}
        .ds-section-tab{padding:10px 16px;font-size:.82rem}
        .ds-dashboard-tab.active,.ds-section-tab.active{color:#06151d;background:linear-gradient(90deg,#36d8ff,#39e3a1);border-color:transparent}
        .ds-dashboard-tab:hover,.ds-section-tab:hover{border-color:rgba(54,216,255,.55);color:#f2f6ff}
        body.ds-model-research-view .ds-primary-stock-section{display:none!important}
        body.ds-model-research-view .ds-market-card{display:none!important}
        body.ds-model-research-view .ds-market-section{grid-template-columns:1fr!important}
        body.ds-model-research-view .market-history-card{display:none!important}
        body.ds-model-research-view .ds-recent-market-data{display:none!important}
        body.ds-live-stock-view .shell>section:not(.ds-live-stock-keep):not(.market-history-card){display:none!important}
        body.ds-live-stock-view .ds-market-section{grid-template-columns:1fr!important}
        body.ds-live-stock-view .ds-model-signal-card{display:none!important}
        body.ds-live-stock-view .market-history-card{display:block!important}
        body.ds-live-stock-view #v8-holdout-monitor,
        body.ds-live-stock-view .v8-holdout-monitor,
        body.ds-live-stock-view [data-v8-holdout-monitor]{display:none!important}
        body.ds-live-stock-view footer{margin-top:24px}
        @media(max-width:650px){.ds-dashboard-tab,.ds-section-tab{flex:1 1 auto;text-align:center}.ds-section-tabs{padding-left:0;border-left:0}}
      `;
      document.head.appendChild(style);
    }

    const primary = document.createElement('nav');
    primary.className = 'ds-dashboard-tabs ds-primary-tabs';
    primary.setAttribute('aria-label', 'Primary platform areas');
    primary.innerHTML = `
      <a class="ds-dashboard-tab ${stockArea ? 'active' : ''}" href="/dashboard" ${stockArea ? 'aria-current="page"' : ''}>STOCKS</a>
      <a class="ds-dashboard-tab ${cryptoArea ? 'active' : ''}" href="/crypto" ${cryptoArea ? 'aria-current="page"' : ''}>CRYPTO</a>
      <a class="ds-dashboard-tab ${readinessArea ? 'active' : ''}" href="/trading-readiness" ${readinessArea ? 'aria-current="page"' : ''}>TRADING READINESS</a>
    `;
    header.insertAdjacentElement('afterend', primary);

    if (stockArea || cryptoArea) {
      const secondary = document.createElement('nav');
      secondary.className = 'ds-section-tabs';
      secondary.setAttribute('aria-label', stockArea ? 'Stock areas' : 'Crypto areas');
      secondary.innerHTML = stockArea
        ? `<a class="ds-section-tab ${modelResearchView ? 'active' : ''}" href="/dashboard" ${modelResearchView ? 'aria-current="page"' : ''}>MODEL RESEARCH</a>
           <a class="ds-section-tab ${liveStockView ? 'active' : ''}" href="/dashboard?view=live" ${liveStockView ? 'aria-current="page"' : ''}>LIVE STOCK VIEWER</a>`
        : `<a class="ds-section-tab ${path === '/crypto' ? 'active' : ''}" href="/crypto" ${path === '/crypto' ? 'aria-current="page"' : ''}>CRYPTO MODEL RESEARCH</a>
           <a class="ds-section-tab ${path === '/crypto-visual' ? 'active' : ''}" href="/crypto-visual" ${path === '/crypto-visual' ? 'aria-current="page"' : ''}>CRYPTO LIVE</a>`;
      primary.insertAdjacentElement('afterend', secondary);
    }
  }

  if (window.location.pathname === '/dashboard') {
    const streamHealthScript = document.createElement('script');
    streamHealthScript.src = '/static/js/v8_stream_health_visual.js';
    streamHealthScript.onerror = () => console.error('Unable to load V8 stream health visualization.');
    document.head.appendChild(streamHealthScript);

    const selector = Array.from(document.querySelectorAll('section.card')).find(section =>
      section.querySelector(':scope .label')?.textContent?.trim() === 'PRIMARY STOCK VIEW'
    );
    if (selector) selector.classList.add('ds-primary-stock-section', 'ds-live-stock-keep');

    const marketCard = Array.from(document.querySelectorAll('section.grid.grid-2 > .card')).find(card =>
      card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET'
    );
    let modelSignal = null;
    if (marketCard) {
      marketCard.classList.add('ds-market-card');
      const marketSection = marketCard.parentElement;
      marketSection?.classList.add('ds-market-section', 'ds-live-stock-keep');
      modelSignal = Array.from(marketSection?.children || []).find(card => card !== marketCard);
      modelSignal?.classList.add('ds-model-signal-card');
    }

    const recentMarketData = Array.from(document.querySelectorAll('section.card')).find(section =>
      section.querySelector(':scope > .label')?.textContent?.trim() === 'RECENT MARKET DATA'
    );
    if (recentMarketData) recentMarketData.classList.add('ds-recent-market-data', 'ds-live-stock-keep');

    // Replace the legacy V5 selected-stock signal with the frozen V8 DISTANCE_ONLY
    // signal, and keep this model-specific card on MODEL RESEARCH only.
    if (modelResearchView && modelSignal) {
      const selectedSymbol = document.getElementById('stock-select')?.value || params.get('symbol') || 'AAPL';
      modelSignal.innerHTML = `
        <div class="label">V8 5-DAY RELATIVE-RANK SIGNAL</div>
        <h2 id="v8-model-rank">Loading…</h2>
        <div id="v8-model-score" class="hero-value">—</div>
        <div class="muted">Frozen V8 DISTANCE_ONLY cross-sectional ranking score</div>
        <div class="grid grid-3" style="margin-top:18px">
          <div class="metric"><span>RANK PERCENTILE</span><strong id="v8-model-percentile">—</strong></div>
          <div class="metric"><span>TOP 10</span><strong id="v8-model-top10">—</strong></div>
          <div class="metric"><span>SIGNAL</span><strong id="v8-model-signal">—</strong></div>
        </div>
        <div id="v8-model-note" class="muted" style="margin-top:14px;font-size:.76rem;line-height:1.45">Latest eligible frozen-model development snapshot; not forward holdout evidence.</div>`;

      fetch('/api/v8/holdout', {cache:'no-store'})
        .then(response => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.json();
        })
        .then(data => {
          const rows = Array.isArray(data.latest_research_rankings) ? data.latest_research_rankings : [];
          const row = rows.find(item => String(item.symbol).toUpperCase() === String(selectedSymbol).toUpperCase());
          if (!row) throw new Error(`No V8 ranking for ${selectedSymbol}`);
          const count = rows.length;
          const rank = Number(row.rank);
          const score = Number(row.score);
          const percentile = count > 1 ? ((count - rank) / (count - 1)) * 100 : 100;
          const top10 = Boolean(row.selected_top10 || rank <= 10);

          const rankEl = modelSignal.querySelector('#v8-model-rank');
          const scoreEl = modelSignal.querySelector('#v8-model-score');
          const pctEl = modelSignal.querySelector('#v8-model-percentile');
          const topEl = modelSignal.querySelector('#v8-model-top10');
          const signalEl = modelSignal.querySelector('#v8-model-signal');
          const noteEl = modelSignal.querySelector('#v8-model-note');

          rankEl.textContent = `#${rank} / ${count}`;
          scoreEl.textContent = Number.isFinite(score) ? score.toFixed(4) : '—';
          scoreEl.classList.remove('positive','negative');
          if (Number.isFinite(score)) scoreEl.classList.add(score >= 0 ? 'positive' : 'negative');
          pctEl.textContent = `${percentile.toFixed(1)}%`;
          topEl.textContent = top10 ? 'YES' : 'NO';
          topEl.className = top10 ? 'positive' : '';
          signalEl.textContent = top10 ? 'TOP-10 SELECTED' : 'RANKED';

          if (data.latest_research_rankings_timestamp_utc) {
            const dt = new Date(data.latest_research_rankings_timestamp_utc);
            if (!Number.isNaN(dt.getTime())) {
              noteEl.textContent = `Frozen V8 DISTANCE_ONLY snapshot from ${dt.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'})}. Score is a ranking signal, not a calibrated probability or guaranteed return.`;
            }
          }
        })
        .catch(error => {
          modelSignal.querySelector('#v8-model-rank').textContent = 'V8 data unavailable';
          modelSignal.querySelector('#v8-model-score').textContent = '—';
          modelSignal.querySelector('#v8-model-percentile').textContent = '—';
          modelSignal.querySelector('#v8-model-top10').textContent = '—';
          modelSignal.querySelector('#v8-model-signal').textContent = '—';
          modelSignal.querySelector('#v8-model-note').textContent = 'Unable to load the frozen V8 ranking snapshot for this stock.';
          console.error('[MODEL RESEARCH V8 SIGNAL]', error);
        });
    }

    const hideV8HoldoutFromLiveViewer = () => {
      if (!liveStockView) return;
      const researchOnlyIds = [
        'stock-model-comparison',
        'v8-holdout-monitor',
        'v8-launch-readiness-card',
        'v8-launch-day-operations',
        'v10-confirmation-card',
        'v10-cycle3-holdout-monitor'
      ];
      researchOnlyIds.forEach(id => document.getElementById(id)?.style.setProperty('display','none','important'));
      for (const section of document.querySelectorAll('.shell section, .shell .panel')) {
        const label = section.querySelector('.label')?.textContent?.trim() || '';
        const heading = section.querySelector('h2,h3')?.textContent?.trim() || '';
        if (/MODEL PERFORMANCE COMPARISON|V8 HOLDOUT|V8 FROZEN FORWARD|V8 HOLDOUT LAUNCH READINESS|ORIGINAL V10 RESEARCH|V10 CYCLE 3 FRESH FORWARD/i.test(`${label} ${heading}`)) {
          section.style.setProperty('display', 'none', 'important');
        }
      }
    };

    document.body.classList.add(liveStockView ? 'ds-live-stock-view' : 'ds-model-research-view');
    hideV8HoldoutFromLiveViewer();
    if (liveStockView) {
      const observer = new MutationObserver(hideV8HoldoutFromLiveViewer);
      observer.observe(shell, {childList:true, subtree:true});
    }

    if (liveStockView) {
      const brandSubtitle = document.querySelector('.brand .muted');
      if (brandSubtitle) brandSubtitle.textContent = 'Live Stock Viewer · real-time market data + interactive price history';
      const selectorLabel = selector?.querySelector('.label');
      if (selectorLabel) selectorLabel.textContent = 'LIVE STOCK VIEWER';
      const selectorTitle = selector?.querySelector('h3');
      if (selectorTitle) selectorTitle.textContent = 'Search and Inspect Live Stocks';
      const selectorCopy = selector?.querySelector('.muted');
      if (selectorCopy) selectorCopy.textContent = 'Search by ticker or company name, then inspect live market data and interactive history.';

      const form = document.getElementById('stock-selector-form');
      const select = document.getElementById('stock-select');
      const search = document.getElementById('stock-search');
      const navigateLive = () => {
        const symbol = select?.value || 'AAPL';
        window.location.assign(`/dashboard?view=live&symbol=${encodeURIComponent(symbol)}#primary-stock-view`);
      };
      if (form) {
        form.action = '/dashboard?view=live';
        form.submit = navigateLive;
        form.addEventListener('submit', event => {
          event.preventDefault();
          navigateLive();
        }, true);
      }
      if (search && select) {
        search.addEventListener('keydown', event => {
          if (event.key === 'Enter') {
            event.preventDefault();
            if (select.options.length && !select.options[0].disabled) navigateLive();
          }
        }, true);
      }
    }

    window.addEventListener('DOMContentLoaded', () => {
      const form = document.getElementById('stock-selector-form');
      if (form && liveStockView) form.action = `/dashboard?view=live#primary-stock-view`;
      hideV8HoldoutFromLiveViewer();
    });
  }

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