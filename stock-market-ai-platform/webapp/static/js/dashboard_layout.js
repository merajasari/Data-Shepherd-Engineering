(() => {
  const technicalIndicators = Array.from(document.querySelectorAll('section.grid.metrics')).find(section => {
    const labels = Array.from(section.querySelectorAll('.metric > span')).map(node => node.textContent.trim());
    return ['RSI 14','SMA 20','SMA 50','SMA 200','20D VOL','VOLUME RATIO'].every(label => labels.includes(label));
  });
  if (technicalIndicators) {
    technicalIndicators.classList.add('ds-technical-indicators', 'ds-live-stock-keep');
    technicalIndicators.setAttribute('data-selected-stock-indicators', 'true');
    const marketSection = document.querySelector('.ds-market-section');
    if (marketSection && marketSection.nextElementSibling !== technicalIndicators) marketSection.insertAdjacentElement('afterend', technicalIndicators);
  }
  const technicalStyle = document.createElement('style');
  technicalStyle.id = 'ds-technical-indicators-placement';
  technicalStyle.textContent = `body.ds-model-research-view .ds-technical-indicators{display:none!important}body.ds-live-stock-view .ds-technical-indicators{display:grid!important}body.ds-live-stock-view .ds-live-comparison-stack{display:grid!important;grid-template-columns:1fr!important;gap:22px!important}body.ds-live-stock-view .ds-live-comparison-stack > .ds-top-live-row,body.ds-live-stock-view .ds-live-comparison-stack > .ds-live-viewer-card{grid-column:1/-1!important;width:100%!important}`;
  document.getElementById(technicalStyle.id)?.remove(); document.head.appendChild(technicalStyle);

  const removeCompactV4Equity = () => { const compact=document.getElementById('v4-compact-equity-card'); if(compact){compact.remove();return true} return false; };
  const moveV8RankSignal = () => {
    const latestModelEquity=document.getElementById('v8-compact-equity-card'); if(!latestModelEquity)return false;
    const signal=Array.from(document.querySelectorAll('.card')).find(node=>{const label=node.querySelector(':scope > .label')?.textContent?.trim()||'';return label==='V8 5-DAY RELATIVE-RANK SIGNAL'||label==='V5 5-DAY RELATIVE-RANK SIGNAL'}); if(!signal)return false;
    if(latestModelEquity.nextElementSibling!==signal)latestModelEquity.insertAdjacentElement('afterend',signal); signal.style.marginTop='20px'; return true;
  };
  const findFullLiveViewer = () => {
    const heading=Array.from(document.querySelectorAll('h1,h2,h3,h4')).find(node=>node.textContent.trim()==='Search and Inspect Live Stocks');
    if(heading){const panel=heading.closest('.card, section, article');if(panel)return panel}
    const candidates=Array.from(document.querySelectorAll('.card, section, article')).filter(node=>{const text=node.textContent||'';return /LIVE STOCK VIEWER/i.test(text)&&/Search and Inspect Live Stocks/i.test(text)&&(node.querySelector('input')||node.querySelector('select')||node.querySelector('[role="combobox"]'))});
    return candidates.sort((a,b)=>a.textContent.length-b.textContent.length)[0]||null;
  };
  const arrangeLiveStockViewer = () => {
    if(!document.body.classList.contains('ds-live-stock-view'))return false;
    const comparison=document.getElementById('ds-top-live-comparison');if(!comparison)return false;
    const comparisonRow=comparison.closest('.ds-top-live-row')||comparison;const liveViewer=findFullLiveViewer();
    const market=Array.from(document.querySelectorAll('.card')).find(node=>{const label=node.querySelector(':scope > .label')?.textContent?.trim()||'';return label==='MARKET'||node.classList.contains('ds-market-section')});
    const stack=comparisonRow.parentElement;if(stack){stack.classList.remove('ds-market-comparison-grid');stack.classList.add('ds-live-comparison-stack')}
    if(liveViewer&&stack){liveViewer.classList.add('ds-live-viewer-card','ds-live-stock-keep');if(comparisonRow.nextElementSibling!==liveViewer)comparisonRow.insertAdjacentElement('afterend',liveViewer)}
    if(market&&market!==liveViewer)market.remove();return Boolean(liveViewer||market);
  };

  const clarifyDashboardDataClocks = () => {
    const cards = Array.from(document.querySelectorAll('section.card'));
    const snapshot = cards.find(card => card.querySelector(':scope > .label')?.textContent?.trim() === 'V8 FROZEN STRATEGY');
    if (snapshot) {
      snapshot.querySelector(':scope > .label').textContent = 'V8 COMPLETED-EOD RESEARCH SNAPSHOT · NOT FORWARD EVIDENCE';
      const note = snapshot.querySelector(':scope > p.muted');
      if (note && !note.textContent.includes('different completed market session')) {
        note.textContent += ' This reference snapshot may differ from an earlier official holdout decision because it represents a different completed market session.';
      }
    }

    const leaders = cards.find(card => card.querySelector(':scope > .label')?.textContent?.trim() === 'V8 LEADERS');
    if (leaders) {
      leaders.querySelector(':scope > .label').textContent = 'V8 COMPLETED-EOD RESEARCH LEADERS';
      if (!leaders.querySelector('.ds-eod-clock-note')) {
        const note = document.createElement('p');
        note.className = 'muted ds-eod-clock-note';
        note.textContent = 'Latest price can refresh intraday. Change, rank, signal, Top-10 membership, and RSI remain tied to the completed-EOD research session.';
        leaders.querySelector('h2')?.insertAdjacentElement('afterend', note);
      }
      const labels = ['Symbol','Latest Price','Completed-EOD Change','EOD Rank','EOD Rank Percentile','EOD V8 Signal','EOD Top 10','EOD RSI'];
      leaders.querySelectorAll('thead th').forEach((node, index) => { if (labels[index]) node.textContent = labels[index]; });
    }
  };

  const addV8OperationsDashboard = () => {
    if(document.getElementById('v8-forward-ops')) return;
    const anchor=document.getElementById('stock-stream-health-card') || document.querySelector('section.card'); if(!anchor)return;
    const section=document.createElement('section'); section.className='card'; section.id='v8-forward-ops'; section.style.marginBottom='22px';
    section.innerHTML=`<div class="label">V8 FORWARD EVIDENCE + RESEARCH SNAPSHOT</div><h2>Frozen Strategy · Synchronized Provenance</h2><p class="muted">One synchronized API snapshot separates operational readiness, research rankings, and official forward evidence. Read-only; no brokerage orders are placed.</p><div class="grid metrics" style="margin-top:18px"><div class="metric"><span>OPERATIONAL READINESS</span><strong id="v8ops-ready">CHECKING</strong></div><div class="metric"><span>HOLDOUT STATE</span><strong id="v8ops-holdout">—</strong></div><div class="metric"><span>PRODUCTION RANKING SESSION</span><strong id="v8ops-date">—</strong></div><div class="metric"><span>PRODUCTION ELIGIBILITY</span><strong id="v8ops-eligible">—</strong></div><div class="metric"><span>OFFICIAL JOURNAL EVENTS</span><strong id="v8ops-events">—</strong></div><div class="metric"><span>COMPLETED COHORTS</span><strong id="v8ops-cohorts">—</strong></div></div><div class="grid grid-2" style="margin-top:18px"><div class="metric"><span>LATEST COMPLETED-EOD RESEARCH SNAPSHOT</span><div id="v8ops-top10" class="top5" style="margin-top:12px"><span class="muted">Loading…</span></div><div id="v8ops-top10-note" class="muted" style="margin-top:10px;font-size:.82rem"></div></div><div class="metric"><span>OFFICIAL FORWARD EVIDENCE</span><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:12px"><div><div class="muted">Decisions</div><strong id="v8ops-decisions">—</strong></div><div><div class="muted">Entries</div><strong id="v8ops-entries">—</strong></div><div><div class="muted">Rel. Return</div><strong id="v8ops-return">—</strong></div></div><div id="v8ops-sha" class="muted" style="margin-top:14px;font-size:.78rem;word-break:break-all">Frozen SHA: checking…</div></div></div><div id="v8ops-detail" class="muted" style="margin-top:16px">Loading synchronized V8 operational state…</div>`;
    anchor.insertAdjacentElement('afterend',section);
    const style=document.createElement('style');style.id='v8-forward-ops-style';style.textContent=`#v8-forward-ops .top5 .chip{font-size:.82rem;padding:8px 11px}#v8-forward-ops .v8-ready{color:var(--green)}#v8-forward-ops .v8-bad{color:var(--red)}#v8-forward-ops .v8-wait{color:var(--gold)}@media(max-width:650px){#v8-forward-ops .grid-2{grid-template-columns:1fr!important}}`;document.head.appendChild(style);
    const fmtDate=v=>v?new Date(v).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric',timeZone:'UTC'}):'—';
    const fmtTime=v=>v?new Date(v).toLocaleString(undefined,{year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—';
    const refresh=async()=>{try{const d=await window.DataShepherdV8Snapshot.get();
      const ready=document.getElementById('v8ops-ready');ready.textContent=d.readiness_status||'UNKNOWN';ready.className=d.readiness_status==='READY'?'v8-ready':'v8-bad';
      document.getElementById('v8ops-holdout').textContent=d.state==='WAITING_FOR_HOLDOUT'?`${d.days_until_holdout}d`:d.state;
      document.getElementById('v8ops-date').textContent=d.ranking_timestamp_utc?fmtDate(d.ranking_timestamp_utc):'Awaiting production ranking';
      document.getElementById('v8ops-eligible').textContent=d.ranking_eligible_count!=null?`${d.ranking_eligible_count}/100`:'—';
      document.getElementById('v8ops-events').textContent=d.journal_event_count??0;document.getElementById('v8ops-cohorts').textContent=d.completed_cohorts??0;document.getElementById('v8ops-decisions').textContent=d.decisions??0;document.getElementById('v8ops-entries').textContent=d.entries??0;
      const rr=document.getElementById('v8ops-return');rr.textContent=d.mean_net_relative_return==null?'Awaiting holdout':`${(100*d.mean_net_relative_return).toFixed(2)}%`;if(d.mean_net_relative_return!=null)rr.className=d.mean_net_relative_return>=0?'positive':'negative';
      const top=document.getElementById('v8ops-top10');const researchRows=d.latest_research_top10||[];top.innerHTML=researchRows.map((x,i)=>`<span class="chip top">${i+1}. ${x.symbol}</span>`).join('')||'<span class="muted">No completed-EOD research ranking list has been published.</span>';document.getElementById('v8ops-top10-note').textContent=`Research session: ${fmtDate(d.latest_research_top10_timestamp_utc)} · ${d.latest_research_top10_note||'Reference snapshot only; not forward evidence.'}`;
      document.getElementById('v8ops-sha').textContent=`Frozen SHA ${d.frozen_sha_verified?'✓':'⚠'}: ${d.frozen_sha256||'—'}`;
      const issues=[...(d.readiness_failures||[]),...(d.readiness_warnings||[])];const sync=window.DataShepherdV8Snapshot.info();document.getElementById('v8ops-detail').textContent=issues.length?`Operational issues: ${issues.join(' · ')} · Browser synchronized ${fmtTime(sync.fetchedAtUtc)}`:`Operational state published ${fmtTime(d.readiness_updated_at_utc)} · Browser synchronized ${fmtTime(sync.fetchedAtUtc)} · Feature session ${fmtDate(d.feature_common_latest_utc)} · Gold session ${fmtDate(d.gold_common_latest_utc)} · Brokerage orders: NO · Strategy modified: NO`;
    }catch(e){const ready=document.getElementById('v8ops-ready');if(ready){ready.textContent='UNAVAILABLE';ready.className='v8-bad'}const detail=document.getElementById('v8ops-detail');if(detail)detail.textContent=`V8 dashboard unavailable: ${e.message}`}};
    refresh(); window.setInterval(refresh,30000);
  };

  removeCompactV4Equity(); moveV8RankSignal(); arrangeLiveStockViewer(); clarifyDashboardDataClocks(); addV8OperationsDashboard();
  const layoutObserver=new MutationObserver(()=>{removeCompactV4Equity();moveV8RankSignal();arrangeLiveStockViewer();clarifyDashboardDataClocks();addV8OperationsDashboard()});layoutObserver.observe(document.documentElement,{childList:true,subtree:true});window.setTimeout(()=>layoutObserver.disconnect(),12000);
  const sections=Array.from(document.querySelectorAll('section.card'));const rankingBoard=sections.find(section=>{const label=section.querySelector('.label')?.textContent?.trim()||'';const heading=section.querySelector('h2,h3')?.textContent?.trim()||'';return /100[- ]STOCK.*(?:V8|V5).*RANKING BOARD/i.test(`${label} ${heading}`)||/(?:V8|V5).*100[- ]STOCK.*RANKING BOARD/i.test(`${label} ${heading}`)});if(rankingBoard)rankingBoard.remove();
  const remainingSections=Array.from(document.querySelectorAll('section.card'));const recentMarketData=remainingSections.find(section=>section.querySelector('.label')?.textContent?.trim()==='RECENT MARKET DATA');const v5Leaders=remainingSections.find(section=>section.querySelector('.label')?.textContent?.trim()==='V5 LEADERS');if(recentMarketData&&v5Leaders)v5Leaders.parentNode.insertBefore(recentMarketData,v5Leaders);
})();
