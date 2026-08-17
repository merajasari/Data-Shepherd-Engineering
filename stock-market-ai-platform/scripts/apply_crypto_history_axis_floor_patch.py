"""Clamp Crypto Visual normalized-growth y-axis padding at zero without changing raw-price scaling."""
from pathlib import Path

JS = Path("webapp/static/js/crypto_history_chart.js")

OLD = """    let yMin=transform(minV),yMax=transform(maxV); const pad=(yMax-yMin)*.07||1; yMin-=pad;yMax+=pad;\n"""

NEW = """    let yMin=transform(minV),yMax=transform(maxV);\n    const pad=(yMax-yMin)*.07||1;\n    if(mode==='normalized' && !logScale) {\n      yMin=Math.max(0,yMin-pad);\n    } else {\n      yMin-=pad;\n    }\n    yMax+=pad;\n"""


def main() -> None:
    text = JS.read_text(encoding="utf-8")
    if NEW in text:
        print("[SKIP] normalized growth axis floor already applied")
    elif OLD in text:
        text = text.replace(OLD, NEW, 1)
        JS.write_text(text, encoding="utf-8")
        print("[APPLY] clamp normalized-growth axis floor at zero")
    else:
        raise SystemExit("Cannot apply normalized axis floor: expected chart scaling block not found")

    print("Crypto Visual normalized axis floor patch complete.")
    print("Normalized linear charts cannot display negative y-axis padding; log and raw-USD scaling are unchanged.")


if __name__ == "__main__":
    main()
