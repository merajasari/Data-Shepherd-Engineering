from pathlib import Path


JS_PATH = Path("webapp/static/js/crypto_visual_dashboard.js")


def replace_once(text, old, new, label):
    if new in text:
        print(f"[SKIP] {label}")
        return text
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found in {JS_PATH}")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


text = JS_PATH.read_text()

text = replace_once(
    text,
    "    select.innerHTML = symbols.map(s => `<option value=\"${esc(s)}\">${esc(s)}</option>`).join('');",
    "    select.innerHTML = symbols.map(s => `<option value=\"${esc(s)}\">${esc(s)} — ${esc(assetNames[s] || s.replace('-USD',''))}</option>`).join('');",
    "full names in crypto dropdown",
)

text = replace_once(
    text,
    "    const symbol=document.getElementById('visual-selected-symbol');if(symbol)symbol.textContent=selected;",
    "    const symbol=document.getElementById('visual-selected-symbol');if(symbol)symbol.textContent=`${selected} — ${assetNames[selected] || selected.replace('-USD','')}`;",
    "full name in selected live-chart heading",
)

# Search results already carry the readable asset name, but make the result layout
# explicit and consistent by showing symbol+name together on the left and 24h move
# on the right when a live quote is available.
old_results = "    root.innerHTML = matches.map((symbol, index) => `<button type=\"button\" class=\"crypto-search-result ${index===0?'active':''}\" data-symbol=\"${esc(symbol)}\"><strong>${esc(symbol)}</strong><small>${esc(assetNames[symbol] || '')}</small></button>`).join('');"
new_results = "    root.innerHTML = matches.map((symbol, index) => { const q=latestQuotes[symbol]; const c=quoteChange(q); return `<button type=\"button\" class=\"crypto-search-result ${index===0?'active':''}\" data-symbol=\"${esc(symbol)}\"><span><strong>${esc(symbol)}</strong><small style=\"display:block;margin-top:2px\">${esc(assetNames[symbol] || symbol.replace('-USD',''))}</small></span><strong class=\"${colorClass(c)}\">${pct(c)}</strong></button>`; }).join('');"
text = replace_once(text, old_results, new_results, "readable crypto search results")

JS_PATH.write_text(text)
print("Crypto Visual asset-name presentation patch complete.")
print("Presentation only; live feeds, frozen research, journals, policies, and brokerage settings are unchanged.")
