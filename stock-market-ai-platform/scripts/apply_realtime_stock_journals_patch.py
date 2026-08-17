"""Apply near-real-time V4 and V4/V5/SPY diagnostic journal collection.

Presentation/diagnostic only. Does not alter portfolio state, frozen models,
official V5 holdout evidence, or brokerage settings.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(rel, text):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print(f"[APPLY] {rel}")


write("webapp/services/v4_realtime_equity_journal_service.py", r'''"""Append-only near-real-time V4 mark-to-market equity journal."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from webapp.services.paper_trading_service import get_pnl_attribution, get_portfolio_summary

JOURNAL_DIR = Path("data/paper_trading")
JOURNAL_PATH = JOURNAL_DIR / "realtime_equity_journal.jsonl"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(rows):
    payload = [
        {
            "symbol": r.get("symbol"),
            "current_price": r.get("current_price"),
            "quote_timestamp": r.get("quote_timestamp"),
            "price_source": r.get("price_source"),
        }
        for r in sorted(rows, key=lambda x: str(x.get("symbol")))
    ]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_last():
    if not JOURNAL_PATH.exists():
        return None
    last = None
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def build_observation():
    summary = get_portfolio_summary()
    attribution = get_pnl_attribution()
    positions = list(attribution.get("positions") or [])
    return {
        "timestamp": _utc_now(),
        "equity": float(summary.get("equity") or 0.0),
        "cash": float(summary.get("cash") or 0.0),
        "market_value": float(summary.get("market_value") or 0.0),
        "realized_pnl": float(summary.get("realized_pnl") or 0.0),
        "unrealized_pnl": float(summary.get("unrealized_pnl") or 0.0),
        "total_return_pct": float(summary.get("total_return_pct") or 0.0),
        "quote_fingerprint": _fingerprint(positions),
        "quote_sources": sorted({str(r.get("price_source")) for r in positions}),
        "journal_type": "V4_REALTIME_MARK_TO_MARKET",
        "portfolio_state_modified": False,
        "brokerage_orders": False,
    }


def append_realtime_equity_observation(skip_duplicate_quotes=True):
    observation = build_observation()
    last = _read_last()
    if skip_duplicate_quotes and last and last.get("quote_fingerprint") == observation.get("quote_fingerprint"):
        return {"status": "skipped_duplicate_quotes", "timestamp": observation["timestamp"]}
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(observation, sort_keys=True) + "\n")
    return {
        "status": "appended",
        "timestamp": observation["timestamp"],
        "equity": observation["equity"],
        "journal_path": str(JOURNAL_PATH),
    }


def get_v4_realtime_equity_history():
    if not JOURNAL_PATH.exists():
        return []
    rows = []
    with JOURNAL_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("timestamp")
            eq = row.get("equity")
            if ts is None or eq is None:
                continue
            rows.append({"timestamp": ts, "equity": float(eq), "realtime_mark": True})
    return rows
''')

write("ml/run_realtime_stock_journals.py", r'''"""Continuously collect near-real-time stock diagnostic journal snapshots."""
from __future__ import annotations

import json
import signal
import time

from webapp.services.v4_realtime_equity_journal_service import append_realtime_equity_observation
from webapp.services.v5_shadow_comparison_journal_service import append_comparison_observation

POLL_SECONDS = 5.0
_running = True


