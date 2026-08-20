(() => {
  const dashboard = document.querySelector('.v4-dashboard');
  const help = dashboard?.querySelector('.v4-help');
  if (!dashboard || !help || document.getElementById('v8-leaders')) return;

  const leaders = Array.from(document.querySelectorAll('section.card')).find(section =>
    section.querySelector(':scope > .label')?.textContent?.trim() === 'V5 LEADERS'
  );
  if (!leaders) return;

  const style = document.createElement('style');
  style.id = 'v8-leaders-style';
  style.textContent = `
    #v8-leaders{margin-top:20px;overflow:hidden}
    #v8-leaders .v8l-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap}
    #v8-leaders .v8l-state{padding:7px 10px;border:1px solid rgba(239,197,107,.28);border-radius:999px;background:rgba(239,197,107,.07);color:var(--gold);font-size:.68rem;font-weight:900;letter-spacing:.04em}
    #v8-leaders .v8l-note{margin-top:5px;color:var(--muted);font-size:.78rem;line-height:1.5}
    #v8-leaders .v8l-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:16px}
    #v8-leaders .v8l-row{display:grid;grid-template-columns:46px minmax(0,1fr) 120px 90px;gap:12px;align-items:center;padding:12px 14px;border:1px solid rgba(120,155,205,.15);border-radius:14px;background:rgba(8,20,36,.5);transition:transform .15s ease,border-color .15s ease,background .15s ease}
    #v8-leaders .v8l-row:hover{transform:translateY(-1px);border-color:rgba(239,197,107,.42);background:rgba(239,197,107,.055)}
    #v8-leaders .v8l-rank{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:rgba(239,197,107,.14);color:var(--gold);font-weight:950}
    #v8-leaders .v8l-symbol{font-size:1rem;font-weight:950}.v8l-score{color:var(--muted);font-size:.7rem;margin-top:3px}
    #v8-leaders .v8l-bar{height:8px;border-radius:999px;background:rgba(120,155,205,.11);overflow:hidden;margin-top:7px}.v8l-bar span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--gold),var(--cyan))}
    #v8-leaders .v8l-signal{text-align:right}.v8l-signal span{display:block;color:var(--muted);font-size:.62rem;font-weight:900;letter-spacing:.06em}.v8l-signal strong{display:block;margin-top:3px;font-size:.86rem}
    #v8-leaders .v8l-weight{text-align:right;color:var(--green);font-size:.78rem;font-weight:900}
    #v8-leaders .v8l-footer{display:flex;gap:9px;flex-wrap:wrap;margin-top:14px;padding-top:14px;border-top:1px solid rgba(120,155,205,.14)}.v8l-chip{padding:6px 9px;border-radius:999px;border:1px solid rgba(120,155,205,.16);background:rgba(8,20,36,.45);color:#dfe8f6;font-size:.68rem;font-weight:850}
    @media(max-width:1000px){#v8-leaders .v8l-grid{grid-template-columns:1fr}}@media(max-width:650px){#v8-leaders .v8l-row{grid-template-columns:42px minmax(0,1fr) 80px}.v8l-weight{display:none}}
  `;
  document.getElementById(style.id)?.remove(); document.head.appendChild(style);

  leaders.id = 'v8-leaders';
  leaders.innerHTML = `<div class="v8l-head"><div><div class="label">V8 LEADERS</div><h2>Top 10 Frozen DISTANCE_ONLY Rankings</h2><div class="v8l-note" id="v8l-note">Loading the latest eligible frozen-model snapshot…</div></div><div class="v8l-state" id="v8l-state">LOADING</div></div><div class="v8l-grid" id="v8l-grid"></div><div class="v8l-footer"><span class="v8l-chip">Top 10</span><span class="v8l-chip">10% target each</span><span class="v8l-chip">DISTANCE_ONLY</span><span class="v8l-chip">SPY benchmark only</span><span class="v8l-chip">Development snapshot — not holdout evidence</span></div>`;
  help.insertAdjacentElement('beforebegin', leaders);
  const grid=leaders.querySelector('#v8l-grid'),state=leaders.querySelector('#v8l-state'),note=leaders.querySelector('#v8l-note');

  async function load(){
    try{
      const r=await fetch('/api/v8/holdout',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`); const d=await r.json();
      const rows=Array.isArray(d.latest_research_top10)?d.latest_research_top10.slice(0,10):[];
      state.textContent=String(d.state||'FROZEN').replaceAll('_',' ');
      const ts=d.latest_research_top10_timestamp_utc?new Date(d.latest_research_top10_timestamp_utc):null;
      note.textContent=ts&&!Number.isNaN(ts.getTime())?`Latest eligible frozen V8 development snapshot: ${ts.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'})}. Scores are ranking signals, not calibrated probabilities.`:'Latest eligible frozen V8 development snapshot. Scores are ranking signals, not calibrated probabilities.';
      const scores=rows.map(x=>Number(x.score)).filter(Number.isFinite),lo=scores.length?Math.min(...scores):0,hi=scores.length?Math.max(...scores):1,span=Math.max(1e-9,hi-lo);
      grid.innerHTML=rows.length?rows.map(row=>{const score=Number(row.score),width=Number.isFinite(score)?20+80*((score-lo)/span):0;return `<div class="v8l-row"><div class="v8l-rank">#${row.rank}</div><div><div class="v8l-symbol">${row.symbol}</div><div class="v8l-score">DISTANCE_ONLY score ${Number.isFinite(score)?score.toFixed(4):'—'}</div><div class="v8l-bar"><span style="width:${Math.max(0,Math.min(100,width))}%"></span></div></div><div class="v8l-signal"><span>RANK SIGNAL</span><strong>${Number.isFinite(score)?score.toFixed(4):'—'}</strong></div><div class="v8l-weight">10% target</div></div>`}).join(''):'<div class="muted">V8 Top-10 ranking snapshot is unavailable.</div>';
    }catch(e){state.textContent='DATA UNAVAILABLE';note.textContent='Unable to load the frozen V8 ranking snapshot.';grid.innerHTML='<div class="muted">V8 leaders are temporarily unavailable.</div>';console.error('V8 leaders failed:',e);}
  }
  load(); setInterval(load,30000);
})();
