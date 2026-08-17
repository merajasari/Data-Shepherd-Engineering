from pathlib import Path

TARGET = Path("webapp/static/js/v4_equity_chart.js")

text = TARGET.read_text(encoding="utf-8")

old_overlay = """    const overlay=node('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'transparent',style:'cursor:crosshair;touch-action:none'});\n    const selectFromEvent=event=>{const rect=svg.getBoundingClientRect();const px=(event.clientX-rect.left)*W/rect.width;const ratio=Math.max(0,Math.min(1,(px-p.l)/(W-p.l-p.r)));const idx=rows.length===1?0:Math.round(ratio*(rows.length-1));updateSelection(idx,event.clientX,event.clientY,true);};\n    overlay.addEventListener('pointermove',selectFromEvent);\n    overlay.addEventListener('pointerdown',event=>{overlay.setPointerCapture?.(event.pointerId);selectFromEvent(event);});\n    overlay.addEventListener('pointerleave',()=>{tooltip.style.display='none';});\n"""

new_overlay = """    const overlay=node('rect',{\n      x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,\n      fill:'rgba(0,0,0,0.001)',\n      'pointer-events':'all',\n      style:'cursor:crosshair;touch-action:none'\n    });\n\n    const selectFromEvent=event=>{\n      const rect=svg.getBoundingClientRect();\n      const px=(event.clientX-rect.left)*W/rect.width;\n      const plotLeft=p.l;\n      const plotRight=W-p.r;\n      const guideX=Math.max(plotLeft,Math.min(plotRight,px));\n      const ratio=(guideX-plotLeft)/(plotRight-plotLeft);\n      const idx=rows.length===1?0:Math.round(ratio*(rows.length-1));\n\n      // Update the selected observation/readouts first.\n      updateSelection(idx,event.clientX,event.clientY,true);\n\n      // Then keep the vertical guide physically under the pointer instead of\n      // snapping it to the sparse journal observation.  This makes the V4\n      // chart feel like Interactive Market History even when only a handful\n      // of V4 journal observations exist.\n      const guide=svg.querySelector('#v4-equity-guide');\n      if(guide){\n        guide.setAttribute('x1',guideX);\n        guide.setAttribute('x2',guideX);\n        guide.setAttribute('opacity','.98');\n      }\n    };\n\n    overlay.addEventListener('pointermove',selectFromEvent);\n    overlay.addEventListener('pointerdown',event=>{\n      overlay.setPointerCapture?.(event.pointerId);\n      selectFromEvent(event);\n    });\n    overlay.addEventListener('pointerleave',()=>{tooltip.style.display='none';});\n"""

if old_overlay not in text:
    raise SystemExit("Expected current V4 interactive overlay block not found; no changes made.")

text = text.replace(old_overlay, new_overlay, 1)
TARGET.write_text(text, encoding="utf-8")

print("[APPLY] V4 equity guide now follows the pointer continuously")
print("[APPLY] V4 chart hit-area explicitly receives pointer events")
print("Nearest journal observation still drives the equity/time readouts.")
print("Presentation only; V4 portfolio state, journals, models, and brokerage settings are unchanged.")
