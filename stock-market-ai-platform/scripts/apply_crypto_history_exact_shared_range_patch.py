#!/usr/bin/env python3
"""Finish Crypto Visual shared-history loading against the current local JS shape.

This is a presentation/loading optimization only. It does not alter the
historical archive, model inputs, frozen policies, journals, or brokerage
settings.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "webapp/static/js/crypto_history_chart.js"

text = JS.read_text()


def replace_exact(old: str, new: str, label: str) -> None:
    global text
    if new in text:
        print(f"[SKIP] {label}")
        return
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: exact current code not found")
    text = text.replace(old, new, 1)
    print(f"[APPLY] {label}")


replace_exact(
    """  async function loadHistory(){\n    const status=document.getElementById('history-load-status');\n    try{const r=await fetch('/api/crypto-history?range=90D',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error(`HTTP ${r.status}`);historical=await r.json();if(status)status.textContent='HISTORY LOADED';renderAll();}\n    catch(err){if(status){status.textContent='HISTORY ERROR';status.className='negative';}console.warn('[CRYPTO HISTORY]',err);}\n  }\n""",
    """  async function loadHistory(){\n    const status=document.getElementById('history-load-status');\n    try{\n      if(status)status.textContent='LOADING 90D';\n      historical=await window.DataShepherdCryptoHistory.load('90D');\n      range='90D';\n      if(status){status.textContent='HISTORY LOADED';status.className='mode';}\n      renderAll();\n    }\n    catch(err){if(status){status.textContent='HISTORY ERROR';status.className='negative';}console.warn('[CRYPTO HISTORY]',err);}\n  }\n""",
    "Full History initial load uses shared 90D request",
)

replace_exact(
    """  document.querySelectorAll('[data-history-range]').forEach(b=>b.addEventListener('click',()=>{range=b.dataset.historyRange;zoomLevel=1;panOffset=0;renderAll();}));\n""",
    """  document.querySelectorAll('[data-history-range]').forEach(b=>b.addEventListener('click',async()=>{\n    const nextRange=b.dataset.historyRange;\n    if(!nextRange||nextRange===range)return;\n    const status=document.getElementById('history-load-status');\n    try{\n      if(status)status.textContent=`LOADING ${nextRange}`;\n      const nextPayload=await window.DataShepherdCryptoHistory.load(nextRange);\n      historical=nextPayload;\n      range=nextRange;\n      zoomLevel=1;\n      panOffset=0;\n      if(status){status.textContent='HISTORY LOADED';status.className='mode';}\n      renderAll();\n    }catch(err){\n      if(status){status.textContent='HISTORY ERROR';status.className='negative';}\n      console.warn('[CRYPTO HISTORY RANGE]',nextRange,err);\n    }\n  }));\n""",
    "range buttons lazy-load selected history window",
)

replace_exact(
    """  document.getElementById('history-reset-view')?.addEventListener('click',()=>{range='ALL';mode='normalized';showAll=true;selected=new Set(['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD']);zoomLevel=1;panOffset=0;hoverSymbol=null;renderAll();});\n""",
    """  document.getElementById('history-reset-view')?.addEventListener('click',async()=>{\n    const status=document.getElementById('history-load-status');\n    try{\n      if(status)status.textContent='LOADING 90D';\n      historical=await window.DataShepherdCryptoHistory.load('90D');\n      range='90D';\n      mode='normalized';\n      showAll=true;\n      selected=new Set(['BTC-USD','ETH-USD','XRP-USD','SOL-USD','ADA-USD']);\n      zoomLevel=1;\n      panOffset=0;\n      hoverSymbol=null;\n      if(status){status.textContent='HISTORY LOADED';status.className='mode';}\n      renderAll();\n    }catch(err){\n      if(status){status.textContent='HISTORY ERROR';status.className='negative';}\n      console.warn('[CRYPTO HISTORY RESET]',err);\n    }\n  });\n""",
    "Reset View returns to cached 90D default",
)

JS.write_text(text)

print("Crypto Visual exact shared-range patch complete.")
print("Full History and Relationships now share the initial 90D promise.")
print("30D/1Y/3Y/5Y/ALL are fetched only when selected and cached by the shared loader.")
print("Reset View returns to the fast 90D default.")
