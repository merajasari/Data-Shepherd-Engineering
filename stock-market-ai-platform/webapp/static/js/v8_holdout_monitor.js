(() => {
  const EXPECTED_SHA='ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41';
  const money=v=>'$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const pct=v=>v==null?'—':`${Number(v)>=0?'+':''}${(100*Number(v)).toFixed(2)}%`;
  const date=t=>t?new Date(t).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'—';

  const style=document.createElement('style');
  style.textContent=`
    .v8h-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}.v8h-card{padding:12px;border:1px solid rgba(120,155,205,.16);border-radius:12px;background:rgba(7,16,31,.48)}.v8h-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.v8h-value{font-size:1.05rem;font-weight:700;margin-top:3px}.v8h-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;word-break:break-all;color:var(--muted)}.v8h-chart{height:280px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.45);overflow:hidden;margin-top:12px}.v8h-chart svg{width:100%;height:100%;display:block}.v8h-note{font-size:.78rem;color:var(--muted);margin-top:8px}
    .v8-paper-card{margin-top:18px;border:1px solid rgba(57,227,161,.25);border-radius:18px;padding:18px;background:rgba(8,20,36,.58)}.v8-paper-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-end;flex-wrap:wrap}.v8-paper-wrap{position:relative;height:330px;margin-top:12px}.v8-paper-wrap svg{width:100%;height:100%;display:block}.v8-paper-tooltip{position:absolute;display:none;pointer-events:none;background:#071525;border:1px solid var(--border);padding:8px 10px;border-radius:9px;font-size:.78rem;z-index:20}.v8-rank-row{display:grid;grid-template-columns:60px 90px 1fr 150px;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid rgba(120,155,205,.1)}.v8-scorebar{height:9px;border-radius:99px;background:#172943;overflow:hidden}.v8-scorefill{height:100%;background:linear-gradient(90deg,var(--purple),var(--cyan))}
    @media(max-width:800px){.v8h-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.v8-rank-row{grid-template-columns:48px 72px 1fr 100px}}
  `; document.head.appendChild(style);

  function sectionByLabel(text){return [...document.querySelectorAll('section')].find(s=>s.querySelector('.label')?.textContent.trim()===text);}
  function currentSymbol(){const sel=document.getElementById('stock-select');return sel?.value||new URLSearchParams(location.search).get('symbol')||'AAPL';}

  function drawSimple(box, curve, strategyKey, spyKey, tooltip){
    if(!box)return;
    if(!curve||curve.length<1){box.innerHTML='<div style="padding:28px;color:var(--muted)">Paper equity history will appear after completed V8 cohorts are available.</div>';return;}
    const W=1000,H=300,p={l:70,r:28,t:24,b:42}; const vals=curve.flatMap(x=>[Number(x[strategyKey]),Number(x[spyKey])]);
    let lo=Math.min(...vals),hi=Math.max(...vals); const span=Math.max(100,hi-lo); lo-=span*.12; hi+=span*.12;
    const x=i=>p.l+(W-p.l-p.r)*(i/Math.max(1,curve.length-1)); const y=v=>p.t+(H-p.t-p.b)*(1-(v-lo)/Math.max(1,hi-lo));
    const path=k=>curve.map((d,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(Number(d[k])).toFixed(1)}`).join(' ');
    let grid=''; for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3,yy=y(v);grid+=`<line x1="${p.l}" y1="${yy}" x2="${W-p.r}" y2="${yy}" stroke="rgba(145,166,194,.12)"/><text x="${p.l-8}" y="${yy+4}" text-anchor="end" fill="#91a6c2" font-size="11">${money(v)}</text>`;}
    box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}<path d="${path(strategyKey)}" fill="none" stroke="#39e3a1" stroke-width="3"/><path d="${path(spyKey)}" fill="none" stroke="#91a6c2" stroke-width="2" stroke-dasharray="8 6"/><rect data-overlay x="${p.l}" y="${p.t}" width="${W-p.l-p.r}" height="${H-p.t-p.b}" fill="rgba(0,0,0,.001)"/></svg>`;
    const overlay=box.querySelector('[data-overlay]');
    if(overlay&&tooltip){overlay.addEventListener('mousemove',e=>{const r=box.getBoundingClientRect();const frac=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));const i=Math.min(curve.length-1,Math.round(frac*(curve.length-1)));const d=curve[i];tooltip.style.display='block';tooltip.style.left=Math.min(r.width-230,e.clientX-r.left+12)+'px';tooltip.style.top='12px';tooltip.innerHTML=`<strong>${date(d.timestamp_utc)}</strong><br>V8 paper: ${money(d[strategyKey])}<br>SPY: ${money(d[spyKey])}`;});overlay.addEventListener('mouseleave',()=>tooltip.style.display='none');}
  }

  function renderPaper(paper){
    const dash=document.querySelector('.v4-dashboard'); if(!dash)return;
    const label=dash.querySelector(':scope > .label'); if(label)label.textContent='V8 OPERATIONAL PAPER PORTFOLIO';
    const h2=dash.querySelector(':scope > h2'); if(h2)h2.textContent='Frozen V8 Paper-Trading Monitor';
    const intro=dash.querySelector(':scope > p.muted'); if(intro)intro.textContent='Exact frozen V8 DISTANCE_ONLY strategy: Top 10, equal weight, next-session open entry, 5-session hold, all five cohort offsets, and 10 bps modeled trading cost. Operational simulation only — never holdout evidence and never brokerage orders.';
    const eq=document.getElementById('v4-equity'); if(eq)eq.textContent=money(paper.equity);
    const gain=document.getElementById('v4-gain'); if(gain){gain.textContent=pct(paper.total_return);gain.className='v4-gain '+(paper.total_return>=0?'positive':'negative');}
    const start=document.getElementById('v4-starting-equity');if(start)start.textContent='vs $100,000 V8 paper starting equity';
    const ids=[['v4-total-return',paper.total_return],['v4-return',paper.total_return],['v4-spy',paper.spy_return],['v4-excess',paper.excess_return]];ids.forEach(([id,v])=>{const n=document.getElementById(id);if(n)n.textContent=pct(v);});
    const metrics=dash.querySelectorAll('.v4-small-metrics .metric span'); if(metrics[0])metrics[0].textContent='V8 PAPER TOTAL RETURN';if(metrics[1])metrics[1].textContent='V8 PAPER RETURN';if(metrics[2])metrics[2].textContent='SPY SINCE PAPER START';if(metrics[3])metrics[3].textContent='V8 EXCESS VS SPY';

    let card=document.getElementById('v8-paper-equity-history');
    if(!card){card=document.createElement('div');card.id='v8-paper-equity-history';card.className='v8-paper-card';const main=dash.querySelector('.v4-main');main?.insertAdjacentElement('afterend',card);}
    card.innerHTML=`<div class="v8-paper-head"><div><div class="label">V8 PAPER PORTFOLIO EQUITY</div><h3>Operational Paper Equity vs SPY</h3><div class="muted">Append-only V8 operational paper journal. This is intentionally separate from the MODEL PERFORMANCE COMPARISON and from the Sep-1+ untouched holdout.</div></div><div class="top5"><span class="chip">STATE: ${paper.state}</span><span class="chip">EXITS: ${paper.completed_cohorts}</span><span class="chip">ORDERS: NO</span></div></div><div class="v8-paper-wrap"><div class="v8-paper-tooltip"></div><div class="v8-paper-chart" style="height:100%"></div></div><div class="v8h-note">Solid = V8 operational paper portfolio · dashed = SPY benchmark. Starts at $100,000 and grows only from genuinely recorded paper events.</div>`;
    drawSimple(card.querySelector('.v8-paper-chart'),paper.curve,'strategy_equity','spy_equity',card.querySelector('.v8-paper-tooltip'));
  }

  function renderRankings(model){
    if(!model?.available)return;
    document.title='Data Shepherd Engineering — V8 Dashboard';
    const subtitle=document.querySelector('header .brand .muted');if(subtitle)subtitle.textContent='Frozen V8 DISTANCE_ONLY cross-sectional signal + V8 operational paper monitoring';
    const health=document.getElementById('stock-stream-health-card');if(health){const p=health.querySelector('p.muted');if(p)p.textContent='Read-only monitoring for the frozen V8 universe (100 stocks + SPY). During regular U.S. trading hours this card turns stale if live quote timestamps stop advancing.';}

    const shadow=document.getElementById('v5-shadow-status')?.closest('section');if(shadow)shadow.style.display='none';

    const snap=sectionByLabel('V5 FROZEN MODEL');if(snap){snap.innerHTML=`<div class="label">V8 FROZEN MODEL</div><h2>Cross-Sectional Ranking Snapshot</h2><p class="muted">DISTANCE_ONLY ranks the 100-stock universe by distance-from-20-day-low residualized against same-day 20-day volatility and 60-day beta. Higher residual signal ranks higher.</p><div class="grid metrics" style="margin-top:18px"><div class="metric"><span>DECISION DATE</span><strong>${date(model.decision_date_utc)}</strong></div><div class="metric"><span>CANDIDATES</span><strong>${model.candidate_count}</strong></div><div class="metric"><span>SIGNAL</span><strong>DISTANCE_ONLY</strong></div><div class="metric"><span>TOP N</span><strong>10</strong></div><div class="metric"><span>HOLD</span><strong>5 sessions</strong></div><div class="metric"><span>COST</span><strong>10 bps</strong></div></div><div class="top5" style="margin-top:18px">${model.top10.map(r=>`<div class="chip top">#${r.rank} ${r.symbol} · ${r.score.toFixed(5)}</div>`).join('')}</div>`;}

    const selector=sectionByLabel('PRIMARY STOCK VIEW');if(selector){const h=selector.querySelector('h3');if(h)h.textContent='Detailed Market + V8 Rank';const m=selector.querySelector('.muted');if(m)m.textContent='Search by ticker or company name, then inspect its market data and frozen V8 cross-sectional rank.';}

    const sym=currentSymbol();const row=model.rankings.find(r=>r.symbol===sym);
    const signalCard=[...document.querySelectorAll('section.grid.grid-2 .card')].find(c=>c.querySelector('.label')?.textContent.includes('V5 5-DAY'));
    if(signalCard&&row){signalCard.innerHTML=`<div class="label">V8 DISTANCE_ONLY SIGNAL</div><h2>#${row.rank} / ${model.candidate_count}</h2><div class="hero-value ${row.selected_top10?'positive':''}">${row.score.toFixed(6)}</div><div class="muted">Cross-sectional residual score; higher ranks higher. This is not a calibrated return forecast.</div><div class="grid grid-3" style="margin-top:18px"><div class="metric"><span>RANK PERCENTILE</span><strong>${(row.rank_percentile*100).toFixed(1)}%</strong></div><div class="metric"><span>TOP 10</span><strong>${row.selected_top10?'YES':'NO'}</strong></div><div class="metric"><span>FROZEN SHA</span><strong style="font-size:.75rem">${EXPECTED_SHA.slice(0,12)}…</strong></div></div>`;}

    const leaders=sectionByLabel('V5 LEADERS');if(leaders){leaders.innerHTML=`<div class="label">V8 LEADERS</div><h2>Top 10 Frozen V8 Cross-Sectional Rankings</h2><div class="table-wrap"><table><thead><tr><th>Rank</th><th>Symbol</th><th>Residual Score</th><th>Rank Percentile</th><th>Selected</th></tr></thead><tbody>${model.top10.map(r=>`<tr><td>#${r.rank}</td><td><strong>${r.symbol}</strong></td><td>${r.score.toFixed(6)}</td><td>${(r.rank_percentile*100).toFixed(1)}%</td><td>YES</td></tr>`).join('')}</tbody></table></div>`;}

    const board=sectionByLabel('100-STOCK V5 RANKING BOARD');if(board){board.innerHTML=`<div class="label">100-STOCK V8 RANKING BOARD</div><h2>Full Frozen V8 Investable Universe</h2><p class="muted">Sorted strongest to weakest by the frozen DISTANCE_ONLY residual signal.</p><div class="rank-board">${model.rankings.map(r=>`<div class="v8-rank-row ${r.selected_top10?'top5row':''}"><strong>#${r.rank}</strong><strong>${r.symbol}</strong><div class="v8-scorebar"><div class="v8-scorefill" style="width:${Math.max(1,r.rank_percentile*100)}%"></div></div><div>${r.score.toFixed(6)}</div></div>`).join('')}</div>`;}

    const contract=sectionByLabel('FROZEN V5 MODEL CONTRACT');if(contract){const parent=contract.parentElement;contract.innerHTML=`<div class="label">FROZEN V8 MODEL CONTRACT</div><h3>V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS</h3><div class="muted">distance_from_low_20d · neutralized to volatility_20d + beta_60 · 100 stocks · no refitting, signal search, Top-N tuning, holding-period tuning, or cost tuning.</div><div class="warning" style="margin-top:16px">Frozen SHA-256: ${EXPECTED_SHA}</div>`;const pc=parent?.querySelectorAll('.card')[1];if(pc)pc.innerHTML=`<div class="label">PORTFOLIO CONTRACT</div><h3>Frozen V8</h3><div class="metric"><span>TOP 10</span><strong>Equal weight</strong></div><div class="metric" style="margin-top:10px"><span>EXECUTION</span><strong>Next-session open</strong></div><div class="metric" style="margin-top:10px"><span>HOLD</span><strong>5 sessions · 5 cohorts</strong></div><div class="metric" style="margin-top:10px"><span>MODELED COST</span><strong>10 bps / $ traded</strong></div>`;}

    const pipe=sectionByLabel('PLATFORM PIPELINE');if(pipe){pipe.innerHTML=pipe.innerHTML.replaceAll('FROZEN V5 MODEL','FROZEN V8 MODEL').replaceAll('RANKINGS','V8 RANKINGS');}
  }

  function renderHoldout(d){const root=document.getElementById('v8-holdout-monitor');if(!root)return;const q=s=>root.querySelector(s);if(q('[data-v8h-state]'))q('[data-v8h-state]').textContent=d.state;if(q('[data-v8h-decisions]'))q('[data-v8h-decisions]').textContent=d.decisions;if(q('[data-v8h-exits]'))q('[data-v8h-exits]').textContent=d.completed_cohorts;if(q('[data-v8h-edge]'))q('[data-v8h-edge]').textContent=pct(d.mean_net_relative_return);if(q('[data-v8h-hit]'))q('[data-v8h-hit]').textContent=d.net_relative_hit_rate==null?'—':(100*d.net_relative_hit_rate).toFixed(1)+'%';if(q('[data-v8h-sha]'))q('[data-v8h-sha]').textContent=d.frozen_sha256;if(q('[data-v8h-start]'))q('[data-v8h-start]').textContent=date(d.holdout_start_utc);drawSimple(q('.v8h-chart'),(d.curve||[]).map(x=>({...x,strategy_equity:x.strategy_normalized,spy_equity:x.spy_normalized})),'strategy_equity','spy_equity',null);}

  async function refresh(){try{const r=await fetch('/api/v8/holdout',{cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();renderRankings(d.dashboard);renderPaper(d.paper);renderHoldout(d);}catch(e){console.error('V8 dashboard refresh failed',e);}}
  refresh(); setInterval(refresh,30000);
})();
