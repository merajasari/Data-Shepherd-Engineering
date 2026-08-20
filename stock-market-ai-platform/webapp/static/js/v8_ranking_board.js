(() => {
  const sections = Array.from(document.querySelectorAll('section.card'));
  const board = sections.find(section =>
    section.querySelector(':scope > .label')?.textContent?.trim() === '100-STOCK V5 RANKING BOARD'
  );
  if (!board) return;

  const legacyMeta = {};
  board.querySelectorAll('.rank-row').forEach(row => {
    const symbolEl = row.querySelector('.ticker-hover');
    if (!symbolEl) return;
    const symbol = symbolEl.textContent.trim();
    legacyMeta[symbol] = {
      company: symbolEl.dataset.company || '',
      sector: row.querySelector('.sector')?.textContent?.trim() || ''
    };
  });

  const style = document.createElement('style');
  style.id = 'v8-full-ranking-board-style';
  style.textContent = `
    #v8-full-ranking-board .v8rb-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}
    #v8-full-ranking-board .v8rb-badge{padding:7px 10px;border:1px solid rgba(239,197,107,.28);border-radius:999px;background:rgba(239,197,107,.07);color:var(--gold);font-size:.68rem;font-weight:900}
    #v8-full-ranking-board .v8rb-note{margin-top:5px;color:var(--muted);font-size:.78rem;line-height:1.45}
    #v8-full-ranking-board .v8rb-controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:16px}
    #v8-full-ranking-board .v8rb-search{min-width:250px;flex:1 1 260px;padding:10px 12px;border-radius:11px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:800}
    #v8-full-ranking-board .v8rb-toggle{padding:9px 11px;border-radius:999px;border:1px solid var(--border);background:rgba(8,20,36,.55);color:var(--muted);font-weight:850;cursor:pointer}
    #v8-full-ranking-board .v8rb-toggle.active,#v8-full-ranking-board .v8rb-toggle:hover{color:#07101f;background:linear-gradient(90deg,var(--gold),var(--cyan));border-color:transparent}
    #v8-full-ranking-board .v8rb-board{max-height:720px;overflow:auto;margin-top:14px;padding-right:4px}
    #v8-full-ranking-board .v8rb-row{display:grid;grid-template-columns:64px 110px minmax(180px,1fr) 130px 130px 160px;gap:12px;align-items:center;padding:11px 10px;border-bottom:1px solid rgba(120,155,205,.10);border-radius:10px}
    #v8-full-ranking-board .v8rb-row.top10{background:linear-gradient(90deg,rgba(239,197,107,.09),rgba(57,227,161,.035));border:1px solid rgba(239,197,107,.16);margin-bottom:4px}
    #v8-full-ranking-board .v8rb-rank{font-weight:950;color:#dfe8f6}
    #v8-full-ranking-board .v8rb-row.top10 .v8rb-rank{color:var(--gold)}
    #v8-full-ranking-board .v8rb-symbol{font-weight:950}
    #v8-full-ranking-board .v8rb-company{color:var(--muted);font-size:.7rem;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    #v8-full-ranking-board .v8rb-bar{height:9px;border-radius:99px;background:#172943;overflow:hidden}
    #v8-full-ranking-board .v8rb-fill{height:100%;background:linear-gradient(90deg,var(--purple),var(--cyan))}
    #v8-full-ranking-board .v8rb-score{text-align:right;font-weight:900}
    #v8-full-ranking-board .v8rb-selected{text-align:right;font-size:.72rem;font-weight:900;color:var(--green)}
    #v8-full-ranking-board .v8rb-sector{text-align:right;color:var(--muted);font-size:.72rem}
    #v8-full-ranking-board .v8rb-header{display:grid;grid-template-columns:64px 110px minmax(180px,1fr) 130px 130px 160px;gap:12px;padding:0 10px 8px;color:var(--muted);font-size:.64rem;font-weight:900;letter-spacing:.08em}
    #v8-full-ranking-board .v8rb-header span:nth-child(n+4){text-align:right}
    @media(max-width:900px){#v8-full-ranking-board .v8rb-header{display:none}#v8-full-ranking-board .v8rb-row{grid-template-columns:52px 90px 1fr 110px}.v8rb-sector,.v8rb-selected{display:none}}
  `;
  document.getElementById(style.id)?.remove();
  document.head.appendChild(style);

  board.id = 'v8-full-ranking-board';
  board.innerHTML = `
    <div class="v8rb-head">
      <div>
        <div class="label">100-STOCK V8 RANKING BOARD</div>
        <h2>Frozen DISTANCE_ONLY Full Investable Universe</h2>
        <div class="v8rb-note" id="v8rb-note">Loading the latest eligible frozen-model ranking snapshot…</div>
      </div>
      <div class="v8rb-badge" id="v8rb-badge">LOADING</div>
    </div>
    <div class="v8rb-controls">
      <input id="v8rb-search" class="v8rb-search" type="search" placeholder="Search ticker, company, or sector…" aria-label="Search V8 rankings">
      <button type="button" class="v8rb-toggle active" data-filter="all">All 100</button>
      <button type="button" class="v8rb-toggle" data-filter="top10">Top 10 only</button>
    </div>
    <div class="v8rb-board">
      <div class="v8rb-header"><span>RANK</span><span>SYMBOL</span><span>RANK STRENGTH</span><span>SCORE</span><span>V8 STATUS</span><span>SECTOR</span></div>
      <div id="v8rb-rows" class="muted">Loading V8 rankings…</div>
    </div>`;

  const rowsHost = board.querySelector('#v8rb-rows');
  const search = board.querySelector('#v8rb-search');
  const toggles = Array.from(board.querySelectorAll('.v8rb-toggle'));
  let allRows = [];
  let activeFilter = 'all';

  const fmtScore = v => Number.isFinite(Number(v)) ? Number(v).toFixed(5) : '—';

  function render(){
    const q = search.value.trim().toLowerCase();
    const filtered = allRows.filter(row => {
      const meta = legacyMeta[row.symbol] || {};
      const match = !q || row.symbol.toLowerCase().includes(q) || (meta.company || '').toLowerCase().includes(q) || (meta.sector || '').toLowerCase().includes(q);
      const filterMatch = activeFilter === 'top10' ? row.selected_top10 : true;
      return match && filterMatch;
    });
    const n = Math.max(1, allRows.length);
    rowsHost.innerHTML = filtered.length ? filtered.map(row => {
      const meta = legacyMeta[row.symbol] || {};
      const strength = n <= 1 ? 100 : Math.max(0, Math.min(100, 100 * (n - Number(row.rank)) / (n - 1)));
      const top = !!row.selected_top10;
      return `<div class="v8rb-row${top ? ' top10' : ''}">
        <div class="v8rb-rank">#${row.rank}</div>
        <div><div class="v8rb-symbol">${row.symbol}</div><div class="v8rb-company">${meta.company || '—'}</div></div>
        <div><div class="v8rb-bar"><div class="v8rb-fill" style="width:${strength.toFixed(1)}%"></div></div></div>
        <div class="v8rb-score">${fmtScore(row.score)}</div>
        <div class="v8rb-selected">${top ? 'TOP 10 · 10%' : 'WATCH'}</div>
        <div class="v8rb-sector">${meta.sector || '—'}</div>
      </div>`;
    }).join('') : '<div class="muted" style="padding:20px">No V8 rankings match this filter.</div>';
  }

  toggles.forEach(btn => btn.addEventListener('click', () => {
    activeFilter = btn.dataset.filter;
    toggles.forEach(x => x.classList.toggle('active', x === btn));
    render();
  }));
  search.addEventListener('input', render);

  async function load(){
    try {
      const r = await fetch('/api/v8/holdout',{cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      allRows = Array.isArray(d.latest_research_rankings) ? d.latest_research_rankings.slice().sort((a,b)=>Number(a.rank)-Number(b.rank)) : [];
      const ts = d.latest_research_rankings_timestamp_utc ? new Date(d.latest_research_rankings_timestamp_utc) : null;
      board.querySelector('#v8rb-badge').textContent = `${allRows.length || 0} STOCKS · FROZEN V8`;
      board.querySelector('#v8rb-note').textContent = ts && !Number.isNaN(ts.getTime())
        ? `Latest eligible DISTANCE_ONLY development snapshot: ${ts.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'})}. Top 10 are highlighted and receive 10% target weight each. Not forward holdout evidence.`
        : 'Latest eligible DISTANCE_ONLY development snapshot. Top 10 are highlighted and receive 10% target weight each. Not forward holdout evidence.';
      render();
    } catch (e) {
      board.querySelector('#v8rb-badge').textContent = 'DATA UNAVAILABLE';
      board.querySelector('#v8rb-note').textContent = 'The frozen V8 full-universe ranking snapshot is temporarily unavailable.';
      rowsHost.innerHTML = '<div class="muted" style="padding:20px">Unable to load V8 ranking board.</div>';
      console.error('V8 ranking board failed:', e);
    }
  }

  load();
})();
