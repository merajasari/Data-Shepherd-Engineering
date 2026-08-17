#!/usr/bin/env python3
"""Apply range-aware lazy loading to the Crypto Visual historical chart.

Presentation/read-only optimization only. The authoritative 15-minute archive,
model inputs, frozen policies, journals, and brokerage settings are unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "webapp/services/crypto_history_service.py"
APP = ROOT / "webapp/app.py"
JS = ROOT / "webapp/static/js/crypto_history_chart.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"[SKIP] {label}")
        return text
    if old not in text:
        raise SystemExit(f"Cannot apply {label}: expected text not found")
    print(f"[APPLY] {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1) Server: let the history payload return only the requested time window,
# while preserving full-archive metadata for the dashboard summary.
# ---------------------------------------------------------------------------
service = SERVICE.read_text()

service = replace_once(
    service,
    'def get_crypto_history_payload(products: Iterable[str] | None = None) -> dict:\n',
    '''HISTORY_RANGE_DAYS = {\n    "30D": 30,\n    "90D": 90,\n    "1Y": 365,\n    "3Y": 3 * 365,\n    "5Y": 5 * 365,\n    "ALL": None,\n}\n\n\ndef _normalize_range_key(range_key: str | None) -> str:\n    key = str(range_key or "1Y").upper().strip()\n    return key if key in HISTORY_RANGE_DAYS else "1Y"\n\n\ndef _slice_daily_for_range(daily: pd.DataFrame, range_key: str) -> pd.DataFrame:\n    days = HISTORY_RANGE_DAYS[range_key]\n    if daily.empty or days is None:\n        return daily\n    end = daily["timestamp_utc"].max()\n    cutoff = end - pd.Timedelta(days=days)\n    return daily[daily["timestamp_utc"] >= cutoff].copy()\n\n\ndef get_crypto_history_payload(\n    products: Iterable[str] | None = None,\n    range_key: str | None = "1Y",\n) -> dict:\n''',
    "range-aware history service",
)

service = replace_once(
    service,
    '''    series = {}\n    global_start = None\n    global_end = None\n    total_points = 0\n\n    for product_id in requested:\n        daily = _daily_product(product_id)\n''',
    '''    range_key = _normalize_range_key(range_key)\n    series = {}\n    global_start = None\n    global_end = None\n    archive_total_points = 0\n    loaded_total_points = 0\n\n    for product_id in requested:\n        full_daily = _daily_product(product_id)\n        archive_total_points += len(full_daily)\n        daily = _slice_daily_for_range(full_daily, range_key)\n''',
    "range slicing and archive counters",
)

service = replace_once(
    service,
    '''        total_points += len(points)\n        series[product_id] = {\n''',
    '''        loaded_total_points += len(points)\n        series[product_id] = {\n''',
    "loaded point counter",
)

service = replace_once(
    service,
    '''        "product_count": len(requested),\n        "total_chart_points": total_points,\n        "global_start_utc": global_start.isoformat() if global_start is not None else None,\n''',
    '''        "product_count": len(requested),\n        "requested_range": range_key,\n        "total_chart_points": loaded_total_points,\n        "loaded_chart_points": loaded_total_points,\n        "archive_total_chart_points": archive_total_points,\n        "global_start_utc": global_start.isoformat() if global_start is not None else None,\n''',
    "history range metadata",
)

SERVICE.write_text(service)


# ---------------------------------------------------------------------------
# 2) Flask route: accept ?range=1Y / 3Y / 5Y / ALL.
# ---------------------------------------------------------------------------
app = APP.read_text()
app = replace_once(
    app,
    '''def api_crypto_history():\n    return jsonify(get_crypto_history_payload())\n''',
    '''def api_crypto_history():\n    range_key = request.args.get("range", "1Y")\n    return jsonify(get_crypto_history_payload(range_key=range_key))\n''',
    "range-aware crypto history API",
)
APP.write_text(app)


# ---------------------------------------------------------------------------
# 3) Browser: initial request is 1Y. Cache fetched ranges in memory. Longer
# ranges are requested only when selected.
# ---------------------------------------------------------------------------
js = JS.read_text()

js = replace_once(
    js,
    "  let historical = null;\n  let liveQuotes = {};\n",
    '''  let historical = null;\n  const historyRangeCache = new Map();\n  let historyFetchToken = 0;\n  let liveQuotes = {};\n''',
    "browser range cache state",
)

# Existing init fetch: make the common page-load request explicitly 1Y.
if "/api/crypto-history?range=1Y" not in js:
    if "fetch('/api/crypto-history')" in js:
        js = js.replace("fetch('/api/crypto-history')", "fetch('/api/crypto-history?range=1Y')", 1)
        print("[APPLY] initial 1Y history request")
    elif 'fetch("/api/crypto-history")' in js:
        js = js.replace('fetch("/api/crypto-history")', 'fetch("/api/crypto-history?range=1Y")', 1)
        print("[APPLY] initial 1Y history request")
    else:
        raise SystemExit("Cannot apply initial 1Y history request: history fetch not found")
else:
    print("[SKIP] initial 1Y history request")

# Add lazy fetch helper before rangeStart().
helper_marker = "  function rangeStart(endMs) {\n"
helper = '''  async function loadHistoryRange(rangeKey) {\n    const key=String(rangeKey||'1Y').toUpperCase();\n    if(historyRangeCache.has(key)) {\n      historical=historyRangeCache.get(key);\n      return historical;\n    }\n    const token=++historyFetchToken;\n    const state=document.getElementById('history-load-state');\n    if(state) state.textContent=`LOADING ${key}…`;\n    const response=await fetch(`/api/crypto-history?range=${encodeURIComponent(key)}`, {cache:'no-store'});\n    if(!response.ok) throw new Error(`history ${key} HTTP ${response.status}`);\n    const payload=await response.json();\n    if(token!==historyFetchToken) return null;\n    historyRangeCache.set(key,payload);\n    historical=payload;\n    if(state) state.textContent='HISTORY LOADED';\n    return payload;\n  }\n\n'''
if "async function loadHistoryRange(rangeKey)" not in js:
    if helper_marker not in js:
        raise SystemExit("Cannot add lazy range loader: rangeStart marker not found")
    js = js.replace(helper_marker, helper + helper_marker, 1)
    print("[APPLY] lazy history range loader")
else:
    print("[SKIP] lazy history range loader")

# Preserve archive-wide point count in the summary even when only 1Y is loaded.
js = replace_once(
    js,
    "    set('history-points',historical.total_chart_points?.toLocaleString()||'0');\n",
    "    set('history-points',(historical.archive_total_chart_points ?? historical.total_chart_points)?.toLocaleString()||'0');\n",
    "archive point-count summary",
)

# Replace the range-button listener structurally. The original listener may span
# one or several physical lines, so use a conservative regex bounded by the
# next mode-button listener.
if "await loadHistoryRange(nextRange)" not in js:
    pattern = re.compile(
        r"  document\.querySelectorAll\('\[data-history-range\]'\)\.forEach\(btn=>btn\.addEventListener\('click',[\s\S]*?\n  document\.querySelectorAll\('\[data-history-mode\]'\)",
        re.MULTILINE,
    )
    match = pattern.search(js)
    if not match:
        raise SystemExit("Cannot apply lazy range switching: range-button listener block not found")
    replacement = '''  document.querySelectorAll('[data-history-range]').forEach(btn=>btn.addEventListener('click',async()=>{\n    const nextRange=btn.dataset.historyRange;\n    if(!nextRange) return;\n    range=nextRange;\n    zoomLevel=1;\n    panOffset=0;\n    document.querySelectorAll('[data-history-range]').forEach(b=>b.classList.toggle('active',b===btn));\n    try {\n      if(!historyRangeCache.has(nextRange)) await loadHistoryRange(nextRange);\n      else historical=historyRangeCache.get(nextRange);\n      renderAll();\n    } catch(err) {\n      console.error('Crypto history range load failed',err);\n      const state=document.getElementById('history-load-state');\n      if(state) state.textContent='HISTORY LOAD FAILED';\n    }\n  }));\n  document.querySelectorAll('[data-history-mode]')'''
    js = js[:match.start()] + replacement + js[match.end():]
    print("[APPLY] lazy range switching")
else:
    print("[SKIP] lazy range switching")

# Seed the 1Y cache after the existing initial history assignment. Handle the
# common `historical=...` spellings without depending on the whole init block.
if "historyRangeCache.set('1Y',historical)" not in js:
    candidates = [
        "historical=await historyResponse.json();",
        "historical = await historyResponse.json();",
        "historical=await response.json();",
        "historical = await response.json();",
    ]
    seeded = False
    for old in candidates:
        if old in js:
            js = js.replace(old, old + "\n    historyRangeCache.set('1Y',historical);", 1)
            seeded = True
            break
    if seeded:
        print("[APPLY] seed initial 1Y browser cache")
    else:
        # Fallback: first assignment from a parsed history fetch.
        m = re.search(r"historical\s*=\s*await\s+[^;]+\.json\(\);", js)
        if not m:
            raise SystemExit("Cannot seed 1Y history cache: initial history assignment not found")
        old = m.group(0)
        js = js[:m.start()] + old + "\n    historyRangeCache.set('1Y',historical);" + js[m.end():]
        print("[APPLY] seed initial 1Y browser cache")
else:
    print("[SKIP] seed initial 1Y browser cache")

JS.write_text(js)

print("Crypto Visual lazy history loading patch complete.")
print("Initial history payload is 1Y only; 3Y/5Y/ALL load on demand and cache in the page.")
print("Read-only optimization; archive contents, models, policies, journals, and brokerage settings are unchanged.")
