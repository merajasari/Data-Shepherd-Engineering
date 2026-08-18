"""Apply V8 frozen holdout runner, append-only journal, and dashboard monitoring."""

from pathlib import Path

EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"

FILES = {
"ml/v8/holdout_runner.py": r'''"""V8 frozen forward-holdout runner.

This runner is operational infrastructure around the already-frozen V8 spec.
It refuses to run evidence collection unless the exact frozen SHA is present.
Before 2026-09-01 UTC it writes no holdout journal evidence.

Journal policy: append-only JSONL events (DECISION / ENTRY / EXIT). Duplicate
events are skipped deterministically. No strategy parameters are tuned here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
TOP_N = 10
HOLD_SESSIONS = 5
COST_BPS = 10

ROOT = Path("data/model/v8")
FREEZE_ROOT = ROOT / "phase7"
SPEC_PATH = FREEZE_ROOT / "frozen_candidate_spec.json"
LOCK_PATH = FREEZE_ROOT / "frozen_candidate.sha256"
PHASE1_PANEL = ROOT / "phase1" / "orthogonal_signal_panel.parquet"
FEATURE_ROOT = Path("data/features/stocks")
HOLDOUT_ROOT = ROOT / "holdout"
JOURNAL_PATH = HOLDOUT_ROOT / "journal.jsonl"
STATUS_PATH = HOLDOUT_ROOT / "status.json"


def _verify_freeze():
    if not SPEC_PATH.exists() or not LOCK_PATH.exists():
        raise FileNotFoundError("V8 Phase-7 frozen spec/lock missing; run Phase 7 first")
    spec = json.loads(SPEC_PATH.read_text())
    spec_sha = str(spec.get("spec_sha256", ""))
    lock_sha = LOCK_PATH.read_text().strip().split()[0]
    if spec_sha != EXPECTED_SHA or lock_sha != EXPECTED_SHA:
        raise RuntimeError(
            f"Frozen V8 SHA mismatch. expected={EXPECTED_SHA} spec={spec_sha} lock={lock_sha}"
        )
    # Contract invariants: fail closed if any frozen rule differs.
    checks = [
        spec.get("candidate_id") == "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        spec.get("signal", {}).get("raw_feature") == "distance_from_low_20d",
        spec.get("signal", {}).get("neutralization", {}).get("controls") == ["volatility_20d", "beta_60"],
        spec.get("portfolio_contract", {}).get("top_n") == TOP_N,
        spec.get("portfolio_contract", {}).get("weighting") == "equal_weight",
        spec.get("decision_execution_contract", {}).get("holding_sessions") == HOLD_SESSIONS,
        spec.get("decision_execution_contract", {}).get("cohort_offsets") == [0, 1, 2, 3, 4],
        spec.get("cost_contract", {}).get("primary_cost_bps_per_dollar_traded") == COST_BPS,
    ]
    if not all(checks):
        raise RuntimeError("Frozen V8 specification does not match the registered operational contract")
    return spec


def _feature_files():
    out = {}
    for p in sorted(FEATURE_ROOT.glob("*/*.parquet")):
        out.setdefault(p.parent.name.upper(), p)
    return out


def _load_symbol_frame(path):
    d = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in d.columns else "timestamp"
    required = {ts_col, "open", "close"}
    if not required.issubset(d.columns):
        raise ValueError(f"{path} missing timestamp/open/close")
    x = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(d[ts_col], utc=True),
        "open": pd.to_numeric(d["open"], errors="coerce"),
        "close": pd.to_numeric(d["close"], errors="coerce"),
    }).sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    x["ret1"] = x["close"].pct_change()
    x["volatility_20d"] = x["ret1"].rolling(20, min_periods=20).std()
    low20 = x["close"].rolling(20, min_periods=20).min()
    x["distance_from_low_20d"] = x["close"] / low20 - 1.0
    return x.set_index("timestamp_utc")


def _universe():
    if not PHASE1_PANEL.exists():
        raise FileNotFoundError(f"Missing frozen-development universe source: {PHASE1_PANEL}")
    p = pd.read_parquet(PHASE1_PANEL, columns=["symbol"])
    symbols = sorted(set(p["symbol"].astype(str).str.upper()) - {"SPY"})
    if len(symbols) != 100:
        raise RuntimeError(f"Expected frozen V8 universe of 100 stocks; found {len(symbols)}")
    return symbols


def _load_market():
    files = _feature_files()
    symbols = _universe()
    missing = sorted(set(symbols + ["SPY"]) - set(files))
    if missing:
        raise FileNotFoundError("Missing stock feature files: " + ", ".join(missing))
    frames = {s: _load_symbol_frame(files[s]) for s in symbols + ["SPY"]}
    spy = frames["SPY"].copy()
    trading_dates = list(spy.index[spy["close"].notna()])
    date_to_idx = {ts: i for i, ts in enumerate(trading_dates)}
    return symbols, frames, trading_dates, date_to_idx


def _beta60(stock_ret, spy_ret, ts):
    joined = pd.concat([stock_ret.rename("s"), spy_ret.rename("m")], axis=1).loc[:ts].dropna().tail(60)
    if len(joined) < 40:
        return np.nan
    var = float(joined["m"].var())
    if not np.isfinite(var) or var <= 0:
        return np.nan
    return float(joined["s"].cov(joined["m"]) / var)


def _rank_for_date(ts, symbols, frames):
    spy_ret = frames["SPY"]["ret1"]
    rows = []
    for sym in symbols:
        f = frames[sym]
        if ts not in f.index:
            continue
        row = f.loc[ts]
        raw = row["distance_from_low_20d"]
        vol = row["volatility_20d"]
        beta = _beta60(f["ret1"], spy_ret, ts)
        if not (np.isfinite(raw) and np.isfinite(vol) and np.isfinite(beta)):
            continue
        rows.append((sym, float(raw), float(vol), float(beta)))
    if len(rows) < 80:
        raise RuntimeError(f"Only {len(rows)} eligible V8 names on {ts}; refusing decision")
    d = pd.DataFrame(rows, columns=["symbol", "raw", "volatility_20d", "beta_60"])
    X = np.column_stack([np.ones(len(d)), d["volatility_20d"], d["beta_60"]])
    y = d["raw"].to_numpy(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    d["orthogonal_signal"] = y - X @ coef
    d = d.sort_values(["orthogonal_signal", "symbol"], ascending=[False, True]).reset_index(drop=True)
    return d


def _read_events():
    rows = []
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _event_key(e):
    return (e.get("event_type"), e.get("decision_timestamp_utc"), e.get("cohort_offset"))


def _append(e, existing):
    key = _event_key(e)
    if key in existing:
        return False
    HOLDOUT_ROOT.mkdir(parents=True, exist_ok=True)
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(e, sort_keys=True) + "\n")
    existing.add(key)
    return True


def _transition_notional(previous, new):
    nw = {s: 1.0 / TOP_N for s in new}
    if previous is None:
        return 1.0
    ow = {s: 1.0 / TOP_N for s in previous}
    return float(sum(abs(nw.get(s, 0.0) - ow.get(s, 0.0)) for s in set(nw) | set(ow)))


def _status(payload):
    HOLDOUT_ROOT.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["frozen_sha256"] = EXPECTED_SHA
    STATUS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main():
    _verify_freeze()
    now = pd.Timestamp.now(tz="UTC")
    if now < HOLDOUT_START:
        _status({"status": "WAITING_FOR_HOLDOUT", "holdout_start_utc": HOLDOUT_START.isoformat(), "journal_written": False})
        print("V8 FROZEN HOLDOUT MONITOR")
        print("=" * 88)
        print(f"Status: WAITING_FOR_HOLDOUT | starts {HOLDOUT_START.isoformat()}")
        print(f"Frozen SHA: {EXPECTED_SHA}")
        print("No holdout journal evidence written before boundary.")
        return

    symbols, frames, dates, date_to_idx = _load_market()
    available = [d for d in dates if d >= HOLDOUT_START and d <= now.normalize()]
    if not available:
        _status({"status": "WAITING_FOR_FIRST_COMPLETED_SESSION", "holdout_start_utc": HOLDOUT_START.isoformat(), "journal_written": False})
        print("No completed holdout session is available yet.")
        return

    events = _read_events()
    existing = {_event_key(e) for e in events}
    appended = 0

    # 1) Append every newly available decision in chronological order.
    for decision_ts in available:
        i = date_to_idx[decision_ts]
        if i + 1 >= len(dates):
            continue  # next open not available in market data yet
        cohort = int(i % HOLD_SESSIONS)
        key = ("DECISION", decision_ts.isoformat(), cohort)
        if key in existing:
            continue
        ranking = _rank_for_date(decision_ts, symbols, frames)
        picks = ranking.head(TOP_N)["symbol"].tolist()
        entry_ts = dates[i + 1]
        exit_ts = dates[i + 1 + HOLD_SESSIONS] if i + 1 + HOLD_SESSIONS < len(dates) else None
        e = {
            "event_type": "DECISION",
            "journal_type": "V8_FROZEN_FORWARD_HOLDOUT",
            "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": decision_ts.isoformat(),
            "cohort_offset": cohort,
            "symbols": picks,
            "entry_timestamp_utc": entry_ts.isoformat(),
            "planned_exit_timestamp_utc": exit_ts.isoformat() if exit_ts is not None else None,
            "top10_scores": {r.symbol: float(r.orthogonal_signal) for r in ranking.head(TOP_N).itertuples()},
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(e, existing))

    # Refresh after decisions.
    events = _read_events()
    decisions = [e for e in events if e.get("event_type") == "DECISION"]

    # 2) ENTRY events when next-open data is available.
    for dec in decisions:
        entry_ts = pd.Timestamp(dec["entry_timestamp_utc"])
        if entry_ts not in date_to_idx:
            continue
        cohort = int(dec["cohort_offset"])
        key = ("ENTRY", dec["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        prices = {}
        valid = True
        for sym in dec["symbols"]:
            if entry_ts not in frames[sym].index or not np.isfinite(frames[sym].loc[entry_ts, "open"]):
                valid = False; break
            prices[sym] = float(frames[sym].loc[entry_ts, "open"])
        if not valid or entry_ts not in frames["SPY"].index:
            continue
        # Previous entered basket for same cohort determines transition notional.
        prior_entries = [e for e in _read_events() if e.get("event_type") == "ENTRY" and int(e.get("cohort_offset", -1)) == cohort]
        prior_entries.sort(key=lambda e: e["entry_timestamp_utc"])
        previous = prior_entries[-1]["symbols"] if prior_entries else None
        traded = _transition_notional(previous, dec["symbols"])
        e = {
            "event_type": "ENTRY",
            "journal_type": "V8_FROZEN_FORWARD_HOLDOUT",
            "candidate_id": dec["candidate_id"],
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": dec["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": dec["symbols"],
            "entry_timestamp_utc": entry_ts.isoformat(),
            "entry_prices": prices,
            "spy_entry_open": float(frames["SPY"].loc[entry_ts, "open"]),
            "transition_notional": traded,
            "modeled_cost_rate": float(traded * COST_BPS / 10000.0),
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(e, existing))

    # 3) EXIT events when the fifth-session-later open exists.
    all_events = _read_events()
    entries = [e for e in all_events if e.get("event_type") == "ENTRY"]
    for ent in entries:
        cohort = int(ent["cohort_offset"])
        key = ("EXIT", ent["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = pd.Timestamp(ent["entry_timestamp_utc"])
        i = date_to_idx.get(entry_ts)
        if i is None or i + HOLD_SESSIONS >= len(dates):
            continue
        exit_ts = dates[i + HOLD_SESSIONS]
        if exit_ts > now.normalize() or exit_ts not in frames["SPY"].index:
            continue
        rets = []
        exit_prices = {}
        valid = True
        for sym in ent["symbols"]:
            if exit_ts not in frames[sym].index:
                valid = False; break
            p0 = float(ent["entry_prices"][sym])
            p1 = float(frames[sym].loc[exit_ts, "open"])
            if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
                valid = False; break
            exit_prices[sym] = p1
            rets.append(p1 / p0 - 1.0)
        if not valid:
            continue
        gross = float(np.mean(rets))
        cost = float(ent["modeled_cost_rate"])
        net = float((1.0 + gross) * (1.0 - cost) - 1.0)
        spy_ret = float(frames["SPY"].loc[exit_ts, "open"] / float(ent["spy_entry_open"]) - 1.0)
        e = {
            "event_type": "EXIT",
            "journal_type": "V8_FROZEN_FORWARD_HOLDOUT",
            "candidate_id": ent["candidate_id"],
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": ent["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": ent["symbols"],
            "entry_timestamp_utc": ent["entry_timestamp_utc"],
            "exit_timestamp_utc": exit_ts.isoformat(),
            "exit_prices": exit_prices,
            "gross_portfolio_return": gross,
            "modeled_cost_rate": cost,
            "net_portfolio_return": net,
            "spy_return": spy_ret,
            "net_relative_return": float(net - spy_ret),
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(e, existing))

    final = _read_events()
    exits = [e for e in final if e.get("event_type") == "EXIT"]
    _status({
        "status": "ACTIVE",
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "journal_path": str(JOURNAL_PATH),
        "events": len(final),
        "decisions": sum(e.get("event_type") == "DECISION" for e in final),
        "entries": sum(e.get("event_type") == "ENTRY" for e in final),
        "exits": len(exits),
        "last_decision_timestamp_utc": max((e["decision_timestamp_utc"] for e in decisions), default=None),
        "appended_this_run": appended,
        "brokerage_orders": False,
    })
    print("V8 FROZEN HOLDOUT MONITOR")
    print("=" * 88)
    print(f"Frozen SHA: {EXPECTED_SHA}")
    print(f"Events: {len(final)} | exits: {len(exits)} | appended: {appended}")
    print("Append-only forward evidence. No brokerage orders. Frozen strategy unchanged.")

if __name__ == "__main__":
    main()
''',
"webapp/services/v8_holdout_service.py": r'''"""Read-only V8 frozen holdout dashboard service."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
HOLDOUT_START = pd.Timestamp("2026-09-01T00:00:00Z")
ROOT = Path("data/model/v8/holdout")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"


def _events():
    out = []
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text().splitlines():
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except Exception: pass
    return out


def _curve(exits):
    if not exits:
        return []
    by_cohort = {i: {"strategy": 1.0, "spy": 1.0} for i in range(5)}
    points = []
    exits = sorted(exits, key=lambda e: e.get("exit_timestamp_utc", ""))
    for e in exits:
        c = int(e["cohort_offset"])
        by_cohort[c]["strategy"] *= 1.0 + float(e["net_portfolio_return"])
        by_cohort[c]["spy"] *= 1.0 + float(e["spy_return"])
        active = [v for v in by_cohort.values() if v["strategy"] != 1.0 or v["spy"] != 1.0]
        points.append({
            "timestamp_utc": e["exit_timestamp_utc"],
            "strategy_normalized": 100000.0 * sum(v["strategy"] for v in active) / len(active),
            "spy_normalized": 100000.0 * sum(v["spy"] for v in active) / len(active),
        })
    return points


def get_v8_holdout_dashboard():
    now = pd.Timestamp.now(tz="UTC")
    status = {}
    if STATUS_PATH.exists():
        try: status = json.loads(STATUS_PATH.read_text())
        except Exception: status = {}
    ev = _events()
    decisions = [e for e in ev if e.get("event_type") == "DECISION"]
    entries = [e for e in ev if e.get("event_type") == "ENTRY"]
    exits = [e for e in ev if e.get("event_type") == "EXIT"]
    rel = [float(e["net_relative_return"]) for e in exits if e.get("net_relative_return") is not None]
    if now < HOLDOUT_START:
        state = "WAITING_FOR_HOLDOUT"
    elif not exits:
        state = status.get("status", "ACTIVE_WAITING_FOR_COMPLETED_COHORT")
    else:
        state = "ACTIVE"
    return {
        "candidate_id": "V8_DISTANCE_ONLY_TOP10_5D_NEXT_OPEN_10BPS",
        "frozen_sha256": EXPECTED_SHA,
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "state": state,
        "days_until_holdout": max(0, int((HOLDOUT_START - now).total_seconds() // 86400) + (1 if now < HOLDOUT_START else 0)),
        "journal_path": str(JOURNAL_PATH),
        "decisions": len(decisions),
        "entries": len(entries),
        "completed_cohorts": len(exits),
        "mean_net_relative_return": (sum(rel) / len(rel)) if rel else None,
        "net_relative_hit_rate": (sum(x > 0 for x in rel) / len(rel)) if rel else None,
        "latest_exit": exits[-1] if exits else None,
        "curve": _curve(exits),
        "brokerage_orders": False,
        "strategy_modified": False,
    }
''',
"webapp/static/js/v8_holdout_monitor.js": r'''(() => {
  const root = document.getElementById('v8-holdout-monitor');
  if (!root) return;
  const style = document.createElement('style');
  style.textContent = `
    .v8h-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0}
    .v8h-card{padding:12px;border:1px solid rgba(120,155,205,.16);border-radius:12px;background:rgba(7,16,31,.48)}
    .v8h-label{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.v8h-value{font-size:1.05rem;font-weight:700;margin-top:3px}
    .v8h-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.72rem;word-break:break-all;color:var(--muted)}
    .v8h-chart{height:280px;border:1px solid rgba(120,155,205,.14);border-radius:14px;background:rgba(7,16,31,.45);overflow:hidden;margin-top:12px}
    .v8h-chart svg{width:100%;height:100%;display:block}.v8h-note{font-size:.78rem;color:var(--muted);margin-top:8px}
    @media(max-width:800px){.v8h-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `; document.head.appendChild(style);
  const fmtPct = v => v == null ? '—' : `${(100*v).toFixed(3)}%`;
  function draw(curve){
    const box=root.querySelector('.v8h-chart'); if(!box)return;
    if(!curve.length){box.innerHTML='<div style="padding:28px;color:var(--muted)">Forward curve will begin after completed holdout cohorts are available.</div>';return;}
    const W=1000,H=280,p=34; const vals=curve.flatMap(x=>[x.strategy_normalized,x.spy_normalized]);
    const lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1,hi-lo);
    const x=i=>p+(W-2*p)*(i/Math.max(1,curve.length-1)); const y=v=>H-p-(H-2*p)*((v-lo)/span);
    const path=k=>curve.map((d,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(d[k]).toFixed(1)}`).join(' ');
    box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><path d="${path('strategy_normalized')}" fill="none" stroke="currentColor" stroke-width="3"/><path d="${path('spy_normalized')}" fill="none" stroke="currentColor" stroke-opacity=".45" stroke-width="2" stroke-dasharray="8 6"/></svg>`;
  }
  async function refresh(){
    try{
      const r=await fetch('/api/v8/holdout',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`); const d=await r.json();
      root.querySelector('[data-v8h-state]').textContent=d.state;
      root.querySelector('[data-v8h-decisions]').textContent=d.decisions;
      root.querySelector('[data-v8h-exits]').textContent=d.completed_cohorts;
      root.querySelector('[data-v8h-edge]').textContent=fmtPct(d.mean_net_relative_return);
      root.querySelector('[data-v8h-hit]').textContent=fmtPct(d.net_relative_hit_rate);
      root.querySelector('[data-v8h-sha]').textContent=d.frozen_sha256;
      root.querySelector('[data-v8h-start]').textContent=d.holdout_start_utc.replace('T00:00:00+00:00','');
      draw(d.curve||[]);
    }catch(e){root.querySelector('[data-v8h-state]').textContent='MONITOR ERROR'; console.error(e);}
  }
  refresh(); setInterval(refresh,15000);
})();
''',
"scripts/install_v8_holdout_monitor_launchagent.sh": r'''#!/bin/zsh
set -euo pipefail
ROOT="$HOME/Data-Shepherd-Engineering/stock-market-ai-platform"
PY="$ROOT/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.datashepherd.v8holdoutmonitor.plist"
LOGDIR="$ROOT/logs"
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"
if [[ ! -x "$PY" ]]; then echo "Missing venv python: $PY"; exit 1; fi
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.datashepherd.v8holdoutmonitor</string>
<key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>ml.v8.holdout_runner</string></array>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>StartInterval</key><integer>300</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>$LOGDIR/v8_holdout_monitor.out.log</string>
<key>StandardErrorPath</key><string>$LOGDIR/v8_holdout_monitor.err.log</string>
</dict></plist>
EOF
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/com.datashepherd.v8holdoutmonitor" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.datashepherd.v8holdoutmonitor"
echo "===== V8 FROZEN HOLDOUT MONITOR ====="
launchctl print "gui/$(id -u)/com.datashepherd.v8holdoutmonitor" | grep -E 'state =|runs =|pid =|last exit code' || true
echo "Cadence: every 5 minutes; append-only; duplicates skipped"
echo "Holdout start: 2026-09-01 UTC"
echo "Frozen SHA: ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"
echo "No brokerage orders. Before Sep 1, no holdout journal evidence is written."
''',
}

