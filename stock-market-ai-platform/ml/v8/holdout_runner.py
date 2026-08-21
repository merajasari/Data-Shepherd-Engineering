"""V8 frozen forward-holdout runner.

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

from ml.feature_source import (
    feature_dataset_exists,
    get_feature_dataset_path,
    get_feature_root,
)

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
    """Resolve V8 inputs through the shared Pandas/Spark backend contract."""
    root = get_feature_root(project_root=Path("."))
    if not root.is_dir():
        return {}

    out = {}
    for symbol_root in sorted(path for path in root.iterdir() if path.is_dir()):
        symbol = symbol_root.name.upper()
        path = get_feature_dataset_path(symbol, project_root=Path("."))
        if feature_dataset_exists(path):
            out[symbol] = path
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