def _stop(_sig, _frame):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("REAL-TIME STOCK DIAGNOSTIC JOURNALS", flush=True)
    print("Polling every 5 seconds; unchanged quote fingerprints are skipped.", flush=True)
    print("No portfolio writes, official holdout writes, or brokerage orders.", flush=True)
    while _running:
        try:
            v4 = append_realtime_equity_observation(skip_duplicate_quotes=True)
            comp = append_comparison_observation(skip_duplicate_quotes=True)
            if v4.get("status") == "appended" or comp.get("status") == "appended":
                print(json.dumps({"v4": v4, "comparison": comp}, sort_keys=True), flush=True)
        except Exception as exc:
            print(f"[REALTIME STOCK JOURNAL ERROR] {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
''')

write("scripts/install_realtime_stock_journals_launchagent.sh", r'''#!/bin/zsh
set -euo pipefail
PROJECT_ROOT="${HOME}/Data-Shepherd-Engineering/stock-market-ai-platform"
PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then PYTHON="$(command -v python3)"; fi
LABEL="com.datashepherd.realtimestockjournals"
OLD_LABEL="com.datashepherd.v5shadowcomparisonjournal"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${HOME}/Library/Logs/DataShepherd"
mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents"

# Retire the old hourly comparison scheduler; the continuous collector replaces it.
launchctl bootout "gui/$(id -u)/${OLD_LABEL}" 2>/dev/null || true

cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${LABEL}</string>
<key>ProgramArguments</key><array><string>${PYTHON}</string><string>-m</string><string>ml.run_realtime_stock_journals</string></array>
<key>WorkingDirectory</key><string>${PROJECT_ROOT}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>5</integer>
<key>StandardOutPath</key><string>${LOG_DIR}/realtimestockjournals.out.log</string>
<key>StandardErrorPath</key><string>${LOG_DIR}/realtimestockjournals.err.log</string>
</dict></plist>
EOF
plutil -lint "${PLIST}"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"
sleep 1

echo "===== REAL-TIME STOCK JOURNALS ====="
launchctl print "gui/$(id -u)/${LABEL}" | grep -E 'state =|runs =|pid =|last exit code' || true
echo
echo "Cadence: 5 seconds while quotes change; duplicate quote snapshots are skipped"
echo "V4 journal: ${PROJECT_ROOT}/data/paper_trading/realtime_equity_journal.jsonl"
echo "Comparison journal: ${PROJECT_ROOT}/data/paper_trading/v5_shadow/comparison_journal.jsonl"
echo "Official Sep 1+ V5 holdout remains untouched"
''')

# Patch app.py so Portfolio Equity Over Time includes persisted real-time marks.
app = ROOT / "webapp/app.py"
text = app.read_text(encoding="utf-8")
import_line = "from webapp.services.v5_shadow_history_service import get_v5_shadow_history  # noqa: E402\n"
new_import = import_line + "from webapp.services.v4_realtime_equity_journal_service import get_v4_realtime_equity_history  # noqa: E402\n"
if "get_v4_realtime_equity_history" not in text:
    if import_line not in text:
        raise SystemExit("Cannot patch app.py import: anchor not found")
    text = text.replace(import_line, new_import, 1)
    print("[APPLY] app.py real-time V4 history import")

old = '    history = list(forward.get("equity_history", []))\n'
new = '''    history = list(forward.get("equity_history", []))
    history.extend(get_v4_realtime_equity_history())
    history.sort(key=lambda row: str(row.get("timestamp") or ""))
'''
if new not in text:
    if old not in text:
        raise SystemExit("Cannot patch app.py chart history: anchor not found")
    text = text.replace(old, new, 1)
    print("[APPLY] Portfolio Equity chart includes persisted near-real-time marks")
app.write_text(text, encoding="utf-8")

# Upgrade comparison history dashboard refresh from 60 seconds to 5 seconds.
js = ROOT / "webapp/static/js/v5_shadow_history_chart.js"
text = js.read_text(encoding="utf-8")
text = text.replace("'1 OBSERVATION · MORE HISTORY WILL APPEAR HOURLY'", "'1 OBSERVATION · REAL-TIME HISTORY ACTIVE'")
text = text.replace("window.setInterval(load,60000);", "window.setInterval(load,5000);")
js.write_text(text, encoding="utf-8")
print("[APPLY] V4/V5/SPY history chart refreshes every 5 seconds")

# Upgrade current local interactive V4 chart to refresh from persisted marks every 5 sec,
# but do not redraw while the user is actively moving the pointer.
v4js = ROOT / "webapp/static/js/v4_equity_chart.js"
if v4js.exists():
    text = v4js.read_text(encoding="utf-8")
    if "let pointerActive = false;" not in text and "let geometry = null;" in text:
        text = text.replace("  let geometry = null;", "  let geometry = null;\n  let pointerActive = false;", 1)
    if "overlay.addEventListener('pointerenter'" not in text and "overlay.addEventListener('pointermove',selectFromEvent);" in text:
        text = text.replace(
            "    overlay.addEventListener('pointermove',selectFromEvent);",
            "    overlay.addEventListener('pointerenter',()=>{pointerActive=true;});\n    overlay.addEventListener('pointermove',selectFromEvent);",
            1,
        )
    old_leave = "    overlay.addEventListener('pointerleave',()=>{tooltip.style.display='none';});"
    new_leave = "    overlay.addEventListener('pointerleave',()=>{pointerActive=false;tooltip.style.display='none';});"
    text = text.replace(old_leave, new_leave)
    marker = "  if('requestIdleCallback' in window) requestIdleCallback(startLoad,{timeout:700}); else setTimeout(startLoad,80);"
    realtime = marker + "\n  window.setInterval(()=>{if(!pointerActive) startLoad();},5000);"
    if "window.setInterval(()=>{if(!pointerActive) startLoad();},5000);" not in text:
        if marker not in text:
            print("[INFO] V4 interactive chart refresh anchor not found; collector still installed")
        else:
            text = text.replace(marker, realtime, 1)
            print("[APPLY] Portfolio Equity chart refreshes every 5 seconds when not being inspected")
    v4js.write_text(text, encoding="utf-8")

print()
print("Near-real-time stock journal patch complete.")
print("Collection cadence: 5 seconds while quote fingerprints change.")
print("Both V4 equity history and V4/V5/SPY comparison history are persisted near-real-time.")
print("No V4 portfolio state, frozen V5 model, official Sep 1+ holdout, or brokerage settings are changed.")
