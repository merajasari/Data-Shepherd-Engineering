(() => {
  const root = document.getElementById('v11-phase2-status');
  if (!root) return;

  const set = (name, value) => {
    const node = root.querySelector(`[data-v11-${name}]`);
    if (node) node.textContent = value;
    return node;
  };
  const pct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
  const date = value => value ? new Date(value).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
  }) : '—';

  const refresh = async () => {
    try {
      const response = await fetch('/api/v11/phase2', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const displayStatus = data.display_status || data.status || 'UNKNOWN';
      const badge = set('status', String(displayStatus).replaceAll('_', ' '));
      if (badge) badge.className = `v11p-badge ${displayStatus === 'FRESH_EVIDENCE_ACTIVE' ? 'v11p-good' : displayStatus === 'ALERT' ? 'v11p-alert' : 'v11p-wait'}`;
      set('state', String(data.state || 'UNKNOWN').replaceAll('_', ' '));
      set('evidence', String(data.evidence_status || 'UNKNOWN').replaceAll('_', ' '));
      set('sessions', data.completed_sessions ?? 0);
      set('events', data.journal_event_count ?? 0);
      set('scheduler', String(data.scheduler_status || 'UNKNOWN').replaceAll('_', ' '));
      set('boundary', date(data.fresh_confirmation_start_utc));
      set('requests', `${data.maximum_tiingo_requests_per_session ?? 404}/${data.tiingo_hourly_request_limit ?? 500}`);
      set('orders', data.brokerage_orders === false ? 'OFF' : 'ALERT');
      set('latest-session', data.latest_session_date || 'Awaiting first fresh session');
      set('strategy-return', pct(data.latest_strategy_net_return));
      set('spy-return', pct(data.latest_spy_return));
      const excess = set('excess-return', pct(data.latest_net_excess_return));
      if (excess && data.latest_net_excess_return != null) excess.className = Number(data.latest_net_excess_return) >= 0 ? 'positive' : 'negative';
      set('windows', (data.collection_windows_eastern || []).join(' · '));
      set('catch-up', data.catch_up_enabled ? data.catch_up_policy : 'DISABLED');
      set('sha', `${data.contract_sha_verified ? '✓' : '⚠'} ${data.contract_sha256 || '—'}`);
      const failures = data.operational_failures || [];
      const lastAttempt = data.last_collection_attempt;
      const attemptDetail = lastAttempt?.status
        ? ` Last collection attempt: ${String(lastAttempt.status).replaceAll('_', ' ')}${lastAttempt.attempted_at_utc ? ` at ${date(lastAttempt.attempted_at_utc)}` : ''}.`
        : '';
      const detail = failures.length
        ? failures.join(' · ')
        : data.completed_sessions === 0
          ? `Controls are healthy, but no fresh session has been accepted. Scheduler state: ${String(data.state || 'UNKNOWN').replaceAll('_', ' ')}.${attemptDetail} No evidence was backfilled.`
          : `Controls are healthy and ${data.completed_sessions} fresh session${data.completed_sessions === 1 ? '' : 's'} ${data.completed_sessions === 1 ? 'is' : 'are'} recorded.${attemptDetail}`;
      set('detail', `${detail} Paper only; no live orders or V8/V10 production changes.`);
    } catch (error) {
      const badge = set('status', 'UNAVAILABLE');
      if (badge) badge.className = 'v11p-badge v11p-alert';
      set('detail', `V11 Phase 2 status unavailable: ${error.message}`);
    }
  };

  refresh();
  window.setInterval(refresh, 60000);
})();