PANEL = r'''
<section id="v8-holdout-monitor" class="panel" style="margin-top:18px">
  <div class="panel-head"><div><h2>V8 FROZEN FORWARD HOLDOUT</h2><p>Exact frozen DISTANCE_ONLY candidate — append-only monitoring beginning September 1, 2026.</p></div></div>
  <div class="v8h-grid">
    <div class="v8h-card"><div class="v8h-label">State</div><div class="v8h-value" data-v8h-state>Loading…</div></div>
    <div class="v8h-card"><div class="v8h-label">Decisions</div><div class="v8h-value" data-v8h-decisions>—</div></div>
    <div class="v8h-card"><div class="v8h-label">Completed Cohorts</div><div class="v8h-value" data-v8h-exits>—</div></div>
    <div class="v8h-card"><div class="v8h-label">Mean Net Excess</div><div class="v8h-value" data-v8h-edge>—</div></div>
    <div class="v8h-card"><div class="v8h-label">Excess Hit Rate</div><div class="v8h-value" data-v8h-hit>—</div></div>
    <div class="v8h-card"><div class="v8h-label">Holdout Start</div><div class="v8h-value" data-v8h-start>—</div></div>
  </div>
  <div class="v8h-sha">Frozen SHA-256: <span data-v8h-sha>—</span></div>
  <div class="v8h-chart"></div>
  <div class="v8h-note">Solid = frozen V8 completed-cohort normalized wealth; dashed = SPY. Diagnostic monitoring only. Strategy SHA, Top-10, 5-session hold, next-open execution, five cohort offsets, and 10-bps cost contract cannot change here.</div>
</section>
'''

