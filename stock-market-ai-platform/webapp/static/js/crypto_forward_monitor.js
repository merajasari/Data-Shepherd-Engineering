(() => {
  const REFRESH_MS = 60000;
  let timer = null;

  const fmtPct = v => Number.isFinite(Number(v)) ? `${(Number(v) * 100).toFixed(2)}%` : '—';
  const rootCard = () => Array.from(document.querySelectorAll('section.card')).find(card =>
    card.querySelector(':scope > .label')?.textContent?.trim() === 'CRYPTO 15M V2 — FROZEN FORWARD MONITOR'
  );

  function metricMap(card) {
    const map = {};
    card.querySelectorAll('.metric').forEach(metric => {
      const label = metric.querySelector('span')?.textContent?.trim();
      const value = metric.querySelector('strong');
      if (label && value) map[label] = value;
    });
    return map;
  }

  function setMetric(metrics, label, value) {
    if (metrics[label]) metrics[label].textContent = value ?? '—';
  }

  function renderProbability(card, name, value) {
    const blocks = Array.from(card.querySelectorAll('.lower .card:first-child > div[style*="margin:16px"]'));
    const block = blocks.find(el => el.querySelector('strong')?.textContent?.trim() === name);
    if (!block) return;
    const strongs = block.querySelectorAll('strong');
    if (strongs[1]) strongs[1].textContent = fmtPct(value);
    const bar = block.querySelector('.prob > i');
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(value || 0) * 100))}%`;
  }

  function replaceChips(card, headingText, items) {
    const heading = Array.from(card.querySelectorAll('.muted')).find(el => el.textContent.trim() === headingText);
    const chips = heading?.nextElementSibling;
    if (!chips || !chips.classList.contains('chips')) return;
    const values = Array.isArray(items) && items.length ? items : ['None'];
    chips.innerHTML = values.map(v => `<span class="chip">${String(v).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}</span>`).join('');
  }

  function render(payload) {
    const card = rootCard();
    const live = payload?.live_v2;
    if (!card || !live?.available) return;

    const mode = card.querySelector('.mode');
    if (mode) mode.textContent = `${live.mode || 'UNKNOWN'} MODE`;

    const metrics = metricMap(card);
    setMetric(metrics, 'EXECUTED SLEEVE', live.current_executed_label);
    setMetric(metrics, 'RAW PREDICTION', live.raw_predicted_label);
    setMetric(metrics, 'ELIGIBLE ALTS', String(live.alt_asset_count ?? 0));
    setMetric(metrics, 'DECISION TIME UTC', live.decision_timestamp_utc);
    setMetric(metrics, 'RECONCILED THROUGH', live.reconcile_boundary);
    setMetric(metrics, 'REAL ORDERS', live.brokerage_orders ? 'YES' : 'NO');
    if (metrics['REAL ORDERS']) metrics['REAL ORDERS'].className = live.brokerage_orders ? 'negative' : 'positive';

    renderProbability(card, 'ALT', live.prob_alt);
    renderProbability(card, 'CASH', live.prob_cash);
    renderProbability(card, 'BTC', live.prob_btc);

    const health = Array.from(card.querySelectorAll('.lower .card')).find(el =>
      el.querySelector(':scope > .label')?.textContent?.trim() === 'DATA QUALITY + FORWARD STATE'
    );
    if (health) {
      const paragraph = health.querySelector('p');
      if (paragraph) paragraph.innerHTML = `<strong>${live.reconcile_product_count ?? '—'}</strong> products in reconciliation service · <strong>${live.journal_rows ?? 0}</strong> forward journal rows · <strong>${live.realized_rows ?? 0}</strong> realized forward rows.`;
      replaceChips(health, 'Missing exact-hour ALT candles', live.missing_alts);
      replaceChips(health, 'Feature-ineligible ALTs', live.ineligible_alts);
    }

    card.dataset.lastRefreshUtc = new Date().toISOString();
  }

  async function refresh() {
    if (location.pathname !== '/crypto' || document.visibilityState !== 'visible') return;
    try {
      const response = await fetch(`/api/crypto-v1?t=${Date.now()}`, {
        cache: 'no-store',
        headers: {'Accept': 'application/json'}
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
    } catch (error) {
      console.warn('[CRYPTO FORWARD MONITOR REFRESH]', error);
    }
  }

  function start() {
    clearInterval(timer);
    refresh();
    timer = setInterval(refresh, REFRESH_MS);
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') start();
    else clearInterval(timer);
  });
  document.addEventListener('DOMContentLoaded', start);
})();
