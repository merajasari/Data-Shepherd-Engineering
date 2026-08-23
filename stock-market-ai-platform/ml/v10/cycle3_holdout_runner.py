"""Frozen V10 Cycle 3 forward-holdout runner.

The runner verifies the immutable Cycle 3 specification on every invocation.
Before 2027-01-04 UTC it writes no journal evidence. After the boundary it
records append-only DECISION / ENTRY / EXIT evidence under the fixed Top-10,
next-open, five-session, 10-bps contract.

It never modifies V8 or places brokerage orders.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from ml.feature_source import (
    feature_dataset_exists,
    get_feature_dataset_path,
    get_feature_root,
)

EXPECTED_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
HOLDOUT_START = pd.Timestamp("2027-01-04T00:00:00Z")
ORIGINAL_V10_BOUNDARY = pd.Timestamp("2026-11-02T00:00:00Z")
CANDIDATE_ID = "c3_confirm2_blend50"
TOP_N = 10
HOLD_SESSIONS = 5
COST_BPS = 10

ROOT = Path("data/model/v10/cycle3")
FREEZE_ROOT = ROOT / "freeze"
SPEC_PATH = FREEZE_ROOT / "frozen_candidate_spec.json"
LOCK_PATH = FREEZE_ROOT / "frozen_candidate.sha256"
V8_UNIVERSE_PANEL = Path("data/model/v8/phase1/orthogonal_signal_panel.parquet")
HOLDOUT_ROOT = ROOT / "holdout"
JOURNAL_PATH = HOLDOUT_ROOT / "journal.jsonl"
JOURNAL_LOCK_PATH = HOLDOUT_ROOT / "journal.lock"
STATUS_PATH = HOLDOUT_ROOT / "status.json"


def _canonical_sha(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_freeze():
    if not SPEC_PATH.exists() or not LOCK_PATH.exists():
        raise FileNotFoundError(
            "V10 Cycle 3 frozen spec/lock missing; run cycle3_freeze_audit first"
        )
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    lock_sha = LOCK_PATH.read_text(encoding="utf-8").strip().split()[0]
    core = dict(spec)
    embedded_sha = core.pop("spec_sha256", None)
    core.pop("frozen_at_utc", None)
    computed_sha = _canonical_sha(core)
    if not (
        embedded_sha == lock_sha == computed_sha == EXPECTED_SHA
    ):
        raise RuntimeError(
            "Frozen V10 Cycle 3 SHA mismatch "
            f"expected={EXPECTED_SHA} embedded={embedded_sha} "
            f"lock={lock_sha} computed={computed_sha}"
        )

    signal = spec.get("signal_contract", {})
    portfolio = spec.get("portfolio_contract", {})
    cost = spec.get("cost_contract", {})
    holdout = spec.get("holdout_contract", {})
    authority = spec.get("authority", {})
    checks = [
        spec.get("candidate_id") == CANDIDATE_ID,
        signal.get("v8_signal") == "distance_from_low_20d",
        signal.get("negative_entry") == "two consecutive completed negative_spy20 decisions",
        signal.get("positive_score") == "exact V8 raw distance_from_low_20d score",
        portfolio.get("top_n") == TOP_N,
        portfolio.get("weighting") == "equal_weight",
        portfolio.get("entry") == "next_session_open",
        portfolio.get("holding_sessions") == HOLD_SESSIONS,
        portfolio.get("cohort_offsets") == [0, 1, 2, 3, 4],
        cost.get("primary_cost_bps_per_dollar_traded") == COST_BPS,
        holdout.get("fresh_holdout_start_utc") == HOLDOUT_START.isoformat(),
        holdout.get("candidate_retuning_allowed") is False,
        holdout.get("holdout_outcomes_for_selection_allowed") is False,
        authority.get("modify_v8") is False,
        authority.get("modify_production") is False,
        authority.get("brokerage_orders") is False,
    ]
    if not all(checks):
        raise RuntimeError("Frozen V10 Cycle 3 specification contract mismatch")
    return spec


def _feature_files():
    root = get_feature_root(project_root=Path("."))
    if not root.is_dir():
        return {}
    output = {}
    for symbol_root in sorted(path for path in root.iterdir() if path.is_dir()):
        symbol = symbol_root.name.upper()
        path = get_feature_dataset_path(symbol, project_root=Path("."))
        if feature_dataset_exists(path):
            output[symbol] = path
    return output


def _load_symbol_frame(path):
    data = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in data.columns else "timestamp"
    required = {
        ts_col, "open", "close", "downside_vol_ratio_20", "volume_trend_5_20"
    }
    if not required.issubset(data.columns):
        raise ValueError(f"{path} missing required Cycle 3 feature columns")
    frame = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(data[ts_col], utc=True),
        "open": pd.to_numeric(data["open"], errors="coerce"),
        "close": pd.to_numeric(data["close"], errors="coerce"),
        "downside_vol_ratio_20": pd.to_numeric(
            data["downside_vol_ratio_20"], errors="coerce"
        ),
        "volume_trend_5_20": pd.to_numeric(
            data["volume_trend_5_20"], errors="coerce"
        ),
    }).sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
    frame["ret1"] = frame["close"].pct_change()
    low20 = frame["close"].rolling(20, min_periods=20).min()
    frame["distance_from_low_20d"] = frame["close"] / low20 - 1.0
    return frame.set_index("timestamp_utc")


def _universe():
    if not V8_UNIVERSE_PANEL.exists():
        raise FileNotFoundError(
            f"Missing fixed 100-stock universe source: {V8_UNIVERSE_PANEL}"
        )
    panel = pd.read_parquet(V8_UNIVERSE_PANEL, columns=["symbol"])
    symbols = sorted(set(panel["symbol"].astype(str).str.upper()) - {"SPY"})
    if len(symbols) != 100:
        raise RuntimeError(f"Expected fixed universe of 100 stocks; found {len(symbols)}")
    return symbols


def _load_market():
    files = _feature_files()
    symbols = _universe()
    missing = sorted(set(symbols + ["SPY"]) - set(files))
    if missing:
        raise FileNotFoundError("Missing stock feature files: " + ", ".join(missing))
    frames = {symbol: _load_symbol_frame(files[symbol]) for symbol in symbols + ["SPY"]}
    dates = list(frames["SPY"].index[frames["SPY"]["close"].notna()])
    date_to_idx = {timestamp: index for index, timestamp in enumerate(dates)}
    return symbols, frames, dates, date_to_idx


def _negative_spy20(spy_frame, timestamp):
    returns = spy_frame.loc[:timestamp, "ret1"].dropna().tail(20)
    if len(returns) < 20:
        return False
    trailing = float((1.0 + returns).prod() - 1.0)
    return bool(np.isfinite(trailing) and trailing < 0.0)


def _confirmed_negative(spy_frame, dates, date_to_idx, timestamp):
    index = date_to_idx.get(timestamp)
    if index is None or index < 1:
        return False
    return _negative_spy20(spy_frame, timestamp) and _negative_spy20(
        spy_frame, dates[index - 1]
    )


def _rank_for_date(timestamp, symbols, frames, dates, date_to_idx):
    rows = []
    for symbol in symbols:
        frame = frames[symbol]
        if timestamp not in frame.index:
            continue
        row = frame.loc[timestamp]
        raw = row["distance_from_low_20d"]
        downside = row["downside_vol_ratio_20"]
        volume = row["volume_trend_5_20"]
        if np.isfinite(raw) and np.isfinite(downside) and np.isfinite(volume):
            rows.append((symbol, float(raw), float(downside), float(volume)))
    if len(rows) < 80:
        raise RuntimeError(
            f"Only {len(rows)} eligible V10 Cycle 3 names on {timestamp}; refusing decision"
        )

    ranked = pd.DataFrame(
        rows, columns=["symbol", "raw", "downside_vol_ratio_20", "volume_trend_5_20"]
    )
    ranked["raw_rank"] = ranked["raw"].rank(pct=True, method="average")
    ranked["downside_rank"] = ranked["downside_vol_ratio_20"].rank(
        pct=True, method="average"
    )
    ranked["volume_rank"] = ranked["volume_trend_5_20"].rank(
        pct=True, method="average"
    )
    ranked["defensive_signal"] = (
        0.5 * ranked["downside_rank"] + 0.5 * ranked["volume_rank"]
    )
    defensive_active = _confirmed_negative(
        frames["SPY"], dates, date_to_idx, timestamp
    )
    ranked["score"] = (
        0.5 * ranked["raw_rank"] + 0.5 * ranked["defensive_signal"]
        if defensive_active
        else ranked["raw"]
    )
    ranked["defensive_active"] = defensive_active
    return ranked.sort_values(
        ["score", "symbol"], ascending=[False, True]
    ).reset_index(drop=True)


def _read_events(path=None):
    path = JOURNAL_PATH if path is None else Path(path)
    events = []
    if path.exists():
        for line_number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            text = raw.strip()
            if not text:
                continue
            try:
                events.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Corrupt Cycle 3 holdout journal line {line_number}: {path}"
                ) from exc
    return events


def _event_key(event):
    return (
        event.get("event_type"),
        event.get("decision_timestamp_utc"),
        event.get("cohort_offset"),
    )


@contextmanager
def _journal_lock(lock_path=None):
    lock_path = JOURNAL_LOCK_PATH if lock_path is None else Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append(event, existing=None, path=None, lock_path=None):
    path = JOURNAL_PATH if path is None else Path(path)
    lock_path = JOURNAL_LOCK_PATH if lock_path is None else Path(lock_path)
    with _journal_lock(lock_path):
        disk_events = _read_events(path)
        disk_existing = {_event_key(item) for item in disk_events}
        key = _event_key(event)
        if key in disk_existing:
            if existing is not None:
                existing.update(disk_existing)
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(event, sort_keys=True) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
        if existing is not None:
            existing.update(disk_existing)
            existing.add(key)
        return True


def _transition_notional(previous, new):
    new_weights = {symbol: 1.0 / TOP_N for symbol in new}
    if previous is None:
        return 1.0
    old_weights = {symbol: 1.0 / TOP_N for symbol in previous}
    return float(sum(
        abs(new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0))
        for symbol in set(new_weights) | set(old_weights)
    ))


def _atomic_status(payload):
    output = dict(payload)
    output["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    output["frozen_sha256"] = EXPECTED_SHA
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{STATUS_PATH.name}.", suffix=".tmp", dir=STATUS_PATH.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(output, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, STATUS_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main():
    _verify_freeze()
    now = pd.Timestamp.now(tz="UTC")
    if now < HOLDOUT_START:
        _atomic_status({
            "status": "WAITING_FOR_HOLDOUT",
            "holdout_start_utc": HOLDOUT_START.isoformat(),
            "journal_written": False,
            "brokerage_orders": False,
        })
        print("V10 CYCLE 3 FROZEN HOLDOUT MONITOR")
        print("=" * 88)
        print(f"Status: WAITING_FOR_HOLDOUT | starts {HOLDOUT_START.isoformat()}")
        print(f"Frozen SHA: {EXPECTED_SHA}")
        print("No holdout journal evidence written before boundary. Orders: OFF.")
        return

    symbols, frames, dates, date_to_idx = _load_market()
    available = [
        timestamp for timestamp in dates
        if timestamp >= HOLDOUT_START and timestamp <= now.normalize()
    ]
    if not available:
        _atomic_status({
            "status": "WAITING_FOR_FIRST_COMPLETED_SESSION",
            "holdout_start_utc": HOLDOUT_START.isoformat(),
            "journal_written": False,
            "brokerage_orders": False,
        })
        print("No completed V10 Cycle 3 holdout session is available yet.")
        return

    events = _read_events()
    existing = {_event_key(event) for event in events}
    appended = 0

    for decision_ts in available:
        decision_index = date_to_idx[decision_ts]
        if decision_index + 1 >= len(dates):
            continue
        cohort = int(decision_index % HOLD_SESSIONS)
        key = ("DECISION", decision_ts.isoformat(), cohort)
        if key in existing:
            continue
        ranking = _rank_for_date(
            decision_ts, symbols, frames, dates, date_to_idx
        )
        picks = ranking.head(TOP_N)["symbol"].tolist()
        entry_ts = dates[decision_index + 1]
        exit_index = decision_index + 1 + HOLD_SESSIONS
        exit_ts = dates[exit_index] if exit_index < len(dates) else None
        defensive_active = bool(ranking["defensive_active"].iloc[0])
        event = {
            "event_type": "DECISION",
            "journal_type": "V10_CYCLE3_FROZEN_FORWARD_HOLDOUT",
            "candidate_id": CANDIDATE_ID,
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": decision_ts.isoformat(),
            "cohort_offset": cohort,
            "symbols": picks,
            "entry_timestamp_utc": entry_ts.isoformat(),
            "planned_exit_timestamp_utc": (
                exit_ts.isoformat() if exit_ts is not None else None
            ),
            "defensive_active": defensive_active,
            "top10_scores": {
                row.symbol: float(row.score)
                for row in ranking.head(TOP_N).itertuples()
            },
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(event, existing))

    events = _read_events()
    decisions = [event for event in events if event.get("event_type") == "DECISION"]
    for decision in decisions:
        entry_ts = pd.Timestamp(decision["entry_timestamp_utc"])
        cohort = int(decision["cohort_offset"])
        key = ("ENTRY", decision["decision_timestamp_utc"], cohort)
        if key in existing or entry_ts not in date_to_idx:
            continue
        prices = {}
        valid = True
        for symbol in decision["symbols"]:
            if (
                entry_ts not in frames[symbol].index
                or not np.isfinite(frames[symbol].loc[entry_ts, "open"])
            ):
                valid = False
                break
            prices[symbol] = float(frames[symbol].loc[entry_ts, "open"])
        if not valid or entry_ts not in frames["SPY"].index:
            continue
        prior_entries = [
            event for event in _read_events()
            if event.get("event_type") == "ENTRY"
            and int(event.get("cohort_offset", -1)) == cohort
        ]
        prior_entries.sort(key=lambda event: event["entry_timestamp_utc"])
        previous = prior_entries[-1]["symbols"] if prior_entries else None
        traded = _transition_notional(previous, decision["symbols"])
        event = {
            "event_type": "ENTRY",
            "journal_type": "V10_CYCLE3_FROZEN_FORWARD_HOLDOUT",
            "candidate_id": CANDIDATE_ID,
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": decision["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": decision["symbols"],
            "entry_timestamp_utc": entry_ts.isoformat(),
            "entry_prices": prices,
            "spy_entry_open": float(frames["SPY"].loc[entry_ts, "open"]),
            "transition_notional": float(traded),
            "modeled_cost_rate": float(traded * COST_BPS / 10000.0),
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(event, existing))

    entries = [
        event for event in _read_events() if event.get("event_type") == "ENTRY"
    ]
    for entry in entries:
        cohort = int(entry["cohort_offset"])
        key = ("EXIT", entry["decision_timestamp_utc"], cohort)
        if key in existing:
            continue
        entry_ts = pd.Timestamp(entry["entry_timestamp_utc"])
        entry_index = date_to_idx.get(entry_ts)
        if entry_index is None or entry_index + HOLD_SESSIONS >= len(dates):
            continue
        exit_ts = dates[entry_index + HOLD_SESSIONS]
        if exit_ts > now.normalize() or exit_ts not in frames["SPY"].index:
            continue
        returns = []
        exit_prices = {}
        valid = True
        for symbol in entry["symbols"]:
            if exit_ts not in frames[symbol].index:
                valid = False
                break
            p0 = float(entry["entry_prices"][symbol])
            p1 = float(frames[symbol].loc[exit_ts, "open"])
            if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
                valid = False
                break
            exit_prices[symbol] = p1
            returns.append(p1 / p0 - 1.0)
        if not valid:
            continue
        gross = float(np.mean(returns))
        cost = float(entry["modeled_cost_rate"])
        net = float((1.0 + gross) * (1.0 - cost) - 1.0)
        spy_return = float(
            frames["SPY"].loc[exit_ts, "open"] / float(entry["spy_entry_open"]) - 1.0
        )
        event = {
            "event_type": "EXIT",
            "journal_type": "V10_CYCLE3_FROZEN_FORWARD_HOLDOUT",
            "candidate_id": CANDIDATE_ID,
            "frozen_sha256": EXPECTED_SHA,
            "decision_timestamp_utc": entry["decision_timestamp_utc"],
            "cohort_offset": cohort,
            "symbols": entry["symbols"],
            "entry_timestamp_utc": entry["entry_timestamp_utc"],
            "exit_timestamp_utc": exit_ts.isoformat(),
            "exit_prices": exit_prices,
            "gross_portfolio_return": gross,
            "modeled_cost_rate": cost,
            "net_portfolio_return": net,
            "spy_return": spy_return,
            "net_relative_return": float(net - spy_return),
            "brokerage_orders": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        appended += int(_append(event, existing))

    final = _read_events()
    _atomic_status({
        "status": "ACTIVE",
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "journal_path": str(JOURNAL_PATH),
        "events": len(final),
        "decisions": sum(event.get("event_type") == "DECISION" for event in final),
        "entries": sum(event.get("event_type") == "ENTRY" for event in final),
        "exits": sum(event.get("event_type") == "EXIT" for event in final),
        "appended_this_run": appended,
        "brokerage_orders": False,
    })
    print("V10 CYCLE 3 FROZEN HOLDOUT MONITOR")
    print("=" * 88)
    print(f"Frozen SHA: {EXPECTED_SHA}")
    print(f"Events: {len(final)} | appended: {appended}")
    print("Append-only forward evidence. V8 unchanged. Brokerage orders: OFF.")


if __name__ == "__main__":
    main()
