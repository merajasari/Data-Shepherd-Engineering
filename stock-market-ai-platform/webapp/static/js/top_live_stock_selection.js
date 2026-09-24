(()=>{
  if(location.pathname!=='/dashboard'||new URLSearchParams(location.search).get('view')!=='live')return;

  const style=document.createElement('style');
  style.textContent=`
    #ds-top-live-performance-list .tlrank-row{cursor:pointer;user-select:none}
    #ds-top-live-performance-list .tlrank-row.tlrank-selected{border-color:rgba(54,216,255,.78)!important;background:rgba(54,216,255,.09);box-shadow:inset 0 0 0 1px rgba(54,216,255,.18)}
    #ds-top-live-performance-list .tlrank-row.tlrank-selected .tlrank-badge{background:linear-gradient(90deg,var(--cyan),var(--green));color:#06151d}
    #ds-top-live-performance-list .tlrank-row.tlrank-dimmed{opacity:.44}
    #ds-top-live-performance-list .tlrank-row:focus-visible{outline:2px solid var(--cyan);outline-offset:2px}
    .tlrank-selection-help{margin-top:12px;color:var(--muted);font-size:.72rem}
  `;
  document.head.appendChild(style);

  const selected=new Set();
  let syncing=false;

  function getList(){return document.getElementById('tlrank-list');}
  function getLegend(){return document.getElementById('tll');}

  function currentSymbols(){
    return [...(getList()?.querySelectorAll('[data-rank-symbol]')||[])].map(r=>r.dataset.rankSymbol).filter(Boolean);
  }

  function normalizeSelection(){
    const available=new Set(currentSymbols());
    for(const symbol of [...selected])if(!available.has(symbol))selected.delete(symbol);
  }

  function updateRowState(){
    const rows=[...(getList()?.querySelectorAll('[data-rank-symbol]')||[])];
    const hasSelection=selected.size>0;
    rows.forEach(row=>{
      const symbol=row.dataset.rankSymbol;
      const on=selected.has(symbol);
      row.classList.toggle('tlrank-selected',on);
      row.classList.toggle('tlrank-dimmed',hasSelection&&!on);
      row.setAttribute('role','button');
      row.setAttribute('tabindex','0');
      row.setAttribute('aria-pressed',on?'true':'false');
      row.setAttribute('title',hasSelection?(on?'Click to remove from chart':'Click to add to chart'):'Click to show this stock; click more stocks to compare');
    });
    const card=document.getElementById('ds-top-live-performance-list');
    if(card&&!card.querySelector('.tlrank-selection-help')){
      const help=document.createElement('div');
      help.className='tlrank-selection-help';
      help.textContent='Click a stock to isolate it. Click additional stocks to compare multiple selections. Click selected stocks again to remove them; when none are selected, the current DISPLAY group is shown.';
      card.appendChild(help);
    }
  }

  function syncChart(){
    if(syncing)return;
    syncing=true;
    try{
      normalizeSelection();
      const legend=getLegend();
      if(!legend)return;
      const buttons=[...legend.querySelectorAll('button[data-s]')];
      const hasSelection=selected.size>0;
      buttons.forEach(button=>{
        const symbol=button.dataset.s;
        const shouldShow=!hasSelection||selected.has(symbol);
        const isOff=button.classList.contains('off');
        if(shouldShow===isOff)button.click();
      });
      updateRowState();
    }finally{
      syncing=false;
    }
  }

  function toggleSymbol(symbol){
    if(!symbol)return;
    if(selected.has(symbol))selected.delete(symbol);
    else selected.add(symbol);
    syncChart();
  }

  function bind(){
    const list=getList(),legend=getLegend();
    if(!list||!legend)return false;

    if(!list.dataset.dsSelectionBound){
      list.dataset.dsSelectionBound='1';
      list.addEventListener('click',e=>{
        const row=e.target.closest('[data-rank-symbol]');
        if(!row||!list.contains(row))return;
        toggleSymbol(row.dataset.rankSymbol);
      });
      list.addEventListener('keydown',e=>{
        if(e.key!=='Enter'&&e.key!==' ')return;
        const row=e.target.closest('[data-rank-symbol]');
        if(!row||!list.contains(row))return;
        e.preventDefault();
        toggleSymbol(row.dataset.rankSymbol);
      });
    }

    const observer=new MutationObserver(()=>{
      if(syncing)return;
      queueMicrotask(syncChart);
    });
    observer.observe(list,{childList:true,subtree:true});
    observer.observe(legend,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});

    updateRowState();
    syncChart();
    return true;
  }

  let attempts=0;
  const timer=setInterval(()=>{
    attempts++;
    if(bind()||attempts>80)clearInterval(timer);
  },100);
})();
