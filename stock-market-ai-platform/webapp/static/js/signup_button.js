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
  if (shell && header && !existingTabs && ['/dashboard', '/crypto'].includes(window.location.pathname)) {
    const style = document.createElement('style');
    style.textContent = `
      .ds-dashboard-tabs{display:flex;gap:10px;margin-bottom:22px;flex-wrap:wrap}
      .ds-dashboard-tab{padding:12px 18px;border:1px solid #244261;border-radius:999px;text-decoration:none;color:#91a6c2;font-weight:900;letter-spacing:.04em;background:rgba(13,28,49,.85)}
      .ds-dashboard-tab.active{color:#06151d;background:linear-gradient(90deg,#36d8ff,#39e3a1);border-color:transparent}
      .ds-dashboard-tab:hover{border-color:rgba(54,216,255,.55);color:#f2f6ff}
    `;
    document.head.appendChild(style);

    const nav = document.createElement('nav');
    nav.className = 'ds-dashboard-tabs';
    nav.setAttribute('aria-label', 'Dashboard sections');
    nav.innerHTML = `
      <a class="ds-dashboard-tab ${window.location.pathname === '/dashboard' ? 'active' : ''}" href="/dashboard">STOCKS</a>
      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto' ? 'active' : ''}" href="/crypto">CRYPTO</a>
    `;
    header.insertAdjacentElement('afterend', nav);
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
