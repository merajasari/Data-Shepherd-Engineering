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

    js = replace_once(
        js,
        """  function toggleCompare(symbol) {\n    showAll=false;\n    if(selected.has(symbol) && selected.size>1) selected.delete(symbol);\n    else selected.add(symbol);\n    hoverSymbol=null;\n    renderAll();\n  }\n""",
        """  function toggleCompare(symbol) {\n    showAll=false;\n    if(selected.has(symbol)) selected.delete(symbol);\n    else selected.add(symbol);\n    hoverSymbol=null;\n    renderAll();\n  }\n\n  function selectAllAssets() {\n    showAll=true;\n    selected.clear();\n    hoverSymbol=null;\n    zoomLevel=1;\n    panOffset=0;\n    renderAll();\n  }\n\n  function clearSelection() {\n    showAll=false;\n    selected.clear();\n    hoverSymbol=null;\n    renderAll();\n  }\n""",
        "multi-select toggle behavior",
    )

    old_legend = """  function renderLegend() {\n    const root=document.getElementById('history-legend'); if(!root||!historical) return;\n    const symbols=activeSymbols();\n    root.innerHTML=symbols.map((s,i)=>`<button type=\"button\" class=\"history-legend-chip\" data-symbol=\"${esc(s)}\" title=\"Click to focus. Shift-click to compare.\"><i style=\"background:${palette[i%palette.length]}\"></i><span>${esc(s.replace('-USD',''))}</span><small>${esc(assetNames[s]||'')}</small></button>`).join('');\n    root.querySelectorAll('.history-legend-chip').forEach(btn=>{\n      btn.addEventListener('click',event=>event.shiftKey?toggleCompare(btn.dataset.symbol):focusOnly(btn.dataset.symbol));\n      btn.addEventListener('mouseenter',()=>{hoverSymbol=btn.dataset.symbol;applyLineEmphasis();});\n      btn.addEventListener('mouseleave',()=>{hoverSymbol=null;applyLineEmphasis();});\n    });\n  }\n"""
    new_legend = """  function renderLegend() {\n    const root=document.getElementById('history-legend'); if(!root||!historical) return;\n    const symbols=Object.keys(historical?.series||{}).filter(s=>historical.series[s]?.available).sort();\n    root.innerHTML=symbols.map((s,i)=>{\n      const on=showAll||selected.has(s);\n      return `<button type=\"button\" class=\"history-legend-chip${on?' history-selected':''}\" data-symbol=\"${esc(s)}\" title=\"Click to add/remove. Double-click to focus only.\" aria-pressed=\"${on?'true':'false'}\"><i style=\"background:${palette[i%palette.length]}\"></i><span>${esc(s.replace('-USD',''))}</span><small>${esc(assetNames[s]||'')}</small></button>`;\n    }).join('');\n    root.querySelectorAll('.history-legend-chip').forEach(btn=>{\n      let clickTimer=null;\n      btn.addEventListener('click',()=>{\n        if(clickTimer) window.clearTimeout(clickTimer);\n        clickTimer=window.setTimeout(()=>{toggleCompare(btn.dataset.symbol);clickTimer=null;},220);\n      });\n      btn.addEventListener('dblclick',event=>{\n        event.preventDefault();\n        if(clickTimer){window.clearTimeout(clickTimer);clickTimer=null;}\n        focusOnly(btn.dataset.symbol);\n      });\n      btn.addEventListener('mouseenter',()=>{hoverSymbol=btn.dataset.symbol;applyLineEmphasis();});\n      btn.addEventListener('mouseleave',()=>{hoverSymbol=null;applyLineEmphasis();});\n    });\n  }\n"""
    js = replace_once(js, old_legend, new_legend, "always-visible selectable asset chips")

    js = replace_once(
        js,
        """    root.querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>{\n      focusOnly(btn.dataset.symbol);\n      document.getElementById('history-search').value=''; root.classList.remove('open');\n    }));\n""",
        """    root.querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>{\n      toggleCompare(btn.dataset.symbol);\n      document.getElementById('history-search').value=''; root.classList.remove('open');\n    }));\n""",
        "search result multi-select behavior",
    )

    js = replace_once(
        js,
        """      const hint=svgEl('text',{x:12,y:84,fill:'#91a6c2','font-size':10});hint.textContent='Click to focus · Shift-click to compare';tooltip.appendChild(hint);\n""",
        """      const hint=svgEl('text',{x:12,y:84,fill:'#91a6c2','font-size':10});hint.textContent='Click to add/remove · Double-click to focus only';tooltip.appendChild(hint);\n""",
        "chart hover hint",
    )

    js = replace_once(
        js,
        """    svg.onclick=e=>{if(pointerSymbol){e.shiftKey?toggleCompare(pointerSymbol):focusOnly(pointerSymbol);}};\n""",
        """    let chartClickTimer=null;\n    svg.onclick=()=>{\n      if(!pointerSymbol)return;\n      const symbol=pointerSymbol;\n      if(chartClickTimer)window.clearTimeout(chartClickTimer);\n      chartClickTimer=window.setTimeout(()=>{toggleCompare(symbol);chartClickTimer=null;},220);\n    };\n    svg.ondblclick=e=>{\n      e.preventDefault();\n      if(!pointerSymbol)return;\n      if(chartClickTimer){window.clearTimeout(chartClickTimer);chartClickTimer=null;}\n      focusOnly(pointerSymbol);\n    };\n""",
        "chart click multi-select behavior",
    )

    js = replace_once(
        js,
        """  document.getElementById('history-show-all')?.addEventListener('click',()=>{showAll=!showAll;renderAll();});\n""",
        """  document.getElementById('history-show-all')?.addEventListener('click',selectAllAssets);\n  document.getElementById('history-select-all')?.addEventListener('click',selectAllAssets);\n  document.getElementById('history-clear-selection')?.addEventListener('click',clearSelection);\n""",
        "select-all and clear-selection controls",
    )

    js = replace_once(
        js,
        """const all=document.getElementById('history-show-all');if(all){all.textContent=showAll?'SHOWING ALL 25':'SHOW ALL 25';all.classList.toggle('active',showAll);}""",
        """const all=document.getElementById('history-show-all');if(all){all.textContent=showAll?'SHOWING ALL 25':'SHOW ALL 25';all.classList.toggle('active',showAll);}document.querySelectorAll('.history-legend-chip').forEach(chip=>chip.classList.toggle('history-selected',showAll||selected.has(chip.dataset.symbol)));""",
        "selected-chip state rendering",
    )

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
        controls_new = '<button id="history-select-all" class="history-nav-btn" type="button">SELECT ALL</button><button id="history-clear-selection" class="history-nav-btn" type="button">CLEAR SELECTION</button>' + controls_anchor
        template = replace_once(template, controls_anchor, controls_new, "Select All / Clear Selection buttons")
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
