(() => {
  const search = document.getElementById('stock-search');
  const select = document.getElementById('stock-select');
  const form = document.getElementById('stock-selector-form');
  if (!search || !select || !form) return;

  const host = form.closest('.card') || form.parentElement;
  if (!host || host.dataset.primarySpotlightReady === '1') return;
  host.dataset.primarySpotlightReady = '1';
  host.classList.add('primary-stock-spotlight');
  host.id = 'primary-stock-view';

  // Preserve the user's position after the server-rendered stock selection refresh.
  // Existing selector logic can continue submitting normally; the fragment brings
  // the browser straight back to this block instead of the top of the dashboard.
  form.action = `${window.location.pathname}#primary-stock-view`;

  const allStocks = Array.from(select.options)
    .filter(option => option.value)
    .map(option => ({
      value: option.value,
      text: option.textContent.trim(),
      company: (option.dataset.company || '').trim(),
    }));

  const style = document.createElement('style');
  style.textContent = `
    .primary-stock-spotlight{
      position:relative;
      overflow:visible;
      border-color:rgba(54,216,255,.58)!important;
      background:
        radial-gradient(circle at 15% 0%,rgba(54,216,255,.13),transparent 32%),
        radial-gradient(circle at 88% 18%,rgba(57,227,161,.08),transparent 30%),
        linear-gradient(145deg,rgba(18,37,62,.98),rgba(8,20,36,.98))!important;
      box-shadow:0 0 0 1px rgba(54,216,255,.08),0 18px 55px rgba(0,0,0,.28),0 0 36px rgba(54,216,255,.08)!important;
      transition:border-color .22s ease,box-shadow .22s ease,transform .22s ease;
      scroll-margin-top:18px;
    }
    .primary-stock-spotlight::before{
      content:"";
      position:absolute;
      inset:-1px;
      border-radius:24px;
      pointer-events:none;
      background:linear-gradient(110deg,transparent 5%,rgba(54,216,255,.22) 36%,rgba(57,227,161,.18) 53%,transparent 78%);
      background-size:220% 100%;
      opacity:.55;
      -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
      -webkit-mask-composite:xor;
      mask-composite:exclude;
      padding:1px;
      animation:dsSelectorSweep 4.8s ease-in-out 2;
    }
    @keyframes dsSelectorSweep{0%{background-position:120% 0}100%{background-position:-120% 0}}
    .primary-stock-spotlight:focus-within{
      border-color:rgba(57,227,161,.75)!important;
      box-shadow:0 0 0 3px rgba(57,227,161,.09),0 20px 58px rgba(0,0,0,.3),0 0 42px rgba(54,216,255,.14)!important;
    }
    .primary-stock-prompt{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:16px;
      margin:16px 0 14px;
      padding:13px 15px;
      border:1px solid rgba(54,216,255,.24);
      border-radius:14px;
      background:linear-gradient(90deg,rgba(54,216,255,.09),rgba(57,227,161,.055));
    }
    .primary-stock-prompt-copy{display:flex;align-items:center;gap:12px;min-width:0}
    .primary-stock-prompt-icon{
      width:40px;height:40px;flex:0 0 40px;border-radius:12px;display:grid;place-items:center;
      background:rgba(54,216,255,.13);border:1px solid rgba(54,216,255,.3);font-size:1.12rem;
      box-shadow:inset 0 0 18px rgba(54,216,255,.06)
    }
    .primary-stock-prompt strong{display:block;font-size:.94rem;color:#f2f6ff;letter-spacing:.01em}
    .primary-stock-prompt span{display:block;margin-top:3px;color:#a8b9ce;font-size:.82rem;line-height:1.35}
    .primary-stock-start-badge{
      flex:0 0 auto;padding:7px 10px;border-radius:999px;background:rgba(57,227,161,.11);
      border:1px solid rgba(57,227,161,.3);color:#75f1bd;font-size:.68rem;font-weight:900;letter-spacing:.11em;
    }
    .primary-stock-spotlight #stock-search,
    .primary-stock-spotlight #stock-select{
      border-color:rgba(54,216,255,.5)!important;
      box-shadow:0 0 0 1px rgba(54,216,255,.035),inset 0 0 20px rgba(54,216,255,.025);
      transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease;
    }
    .primary-stock-spotlight #stock-search:hover,
    .primary-stock-spotlight #stock-select:hover{border-color:rgba(54,216,255,.85)!important}
    .primary-stock-spotlight #stock-search:focus,
    .primary-stock-spotlight #stock-select:focus{
      outline:none!important;
      border-color:#39e3a1!important;
      box-shadow:0 0 0 3px rgba(57,227,161,.13),0 0 24px rgba(54,216,255,.12)!important;
      transform:translateY(-1px);
    }
    .primary-stock-search-wrap{position:relative;display:inline-flex;align-items:center;flex:1 1 260px}
    .primary-stock-search-wrap #stock-search{width:100%;padding-left:42px!important}
    .primary-stock-search-icon{position:absolute;left:14px;pointer-events:none;color:#36d8ff;font-size:1rem;z-index:2}
    .primary-stock-search-hint{margin-top:9px;color:#7891ad;font-size:.74rem}
    .primary-stock-suggestions{
      position:absolute;left:0;right:0;top:calc(100% + 7px);z-index:80;
      display:none;max-height:315px;overflow:auto;padding:7px;
      border:1px solid rgba(54,216,255,.42);border-radius:13px;
      background:rgba(7,21,37,.98);box-shadow:0 18px 45px rgba(0,0,0,.46),0 0 28px rgba(54,216,255,.10);
      backdrop-filter:blur(12px);
    }
    .primary-stock-suggestions.open{display:block}
    .primary-stock-suggestion{
      width:100%;display:grid;grid-template-columns:72px 1fr;gap:10px;align-items:center;
      padding:10px 11px;border:0;border-bottom:1px solid rgba(120,155,205,.10);
      border-radius:9px;background:transparent;color:#f2f6ff;text-align:left;cursor:pointer;
    }
    .primary-stock-suggestion:last-child{border-bottom:0}
    .primary-stock-suggestion:hover,.primary-stock-suggestion.active{background:rgba(54,216,255,.10)}
    .primary-stock-suggestion-ticker{font-weight:950;color:#75e8ff;letter-spacing:.035em}
    .primary-stock-suggestion-company{font-size:.83rem;color:#b1c1d4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .primary-stock-no-results{padding:12px;color:#91a6c2;font-size:.82rem;text-align:center}
    @media(max-width:650px){
      .primary-stock-prompt{align-items:flex-start;flex-direction:column}
      .primary-stock-start-badge{margin-left:52px}
      .primary-stock-search-wrap{width:100%;flex-basis:auto}
    }
    @media(prefers-reduced-motion:reduce){.primary-stock-spotlight::before{animation:none}}
  `;
  document.head.appendChild(style);

  const prompt = document.createElement('div');
  prompt.className = 'primary-stock-prompt';
  prompt.innerHTML = `
    <div class="primary-stock-prompt-copy">
      <div class="primary-stock-prompt-icon" aria-hidden="true">⌕</div>
      <div>
        <strong>Explore the market intelligence</strong>
        <span>Search any ticker or company in the 100-stock universe to instantly update the market view, V5 rank, chart, and recent sessions.</span>
      </div>
    </div>
    <div class="primary-stock-start-badge">START HERE</div>`;

  const selector = form.querySelector('.selector') || form.firstElementChild;
  if (selector) form.insertBefore(prompt, selector);
  else form.prepend(prompt);

  const controls = form.querySelector('.selector-controls') || search.parentElement;
  let wrap = search.parentElement;
  if (controls && search.parentElement === controls) {
    wrap = document.createElement('div');
    wrap.className = 'primary-stock-search-wrap';
    controls.insertBefore(wrap, search);
    wrap.appendChild(search);
    const icon = document.createElement('span');
    icon.className = 'primary-stock-search-icon';
    icon.textContent = '⌕';
    wrap.prepend(icon);
  } else {
    wrap.classList.add('primary-stock-search-wrap');
  }

  const suggestions = document.createElement('div');
  suggestions.className = 'primary-stock-suggestions';
  suggestions.setAttribute('role', 'listbox');
  suggestions.setAttribute('aria-label', 'Matching stocks');
  wrap.appendChild(suggestions);

  const hint = document.createElement('div');
  hint.className = 'primary-stock-search-hint';
  hint.textContent = 'Tip: start typing a ticker or company name — matching stocks appear instantly below.';
  form.appendChild(hint);

  const findMatches = query => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return allStocks
      .filter(item => item.value.toLowerCase().includes(q) || item.company.toLowerCase().includes(q) || item.text.toLowerCase().includes(q))
      .sort((a, b) => {
        const av = a.value.toLowerCase();
        const bv = b.value.toLowerCase();
        const aStarts = av.startsWith(q) ? 0 : 1;
        const bStarts = bv.startsWith(q) ? 0 : 1;
        return aStarts - bStarts || av.localeCompare(bv);
      })
      .slice(0, 18);
  };

  const chooseStock = symbol => {
    const option = Array.from(select.options).find(o => o.value === symbol);
    if (option) {
      select.value = symbol;
    } else {
      // The original inline filter may have temporarily removed the option.
      // Recreate the chosen option so the existing GET form submits correctly.
      const item = allStocks.find(x => x.value === symbol);
      if (item) {
        const restored = document.createElement('option');
        restored.value = item.value;
        restored.textContent = item.text;
        restored.dataset.company = item.company;
        restored.selected = true;
        select.appendChild(restored);
      }
    }
    suggestions.classList.remove('open');
    form.submit();
  };

  const renderSuggestions = query => {
    const matches = findMatches(query);
    if (!query.trim()) {
      suggestions.classList.remove('open');
      suggestions.innerHTML = '';
      return;
    }
    if (!matches.length) {
      suggestions.innerHTML = '<div class="primary-stock-no-results">No matching stocks found</div>';
      suggestions.classList.add('open');
      return;
    }
    suggestions.innerHTML = matches.map(item => `
      <button type="button" class="primary-stock-suggestion" data-symbol="${item.value}" role="option">
        <span class="primary-stock-suggestion-ticker">${item.value}</span>
        <span class="primary-stock-suggestion-company">${item.company || item.text}</span>
      </button>`).join('');
    suggestions.classList.add('open');
  };

  // Use the input event so every keystroke immediately refreshes visible choices.
  // Run after the existing inline filter has processed the same keystroke.
  search.addEventListener('input', () => window.setTimeout(() => renderSuggestions(search.value), 0));
  search.addEventListener('focus', () => { if (search.value.trim()) renderSuggestions(search.value); });

  suggestions.addEventListener('mousedown', event => {
    const button = event.target.closest('.primary-stock-suggestion');
    if (!button) return;
    event.preventDefault();
    chooseStock(button.dataset.symbol);
  });

  document.addEventListener('mousedown', event => {
    if (!wrap.contains(event.target)) suggestions.classList.remove('open');
  });

  search.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      suggestions.classList.remove('open');
      return;
    }
    if (event.key === 'Enter') {
      const first = suggestions.querySelector('.primary-stock-suggestion');
      if (first) {
        event.preventDefault();
        event.stopImmediatePropagation();
        chooseStock(first.dataset.symbol);
      }
    }
  }, true);

  const emphasize = () => {
    host.style.transform = 'translateY(-1px)';
    window.setTimeout(() => { host.style.transform = ''; }, 180);
  };
  search.addEventListener('focus', emphasize, { once: true });
})();