APP_IMPORT = "from webapp.services.v8_holdout_service import get_v8_holdout_dashboard\n"
APP_ROUTE = r'''

@app.get("/api/v8/holdout")
def api_v8_holdout():
    return get_v8_holdout_dashboard()
'''


def write_files():
    for name, content in FILES.items():
        p = Path(name); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8")
        print(f"[APPLY] {name}")


def patch_app():
    p = Path("webapp/app.py")
    text = p.read_text()
    if "get_v8_holdout_dashboard" not in text:
        # Place import with other imports; a top-level import is safe.
        text = APP_IMPORT + text
        print("[APPLY] app.py V8 holdout service import")
    if 'def api_v8_holdout' not in text:
        marker = 'if __name__ == "__main__":'
        if marker in text:
            text = text.replace(marker, APP_ROUTE + "\n" + marker, 1)
        else:
            text += APP_ROUTE
        print("[APPLY] app.py V8 holdout API")
    p.write_text(text)


def patch_template():
    p = Path("webapp/templates/index.html")
    text = p.read_text()
    if 'id="v8-holdout-monitor"' not in text:
        marker = "</main>" if "</main>" in text else "</body>"
        text = text.replace(marker, PANEL + "\n" + marker, 1)
        print("[APPLY] dashboard V8 frozen holdout panel")
    script = '<script src="/static/js/v8_holdout_monitor.js"></script>'
    if script not in text:
        text = text.replace("</body>", script + "\n</body>", 1)
        print("[APPLY] dashboard V8 holdout monitor script")
    p.write_text(text)


def main():
    write_files(); patch_app(); patch_template()
    print()
    print("V8 frozen holdout monitoring patch complete.")
    print(f"Frozen SHA enforced: {EXPECTED_SHA}")
    print("Before 2026-09-01 UTC: status only, no holdout journal evidence.")
    print("After boundary: append-only DECISION/ENTRY/EXIT evidence; no brokerage orders.")
    print("Dashboard monitoring is read-only and refreshes every 15 seconds.")

if __name__ == "__main__":
    main()
