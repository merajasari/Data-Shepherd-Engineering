(() => {
  if (new URLSearchParams(window.location.search).get('view') === 'live') return;
  const shell = document.querySelector('.shell');
  if (!shell || document.getElementById('model-research-tabs')) return;

  const MODELS = [
    {id:'overview', label:'Overview', eyebrow:'SHARED RESEARCH CONTEXT', title:'Cross-model overview', note:'Common market data, platform health, and the normalized model-comparison chart remain together here.'},
    {id:'v4', label:'V4 Paper', eyebrow:'V4 · PAPER STRATEGY', title:'V4 paper-trading monitor', note:'V4 portfolio equity, holdings, attribution, and journal-forward measurements. Simulation only.'},
    {id:'v8', label:'V8 Frozen', eyebrow:'V8 · FROZEN FORWARD MODEL', title:'V8 rankings and holdout evidence', note:'Frozen ranking research and genuine append-only forward evidence are labeled and kept separate within this tab.'},
    {id:'v10', label:'V10 Cycle 3', eyebrow:'V10 · FROZEN FUTURE HOLDOUT', title:'V10 research disposition and Cycle 3', note:'Original V10 research disposition plus the separately frozen Cycle 3 forward-holdout monitor.'},
    {id:'v11', label:'V11 Intraday', eyebrow:'V11 · FRESH PAPER CONFIRMATION', title:'V11 intraday confirmation', note:'Five-minute fresh paper-confirmation operations and evidence, isolated from V8 and V10.'},
    {id:'v13', label:'V13 Dev', eyebrow:'V13 · RETROSPECTIVE DEVELOPMENT', title:'V13 development research', note:'V13 is development-only—not frozen and not fresh forward evidence. Its eligible historical curve remains in the shared comparison.'}
  ];

  const style = document.createElement('style');
  style.id = 'model-research-tabs-style';
  style.textContent = `
    #model-research-tabs{position:sticky;top:0;z-index:80;margin:0 0 18px;padding:9px;border:1px solid rgba(120,155,205,.22);border-radius:17px;background:rgba(7,16,31,.94);box-shadow:0 14px 34px rgba(0,0,0,.24);backdrop-filter:blur(14px)}
    #model-research-tabs .mrt-scroll{display:flex;gap:7px;overflow-x:auto;scrollbar-width:thin;padding-bottom:1px}
    #model-research-tabs [role=tab]{flex:0 0 auto;padding:10px 14px;border:1px solid transparent;border-radius:11px;background:transparent;color:var(--muted);font-size:.76rem;font-weight:900;letter-spacing:.035em;cursor:pointer;white-space:nowrap}
    #model-research-tabs [role=tab]:hover{color:var(--text);border-color:rgba(54,216,255,.24);background:rgba(54,216,255,.06)}
    #model-research-tabs [role=tab][aria-selected=true]{color:#06151d;border-color:transparent;background:linear-gradient(90deg,var(--cyan),var(--green));box-shadow:0 7px 18px rgba(54,216,255,.16)}
    #model-research-panels{min-width:0}.model-research-pane[hidden]{display:none!important}.model-research-pane{min-width:0}.model-research-pane-content{display:flex;flex-direction:column;min-width:0}
    .model-research-pane-head{margin:0 0 18px;padding:18px 20px;border:1px solid rgba(120,155,205,.18);border-radius:18px;background:linear-gradient(145deg,rgba(13,28,49,.8),rgba(8,20,36,.72))}
    .model-research-pane-head h2{margin:5px 0 5px}.model-research-pane-head p{margin:0;line-height:1.5}.model-research-pane-content>:first-child{margin-top:0!important}.model-research-pane-content>.smc-full-width-card{margin-top:0}
    .mrt-v13-card{padding:24px;border:1px solid rgba(255,138,61,.28);border-radius:22px;background:linear-gradient(145deg,rgba(47,27,20,.55),rgba(8,20,36,.95))}.mrt-v13-card .warning{margin-top:16px}
    .mrt-single-card-grid{grid-template-columns:1fr!important}.model-research-pane-content>.v4-dashboard{margin-top:0}
    @media(max-width:700px){#model-research-tabs{margin-left:-1%;margin-right:-1%;border-radius:14px}#model-research-tabs [role=tab]{padding:9px 11px;font-size:.7rem}.model-research-pane-head{padding:16px}}
  `;
  document.head.appendChild(style);

  const nav = document.createElement('nav');
  nav.id = 'model-research-tabs';
  nav.setAttribute('aria-label', 'Model research sections');
  nav.innerHTML = `<div class="mrt-scroll" role="tablist">${MODELS.map((model, index) => `<button type="button" role="tab" id="model-research-tab-${model.id}" aria-controls="model-research-pane-${model.id}" aria-selected="${index === 0}" tabindex="${index === 0 ? '0' : '-1'}" data-research-tab="${model.id}">${model.label}</button>`).join('')}</div>`;

  const panels = document.createElement('main');
  panels.id = 'model-research-panels';
  MODELS.forEach((model, index) => {
    const pane = document.createElement('section');
    pane.id = `model-research-pane-${model.id}`;
    pane.className = `model-research-pane model-research-pane-${model.id}`;
    pane.setAttribute('role', 'tabpanel');
    pane.setAttribute('aria-labelledby', `model-research-tab-${model.id}`);
    pane.hidden = index !== 0;
    pane.innerHTML = `<div class="model-research-pane-head"><div class="label">${model.eyebrow}</div><h2>${model.title}</h2><p class="muted">${model.note}</p></div><div class="model-research-pane-content" data-research-content="${model.id}"></div>`;
    panels.appendChild(pane);
  });

  const primaryTabs = shell.querySelector(':scope > .ds-dashboard-tabs');
  const header = shell.querySelector(':scope > header');
  const anchor = primaryTabs || header;
  anchor?.insertAdjacentElement('afterend', nav);
  nav.insertAdjacentElement('afterend', panels);

  const content = id => panels.querySelector(`[data-research-content="${id}"]`);
  const move = (node, id) => {
    const target = content(id);
    if (node && target && node.parentElement !== target) target.appendChild(node);
  };
  const moveId = (id, model) => move(document.getElementById(id), model);

  const V8_IDS = [
    'v8-forward-ops','v8-launch-day-operations','v8-launch-readiness-card',
    'smc-v8-holdout-interaction','v8-holdout-monitor','v8-pnl-attribution',
    'v8-leaders','v8-full-ranking-board','v8-current-top10','v8-structure-help-row'
  ];
  const V10_IDS = ['v10-confirmation-card','v10-cycle3-holdout-monitor'];

  function splitMarketAndSignal() {
    const signal = [...document.querySelectorAll('.card')].find(card =>
      /^V8 (?:DISTANCE-ONLY|COMPLETED-EOD) RANK SIGNAL$/.test(
        card.querySelector(':scope > .label')?.textContent.trim() || ''
      )
    );
    if (!signal) return;
    const row = signal.parentElement;
    move(signal, 'v8');
    if (row?.matches('section.grid')) {
      row.classList.add('mrt-single-card-grid');
      move(row, 'overview');
    }
  }

  function moveV8ContractGrid() {
    const strategy = [...document.querySelectorAll('.card')].find(card =>
      card.querySelector(':scope > .label')?.textContent.trim() === 'FROZEN V8 STRATEGY CONTRACT'
    );
    if (!strategy) return;
    const grid = strategy.parentElement;
    const labels = grid ? [...grid.querySelectorAll(':scope > .card > .label')].map(label => label.textContent.trim()) : [];
    if (
      grid?.matches('section.grid')
      && labels.includes('FROZEN V8 STRATEGY CONTRACT')
      && labels.some(label => /^(?:V8 )?PORTFOLIO CONTRACT$/.test(label))
    ) move(grid, 'v8');
  }

  function routeStaticSections() {
    moveId('stock-stream-health-card', 'overview');
    moveId('stock-operations-health', 'overview');
    move(document.querySelector('.smc-full-width-card'), 'overview');
    move(document.querySelector('.v4-dashboard'), 'v4');
    V8_IDS.forEach(id => moveId(id, 'v8'));
    V10_IDS.forEach(id => moveId(id, 'v10'));
    moveId('v11-phase2-status', 'v11');
    splitMarketAndSignal();
    moveV8ContractGrid();

    [...shell.querySelectorAll(':scope > section')].forEach(section => {
      if (section.classList.contains('model-research-pane')) return;
      const label = section.querySelector(':scope > .label')?.textContent.trim() || '';
      if (/^PRIMARY STOCK VIEW$|^RECENT MARKET DATA$/.test(label) || section.matches('.grid.metrics')) move(section, 'overview');
      else if (/V8|FROZEN V8|PLATFORM PIPELINE/.test(label)) move(section, 'v8');
      else move(section, 'overview');
    });
  }

  function ensureV13Context() {
    const target = content('v13');
    if (!target || target.querySelector('.mrt-v13-card')) return;
    const card = document.createElement('section');
    card.className = 'mrt-v13-card';
    card.innerHTML = `<div class="label">CURRENT CLASSIFICATION</div><h3>Retrospective development research</h3><p class="muted">V13 appears in the Overview comparison only on its scientifically eligible historical window. It does not have a frozen production candidate, fresh confirmation journal, or brokerage authority.</p><div class="warning"><strong>Evidence boundary:</strong> do not interpret the V13 historical curve as forward or holdout performance.</div>`;
    target.appendChild(card);
  }

  function reconcile() {
    routeStaticSections();
    ensureV13Context();
    const lower = document.querySelector('.v4-dashboard .v4-lower');
    if (lower && !lower.children.length) lower.hidden = true;
  }

  const validTab = id => MODELS.some(model => model.id === id);
  function activate(id, options = {}) {
    if (!validTab(id)) id = 'overview';
    nav.querySelectorAll('[role=tab]').forEach(button => {
      const selected = button.dataset.researchTab === id;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    panels.querySelectorAll('[role=tabpanel]').forEach(pane => { pane.hidden = pane.id !== `model-research-pane-${id}`; });
    try { sessionStorage.setItem('data-shepherd-research-tab', id); } catch (_) {}
    if (options.hash !== false && history.replaceState) history.replaceState(null, '', `${location.pathname}${location.search}#research-${id}`);
    if (options.focus) nav.querySelector(`[data-research-tab="${id}"]`)?.focus();
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  }

  nav.addEventListener('click', event => {
    const button = event.target.closest('[data-research-tab]');
    if (button) activate(button.dataset.researchTab);
  });
  nav.addEventListener('keydown', event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    const buttons = [...nav.querySelectorAll('[role=tab]')];
    const current = buttons.indexOf(document.activeElement);
    let next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    event.preventDefault();
    activate(buttons[next].dataset.researchTab, {focus:true});
  });

  reconcile();
  let requested = location.hash.match(/^#research-(overview|v4|v8|v10|v11|v13)$/)?.[1];
  if (!requested) { try { requested = sessionStorage.getItem('data-shepherd-research-tab'); } catch (_) {} }
  activate(validTab(requested) ? requested : 'overview', {hash:false});

  let queued = false;
  const observer = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; reconcile(); });
  });
  observer.observe(shell, {childList:true, subtree:true});
  window.setTimeout(() => { reconcile(); observer.disconnect(); }, 20000);
})();
