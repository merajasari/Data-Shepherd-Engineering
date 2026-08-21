(() => {
  if (window.location.pathname !== '/dashboard') return;

  const literalDate = iso => {
    const ymd = String(iso || '').slice(0, 10);
    const [y, m, d] = ymd.split('-').map(Number);
    if (!y || !m || !d) return '—';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
    }).format(new Date(Date.UTC(y, m - 1, d)));
  };

  const findCardByLabel = label => Array.from(document.querySelectorAll('section.card, .card')).find(card =>
    card.querySelector(':scope > .label')?.textContent?.trim() === label
  );

  const normalizeLayout = () => {
    // Keep the richer V8 Leaders card and remove the older duplicate Top-10 card.
    const duplicate = document.getElementById('v8-current-top10');
    if (duplicate) duplicate.remove();

    // The legacy V4 shell is now populated entirely with V8 forward-holdout metrics.
    const dashboard = document.querySelector('.v4-dashboard');
    if (dashboard) {
      const label = dashboard.querySelector(':scope > .label');
      const heading = dashboard.querySelector(':scope > h2');
      const copy = dashboard.querySelector(':scope > p.muted');
      if (label) label.textContent = 'V8 FORWARD HOLDOUT';
      if (heading) heading.textContent = 'Forward Strategy Monitor';
      if (copy) copy.textContent = 'Frozen V8 DISTANCE_ONLY strategy monitored against SPY. Forward holdout evidence begins Sep 1, 2026. Simulation only — no brokerage orders are placed.';
    }
  };

  const updateV8Dates = async () => {
    try {
      const r = await fetch('/api/v8/holdout', {cache: 'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const rankingDate = literalDate(d.ranking_timestamp_utc || d.latest_research_top10_timestamp_utc);
      const holdoutDate = literalDate(d.holdout_start_utc);

      const opsDate = document.getElementById('v8ops-date');
      if (opsDate) opsDate.textContent = rankingDate;

      const interaction = findCardByLabel('V8 HOLDOUT INTERACTION');
      if (interaction) {
        const metric = Array.from(interaction.querySelectorAll('.metric')).find(x =>
          x.querySelector('span')?.textContent?.trim() === 'HOLDOUT START'
        );
        if (metric) {
          const strong = metric.querySelector('strong');
          if (strong) strong.textContent = holdoutDate;
        }
      }

      const leaders = document.getElementById('v8-leaders');
      const leadersNote = leaders?.querySelector('#v8l-note');
      if (leadersNote && rankingDate !== '—') {
        leadersNote.textContent = `Latest frozen V8 readiness ranking: ${rankingDate}. Scores are ranking signals, not calibrated probabilities. Not forward holdout evidence.`;
      }
    } catch (e) {
      console.warn('V8 date normalization failed:', e);
    }
  };

  let healthChecks = 0;
  const fmtTime = d => d.toLocaleTimeString([], {
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: 'America/Los_Angeles'
  });
  const fmtAgo = seconds => !Number.isFinite(seconds) ? '—' :
    seconds < 60 ? `${Math.max(0, Math.round(seconds))} sec` :
    seconds < 3600 ? `${Math.round(seconds / 60)} min` : `${(seconds / 3600).toFixed(1)} hr`;

  const refreshStreamHealth = async () => {
    const card = document.getElementById('stock-stream-health-card');
    if (!card || !document.getElementById('v8-stream-state')) return;
    try {
      const r = await fetch('/api/stock-stream-health', {cache: 'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      healthChecks += 1;

      const status = String(d.status || 'UNKNOWN').replaceAll('_', ' ');
      const closed = !d.regular_session_expected_open || /AFTER HOURS|CLOSED/i.test(status);
      const bad = /STALE|ERROR|DOWN|DISCONNECTED|FAILED/i.test(status) && !closed;
      const state = document.getElementById('v8-stream-state');
      const pulse = document.getElementById('v8-stream-pulse');
      if (state) {
        state.textContent = closed ? 'MARKET CLOSED · MONITORING' : status;
        state.className = `v8-stream-state${closed ? ' closed' : bad ? ' bad' : ''}`;
      }
      if (pulse) pulse.className = `v8-stream-pulse${closed ? ' closed' : bad ? ' bad' : ''}`;

      const set = (id, value) => { const el = document.getElementById(id); if (el) el.textContent = value; };
      set('v8-stream-live', String(d.live_symbol_count ?? '—'));
      set('v8-stream-configured', String(d.configured_symbol_count ?? '—'));
      set('v8-stream-age', Number.isFinite(Number(d.cache_age_seconds)) ? fmtAgo(Number(d.cache_age_seconds)) : '—');
      set('v8-stream-agent', d.launchagent_running ? 'RUNNING' : (d.launchagent_loaded ? 'LOADED · IDLE' : 'NOT LOADED'));
      set('v8-stream-session', d.regular_session_expected_open ? 'REGULAR SESSION' : 'CLOSED');
      set('v8-stream-detail', d.detail || 'No health detail available.');
      set('v8-stream-refresh-count', String(healthChecks));
      set('v8-stream-last-refresh', fmtTime(new Date()));
      set('v8-stream-refresh-ago', 'just refreshed');

      const live = Number(d.live_symbol_count), configured = Number(d.configured_symbol_count);
      const fill = document.getElementById('v8-stream-fill');
      if (fill) fill.style.width = Number.isFinite(live) && Number.isFinite(configured) && configured > 0
        ? `${Math.max(0, Math.min(100, 100 * live / configured))}%` : '0%';

      if (d.cache_updated_at) {
        const cacheTs = new Date(d.cache_updated_at);
        if (!Number.isNaN(cacheTs.getTime())) {
          set('v8-stream-last-data', fmtTime(cacheTs));
          set('v8-stream-data-ago', `${fmtAgo(Number(d.cache_age_seconds))} ago · quote-cache heartbeat`);
        }
      }
    } catch (e) {
      const state = document.getElementById('v8-stream-state');
      if (state) {
        state.textContent = 'HEALTH API UNAVAILABLE';
        state.className = 'v8-stream-state bad';
      }
      const detail = document.getElementById('v8-stream-detail');
      if (detail) detail.textContent = `Unable to read stock stream health: ${e.message}`;
    }
  };

  normalizeLayout();
  updateV8Dates();
  refreshStreamHealth();

  const observer = new MutationObserver(() => normalizeLayout());
  observer.observe(document.documentElement, {childList: true, subtree: true});
  window.setTimeout(() => observer.disconnect(), 12000);

  window.setInterval(updateV8Dates, 60000);
  window.setInterval(refreshStreamHealth, 10000);
})();
