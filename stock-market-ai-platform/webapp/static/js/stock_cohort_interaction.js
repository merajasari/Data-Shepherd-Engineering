(() => {
  if(window.DataShepherdCohortInteractionLoaded)return;
  window.DataShepherdCohortInteractionLoaded=true;
  const configs={
    v10:{parent:'v10-cycle3-accelerated-monitor',anchor:'.a10-live',title:'V10 accelerated holdout interaction',note:'Accelerated prospective cohorts only; independent January confirmation is excluded.'},
    v14:{parent:'v14-ml-ai-dashboard',anchor:'.v14-split',title:'V14 paper-forward cohort interaction',note:'V14 decision, next-open entry, and recorded exit events from its own forward journal.'}
  };
  const colors={DECISION:'#efc56b',ENTRY:'#36d8ff',EXIT:'#39e3a1'};
  const descriptions={DECISION:'Basket selected',ENTRY:'Paper purchase / next-open entry',EXIT:'Paper sale / completed holding period'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stamp=value=>value?Date.parse(value):NaN;
  const date=value=>Number.isFinite(stamp(value))?new Date(value).toLocaleString(undefined,{timeZone:'UTC',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}):'Not recorded';
  const percent=value=>value!=null&&Number.isFinite(Number(value))?`${Number(value)>=0?'+':''}${(Number(value)*100).toFixed(2)}%`:'Not recorded';
  const states={};
  const style=document.createElement('style');
  style.textContent=`.sci-card{margin:20px 0;padding:22px;border:1px solid rgba(120,155,205,.25);border-radius:18px;background:rgba(8,20,36,.7)}.sci-card h3{margin:6px 0}.sci-sub,.sci-note{color:#91a6c2;font-size:.78rem;line-height:1.5}.sci-toolbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:14px 0}.sci-toolbar button{padding:8px 11px;border:1px solid #244261;border-radius:10px;background:#0d1c31;color:#f2f6ff;font:800 .72rem system-ui;cursor:pointer}.sci-toolbar button[aria-pressed=false]{opacity:.45;border-style:dashed}.sci-toolbar button:focus-visible{outline:2px solid #36d8ff;outline-offset:2px}.sci-counts{display:flex;flex-wrap:wrap;gap:16px;margin-top:14px;color:#91a6c2;font-size:.78rem}.sci-counts b{color:#f2f6ff}.sci-stage{height:560px;position:relative;border:1px solid rgba(120,155,205,.18);border-radius:14px;background:rgba(7,16,31,.5)}.sci-stage svg{width:100%;height:100%;display:block;touch-action:pan-y}.sci-stage circle{cursor:pointer}.sci-stage circle:focus{outline:none;stroke:#fff;stroke-width:3}.sci-empty{position:absolute;inset:0;display:grid;place-items:center;padding:30px;text-align:center;color:#91a6c2;pointer-events:none}.sci-empty[hidden]{display:none}.sci-tip{position:fixed;z-index:12500;width:360px;max-width:calc(100vw - 24px);max-height:calc(100vh - 24px);overflow:auto;box-sizing:border-box;padding:15px;border:1px solid #456588;border-radius:12px;background:#081526;color:#f2f6ff;box-shadow:0 15px 40px #0007;font:12px/1.5 system-ui;pointer-events:none;visibility:hidden}.sci-tip.show{visibility:visible}.sci-tip strong,.sci-tip small{display:block}.sci-tip small{color:#91a6c2;margin-top:7px}.sci-tip dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 14px;margin:12px 0}.sci-tip dt{color:#91a6c2}.sci-tip dd{margin:0;text-align:right;overflow-wrap:anywhere}.sci-tip p{overflow-wrap:anywhere}@media(max-width:650px){.sci-card{padding:14px}.sci-stage{height:480px}}`;
  document.head.appendChild(style);

  function normalize(rows){
    return (Array.isArray(rows)?rows:[]).map((row,index)=>({...row,index,time:stamp(row.timestamp_utc)}))
      .filter(row=>colors[row.event_type]&&Number.isFinite(row.time))
      .sort((a,b)=>a.time-b.time);
  }
  const cohortKey=row=>`${row.decision_timestamp_utc||row.timestamp_utc}|${row.cohort_offset??'unknown'}`;
  function mount(model){
    if(states[model])return states[model];
    const config=configs[model],parent=document.getElementById(config.parent);
    if(!parent)return null;
    const card=document.createElement('section');card.className='sci-card';card.id=`${model}-cohort-interaction`;
    card.innerHTML=`<div class="label">RECORDED PAPER LIFECYCLE · COHORT INTERACTION</div><h3>${config.title}</h3><div class="sci-sub">${config.note} Dots are actual journal events, not equity snapshots.</div><div class="sci-counts" data-counts></div><div class="sci-toolbar" role="group" aria-label="${model.toUpperCase()} cohort chart controls">${Object.keys(colors).map(kind=>`<button type="button" data-kind="${kind}" aria-pressed="true" style="color:${colors[kind]}">${kind}</button>`).join('')}<button type="button" data-action="in" aria-label="Zoom in">Zoom +</button><button type="button" data-action="out" aria-label="Zoom out">Zoom −</button><button type="button" data-action="left" aria-label="Pan to earlier events">← Earlier</button><button type="button" data-action="right" aria-label="Pan to later events">Later →</button><button type="button" data-action="reset">Full range</button></div><p class="sci-sub">Hover or focus a dot for its event details. Click/tap to pin; Esc to dismiss. Cohort connectors link recorded events only.</p><div class="sci-stage"><svg viewBox="0 0 1100 560" preserveAspectRatio="none" role="img" aria-label="${model.toUpperCase()} recorded decision, entry and exit cohorts"></svg><div class="sci-empty" hidden></div></div><p class="sci-note" data-note></p>`;
    const anchor=parent.querySelector(config.anchor);
    if(anchor)anchor.insertAdjacentElement('afterend',card);else parent.appendChild(card);
    const tip=document.createElement('div');tip.className='sci-tip';tip.setAttribute('role','tooltip');document.body.appendChild(tip);
    const state={model,card,tip,svg:card.querySelector('svg'),events:[],visible:[],enabled:new Set(Object.keys(colors)),zoom:1,pan:1,pinned:false,payload:null};states[model]=state;
    card.addEventListener('click',event=>{
      const button=event.target.closest('button');if(!button)return;
      if(button.dataset.kind){const kind=button.dataset.kind;if(state.enabled.has(kind)&&state.enabled.size>1)state.enabled.delete(kind);else state.enabled.add(kind);}
      else {const action=button.dataset.action;if(action==='in')state.zoom=Math.min(32,state.zoom*1.6);if(action==='out')state.zoom=Math.max(1,state.zoom/1.6);if(action==='left')state.pan=Math.max(0,state.pan-.2);if(action==='right')state.pan=Math.min(1,state.pan+.2);if(action==='reset'){state.zoom=1;state.pan=1;}}
      hide(state);draw(state);
    });
    state.svg.addEventListener('pointermove',event=>{if(state.pinned)return;const hit=nearest(state,event);if(hit)show(state,hit,event);else hide(state);});
    state.svg.addEventListener('pointerleave',()=>{if(!state.pinned)hide(state);});
    state.svg.addEventListener('click',event=>{const hit=nearest(state,event);if(state.pinned){hide(state);}else if(hit){show(state,hit,event);state.pinned=true;}});
    state.svg.addEventListener('focusin',event=>{const node=event.target.closest('[data-sci-index]');if(!node)return;const hit=state.visible[Number(node.dataset.sciIndex)],rect=node.getBoundingClientRect();show(state,hit,{clientX:rect.left+rect.width/2,clientY:rect.top});});
    state.svg.addEventListener('focusout',()=>{if(!state.pinned)hide(state);});
    state.svg.addEventListener('keydown',event=>{if(!['Enter',' '].includes(event.key))return;const node=event.target.closest('[data-sci-index]');if(node){event.preventDefault();state.pinned=!state.pinned;if(!state.pinned)hide(state);}});
    return state;
  }
  function hide(state){state.pinned=false;state.tip.classList.remove('show');state.svg.querySelectorAll?.('[data-sci-cohort]')?.forEach(node=>node.setAttribute('opacity','1'));}
  function nearest(state,event){
    const direct=event.target?.closest?.('[data-sci-index]');if(direct)return state.visible[Number(direct.dataset.sciIndex)];
    const matrix=state.svg.getScreenCTM();if(!matrix)return null;
    let best=null;
    for(const row of state.visible){const x=matrix.a*row.x+matrix.c*row.y+matrix.e,y=matrix.b*row.x+matrix.d*row.y+matrix.f,distance=Math.hypot(event.clientX-x,event.clientY-y);if(distance<=18&&(!best||distance<best.distance))best={row,distance};}
    return best?.row||null;
  }
  function show(state,row,event){
    if(!row)return;
    const key=cohortKey(row);
    state.svg.querySelectorAll?.('[data-sci-cohort]')?.forEach(node=>node.setAttribute('opacity',node.dataset.sciCohort===key?'1':'.18'));
    const model=state.model.toUpperCase(),prices=row.entry_prices&&typeof row.entry_prices==='object'?Object.entries(row.entry_prices).map(([symbol,value])=>`${symbol}: $${Number(value).toFixed(2)}`).join(' · '):null;
    state.tip.innerHTML=`<strong style="color:${colors[row.event_type]}">${model} · ${row.event_type}</strong><small>${descriptions[row.event_type]}</small><dl><dt>Recorded event time</dt><dd>${esc(date(row.timestamp_utc))}</dd><dt>Decision session (UTC)</dt><dd>${esc(String(row.decision_timestamp_utc||'Not recorded').slice(0,10))}</dd><dt>Cohort sleeve</dt><dd>${esc(row.cohort_offset??'Not recorded')}</dd><dt>Entry time</dt><dd>${esc(date(row.entry_timestamp_utc))}</dd><dt>Exit time</dt><dd>${esc(date(row.exit_timestamp_utc))}</dd><dt>Stocks</dt><dd>${Array.isArray(row.symbols)?row.symbols.length:0}</dd>${row.event_type==='EXIT'?`<dt>${model} net return</dt><dd>${percent(row.net_portfolio_return)}</dd><dt>SPY return</dt><dd>${percent(row.spy_return)}</dd><dt>Relative return</dt><dd>${percent(row.net_relative_return)}</dd>`:''}</dl><p><b>Recorded basket:</b> ${esc((row.symbols||[]).join(', ')||'No basket recorded')}</p>${prices?`<p><b>Paper entry prices:</b> ${esc(prices)}</p>`:''}<small>Model: ${esc(row.model_sha256||row.frozen_sha256||'Not recorded')}</small><small>Paper journal event only. No brokerage order is placed by this chart. Click/tap to pin · Esc to dismiss.</small>`;
    state.tip.classList.add('show');const width=state.tip.offsetWidth,height=state.tip.offsetHeight;
    state.tip.style.left=Math.max(12,Math.min(window.innerWidth-width-12,event.clientX+16+width<=window.innerWidth-12?event.clientX+16:event.clientX-width-16))+'px';
    state.tip.style.top=Math.max(12,Math.min(window.innerHeight-height-12,event.clientY+16+height<=window.innerHeight-12?event.clientY+16:event.clientY-height-16))+'px';
  }
  function draw(state){
    const events=state.events,W=1100,H=560,p={l:210,r:30,t:40,b:60},day=86400000;
    const counts=kind=>events.filter(row=>row.event_type===kind).length;
    state.card.querySelector('[data-counts]').innerHTML=Object.keys(colors).map(kind=>`<span>${kind}: <b>${counts(kind)}</b></span>`).join('')+`<span>Cohorts: <b>${new Set(events.map(cohortKey)).size}</b></span>`;
    state.card.querySelectorAll('[data-kind]').forEach(button=>button.setAttribute('aria-pressed',String(state.enabled.has(button.dataset.kind))));
    const boundary=stamp(state.payload?.first_decision_session_utc||state.payload?.paper_forward_start_utc);
    const fullStart=Math.min(...events.map(row=>row.time),Number.isFinite(boundary)?boundary:Date.now())-day;
    const fullEnd=Math.max(Date.now(),...events.map(row=>row.time))+day;
    const fullSpan=Math.max(day,fullEnd-fullStart),span=fullSpan/state.zoom,start=fullStart+(fullSpan-span)*state.pan,end=start+span;
    const x=time=>p.l+(time-start)/span*(W-p.l-p.r),lanes={DECISION:110,ENTRY:270,EXIT:430};
    const y=row=>lanes[row.event_type]+(Number.isFinite(Number(row.cohort_offset))?((Number(row.cohort_offset)%5)-2)*9:0);
    const grouped=new Map();for(const row of events){if(!state.enabled.has(row.event_type))continue;const key=cohortKey(row);if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(row);}
    const clip=`${state.model}-cohort-plot-clip`;
    const paths=[...grouped.values()].map(rows=>rows.length>1?`<polyline data-sci-cohort="${esc(cohortKey(rows[0]))}" points="${rows.map(row=>`${x(row.time)},${y(row)}`).join(' ')}" fill="none" stroke="rgba(231,237,247,.3)" stroke-width="2" stroke-dasharray="4 5"/>`:'').join('');
    state.visible=events.filter(row=>state.enabled.has(row.event_type)&&row.time>=start&&row.time<=end).map(row=>({...row,x:x(row.time),y:y(row)}));
    const dots=state.visible.map((row,index)=>`<circle data-sci-cohort="${esc(cohortKey(row))}" data-sci-index="${index}" cx="${row.x}" cy="${row.y}" r="7" fill="${colors[row.event_type]}" stroke="#07101f" stroke-width="2" tabindex="0" role="button" aria-label="${esc(`${state.model.toUpperCase()} ${row.event_type}, ${date(row.timestamp_utc)}, cohort ${row.cohort_offset??'unknown'}`)}"/>`).join('');
    const axes=Object.keys(lanes).map(kind=>`<line x1="${p.l}" y1="${lanes[kind]}" x2="${W-p.r}" y2="${lanes[kind]}" stroke="#91a6c2" opacity=".2" stroke-dasharray="4 5"/><text x="${p.l-12}" y="${lanes[kind]+4}" text-anchor="end" fill="${colors[kind]}" font-size="12" font-weight="800">${kind} · ${kind==='DECISION'?'Select basket':kind==='ENTRY'?'Paper purchase':'Paper sale'}</text>`).join('');
    const ticks=Array.from({length:5},(_,index)=>{const time=start+span*index/4;return `<text x="${x(time)}" y="${H-24}" text-anchor="${index===0?'start':index===4?'end':'middle'}" fill="#91a6c2" font-size="11">${new Date(time).toLocaleDateString(undefined,{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'})}</text>`;}).join('');
    state.svg.innerHTML=`<defs><clipPath id="${clip}"><rect x="${p.l}" y="${p.t}" width="${W-p.l-p.r}" height="${H-p.t-p.b}"/></clipPath></defs>${axes}${ticks}<g clip-path="url(#${clip})">${paths}${dots}</g>`;
    const empty=state.card.querySelector('.sci-empty');empty.hidden=state.visible.length>0;
    empty.textContent=events.length?'No selected lifecycle events in this view. Reset the range or change event filters.':'No recorded lifecycle events yet. No decisions or trades are reconstructed.';
    state.card.querySelector('[data-note]').textContent=`${state.zoom.toFixed(1)}× zoom · ${state.visible.length} visible events · horizontal axis uses UTC event dates; popup times use UTC · read-only journal projection.`;
  }
  function update(model,payload){
    if(!configs[model]||!payload)return;
    const state=mount(model);if(!state)return;state.payload=payload;
    state.events=normalize(payload.cohort_event_history);draw(state);
  }
  document.addEventListener('data-shepherd-cohort-update',event=>update(event.detail?.model,event.detail?.payload));
  for(const [model,payload] of Object.entries(window.DataShepherdCohortPayloads||{}))update(model,payload);
  const dismiss=()=>Object.values(states).forEach(hide);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')dismiss();});
  document.addEventListener('click',event=>Object.values(states).forEach(state=>{if(!state.svg.contains(event.target))hide(state);}));
  window.addEventListener('scroll',dismiss,{passive:true});window.addEventListener('resize',dismiss);
})();
