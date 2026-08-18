"""Align the V4 equity chart guide and range slider to the same plot geometry.

Presentation-only patcher. The V4 portfolio state, journals, models, and
brokerage settings are not modified.
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

    text = replace_once(
        text,
        "    .v4-eq-slider{width:100%;margin-top:13px;accent-color:var(--cyan)}",
        """    /*
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
    }""",
        "slider track aligned to SVG plot bounds",
    )

    text = replace_once(
        text,
        "    help.textContent = 'The vertical guide follows your pointer. Equity and time labels move with the guide; the floating panel and boxes below show the selected observation.';",
        "    help.textContent = 'Move across the chart or drag the slider. The guide and slider stay aligned to the nearest recorded observation, while the floating panel and boxes show its exact values.';",
        "new aligned interaction help text",
    )

    text = replace_once(
        text,
        "    help.textContent = 'The vertical guide follows your pointer. Equity and time labels move with the guide; the floating panel and boxes below show the selected observation.';",
        "    help.textContent = 'Move across the chart or drag the slider. The guide and slider stay aligned to the nearest recorded observation, while the floating panel and boxes show its exact values.';",
        "existing aligned interaction help text",
    )

    old_pointer = """      // Update the selected observation/readouts first.
      updateSelection(idx,event.clientX,event.clientY,true);

      // Then keep the vertical guide physically under the pointer instead of
      // snapping it to the sparse journal observation.  This makes the V4
      // chart feel like Interactive Market History even when only a handful
      // of V4 journal observations exist.
      const guide=svg.querySelector('#v4-equity-guide');
      if(guide){
        guide.setAttribute('x1',guideX);
        guide.setAttribute('x2',guideX);
        guide.setAttribute('opacity','.98');
      }
"""
    new_pointer = """      // The guide, selected point, and range thumb intentionally use the
      // same discrete observation index.  This keeps all three controls
      // horizontally aligned while pointer movement still selects the nearest
      // available observation.
      updateSelection(idx,event.clientX,event.clientY,true);
"""
    text = replace_once(
        text,
        old_pointer,
        new_pointer,
        "guide snaps to the same observation as the slider thumb",
    )

    PATH.write_text(text, encoding="utf-8")

    print()
    print("V4 equity guide/slider alignment patch complete.")
    print("The guide, selected observation, and slider thumb now share one index and one plot geometry.")
    print("Presentation only; portfolio state, journals, models, and brokerage settings are unchanged.")


if __name__ == "__main__":
    main()
