#!/usr/bin/env python3
"""Finish Crypto Visual shared/lazy history loading.

Read-only presentation optimization. Full History and Relationship Explorer share
one 90D initial payload. Longer history ranges load only when selected and are
cached by window.DataShepherdCryptoHistory for the page session.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "webapp/static/js/crypto_history_chart.js"
TEMPLATE = ROOT / "webapp/templates/crypto_visual.html"

js = JS.read_text()
template = TEMPLATE.read_text()

if "window.DataShepherdCryptoHistory" not in template:
    raise SystemExit("Shared DataShepherdCryptoHistory loader is missing from crypto_visual.html")

# ---------------------------------------------------------------------------
# 1) Initial Full History load: consume the exact same shared 90D promise used
# by the relationship explorer instead of issuing a second HTTP request.
# ---------------------------------------------------------------------------
if "historical=await window.DataShepherdCryptoHistory.load('90D')" not in js:
    exact = "try{const r=await fetch('/api/crypto-history?range=90D',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);historical=await r.json();if(status)status.textContent='HISTORY LOADED';renderAll();}"
    replacement = "try{historical=await window.DataShepherdCryptoHistory.load('90D');if(status)status.textContent='HISTORY LOADED';renderAll();}"
    if exact in js:
        js = js.replace(exact, replacement, 1)
    else:
        # Conservative regex fallback for spacing differences.
        pattern = re.compile(
            r"try\s*\{\s*const\s+r\s*=\s*await\s+fetch\('/api/crypto-history\?range=90D'\s*,\s*\{[^}]*\}\)\s*;\s*"
            r"if\s*\(!r\.ok\)\s*throw\s+new\s+Error\(`HTTP \$\{r\.status\}`\)\s*;\s*"
            r"historical\s*=\s*await\s+r\.json\(\)\s*;",
            re.MULTILINE,
        )
        m = pattern.search(js)
        if not m:
            raise SystemExit("Cannot replace Full History direct 90D fetch")
        js = js[:m.start()] + "try{historical=await window.DataShepherdCryptoHistory.load('90D');" + js[m.end():]
    print("[APPLY] Full History reuses shared 90D payload")
else:
    print("[SKIP] Full History already uses shared 90D payload")

# ---------------------------------------------------------------------------
# 2) Add one helper for range changes. The shared loader already memoizes each
# requested range, so returning to a previously viewed range does not refetch.
# ---------------------------------------------------------------------------
helper = '''\n  async function loadSharedHistoryRange(nextRange) {\n    const key=String(nextRange||'90D').toUpperCase();\n    const status=document.getElementById('history-load-status');\n    if(status) status.textContent=`LOADING ${key}`;\n    historical=await window.DataShepherdCryptoHistory.load(key);\n    if(status) status.textContent='HISTORY LOADED';\n    return historical;\n  }\n\n'''
if "async function loadSharedHistoryRange(nextRange)" not in js:
    markers = [
        "  function rangeStart(endMs) {\n",
        "  function renderMetrics() {\n",
        "  function renderAll()",
    ]
    inserted = False
    for marker in markers:
        if marker in js:
            js = js.replace(marker, helper + marker, 1)
            inserted = True
            break
    if not inserted:
        raise SystemExit("Cannot insert shared range helper: no stable marker found")
    print("[APPLY] shared lazy range helper")
else:
    print("[SKIP] shared lazy range helper")

# ---------------------------------------------------------------------------
# 3) Range controls: replace the current range listener with an async loader.
# This guarantees ALL/5Y/3Y/1Y fetch their actual server slice rather than
# merely filtering whatever 90D data happened to be loaded initially.
# ---------------------------------------------------------------------------
if "await loadSharedHistoryRange(nextRange)" not in js:
    pattern = re.compile(
        r"  document\.querySelectorAll\('\[data-history-range\]'\)\.forEach\(btn=>btn\.addEventListener\('click',[\s\S]*?\n"
        r"  document\.querySelectorAll\('\[data-history-mode\]'\)",
        re.MULTILINE,
    )
    m = pattern.search(js)
    if not m:
        raise SystemExit("Cannot patch history range controls: listener block not found")
    replacement = '''  document.querySelectorAll('[data-history-range]').forEach(btn=>btn.addEventListener('click',async()=>{\n    const nextRange=String(btn.dataset.historyRange||'90D').toUpperCase();\n    range=nextRange;\n    zoomLevel=1;\n    panOffset=0;\n    document.querySelectorAll('[data-history-range]').forEach(b=>b.classList.toggle('active',b===btn));\n    try {\n      await loadSharedHistoryRange(nextRange);\n      renderAll();\n    } catch(err) {\n      console.error('Crypto history range load failed',err);\n      const status=document.getElementById('history-load-status');\n      if(status) status.textContent='HISTORY LOAD FAILED';\n    }\n  }));\n  document.querySelectorAll('[data-history-mode]')'''
    js = js[:m.start()] + replacement + js[m.end():]
    print("[APPLY] cache-aware lazy range controls")
else:
    print("[SKIP] cache-aware lazy range controls")

JS.write_text(js)

print("Crypto Visual final shared history-loader patch complete.")
print("Initial Full History + Relationships now share one 90D request.")
print("30D/1Y/3Y/5Y/ALL load only when selected and remain cached for the page session.")
print("No model, journal, frozen-policy, research, or brokerage behavior is changed.")
