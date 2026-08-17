from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text()
    if new in text:
        print(f"[SKIP] {label}")
        return
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found in {path}")
    p.write_text(text.replace(old, new, 1))
    print(f"[APPLY] {label}")


replace_once(
    "webapp/templates/crypto_visual.html",
    '.selector{padding:9px 12px;border-radius:12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:800}',
    '.selector{padding:9px 12px;border-radius:12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:800}.crypto-search-wrap{position:relative;min-width:310px}.crypto-search{width:100%;padding:10px 14px 10px 38px;border-radius:12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:800;outline:none}.crypto-search:focus{border-color:rgba(54,216,255,.7);box-shadow:0 0 0 3px rgba(54,216,255,.08)}.crypto-search-icon{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--muted);pointer-events:none}.crypto-search-results{position:absolute;z-index:30;top:calc(100% + 7px);left:0;right:0;max-height:280px;overflow:auto;background:#081526;border:1px solid var(--border);border-radius:14px;box-shadow:0 18px 40px rgba(0,0,0,.35);display:none}.crypto-search-results.open{display:block}.crypto-search-result{display:flex;justify-content:space-between;gap:12px;width:100%;padding:11px 13px;border:0;border-bottom:1px solid rgba(120,155,205,.11);background:transparent;color:var(--text);text-align:left;cursor:pointer}.crypto-search-result:hover,.crypto-search-result.active{background:rgba(54,216,255,.08)}.crypto-search-result:last-child{border-bottom:0}.crypto-search-result small{color:var(--muted)}',
    "crypto visual search styles",
)

replace_once(
    "webapp/templates/crypto_visual.html",
    '<div class="controls"><select id="visual-asset-select" class="selector" aria-label="Choose crypto asset"></select><span class="mode" id="visual-selected-change">—</span></div>',
    '<div class="controls"><div class="crypto-search-wrap"><span class="crypto-search-icon">⌕</span><input id="visual-asset-search" class="crypto-search" type="search" autocomplete="off" placeholder="Search BTC, Bitcoin, ETH, Solana…" aria-label="Search crypto assets"><div id="visual-asset-search-results" class="crypto-search-results"></div></div><select id="visual-asset-select" class="selector" aria-label="Choose crypto asset"></select><span class="mode" id="visual-selected-change">—</span></div>',
    "crypto visual search control",
)

p = Path("webapp/static/js/crypto_visual_dashboard.js")
text = p.read_text()
if "const assetNames =" not in text:
    text = text.replace(
        "  let latestQuotes = {};\n",
        "  let latestQuotes = {};\n  const assetNames = {\n    'AAVE-USD':'Aave','ADA-USD':'Cardano','ARB-USD':'Arbitrum','ATOM-USD':'Cosmos','AVAX-USD':'Avalanche','BCH-USD':'Bitcoin Cash','BTC-USD':'Bitcoin','DOGE-USD':'Dogecoin','DOT-USD':'Polkadot','ETC-USD':'Ethereum Classic','ETH-USD':'Ethereum','FIL-USD':'Filecoin','HBAR-USD':'Hedera','ICP-USD':'Internet Computer','INJ-USD':'Injective','LINK-USD':'Chainlink','LTC-USD':'Litecoin','NEAR-USD':'NEAR Protocol','OP-USD':'Optimism','SHIB-USD':'Shiba Inu','SOL-USD':'Solana','SUI-USD':'Sui','UNI-USD':'Uniswap','XLM-USD':'Stellar','XRP-USD':'XRP'\n  };\n"
    )

    marker = "  function renderPulse(quotes, updatedAt) {\n"
    helper = '''  function chooseSymbol(symbol) {\n    if (!latestQuotes[symbol]) return;\n    selected = symbol;\n    const select = document.getElementById('visual-asset-select');\n    if (select) select.value = selected;\n    const search = document.getElementById('visual-asset-search');\n    if (search) search.value = `${selected} — ${assetNames[selected] || selected.replace('-USD','')}`;\n    const results = document.getElementById('visual-asset-search-results');\n    if (results) results.classList.remove('open');\n    renderSelected();\n    renderMovers(latestQuotes);\n  }\n\n  function searchMatches(query) {\n    const q = String(query || '').trim().toLowerCase().replace(/\\s+/g, ' ');\n    const symbols = Object.keys(latestQuotes).sort();\n    if (!q) return symbols;\n    return symbols.filter(symbol => {\n      const base = symbol.replace('-USD','');\n      const name = assetNames[symbol] || '';\n      return symbol.toLowerCase().includes(q) || base.toLowerCase().includes(q) || name.toLowerCase().includes(q);\n    });\n  }\n\n  function renderSearchResults(query) {\n    const root = document.getElementById('visual-asset-search-results');\n    if (!root) return;\n    const matches = searchMatches(query).slice(0, 12);\n    if (!matches.length) {\n      root.innerHTML = '<div style="padding:12px 13px;color:#91a6c2">No matching crypto asset</div>';\n      root.classList.add('open');\n      return;\n    }\n    root.innerHTML = matches.map((symbol, index) => `<button type="button" class="crypto-search-result ${index===0?'active':''}" data-symbol="${esc(symbol)}"><strong>${esc(symbol)}</strong><small>${esc(assetNames[symbol] || '')}</small></button>`).join('');\n    root.classList.add('open');\n    root.querySelectorAll('.crypto-search-result').forEach(btn => btn.addEventListener('click', () => chooseSymbol(btn.dataset.symbol)));\n  }\n\n'''
    if marker not in text:
        raise SystemExit("Cannot apply crypto search JS: marker not found")
    text = text.replace(marker, helper + marker, 1)

    text = text.replace(
        "      selected = btn.dataset.symbol;\n      const select = document.getElementById('visual-asset-select');\n      if (select) select.value = selected;\n      renderSelected();\n      renderMovers(latestQuotes);",
        "      chooseSymbol(btn.dataset.symbol);"
    )

    text = text.replace(
        "  document.getElementById('visual-asset-select')?.addEventListener('change',(e)=>{selected=e.target.value;renderMovers(latestQuotes);renderSelected();});\n",
        "  document.getElementById('visual-asset-select')?.addEventListener('change',(e)=>chooseSymbol(e.target.value));\n  const search = document.getElementById('visual-asset-search');\n  const searchResults = document.getElementById('visual-asset-search-results');\n  search?.addEventListener('focus', () => renderSearchResults(search.value));\n  search?.addEventListener('input', () => renderSearchResults(search.value));\n  search?.addEventListener('keydown', (event) => {\n    if (event.key === 'Enter') {\n      const first = searchMatches(search.value)[0];\n      if (first) { event.preventDefault(); chooseSymbol(first); }\n    } else if (event.key === 'Escape') {\n      searchResults?.classList.remove('open');\n    }\n  });\n  document.addEventListener('click', (event) => {\n    if (!event.target.closest('.crypto-search-wrap')) searchResults?.classList.remove('open');\n  });\n"
    )

    text = text.replace(
        "      populateSelect(symbols);\n      renderPulse(latestQuotes,data.updated_at);",
        "      populateSelect(symbols);\n      if (search && !search.matches(':focus')) search.value = `${selected} — ${assetNames[selected] || selected.replace('-USD','')}`;\n      renderPulse(latestQuotes,data.updated_at);"
    )
    p.write_text(text)
    print("[APPLY] crypto visual search behavior")
else:
    print("[SKIP] crypto visual search behavior")

print("Crypto Visual live-chart search patch complete.")
print("Search changes presentation only; frozen research, journals, policies, and brokerage settings are unchanged.")
