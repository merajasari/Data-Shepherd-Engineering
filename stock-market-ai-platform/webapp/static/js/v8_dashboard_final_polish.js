(() => {
  if (window.location.pathname !== '/dashboard') return;

  const utcDate = value => {
    const ymd = String(value || '').slice(0, 10);
    const m = ymd.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return '—';
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'
    }).format(new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))));
  };

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  const fixBranding = () => {
    const subtitle = document.querySelector('header .brand .muted');
    if (subtitle) subtitle.textContent = 'Frozen V8 cross-sectional ranking + forward holdout monitor';

    document.querySelectorAll('div,span,strong').forEach(el => {
      if (el.children.length) return;
      const t = el.textContent.trim();
      if (t === 'FROZEN V5 MODEL') el.textContent = 'FROZEN V8 MODEL';
    });
  };

  const fixHoldoutDates = async () => {
    try {
      const r = await fetch('/api/v8/holdout', {cache: 'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const ranking = utcDate(d.ranking_timestamp_utc || d.latest_research_top10_timestamp_utc);
      const holdout = utcDate(d.holdout_start_utc);
      const features = utcDate(d.feature_common_latest_utc);
      const gold = utcDate(d.gold_common_latest_utc);

      setText('v8ops-date', ranking);
      const detail = document.getElementById('v8ops-detail');
      if (detail && !(d.readiness_failures || []).length && !(d.readiness_warnings || []).length) {
        detail.textContent = `Features ${features} · Gold ${gold} · Brokerage orders: NO · Strategy modified: NO`;
      }

      const interaction = Array.from(document.querySelectorAll('section.card, .card')).find(card =>
        card.querySelector(':scope > .label')?.textContent?.trim() === 'V8 HOLDOUT INTERACTION'
      );
      if (interaction) {
        const metric = Array.from(interaction.querySelectorAll('.metric')).find(x =>
          x.querySelector('span')?.textContent?.trim() === 'HOLDOUT START'
        );
        if (metric?.querySelector('strong')) metric.querySelector('strong').textContent = holdout;
        interaction.querySelectorAll('text,tspan,span,strong,div').forEach(el => {
          if (el.children.length) return;
          if (el.textContent.trim() === 'Aug 31, 2026') el.textContent = holdout;
        });
      }
    } catch (e) {
      console.warn('V8 final date polish failed:', e);
    }
  };

  let checks = 0;
  const fmtTime = d => d.toLocaleTimeString([], {
    hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: 'America/Los_Angeles'
  });
  const fmtAgo = seconds => !Number.isFinite(seconds) ? '—' :
    seconds < 60 ? `${Math.max(0, Math.round(seconds))} sec` :
    seconds < 3600 ? `${Math.round(seconds / 60)} min` : `${(seconds / 3600).toFixed(1)} hr`;

  const refreshHealth = async () => {
    if (!document.getElementById('v8-stream-state')) return false;
    try {
      const r = await fetch('/api/stock-stream-health', {cache: 'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      checks += 1;

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

      setText('v8-stream-live', String(d.live_symbol_count ?? '—'));
      setText('v8-stream-configured', String(d.configured_symbol_count ?? '—'));
      setText('v8-stream-age', Number.isFinite(Number(d.cache_age_seconds)) ? fmtAgo(Number(d.cache_age_seconds)) : '—');
      setText('v8-stream-agent', d.launchagent_running ? 'RUNNING' : (d.launchagent_loaded ? 'LOADED · IDLE' : 'NOT LOADED'));
      setText('v8-stream-session', d.regular_session_expected_open ? 'REGULAR SESSION' : 'CLOSED');
      setText('v8-stream-detail', d.detail || 'No stream-health detail available.');
      setText('v8-stream-refresh-count', String(checks));
      setText('v8-stream-last-refresh', fmtTime(new Date()));
      setText('v8-stream-refresh-ago', 'just refreshed');

      const live = Number(d.live_symbol_count), configured = Number(d.configured_symbol_count);
      const fill = document.getElementById('v8-stream-fill');
      if (fill) fill.style.width = Number.isFinite(live) && Number.isFinite(configured) && configured > 0
        ? `${Math.max(0, Math.min(100, 100 * live / configured))}%` : '0%';

      if (d.cache_updated_at) {
        const ts = new Date(d.cache_updated_at);
        if (!Number.isNaN(ts.getTime())) {
          setText('v8-stream-last-data', fmtTime(ts));
          setText('v8-stream-data-ago', `${fmtAgo(Number(d.cache_age_seconds))} ago · quote-cache heartbeat`);
        }
      }
      return true;
    } catch (e) {
      const state = document.getElementById('v8-stream-state');
      if (state) {
        state.textContent = 'HEALTH API UNAVAILABLE';
        state.className = 'v8-stream-state bad';
      }
      setText('v8-stream-detail', `Unable to read stock stream health: ${e.message}`);
      return true;
    }
  };

  const bootHealth = (attempt = 0) => {
    refreshHealth().then(done => {
      if (!done && attempt < 20) window.setTimeout(() => bootHealth(attempt + 1), 250);
    });
  };

  fixBranding();
  fixHoldoutDates();
  bootHealth();
  window.setTimeout(fixBranding, 1500);
  window.setTimeout(fixHoldoutDates, 2000);

  // Keep the final values authoritative after older widgets perform their own refreshes.
  window.setInterval(fixHoldoutDates, 10000);
  window.setInterval(refreshHealth, 15000);
})();
