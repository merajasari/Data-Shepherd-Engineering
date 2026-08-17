from pathlib import Path

TARGET = Path("webapp/templates/index.html")

OLD = "renderV4Chart(f.chart_history||[],start);"
NEW = "/* V4 equity SVG is rendered exclusively by /static/js/v4_equity_chart.js so pointer interaction is not overwritten by the legacy inline renderer. */"

text = TARGET.read_text(encoding="utf-8")
count = text.count(OLD)

if count != 1:
    raise SystemExit(
        f"Expected exactly one legacy renderV4Chart call in {TARGET}; found {count}. No changes made."
    )

TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")

print("[APPLY] disabled legacy inline V4 SVG renderer")
print("[APPLY] external interactive v4_equity_chart.js is now the sole owner of the equity SVG")
print("This removes the async render race that was overwriting the pointer overlay and vertical guide.")
print("Presentation only; portfolio state, journals, frozen models, and brokerage settings are unchanged.")
