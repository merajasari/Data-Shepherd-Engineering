"""Improve Crypto Visual history-chart interaction and move it above Live Market Pulse."""
from pathlib import Path

TEMPLATE = Path("webapp/templates/crypto_visual.html")

STYLE_MARKER = "/* CRYPTO HISTORY UX V2 */"
CONTROL_MARKER = 'id="history-reset-view"'

UX_CSS = r'''
/* CRYPTO HISTORY UX V2 */
.history-ux-bar{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:10px 0 14px;padding:10px 12px;border:1px solid rgba(120,155,205,.16);border-radius:14px;background:rgba(8,20,36,.42)}
.history-ux-bar .hint{color:var(--muted);font-size:.82rem;margin-right:auto;line-height:1.45}
.history-nav-btn{padding:8px 11px;border:1px solid var(--border);border-radius:10px;background:var(--panel2);color:var(--text);font-weight:850;cursor:pointer}
.history-nav-btn:hover{border-color:rgba(54,216,255,.65);background:rgba(54,216,255,.08)}
.history-zoom-status{padding:7px 10px;border-radius:10px;background:rgba(54,216,255,.08);border:1px solid rgba(54,216,255,.22);color:var(--cyan);font-size:.76rem;font-weight:900;letter-spacing:.05em}
.history-legend-chip{transition:opacity .14s ease,transform .14s ease,border-color .14s ease,background .14s ease}
.history-legend-chip:hover,.history-legend-chip.history-hover{transform:translateY(-1px);border-color:rgba(54,216,255,.8);background:rgba(54,216,255,.10)}
.history-chart-help{display:flex;gap:18px;flex-wrap:wrap;margin:10px 0 4px;color:var(--muted);font-size:.8rem}
.history-chart-help strong{color:var(--text)}
#crypto-history-chart{cursor:crosshair;touch-action:pan-y}
@media(max-width:760px){.history-ux-bar .hint{width:100%;flex-basis:100%}.history-nav-btn{padding:8px 9px;font-size:.78rem}}
'''

UX_CONTROLS = r'''<div class="history-ux-bar"><div class="hint"><strong>Easy explore:</strong> hover a line or coin chip to highlight it · click to focus one asset · Shift-click to build a comparison.</div><button id="history-pan-left" class="history-nav-btn" type="button" title="Move the zoomed window earlier">◀ EARLIER</button><button id="history-zoom-out" class="history-nav-btn" type="button">− ZOOM OUT</button><span id="history-zoom-status" class="history-zoom-status">FULL RANGE</span><button id="history-zoom-in" class="history-nav-btn" type="button">+ ZOOM IN</button><button id="history-pan-right" class="history-nav-btn" type="button" title="Move the zoomed window later">LATER ▶</button><button id="history-reset-view" class="history-nav-btn" type="button">RESET VIEW</button></div><div class="history-chart-help"><span><strong>Hover:</strong> identifies the nearest crypto line</span><span><strong>Click:</strong> focuses that crypto</span><span><strong>Shift-click:</strong> compares multiple cryptos</span><span><strong>Auto scale:</strong> prevents extreme winners from flattening every other line</span></div>'''


def main() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")

    if STYLE_MARKER not in text:
        if "</style>" not in text:
            raise SystemExit("Cannot add history UX styles: </style> not found")
        text = text.replace("</style>", UX_CSS + "\n</style>", 1)
        print("[APPLY] history UX styles")
    else:
        print("[SKIP] history UX styles")

    start = text.find('<section class="card history-card">')
    if start < 0:
        raise SystemExit("Cannot move history section: history-card section not found. Run the full-history patch first.")
    end_marker = "\n\n{% set live=crypto.live_v2 %}"
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit("Cannot move history section: expected live-state marker not found after history section")

    section = text[start:end]
    if CONTROL_MARKER not in section:
        legend_anchor = '<div id="history-legend" class="history-legend"></div>'
        if legend_anchor not in section:
            raise SystemExit("Cannot add history controls: legend anchor not found")
        section = section.replace(legend_anchor, UX_CONTROLS + legend_anchor, 1)
        print("[APPLY] user-friendly history controls")
    else:
        print("[SKIP] user-friendly history controls")

    # Remove the original section from its position below Live Market Pulse.
    text = text[:start] + text[end:]

    # Insert immediately below the three navigation tabs, making history the first dashboard block.
    nav_anchor = '</nav>\n\n'
    nav_pos = text.find(nav_anchor)
    if nav_pos < 0:
        raise SystemExit("Cannot move history section: navigation anchor not found")
    insert_at = nav_pos + len(nav_anchor)
    text = text[:insert_at] + section + "\n\n" + text[insert_at:]
    print("[APPLY] move Full Crypto Market History above Live Market Pulse")

    TEMPLATE.write_text(text, encoding="utf-8")
    print("Crypto Visual history usability patch complete.")
    print("Presentation only; historical archive, live feed, frozen research, journals, and brokerage settings are unchanged.")


if __name__ == "__main__":
    main()
