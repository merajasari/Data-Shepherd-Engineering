"""Replace the V4 HTML range slider with an SVG-native scrubber.

The scrubber uses the exact same SVG x-coordinate function as the vertical
selection guide, so the thumb and guide cannot drift out of alignment under
responsive scaling, browser range-input quirks, or CSS box-model differences.

Presentation only. No portfolio state, journal, model, or brokerage behavior
is changed.
"""

from pathlib import Path


PATH = Path("webapp/static/js/v4_equity_chart.js")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    # Keep the existing input only as an invisible accessibility/control state
    # element.  The visible scrubber is rendered inside the SVG itself.
    slider_style_start = """    /*
     * The SVG plot occupies x=78..966 in a 1000-unit viewBox.  Keep the
     * range thumb centered on those exact plot endpoints.  The extra 18px
     * compensates for the 18px custom thumb so its center, not its outer
     * edge, maps to the SVG plot boundary.
     */
    .v4-eq-slider{
      display:block;
      -webkit-appearance:none;
      appearance:none;
      width:calc(88.8% + 18px);
      margin:13px calc(3.4% - 9px) 0 calc(7.8% - 9px);
      height:18px;
      background:transparent;
      cursor:pointer;
      box-sizing:border-box;
    }
    .v4-eq-slider::-webkit-slider-runnable-track{
      height:6px;
      border-radius:999px;
      background:linear-gradient(90deg,rgba(54,216,255,.95),rgba(57,227,161,.85));
      box-shadow:inset 0 0 0 1px rgba(145,166,194,.20);
    }
    .v4-eq-slider::-webkit-slider-thumb{
      -webkit-appearance:none;
      appearance:none;
      width:18px;
      height:18px;
      margin-top:-6px;
      border-radius:50%;
      border:2px solid #07101f;
      background:var(--cyan);
      box-shadow:0 0 0 2px rgba(54,216,255,.20),0 2px 8px rgba(0,0,0,.35);
    }
    .v4-eq-slider::-moz-range-track{
      height:6px;
      border:0;
      border-radius:999px;
      background:linear-gradient(90deg,rgba(54,216,255,.95),rgba(57,227,161,.85));
      box-shadow:inset 0 0 0 1px rgba(145,166,194,.20);
    }
    .v4-eq-slider::-moz-range-thumb{
      width:18px;
      height:18px;
      border-radius:50%;
      border:2px solid #07101f;
      background:var(--cyan);
      box-shadow:0 0 0 2px rgba(54,216,255,.20),0 2px 8px rgba(0,0,0,.35);
    }"""
    slider_style_new = """    /* Native range remains available to keyboard/AT but is not visual. */
    .v4-eq-slider{
      position:absolute!important;
      width:1px!important;
      height:1px!important;
      margin:0!important;
      padding:0!important;
      opacity:0!important;
      pointer-events:none!important;
      overflow:hidden!important;
    }"""
    text = replace_once(text, slider_style_start, slider_style_new, "hide browser-native range track")

    text = replace_once(
        text,
        "    .v4-chart-wrap{position:relative;height:390px;min-height:300px;border:1px solid rgba(120,155,205,.14);border-radius:16px;background:rgba(7,16,31,.52);overflow:hidden}",
        "    .v4-chart-wrap{position:relative;height:420px;min-height:330px;border:1px solid rgba(120,155,205,.14);border-radius:16px;background:rgba(7,16,31,.52);overflow:hidden}",
        "reserve SVG space for aligned scrubber",
    )

    text = replace_once(
        text,
        "    @media(max-width:650px){.v4-chart-wrap{height:300px}.v4-eq-readout{grid-template-columns:1fr}.v4-eq-tooltip{min-width:175px;font-size:.72rem}}",
        "    @media(max-width:650px){.v4-chart-wrap{height:335px}.v4-eq-readout{grid-template-columns:1fr}.v4-eq-tooltip{min-width:175px;font-size:.72rem}}",
        "mobile scrubber height",
    )

    text = replace_once(
        text,
        "    help.textContent = 'Move across the chart or drag the slider. The guide and slider stay aligned to the nearest recorded observation, while the floating panel and boxes show its exact values.';",
        "    help.textContent = 'Move across the chart or drag the scrubber. The vertical guide and scrubber thumb share the exact same chart coordinate, while the floating panel and boxes show the selected observation.';",
        "new scrubber help text",
    )
    text = replace_once(
        text,
        "    help.textContent = 'Move across the chart or drag the slider. The guide and slider stay aligned to the nearest recorded observation, while the floating panel and boxes show its exact values.';",
        "    help.textContent = 'Move across the chart or drag the scrubber. The vertical guide and scrubber thumb share the exact same chart coordinate, while the floating panel and boxes show the selected observation.';",
        "existing scrubber help text",
    )

    text = replace_once(
        text,
        "    const W=1000,H=390,p={l:78,r:34,t:24,b:48};",
        "    const W=1000,H=420,p={l:78,r:34,t:24,b:78};",
        "expand SVG view for scrubber",
    )

    old_guide = """    const last=Math.max(0,rows.length-1);
    node('line',{id:'v4-equity-guide',x1:x(last),x2:x(last),y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-width':'1.5','stroke-dasharray':'5 4',opacity:'.92'});
    node('circle',{id:'v4-equity-guide-dot',cx:x(last),cy:y(Number(rows[last].equity)),r:'5.5',fill:'#39e3a1',stroke:'#07101f','stroke-width':'2'});
"""
    new_guide = """    const last=Math.max(0,rows.length-1);
    node('line',{id:'v4-equity-guide',x1:x(last),x2:x(last),y1:p.t,y2:H-p.b,stroke:'#f2f6ff','stroke-width':'1.5','stroke-dasharray':'5 4',opacity:'.92'});
    node('circle',{id:'v4-equity-guide-dot',cx:x(last),cy:y(Number(rows[last].equity)),r:'5.5',fill:'#39e3a1',stroke:'#07101f','stroke-width':'2'});

    // SVG-native scrubber.  Its endpoints are literally p.l and W-p.r, the
    // same coordinates used by x(index) and the vertical guide.
    const scrubberY=H-34;
    node('line',{id:'v4-equity-scrubber-track',x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'rgba(54,216,255,.92)','stroke-width':'7','stroke-linecap':'round'});
    node('line',{x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'rgba(57,227,161,.42)','stroke-width':'3','stroke-linecap':'round','pointer-events':'none'});
    node('circle',{id:'v4-equity-scrubber-thumb',cx:x(last),cy:scrubberY,r:'9',fill:'#36d8ff',stroke:'#07101f','stroke-width':'3',style:'cursor:ew-resize;touch-action:none'});
    const scrubberHit=node('rect',{id:'v4-equity-scrubber-hit',x:p.l,y:scrubberY-15,width:W-p.l-p.r,height:30,fill:'rgba(0,0,0,0.001)','pointer-events':'all',style:'cursor:ew-resize;touch-action:none'});
"""
    text = replace_once(text, old_guide, new_guide, "add SVG-native scrubber")

    old_update = """    if (guide) { guide.setAttribute('x1',x); guide.setAttribute('x2',x); guide.setAttribute('opacity','.92'); }
    if (dot) { dot.setAttribute('cx',x); dot.setAttribute('cy',y); }
"""
    new_update = """    if (guide) { guide.setAttribute('x1',x); guide.setAttribute('x2',x); guide.setAttribute('opacity','.92'); }
    if (dot) { dot.setAttribute('cx',x); dot.setAttribute('cy',y); }
    const scrubberThumb=svg.querySelector('#v4-equity-scrubber-thumb');
    if(scrubberThumb) scrubberThumb.setAttribute('cx',x);
"""
    text = replace_once(text, old_update, new_update, "bind scrubber thumb to guide coordinate")

    old_overlay_tail = """    overlay.addEventListener('pointerenter',()=>{pointerActive=true;});
    overlay.addEventListener('pointermove',selectFromEvent);
    overlay.addEventListener('pointerdown',event=>{
      overlay.setPointerCapture?.(event.pointerId);
      selectFromEvent(event);
    });
    overlay.addEventListener('pointerleave',()=>{pointerActive=false;tooltip.style.display='none';});
    updateSelection(last,null,null,false);
"""
    new_overlay_tail = """    overlay.addEventListener('pointerenter',()=>{pointerActive=true;});
    overlay.addEventListener('pointermove',selectFromEvent);
    overlay.addEventListener('pointerdown',event=>{
      overlay.setPointerCapture?.(event.pointerId);
      selectFromEvent(event);
    });
    overlay.addEventListener('pointerleave',()=>{pointerActive=false;tooltip.style.display='none';});

    const selectFromScrubber=event=>{
      const rect=svg.getBoundingClientRect();
      const px=(event.clientX-rect.left)*W/rect.width;
      const clamped=Math.max(p.l,Math.min(W-p.r,px));
      const ratio=(clamped-p.l)/(W-p.r-p.l);
      const idx=rows.length===1?0:Math.round(ratio*(rows.length-1));
      updateSelection(idx,event.clientX,event.clientY,true);
    };
    scrubberHit.addEventListener('pointerdown',event=>{
      pointerActive=true;
      scrubberHit.setPointerCapture?.(event.pointerId);
      selectFromScrubber(event);
    });
    scrubberHit.addEventListener('pointermove',event=>{
      if(event.buttons || scrubberHit.hasPointerCapture?.(event.pointerId)) selectFromScrubber(event);
    });
    scrubberHit.addEventListener('pointerup',event=>{
      scrubberHit.releasePointerCapture?.(event.pointerId);
      pointerActive=false;
    });
    scrubberHit.addEventListener('pointercancel',()=>{pointerActive=false;});
    updateSelection(last,null,null,false);
"""
    text = replace_once(text, old_overlay_tail, new_overlay_tail, "wire SVG scrubber interaction")

    PATH.write_text(text, encoding="utf-8")
    print()
    print("V4 SVG-native equity scrubber patch complete.")
    print("The visible scrubber and vertical guide now share the same SVG coordinate system.")
    print("Responsive/CSS/native-range alignment drift is eliminated by construction.")
    print("Presentation only; no portfolio, journal, model, or brokerage behavior changed.")


if __name__ == "__main__":
    main()
