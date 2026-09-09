(() => {
  if (new URLSearchParams(window.location.search).get('view') === 'live') return;
  const shell = document.querySelector('.shell');
  if (!shell || document.getElementById('model-research-tabs')) return;

  const MODELS = [
    {id:'overview', label:'Overview', eyebrow:'SHARED RESEARCH CONTEXT', title:'Cross-model overview', note:'Common market data, platform health, and the normalized model-comparison chart remain together here.'},
    {id:'v8', label:'V8 Frozen', eyebrow:'V8 · FROZEN FORWARD MODEL', title:'V8 rankings and holdout evidence', note:'Frozen ranking research and genuine append-only forward evidence are labeled and kept separate within this tab.'},
    {id:'v10', label:'V10 Cycle 3', eyebrow:'V10 · FROZEN CYCLE 3 · ACCELERATED PAPER-FORWARD', title:'V10 Cycle 3 evidence and review runway', note:'Prospective September–December evidence, the independent January confirmation, and rejected legacy V10 research remain visibly separate.'},
    {id:'v11', label:'V11 Intraday', eyebrow:'V11 · PREREGISTERED RESEARCH · NOT FROZEN', title:'V11 intraday confirmation', note:'Its configuration and evidence contract are SHA-locked, but V11 remains a research candidate undergoing five-minute fresh paper confirmation. It has no production or brokerage authority.'},
    {id:'v13', label:'V13 Dev', eyebrow:'V13 · PREREGISTERED DEVELOPMENT · NOT FROZEN', title:'V13 regime-overlay research', note:'V13 is a preregistered successor hypothesis with activation governed by an explicit short-lived paper-only lease. Its retrospective curve remains on Overview and never counts as fresh evidence.'}
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
    .mrt-v13-card{padding:24px;border:1px solid rgba(255,138,61,.28);border-radius:22px;background:linear-gradient(145deg,rgba(47,27,20,.55),rgba(8,20,36,.95))}.mrt-v13-card .warning{margin-top:16px}.mrt-v13-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:18px}.mrt-v13-metric{padding:14px;border:1px solid rgba(120,155,205,.18);border-radius:14px;background:rgba(4,13,25,.38)}.mrt-v13-metric span{display:block;color:var(--muted);font-size:.67rem;font-weight:800;letter-spacing:.06em}.mrt-v13-metric strong{display:block;margin-top:6px;font-size:.9rem;overflow-wrap:anywhere}.mrt-v13-progress{position:relative;overflow:hidden;height:8px;margin-top:9px;border-radius:99px;background:rgba(120,155,205,.14)}.mrt-v13-progress:after{content:'';display:block;width:var(--v13-progress,0%);height:100%;border-radius:inherit;background:linear-gradient(90deg,var(--cyan),var(--green))}.mrt-v13-gates{margin:12px 0 0;padding-left:20px;line-height:1.7}.mrt-v13-split{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}.mrt-v13-card h3{margin:5px 0 8px}.mrt-v13-card h4{margin:0 0 8px}.mrt-v13-card p{line-height:1.55}
    .mrt-single-card-grid{grid-template-columns:1fr!important}.model-research-pane-content>.v4-dashboard{margin-top:0}
    @media(max-width:700px){#model-research-tabs{margin-left:-1%;margin-right:-1%;border-radius:14px}#model-research-tabs [role=tab]{padding:9px 11px;font-size:.7rem}.model-research-pane-head{padding:16px}.mrt-v13-grid,.mrt-v13-split{grid-template-columns:1fr}}
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
  const V10_IDS = [
    'v10-cycle3-accelerated-monitor',
    'v10-cycle3-holdout-monitor',
    'v10-confirmation-card',
  ];

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
    // Legacy class name; dashboard enhancement scripts convert this shell to the V8 forward monitor.
    move(document.querySelector('.v4-dashboard'), 'v8');
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
    card.id = 'v13-regime-overlay-status';
    card.innerHTML = `<div class="label">V13 REGIME-OVERLAY · READ-ONLY STATUS</div><h3 data-v13-display>Loading current paper-only state…</h3><p class="muted">V13 tests a locked negative/high-volatility entry-confirmation overlay against the unchanged frozen V10 control. It is not frozen; fresh evidence is paper-only, with no live trading or brokerage authority.</p><div class="mrt-v13-grid"><div class="mrt-v13-metric"><span>CONTROL STATUS</span><strong data-v13-control>Loading…</strong></div><div class="mrt-v13-metric"><span>OPERATIONAL HEALTH</span><strong data-v13-health>Loading…</strong></div><div class="mrt-v13-metric"><span>FRESH EVIDENCE</span><strong data-v13-evidence>Loading…</strong></div><div class="mrt-v13-metric"><span>ACTIVATION</span><strong data-v13-activation>Loading…</strong></div><div class="mrt-v13-metric"><span>JOURNAL EVENTS</span><strong data-v13-events>—</strong></div><div class="mrt-v13-metric"><span>BROKERAGE ORDERS</span><strong data-v13-brokerage>OFF</strong></div></div><div class="mrt-v13-split"><div class="mrt-v13-metric"><span>COMPLETED FRESH PAIRED SESSIONS</span><strong data-v13-sessions>0 / 60</strong><div class="mrt-v13-progress" data-v13-sessions-bar></div></div><div class="mrt-v13-metric"><span>COMPLETED REGIME-ELIGIBLE SESSIONS</span><strong data-v13-regime>0 / 15</strong><div class="mrt-v13-progress" data-v13-regime-bar></div></div></div><div class="mrt-v13-split"><div class="mrt-v13-metric"><h4>Collection control</h4><p class="muted">Scheduler: <strong data-v13-scheduler>Loading…</strong><br>Collection expected: <strong data-v13-collection>NO</strong><br>Market-data requests: <strong data-v13-requests>0</strong><br>Session decisions: <strong data-v13-decisions>0</strong></p><p class="muted">Last checked: <span data-v13-checked>—</span></p></div><div class="mrt-v13-metric"><h4>Preregistered evaluation gates</h4><ul class="mrt-v13-gates"><li data-v13-return-gate>Return delta gate</li><li>Terminal wealth must exceed the same-session V10 control</li><li>Maximum drawdown must not be worse than control</li><li>Negative/high-volatility net return must exceed control</li><li data-v13-win-gate>Paired-session win-rate gate</li><li data-v13-turnover-gate>Turnover gate</li><li data-v13-feasibility-gate>Small-account feasibility gate</li></ul></div></div><div class="mrt-v13-metric" style="margin-top:14px"><div class="label">ACTIVATION GOVERNANCE · FAIL-CLOSED</div><div class="mrt-v13-grid"><div><span>MANUAL APPROVAL STATUS</span><strong data-v13-approval>Loading…</strong></div><div><span>APPROVAL ARTIFACT</span><strong data-v13-approval-artifact>—</strong></div><div><span>ACTIVATION LEASE</span><strong data-v13-lease>—</strong></div><div><span>TRANSITION PLAN</span><strong data-v13-transition>Loading…</strong></div><div><span>TRANSITION GATES</span><strong data-v13-transition-gates>— / —</strong></div><div><span>APPLY IMPLEMENTATION</span><strong data-v13-apply>ABSENT</strong></div></div><p class="muted">Approved destination state: <strong data-v13-planned-state>ENABLED FRESH EVIDENCE PAPER ONLY</strong>. This read-only panel cannot create approval, write a lease, apply activation, or install a scheduler.</p></div><div class="mrt-v13-split"><div class="mrt-v13-metric"><h4>Signed context inbox</h4><p class="muted">Status: <strong data-v13-context-status>Loading…</strong><br>Candidate: <strong data-v13-candidate>—</strong><br>Control: <strong data-v13-control-id>—</strong><br>Target session: <strong data-v13-context-target>—</strong><br>Source session: <strong data-v13-context-source>—</strong><br>Fresh-evidence boundary: <strong data-v13-boundary>—</strong><br>Next decision window: <strong data-v13-next-window>—</strong></p></div><div class="mrt-v13-metric"><h4>Effective paper lease</h4><p class="muted">Status: <strong data-v13-lease-valid>Loading…</strong><br>Operator: <strong data-v13-lease-operator>—</strong><br>Renewal sequence: <strong data-v13-lease-sequence>—</strong><br>Expires: <strong data-v13-lease-expires>—</strong></p></div></div><div class="mrt-v13-metric" style="margin-top:14px"><div class="label">LATEST AUTOMATIC COLLECTION · IMMUTABLE SESSION RESULT</div><div class="mrt-v13-grid"><div><span>STATUS</span><strong data-v13-automation-status>Loading…</strong></div><div><span>TARGET SESSION</span><strong data-v13-automation-target>—</strong></div><div><span>SOURCE SESSION</span><strong data-v13-automation-source>—</strong></div><div><span>ATTEMPTED</span><strong data-v13-automation-attempted>—</strong></div><div><span>ATTEMPT CONSUMED</span><strong data-v13-automation-consumed>NO</strong></div><div><span>EVIDENCE APPENDED</span><strong data-v13-automation-evidence>NO</strong></div></div><p class="muted">Market-data requests: <strong data-v13-automation-requests>— / 104</strong><br>Quote recovery: <strong data-v13-automation-recovery>—</strong><br>Retry permitted: <strong data-v13-automation-retry>NO</strong><br>Backfill permitted: <strong data-v13-automation-backfill>NO</strong><br>Failure reason: <strong data-v13-automation-failure>NONE</strong></p><p class="muted">A consumed automatic attempt is terminal for that session. It cannot be retried or backfilled and counts as evidence only when a complete signed decision was appended.</p></div><div class="mrt-v13-metric" style="margin-top:14px"><span>SIGNED CONTEXT IDENTITIES</span><p class="muted">Ranking SHA-256: <span data-v13-context-ranking-sha>Not published</span><br>Control-context SHA-256: <span data-v13-context-control-sha>Not published</span></p></div><div class="warning"><strong>Evidence boundary:</strong> the V13 curve on Overview is retrospective development reconstruction. Only completed post-boundary paired observations written after a separately approved activation can enter the counters above.</div><div class="mrt-v13-metric" style="margin-top:14px"><span>OPERATIONAL DIAGNOSTICS</span><ul class="mrt-v13-gates" data-v13-failures><li>Loading read-only diagnostics…</li></ul><p class="muted">Contract SHA-256: <span data-v13-sha>checking…</span></p></div>`;
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
  let requested = location.hash.match(/^#research-(overview|v8|v10|v11|v13)$/)?.[1];
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
