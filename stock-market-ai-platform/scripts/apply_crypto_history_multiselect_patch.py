"""Make Crypto Visual full-history asset selection touch-friendly and multi-select by default."""
from pathlib import Path

JS = Path("webapp/static/js/crypto_history_chart.js")
TEMPLATE = Path("webapp/templates/crypto_visual.html")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[SKIP] {label}")
        return text
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def main() -> None:
    js = JS.read_text(encoding="utf-8")

    # Earlier failed runs may already have applied these sections. Only add the helper
    # functions when they do not already exist.
    if "function selectAllAssets()" not in js:
        old = """  function toggleCompare(symbol) {\n    showAll=false;\n    if(selected.has(symbol) && selected.size>1) selected.delete(symbol);\n    else selected.add(symbol);\n    hoverSymbol=null;\n    renderAll();\n  }\n"""
        new = """  function toggleCompare(symbol) {\n    showAll=false;\n    if(selected.has(symbol)) selected.delete(symbol);\n    else selected.add(symbol);\n    hoverSymbol=null;\n    renderAll();\n  }\n\n  function selectAllAssets() {\n    showAll=true;\n    selected.clear();\n    hoverSymbol=null;\n    zoomLevel=1;\n    panOffset=0;\n    renderAll();\n  }\n\n  function clearSelection() {\n    showAll=false;\n    selected.clear();\n    hoverSymbol=null;\n    renderAll();\n  }\n"""
        js = replace_once(js, old, new, "multi-select toggle behavior")
    else:
        print("[SKIP] multi-select toggle behavior")

    if "Double-click to focus only." not in js:
        start = js.find("  function renderLegend() {")
        end = js.find("\n  function renderSearch(", start)
        if start < 0 or end < 0:
            raise SystemExit("Cannot apply always-visible selectable asset chips: function markers not found")
        new_legend = """  function renderLegend() {\n    const root=document.getElementById('history-legend'); if(!root||!historical) return;\n    const symbols=Object.keys(historical?.series||{}).filter(s=>historical.series[s]?.available).sort();\n    root.innerHTML=symbols.map((s,i)=>{\n      const on=showAll||selected.has(s);\n      return `<button type=\"button\" class=\"history-legend-chip${on?' history-selected':''}\" data-symbol=\"${esc(s)}\" title=\"Click to add/remove. Double-click to focus only.\" aria-pressed=\"${on?'true':'false'}\"><i style=\"background:${palette[i%palette.length]}\"></i><span>${esc(s.replace('-USD',''))}</span><small>${esc(assetNames[s]||'')}</small></button>`;\n    }).join('');\n    root.querySelectorAll('.history-legend-chip').forEach(btn=>{\n      let clickTimer=null;\n      btn.addEventListener('click',()=>{\n        if(clickTimer) window.clearTimeout(clickTimer);\n        clickTimer=window.setTimeout(()=>{toggleCompare(btn.dataset.symbol);clickTimer=null;},220);\n      });\n      btn.addEventListener('dblclick',event=>{\n        event.preventDefault();\n        if(clickTimer){window.clearTimeout(clickTimer);clickTimer=null;}\n        focusOnly(btn.dataset.symbol);\n      });\n      btn.addEventListener('mouseenter',()=>{hoverSymbol=btn.dataset.symbol;applyLineEmphasis();});\n      btn.addEventListener('mouseleave',()=>{hoverSymbol=null;applyLineEmphasis();});\n    });\n  }\n"""
        js = js[:start] + new_legend + js[end:]
        print("[APPLY] always-visible selectable asset chips")
    else:
        print("[SKIP] always-visible selectable asset chips")

    # Search result behavior.
    if "toggleCompare(btn.dataset.symbol);" not in js[js.find("function renderSearch"):js.find("function renderSummary")]:
        search_start = js.find("  function renderSearch(")
        search_end = js.find("\n  function renderSummary(", search_start)
        block = js[search_start:search_end]
        block = block.replace("focusOnly(btn.dataset.symbol);", "toggleCompare(btn.dataset.symbol);")
        js = js[:search_start] + block + js[search_end:]
        print("[APPLY] search result multi-select behavior")
    else:
        print("[SKIP] search result multi-select behavior")

    js = js.replace("Click to focus · Shift-click to compare", "Click to add/remove · Double-click to focus only")

    if "let chartClickTimer=null;" not in js:
        old = "    svg.onclick=e=>{if(pointerSymbol){e.shiftKey?toggleCompare(pointerSymbol):focusOnly(pointerSymbol);}};"
        if old not in js:
            raise SystemExit("Cannot apply chart click multi-select behavior: click handler not found")
        new = """    let chartClickTimer=null;\n    svg.onclick=()=>{\n      if(!pointerSymbol)return;\n      const symbol=pointerSymbol;\n      if(chartClickTimer)window.clearTimeout(chartClickTimer);\n      chartClickTimer=window.setTimeout(()=>{toggleCompare(symbol);chartClickTimer=null;},220);\n    };\n    svg.ondblclick=e=>{\n      e.preventDefault();\n      if(!pointerSymbol)return;\n      if(chartClickTimer){window.clearTimeout(chartClickTimer);chartClickTimer=null;}\n      focusOnly(pointerSymbol);\n    };"""
        js = js.replace(old, new, 1)
        print("[APPLY] chart click multi-select behavior")
    else:
        print("[SKIP] chart click multi-select behavior")

    # Wire controls by inserting immediately before the history search setup. This is a
    # stable marker across the existing UX versions and avoids depending on the exact
    # history-show-all handler text.
    if "history-select-all')?.addEventListener" not in js:
        marker = "  const search=document.getElementById('history-search');"
        if marker not in js:
            raise SystemExit("Cannot apply select-all and clear-selection controls: stable search marker not found")
        wiring = """  document.getElementById('history-show-all')?.addEventListener('click',selectAllAssets);\n  document.getElementById('history-select-all')?.addEventListener('click',selectAllAssets);\n  document.getElementById('history-clear-selection')?.addEventListener('click',clearSelection);\n"""
        # Remove any existing history-show-all handler so one click does not fire twice.
        import re
        js = re.sub(r"  document\.getElementById\('history-show-all'\)\?\.addEventListener\('click',[^\n]+\);\n", "", js, count=1)
        js = js.replace(marker, wiring + marker, 1)
        print("[APPLY] select-all and clear-selection controls")
    else:
        print("[SKIP] select-all and clear-selection controls")

    # renderAll selected-state sync: insert separately so we don't need to replace a
    # long minified renderAll line.
    if "function syncHistorySelectionUI()" not in js:
        marker = "  function renderAll(){"
        if marker not in js:
            raise SystemExit("Cannot apply selected-chip state rendering: renderAll marker not found")
        helper = """  function syncHistorySelectionUI() {\n    const all=document.getElementById('history-show-all');\n    if(all){all.textContent=showAll?'SHOWING ALL 25':'SHOW ALL 25';all.classList.toggle('active',showAll);}\n    document.querySelectorAll('.history-legend-chip').forEach(chip=>{\n      const on=showAll||selected.has(chip.dataset.symbol);\n      chip.classList.toggle('history-selected',on);\n      chip.setAttribute('aria-pressed',on?'true':'false');\n    });\n  }\n\n"""
        js = js.replace(marker, helper + marker, 1)
        # renderLegend already creates the right classes; call helper after renderLegend.
        js = js.replace("renderSummary();renderLegend();renderChart();", "renderSummary();renderLegend();syncHistorySelectionUI();renderChart();", 1)
        print("[APPLY] selected-chip state rendering")
    else:
        print("[SKIP] selected-chip state rendering")

    JS.write_text(js, encoding="utf-8")

    template = TEMPLATE.read_text(encoding="utf-8")
    if "#history-legend .history-legend-chip.history-selected" not in template:
        style_anchor = ".history-legend-chip:hover,.history-legend-chip.history-hover{transform:translateY(-1px);border-color:rgba(54,216,255,.8);background:rgba(54,216,255,.10)}"
        style_new = style_anchor + "\n#history-legend .history-legend-chip{opacity:.38}\n#history-legend .history-legend-chip.history-selected{opacity:1;border-color:rgba(54,216,255,.72);background:rgba(54,216,255,.09);box-shadow:0 0 0 1px rgba(54,216,255,.08) inset}"
        template = replace_once(template, style_anchor, style_new, "selected/unselected chip styles")
    else:
        print("[SKIP] selected/unselected chip styles")

    if 'id="history-select-all"' not in template:
        controls_anchor = '<button id="history-reset-view" class="history-nav-btn" type="button">RESET VIEW</button>'
        if controls_anchor not in template:
            raise SystemExit("Cannot apply Select All / Clear Selection buttons: reset-view button not found")
        controls_new = '<button id="history-select-all" class="history-nav-btn" type="button">SELECT ALL</button><button id="history-clear-selection" class="history-nav-btn" type="button">CLEAR SELECTION</button>' + controls_anchor
        template = template.replace(controls_anchor, controls_new, 1)
        print("[APPLY] Select All / Clear Selection buttons")
    else:
        print("[SKIP] Select All / Clear Selection buttons")

    template = template.replace(
        "hover a line or coin chip to highlight it · click to focus one asset · Shift-click to build a comparison.",
        "hover a line or coin chip to highlight it · click to add/remove assets · double-click to focus one asset.",
    )
    template = template.replace(
        "<span><strong>Click:</strong> focuses that crypto</span><span><strong>Shift-click:</strong> compares multiple cryptos</span>",
        "<span><strong>Click:</strong> adds/removes that crypto</span><span><strong>Double-click:</strong> focuses only that crypto</span>",
    )

    TEMPLATE.write_text(template, encoding="utf-8")
    print("Crypto Visual history multi-select patch complete.")
    print("Normal click now toggles assets. Select All and Clear Selection are touch-friendly. Historical and live data remain read-only.")


if __name__ == "__main__":
    main()
