#!/usr/bin/env python3
from pathlib import Path

PATH = Path('webapp/static/js/v4_equity_chart.js')
text = PATH.read_text(encoding='utf-8')
old = """const o=el('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'transparent',style:'cursor:crosshair;touch-action:none'});const move=e=>{const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)*W/r.width,ratio=Math.max(0,Math.min(1,(px-p.l)/(W-p.l-p.r)));show(Math.round(ratio*(rows.length-1)),e.clientX,e.clientY,true)};o.addEventListener('pointermove',move);o.addEventListener('pointerdown',move);o.addEventListener('pointerleave',()=>tip.style.display='none');show(rows.length-1,null,null,false)}"""
new = """const o=el('rect',{x:p.l,y:p.t,width:W-p.l-p.r,height:H-p.t-p.b,fill:'#000','fill-opacity':'0.001','pointer-events':'all',style:'cursor:crosshair;touch-action:none'});const move=e=>{const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)*W/r.width,ratio=Math.max(0,Math.min(1,(px-p.l)/(W-p.l-p.r)));show(Math.round(ratio*(rows.length-1)),e.clientX,e.clientY,true)};o.addEventListener('pointermove',move);o.addEventListener('pointerdown',e=>{o.setPointerCapture?.(e.pointerId);move(e)});o.addEventListener('pointerleave',()=>tip.style.display='none');show(rows.length-1,null,null,false)}"""
if old not in text:
    raise SystemExit('Expected V4 overlay block not found; no changes made.')
text = text.replace(old, new, 1)
PATH.write_text(text, encoding='utf-8')
print('[APPLY] V4 equity hit-area fixed for reliable pointer tracking')
print('The transparent SVG overlay now receives pointer events across the entire plot area.')
print('Presentation only; no portfolio, journal, model, or brokerage behavior changed.')
