(() => {
  if (window.location.pathname !== '/crypto') return;
  const shell = document.querySelector('.shell');
  if (!shell || document.getElementById('crypto-model-tabs')) return;

  const MODELS = [
    {id:'overview', label:'Overview', eyebrow:'CRYPTO RESEARCH OVERVIEW', title:'Platform health and evidence runway', note:'Shared operational health and forward-evaluation context remain visible without mixing distinct model evidence.'},
    {id:'shared-v2', label:'Shared Crypto V2', eyebrow:'SHARED CRYPTO V2', title:'Frozen shared-market candidate', note:'Frozen development evidence, prospective monitoring, and post-boundary evaluation remain together for the shared V2 candidate.'},
    {id:'xrp-v1', label:'XRP V1', eyebrow:'XRP V1', title:'Dedicated XRP shadow model', note:'The XRP-specific forward monitor remains isolated from the shared crypto candidates.'},
    {id:'crypto-v1', label:'Crypto V1', eyebrow:'CRYPTO V1', title:'Historical BTC-relative research', note:'The original BTC-relative Top-5 simulation and ranking board remain classified as historical research.'},
    {id:'shared-v3', label:'Shared Crypto V3', eyebrow:'SHARED CRYPTO V3', title:'Shared V3 development disposition', note:'Development-only evidence remains visible and cannot replace the running frozen Shared V2 monitor.'},
    {id:'xrp-v2', label:'XRP V2', eyebrow:'XRP V2', title:'XRP V2 development disposition', note:'This rejected or diagnostic research track remains separate from XRP V1 prospective monitoring.'},
    {id:'xrp-v3', label:'XRP V3', eyebrow:'XRP V3', title:'XRP V3 development disposition', note:'This development track remains visible without promotion or brokerage authority.'}
  ];

  const style = document.createElement('style');
  style.id = 'crypto-model-tabs-style';
  style.textContent = `
    #crypto-model-tabs{position:sticky;top:0;z-index:75;margin:0 0 18px;padding:9px;border:1px solid rgba(120,155,205,.22);border-radius:17px;background:rgba(7,16,31,.94);box-shadow:0 14px 34px rgba(0,0,0,.24);backdrop-filter:blur(14px)}
    #crypto-model-tabs .cmt-scroll{display:flex;gap:7px;overflow-x:auto;scrollbar-width:thin;padding-bottom:1px}
    #crypto-model-tabs [role=tab]{flex:0 0 auto;padding:10px 14px;border:1px solid transparent;border-radius:11px;background:transparent;color:var(--muted);font-size:.76rem;font-weight:900;letter-spacing:.035em;cursor:pointer;white-space:nowrap}
    #crypto-model-tabs [role=tab]:hover{color:var(--text);border-color:rgba(54,216,255,.24);background:rgba(54,216,255,.06)}
    #crypto-model-tabs [role=tab][aria-selected=true]{color:#06151d;border-color:transparent;background:linear-gradient(90deg,var(--cyan),var(--green));box-shadow:0 7px 18px rgba(54,216,255,.16)}
    #crypto-model-panels{min-width:0}.crypto-model-pane[hidden]{display:none!important}.crypto-model-pane-content{display:flex;flex-direction:column;gap:22px;min-width:0}
    .crypto-model-pane-head{margin:0 0 18px;padding:18px 20px;border:1px solid rgba(120,155,205,.18);border-radius:18px;background:linear-gradient(145deg,rgba(13,28,49,.8),rgba(8,20,36,.72))}
    .crypto-model-pane-head h2{margin:5px 0}.crypto-model-pane-head p{margin:0;line-height:1.5}.crypto-model-pane-content>section{margin-top:0!important}.crypto-model-track-card{width:100%}
    @media(max-width:700px){#crypto-model-tabs{margin-left:-1%;margin-right:-1;border-radius:14px}#crypto-model-tabs [role=tab]{padding:9px 11px;font-size:.7rem}.crypto-model-pane-head{padding:16px}}
  `;
  document.head.appendChild(style);

  const nav = document.createElement('nav');
  nav.id = 'crypto-model-tabs';
  nav.setAttribute('aria-label', 'Crypto model research sections');
  nav.innerHTML = `<div class="cmt-scroll" role="tablist">${MODELS.map((model, index) => `<button type="button" role="tab" id="crypto-model-tab-${model.id}" aria-controls="crypto-model-pane-${model.id}" aria-selected="${index === 0}" tabindex="${index === 0 ? '0' : '-1'}" data-crypto-model-tab="${model.id}">${model.label}</button>`).join('')}</div>`;

  const panels = document.createElement('main');
  panels.id = 'crypto-model-panels';
  MODELS.forEach((model, index) => {
    const pane = document.createElement('section');
    pane.id = `crypto-model-pane-${model.id}`;
    pane.className = `crypto-model-pane crypto-model-pane-${model.id}`;
    pane.setAttribute('role', 'tabpanel');
    pane.setAttribute('aria-labelledby', `crypto-model-tab-${model.id}`);
    pane.hidden = index !== 0;
    pane.innerHTML = `<div class="crypto-model-pane-head"><div class="label">${model.eyebrow}</div><h2>${model.title}</h2><p class="muted">${model.note}</p></div><div class="crypto-model-pane-content" data-crypto-model-content="${model.id}"></div>`;
    panels.appendChild(pane);
  });

  const anchor = shell.querySelector(':scope > .ds-section-tabs') || shell.querySelector(':scope > .ds-dashboard-tabs') || shell.querySelector(':scope > header');
  anchor.insertAdjacentElement('afterend', nav);
  nav.insertAdjacentElement('afterend', panels);

  const target = id => panels.querySelector(`[data-crypto-model-content="${id}"]`);
  const move = (node, id) => {
    const destination = target(id);
    if (node && destination) destination.appendChild(node);
  };

  const development = [...shell.querySelectorAll(':scope > section')].find(section =>
    section.querySelector(':scope > .label')?.textContent.trim() === 'DEVELOPMENT RESEARCH — VERSION STATUS'
  );
  if (development) {
    [...development.querySelectorAll(':scope .grid > .card')].forEach(card => {
      const name = card.querySelector(':scope > .label')?.textContent.trim() || '';
      const id = name === 'Shared Crypto V3' ? 'shared-v3' : name === 'XRP V2' ? 'xrp-v2' : name === 'XRP V3' ? 'xrp-v3' : 'overview';
      card.classList.add('crypto-model-track-card');
      move(card, id);
    });
    development.remove();
  }

  [...shell.querySelectorAll(':scope > section')].forEach(section => {
    const label = section.querySelector(':scope > .label')?.textContent.trim() || '';
    if (label.startsWith('CRYPTO 15M V2') || label === 'UNTOUCHED FORWARD PERFORMANCE' || label === 'POST-BOUNDARY FORWARD VALIDATION SUMMARY') move(section, 'shared-v2');
    else if (label.startsWith('XRP V1')) move(section, 'xrp-v1');
    else if (label.startsWith('CRYPTO V1')) move(section, 'crypto-v1');
    else move(section, 'overview');
  });

  const activate = id => {
    const next = MODELS.some(model => model.id === id) ? id : 'overview';
    nav.querySelectorAll('[role=tab]').forEach(button => {
      const active = button.dataset.cryptoModelTab === next;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
    });
    panels.querySelectorAll('[role=tabpanel]').forEach(pane => {
      pane.hidden = pane.id !== `crypto-model-pane-${next}`;
    });
    history.replaceState(null, '', next === 'overview' ? window.location.pathname : `#crypto-${next}`);
  };

  nav.addEventListener('click', event => {
    const button = event.target.closest('[data-crypto-model-tab]');
    if (button) activate(button.dataset.cryptoModelTab);
  });
  nav.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...nav.querySelectorAll('[role=tab]')];
    const current = buttons.indexOf(document.activeElement);
    let next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    event.preventDefault();
    buttons[next].focus();
    activate(buttons[next].dataset.cryptoModelTab);
  });

  activate((window.location.hash.match(/^#crypto-(.+)$/) || [])[1] || 'overview');
})();
