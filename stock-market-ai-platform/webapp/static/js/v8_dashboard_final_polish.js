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
    if (subtitle) subtitle.textContent = 'Multi-model research, forward evidence, and operational monitoring';

    document.querySelectorAll('div,span,strong').forEach(el => {
      if (el.children.length) return;
      const t = el.textContent.trim();
      if (t === 'FROZEN V5 MODEL') el.textContent = 'FROZEN V8 MODEL';
    });
  };

  const forceLiteralHoldoutDate = holdout => {
    // Some older V8 visuals format midnight UTC in the browser's Pacific timezone,
    // which turns 2026-09-01 into Aug 31. Correct only the specific holdout date
    // leaves/labels, without observing or rescanning the entire dashboard DOM.
    document.querySelectorAll('.metric strong, text, tspan').forEach(el => {
      const t = (el.textContent || '').trim();
      if (t === 'Aug 31, 2026' || t === '8/31/2026' || t === '08/31/2026') {
        el.textContent = holdout;
      }
    });

    const interactionCandidates = Array.from(document.querySelectorAll('section, article, .card, [id*="v8"]')).filter(el =>
      /V8 HOLDOUT INTERACTION/i.test(el.textContent || '')
    );
    const interaction = interactionCandidates.sort((a, b) =>
      (a.textContent || '').length - (b.textContent || '').length
    )[0];
    if (!interaction) return;

    Array.from(interaction.querySelectorAll('.metric')).forEach(metric => {
      if (metric.querySelector('span')?.textContent?.trim() === 'HOLDOUT START') {
        const strong = metric.querySelector('strong');
        if (strong) strong.textContent = holdout;
      }
    });
  };

  const fixHoldoutDates = async () => {
    try {
      const d = await window.DataShepherdV8Snapshot.get();
      const ranking = utcDate(d.ranking_timestamp_utc);
      const holdout = utcDate(d.holdout_start_utc);
      const features = utcDate(d.feature_common_latest_utc);
      const gold = utcDate(d.gold_common_latest_utc);

      setText('v8ops-date', ranking);
      const detail = document.getElementById('v8ops-detail');
      if (detail && !(d.readiness_failures || []).length && !(d.readiness_warnings || []).length) {
        const sync = window.DataShepherdV8Snapshot.info();
        detail.textContent = `Feature session ${features} · Gold session ${gold} · Browser synchronized ${sync.fetchedAtUtc ? new Date(sync.fetchedAtUtc).toLocaleString() : '—'} · Brokerage orders: NO · Strategy modified: NO`;
      }

      forceLiteralHoldoutDate(holdout);
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
  window.setTimeout(fixHoldoutDates, 750);
  window.setTimeout(fixHoldoutDates, 2000);
  window.setTimeout(fixHoldoutDates, 5000);

  // Keep final values authoritative after older V8 widgets perform their own refreshes.
  window.setInterval(fixHoldoutDates, 10000);
  window.setInterval(refreshHealth, 15000);
})();
