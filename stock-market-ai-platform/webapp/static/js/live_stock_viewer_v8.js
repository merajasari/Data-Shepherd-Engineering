(() => {
  if (window.location.pathname !== '/dashboard') return;
  const params = new URLSearchParams(window.location.search);
  if (params.get('view') !== 'live') return;

  const form = document.getElementById('stock-selector-form');
  const select = document.getElementById('stock-select');
  const search = document.getElementById('stock-search');

  // Keep every selector interaction inside LIVE STOCK VIEWER. The legacy inline
  // handler calls form.submit(), so overriding the instance method is the most
  // reliable way to preserve view=live and the selected symbol.
  const navigateLive = () => {
    const symbol = select?.value || 'AAPL';
    const url = `/dashboard?view=live&symbol=${encodeURIComponent(symbol)}#primary-stock-view`;
    window.location.assign(url);
  };
  if (form) {
    form.action = '/dashboard?view=live';
    form.submit = navigateLive;
    form.addEventListener('submit', event => {
      event.preventDefault();
      navigateLive();
    }, true);
  }

  // Preserve the currently selected value while filtering the dropdown.
  if (search && select) {
    search.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (select.options.length && !select.options[0].disabled) navigateLive();
      }
    }, true);
  }

  const marketSection = Array.from(document.querySelectorAll('section.grid.grid-2')).find(section =>
    Array.from(section.children).some(card => card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET')
  );
  if (!marketSection) return;

  const marketCard = Array.from(marketSection.children).find(card =>
    card.querySelector(':scope > .label')?.textContent?.trim() === 'MARKET'
  );
  const signalCard = Array.from(marketSection.children).find(card => card !== marketCard);
  if (!signalCard) return;

  // The V8 signal is directly relevant to the selected live stock, so keep it
  // visible beside MARKET rather than treating it as legacy V5 model content.
  signalCard.classList.remove('ds-model-signal-card');
  signalCard.classList.add('ds-v8-live-signal-card');
  signalCard.style.setProperty('display', 'block', 'important');
  marketSection.style.setProperty('grid-template-columns', '1fr 1fr', 'important');

  signalCard.innerHTML = `
    <div class="label">V8 5-DAY RELATIVE-RANK SIGNAL</div>
    <h2 id="v8-live-rank">Loading…</h2>
    <div id="v8-live-score" class="hero-value">—</div>
    <div class="muted">Frozen V8 DISTANCE_ONLY cross-sectional ranking score</div>
    <div class="grid grid-3" style="margin-top:18px">
      <div class="metric"><span>RANK PERCENTILE</span><strong id="v8-live-percentile">—</strong></div>
      <div class="metric"><span>TOP 10</span><strong id="v8-live-top10">—</strong></div>
      <div class="metric"><span>SIGNAL</span><strong id="v8-live-signal">—</strong></div>
    </div>
    <div id="v8-live-note" class="muted" style="margin-top:14px;font-size:.76rem;line-height:1.45">Latest eligible frozen-model development snapshot; not forward holdout evidence.</div>`;

  const symbol = select?.value || params.get('symbol') || 'AAPL';
  const rankEl = signalCard.querySelector('#v8-live-rank');
  const scoreEl = signalCard.querySelector('#v8-live-score');
  const pctEl = signalCard.querySelector('#v8-live-percentile');
  const topEl = signalCard.querySelector('#v8-live-top10');
  const signalEl = signalCard.querySelector('#v8-live-signal');
  const noteEl = signalCard.querySelector('#v8-live-note');

  fetch('/api/v8/holdout', {cache:'no-store'})
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      const rows = Array.isArray(data.latest_research_rankings) ? data.latest_research_rankings : [];
      const row = rows.find(item => String(item.symbol).toUpperCase() === String(symbol).toUpperCase());
      if (!row) throw new Error(`No V8 ranking for ${symbol}`);
      const count = rows.length;
      const rank = Number(row.rank);
      const score = Number(row.score);
      const percentile = count > 1 ? ((count - rank) / (count - 1)) * 100 : 100;
      const top10 = Boolean(row.selected_top10 || rank <= 10);

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
      rankEl.textContent = 'V8 data unavailable';
      scoreEl.textContent = '—';
      pctEl.textContent = '—';
      topEl.textContent = '—';
      signalEl.textContent = '—';
      noteEl.textContent = 'Unable to load the frozen V8 ranking snapshot for this stock.';
      console.error('[LIVE STOCK V8 SIGNAL]', error);
    });
})();