"""Build a single comparable stock-model performance artifact for the dashboard.

The comparison intentionally excludes V6 and V7. It contains V4, V5, the
exact frozen V8 candidate, and SPY. Every line is independently normalized to
the same hypothetical $100,000 starting capital at its own first scientifically
eligible observation. Live paper-account balances are never appended to these
historical strategy curves.

Research/display only: no paper state, frozen model, holdout journal, or
brokerage setting is modified.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

STARTING_CAPITAL = 100_000.0
V4_PATH = Path("data/model/v4/full_history_equity.json")
V5_PATH = Path("data/model/v5/phase3/portfolio_daily.csv")
V8_PATH = Path("data/model/v8/phase5/economic_period_results.csv")
V8_FREEZE_PATH = Path("data/model/v8/phase7/frozen_candidate_spec.json")
FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_PATH = Path("webapp/static/generated/stock_model_comparison.json")

V5_COST_BPS = 10.0
V5_HOLD_SESSIONS = 5
V8_COST_BPS = 10
V8_SCORE_ID = "DISTANCE_ONLY"
V8_EXPECTED_SHA = "ebfbdd23f1f7a29d8a1b74939d346384a7a2a04bf3d0c599103285aa02334e41"


def _iso(value) -> str:
    return pd.Timestamp(value).isoformat()


def _series_record(model_id, label, rows, methodology, status):
    if not rows:
        raise ValueError(f"{model_id} produced no comparison rows")
    rows = sorted(rows, key=lambda r: r["timestamp"])
    return {
        "model_id": model_id,
        "label": label,
        "status": status,
        "methodology": methodology,
        "start_timestamp": rows[0]["timestamp"],
        "end_timestamp": rows[-1]["timestamp"],
        "starting_capital": STARTING_CAPITAL,
        "ending_equity": float(rows[-1]["equity"]),
        "total_return_pct": float((rows[-1]["equity"] / STARTING_CAPITAL - 1.0) * 100.0),
        "observations": len(rows),
        "history": rows,
    }


def _discover_spy_path():
    candidates = sorted((FEATURE_ROOT / "SPY").glob("*.parquet"))
    if not candidates:
        raise FileNotFoundError("SPY feature parquet not found under data/features/stocks/SPY")
    return candidates[0]


def _spy_frame():
    df = pd.read_parquet(_discover_spy_path()).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    if ts_col not in df.columns or "close" not in df.columns:
        raise ValueError("SPY feature parquet requires timestamp and close")
    out = pd.DataFrame({
        "timestamp_utc": pd.to_datetime(df[ts_col], utc=True),
        "close": pd.to_numeric(df["close"], errors="coerce"),
    })
    return out[np.isfinite(out["close"]) & (out["close"] > 0)].sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")


def _load_v4():
    if not V4_PATH.exists():
        raise FileNotFoundError(f"Missing {V4_PATH}; run python -m ml.run_v4_full_history_reconstruction")
    payload = json.loads(V4_PATH.read_text(encoding="utf-8"))
    raw = payload.get("history") or []
    if not raw:
        raise ValueError("V4 full-history artifact contains no history")
    first = float(raw[0]["equity"])
    if first <= 0:
        raise ValueError("V4 first equity must be positive")
    scale = STARTING_CAPITAL / first
    rows = [
        {"timestamp": str(r["timestamp"]), "equity": float(r["equity"]) * scale, "source": "V4 causal walk-forward reconstruction"}
        for r in raw if r.get("timestamp") is not None and r.get("equity") is not None
    ]
    return _series_record(
        "V4", "V4", rows,
        "Causal expanding-window V4 walk-forward reconstruction using the existing V4 execution and cost rules.",
        "reconstructed",
    )


def _load_v5():
    if not V5_PATH.exists():
        raise FileNotFoundError(f"Missing {V5_PATH}; run V5 Phase 3 first")
    t = pd.read_csv(V5_PATH)
    required = {"timestamp_utc", "gross_return_5d", "turnover"}
    missing = sorted(required - set(t.columns))
    if missing:
        raise ValueError("V5 portfolio file missing: " + ", ".join(missing))
    t["timestamp_utc"] = pd.to_datetime(t["timestamp_utc"], utc=True)
    t = t.sort_values("timestamp_utc").copy()
    t["net_return"] = pd.to_numeric(t["gross_return_5d"], errors="coerce") - pd.to_numeric(t["turnover"], errors="coerce") * V5_COST_BPS / 10000.0
    t = t[np.isfinite(t["net_return"])].copy()
    if t.empty:
        raise ValueError("V5 Phase-3 portfolio contains no usable periods")

    # Phase 3 stores the decision timestamp with a forward five-session return.
    # Plot the capital change on the corresponding realization date rather than
    # drawing a same-timestamp vertical jump at the first decision.
    trading_dates = list(_spy_frame()["timestamp_utc"])
    date_to_idx = {ts: i for i, ts in enumerate(trading_dates)}
    first_decision = t.iloc[0]["timestamp_utc"]
    rows = [{"timestamp": _iso(first_decision), "equity": STARTING_CAPITAL, "source": "V5 starting capital"}]
    equity = STARTING_CAPITAL
    for row in t.itertuples(index=False):
        ts = row.timestamp_utc
        i = date_to_idx.get(ts)
        if i is None or i + V5_HOLD_SESSIONS >= len(trading_dates):
            continue
        exit_ts = trading_dates[i + V5_HOLD_SESSIONS]
        equity *= 1.0 + float(row.net_return)
        rows.append({
            "timestamp": _iso(exit_ts),
            "equity": float(equity),
            "source": "V5 frozen HGB 60% SPY / 40% Top-5 development portfolio",
        })
    return _series_record(
        "V5", "V5", rows,
        "Frozen HGB ranking portfolio: 60% SPY core, 40% equally weighted Top-5 sleeve, 5-session cadence, 10-bps turnover cost assumption. Historical curve uses development-only out-of-fold rankings.",
        "development reconstruction",
    )


def _validate_v8_freeze():
    if not V8_FREEZE_PATH.exists():
        raise FileNotFoundError(f"Missing {V8_FREEZE_PATH}; run V8 Phase 7 first")
    spec = json.loads(V8_FREEZE_PATH.read_text(encoding="utf-8"))
    digest = str(spec.get("spec_sha256") or "")
    if digest != V8_EXPECTED_SHA:
        raise RuntimeError(f"V8 frozen SHA mismatch: {digest} != {V8_EXPECTED_SHA}")
    return spec


def _load_v8():
    spec = _validate_v8_freeze()
    if not V8_PATH.exists():
        raise FileNotFoundError(f"Missing {V8_PATH}; run V8 Phase 5 first")
    p = pd.read_csv(V8_PATH)
    required = {"score_id", "cohort_offset", "entry_timestamp_utc", "exit_timestamp_utc", "cost_bps_per_dollar_traded", "net_portfolio_return"}
    missing = sorted(required - set(p.columns))
    if missing:
        raise ValueError("V8 economic-period file missing: " + ", ".join(missing))
    p = p[(p["score_id"] == V8_SCORE_ID) & (pd.to_numeric(p["cost_bps_per_dollar_traded"], errors="coerce") == V8_COST_BPS)].copy()
    p["entry_timestamp_utc"] = pd.to_datetime(p["entry_timestamp_utc"], utc=True)
    p["exit_timestamp_utc"] = pd.to_datetime(p["exit_timestamp_utc"], utc=True)
    p["net_portfolio_return"] = pd.to_numeric(p["net_portfolio_return"], errors="coerce")
    p = p[np.isfinite(p["net_portfolio_return"])].sort_values(["exit_timestamp_utc", "cohort_offset"])
    if p.empty:
        raise ValueError("No V8 DISTANCE_ONLY 10-bps periods found")

    cohort_equity = {offset: STARTING_CAPITAL / 5.0 for offset in range(5)}
    first_entry = p["entry_timestamp_utc"].min()
    rows = [{"timestamp": _iso(first_entry), "equity": STARTING_CAPITAL, "source": "V8 starting capital"}]
    for exit_ts, g in p.groupby("exit_timestamp_utc", sort=True):
        for row in g.itertuples(index=False):
            offset = int(row.cohort_offset)
            if offset in cohort_equity:
                cohort_equity[offset] *= 1.0 + float(row.net_portfolio_return)
        rows.append({
            "timestamp": _iso(exit_ts),
            "equity": float(sum(cohort_equity.values())),
            "source": "V8 frozen DISTANCE_ONLY aggregate of five equal staggered cohorts",
        })
    return _series_record(
        "V8", "V8 frozen", rows,
        f"Exact frozen {spec.get('candidate_id')} policy, SHA {V8_EXPECTED_SHA}; five equal staggered cohort sleeves, Top-10, next-open entry, 5-session hold, 10-bps cost contract.",
        "historical reconstruction; future holdout remains separate",
    )


def _load_spy(start_ts):
    df = _spy_frame()
    df = df[df["timestamp_utc"] >= start_ts].copy()
    if df.empty:
        raise ValueError("No SPY observations overlap model-comparison history")
    base = float(df.iloc[0]["close"])
    rows = [
        {"timestamp": _iso(r.timestamp_utc), "equity": float(STARTING_CAPITAL * float(r.close) / base), "source": "SPY buy-and-hold benchmark"}
        for r in df.itertuples(index=False)
    ]
    return _series_record(
        "SPY", "SPY", rows,
        "SPY buy-and-hold benchmark normalized to the same $100,000 starting capital at the earliest model-comparison date.",
        "benchmark",
    )


def main():
    v4 = _load_v4()
    v5 = _load_v5()
    v8 = _load_v8()
    earliest = min(pd.Timestamp(v4["start_timestamp"]), pd.Timestamp(v5["start_timestamp"]), pd.Timestamp(v8["start_timestamp"]))
    spy = _load_spy(earliest)
    series = [v4, v5, v8, spy]
    latest = max(pd.Timestamp(s["end_timestamp"]) for s in series)

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "title": "Stock model performance comparison",
        "starting_capital": STARTING_CAPITAL,
        "default_range": "3Y",
        "excluded_models": ["V6", "V7"],
        "latest_timestamp": latest.isoformat(),
        "comparison_policy": "Each model is shown as its own historical strategy curve on the same hypothetical $100,000 basis. Live paper-account balances are intentionally excluded. Model curves begin only when their scientifically eligible evidence begins; no history is backfilled before eligibility.",
        "holdout_note": "V8 historical reconstruction is development-era evidence only. The genuine 2026-09-01+ forward holdout remains a separate append-only evidence stream and is not retroactively represented as holdout performance.",
        "series": series,
        "research_safety": {
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "v8_frozen_spec_modified": False,
            "v8_future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    print("STOCK MODEL PERFORMANCE COMPARISON")
    print("=" * 84)
    print(f"Output: {OUTPUT_PATH}")
    for s in series:
        print(f"{s['model_id']:>3}: {s['start_timestamp']} -> {s['end_timestamp']} | obs={s['observations']:,} | ${s['ending_equity']:,.2f} | {s['total_return_pct']:+.2f}%")
    print("V6/V7 excluded. Live paper balance excluded. No orders or state changes.")


if __name__ == "__main__":
    main()
