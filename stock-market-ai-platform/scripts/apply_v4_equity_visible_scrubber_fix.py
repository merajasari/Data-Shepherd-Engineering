"""Restore a clearly visible V4 equity scrubber without changing working guide logic.

Run after apply_v4_equity_svg_scrubber_patch.py has been applied locally.
Presentation only: no portfolio, journal, model, or brokerage behavior changes.
"""
from pathlib import Path

PATH = Path("webapp/static/js/v4_equity_chart.js")


def replace_once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


def main():
    text = PATH.read_text(encoding="utf-8")

    # Keep the chart interaction exactly as-is. Make the SVG scrubber visually
    # unmistakable and place it in the reserved bottom band of the same SVG.
    old = """    const scrubberY=H-34;
    node('line',{id:'v4-equity-scrubber-track',x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'rgba(54,216,255,.92)','stroke-width':'7','stroke-linecap':'round'});
    node('line',{x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'rgba(57,227,161,.42)','stroke-width':'3','stroke-linecap':'round','pointer-events':'none'});
    node('circle',{id:'v4-equity-scrubber-thumb',cx:x(last),cy:scrubberY,r:'9',fill:'#36d8ff',stroke:'#07101f','stroke-width':'3',style:'cursor:ew-resize;touch-action:none'});
    const scrubberHit=node('rect',{id:'v4-equity-scrubber-hit',x:p.l,y:scrubberY-15,width:W-p.l-p.r,height:30,fill:'rgba(0,0,0,0.001)','pointer-events':'all',style:'cursor:ew-resize;touch-action:none'});
"""
    new = """    const scrubberY=H-27;
    // Dark rail underlay gives the control enough contrast on the chart.
    node('line',{x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'rgba(7,16,31,.95)','stroke-width':'14','stroke-linecap':'round','pointer-events':'none'});
    node('line',{id:'v4-equity-scrubber-track',x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'#36d8ff','stroke-width':'7','stroke-linecap':'round','pointer-events':'none'});
    node('line',{x1:p.l,y1:scrubberY,x2:W-p.r,y2:scrubberY,stroke:'rgba(57,227,161,.62)','stroke-width':'3','stroke-linecap':'round','pointer-events':'none'});
    node('circle',{id:'v4-equity-scrubber-thumb',cx:x(last),cy:scrubberY,r:'10',fill:'#36d8ff',stroke:'#f2f6ff','stroke-width':'2.5',style:'cursor:ew-resize;touch-action:none'});
    const scrubberHit=node('rect',{id:'v4-equity-scrubber-hit',x:p.l,y:scrubberY-18,width:W-p.l-p.r,height:36,fill:'rgba(0,0,0,0.001)','pointer-events':'all',style:'cursor:ew-resize;touch-action:none'});
"""
    text = replace_once(text, old, new, "restore prominent SVG scrubber bar")

    old_help = "Move across the chart or drag the scrubber. The vertical guide and scrubber thumb share the exact same chart coordinate, while the floating panel and boxes show the selected observation."
    new_help = "Move across the chart or drag the cyan bar below it. The vertical guide and scrubber thumb stay locked to the same selected observation."
    if old_help in text:
        text = text.replace(old_help, new_help)
        print("[APPLY] simplify scrubber help text")

    PATH.write_text(text, encoding="utf-8")
    print()
    print("V4 visible SVG scrubber fix complete.")
    print("Working guide/tooltip selection logic is unchanged.")
    print("The cyan horizontal bar is restored inside the SVG and shares the guide coordinate system.")
    print("Presentation only; no portfolio, journal, model, or brokerage behavior changed.")


if __name__ == "__main__":
    main()
