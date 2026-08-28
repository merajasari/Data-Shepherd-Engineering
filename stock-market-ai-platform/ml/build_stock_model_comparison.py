"""Build a single comparable stock-model performance artifact for the dashboard.

The comparison intentionally excludes V6 and V7. It contains V4, V5, the
exact frozen V8 candidate, the separately frozen V10 Cycle 3 candidate, the
V11 Phase 2 post-hoc development reconstruction, and SPY. Every line is independently normalized to
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

from ml.feature_source import require_feature_dataset
from ml.v11.intraday_phase2_reconstruction import run as build_v11_reconstruction

STARTING_CAPITAL = 100_000.0
V4_PATH = Path("data/model/v4/full_history_equity.json")
V5_PATH = Path("data/model/v5/phase3/portfolio_daily.csv")
V8_PATH = Path("data/model/v8/phase5/economic_period_results.csv")
V8_FREEZE_PATH = Path("data/model/v8/phase7/frozen_candidate_spec.json")
V10_PATH = Path("data/model/v10/cycle3/economic_period_results.csv")
V10_FREEZE_PATH = Path("data/model/v10/cycle3/freeze/frozen_candidate_spec.json")
OUTPUT_PATH = Path("webapp/static/generated/stock_model_comparison.json")

V5_COST_BPS = 10.0
V5_HOLD_SESSIONS = 5
V8_COST_BPS = 10
V8_SCORE_ID = "DISTANCE_ONLY"
V10_CANDIDATE_ID = "c3_confirm2_blend50"
V10_COST_BPS = 10
V10_HOLDOUT_START_UTC = pd.Timestamp("2027-01-04T00:00:00Z")
V10_EXPECTED_SHA = "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
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
    return require_feature_dataset("SPY")


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


def _validate_v10_freeze():
    if not V10_FREEZE_PATH.exists():
        raise FileNotFoundError(
            f"Missing {V10_FREEZE_PATH}; run python -m ml.v10.cycle3_freeze_audit"
        )
    spec = json.loads(V10_FREEZE_PATH.read_text(encoding="utf-8"))
    digest = str(spec.get("spec_sha256") or "")
    if digest != V10_EXPECTED_SHA:
        raise RuntimeError(f"V10 Cycle 3 frozen SHA mismatch: {digest} != {V10_EXPECTED_SHA}")
    if str(spec.get("candidate_id") or "") != V10_CANDIDATE_ID:
        raise RuntimeError(
            f"V10 Cycle 3 candidate mismatch: {spec.get('candidate_id')} != {V10_CANDIDATE_ID}"
        )
    return spec


def _load_v10():
    spec = _validate_v10_freeze()
    if not V10_PATH.exists():
        raise FileNotFoundError(f"Missing {V10_PATH}; run python -m ml.v10.cycle3")

    p = pd.read_csv(V10_PATH)
    required = {
        "candidate_id", "cohort_offset", "entry_timestamp_utc",
        "exit_timestamp_utc", "net_portfolio_return",
    }
    missing = sorted(required - set(p.columns))
    if missing:
        raise ValueError("V10 economic-period file missing: " + ", ".join(missing))

    p = p[p["candidate_id"] == V10_CANDIDATE_ID].copy()
    p["entry_timestamp_utc"] = pd.to_datetime(p["entry_timestamp_utc"], utc=True)
    p["exit_timestamp_utc"] = pd.to_datetime(p["exit_timestamp_utc"], utc=True)
    p["net_portfolio_return"] = pd.to_numeric(p["net_portfolio_return"], errors="coerce")
    p = p[
        np.isfinite(p["net_portfolio_return"])
        & (p["exit_timestamp_utc"] < V10_HOLDOUT_START_UTC)
    ].sort_values(["exit_timestamp_utc", "cohort_offset"])
    if p.empty:
        raise ValueError(f"No pre-holdout V10 {V10_CANDIDATE_ID} periods found")
    if p["cohort_offset"].nunique() != 5:
        raise ValueError("V10 reconstruction requires all five cohort offsets")

    cohort_equity = {offset: STARTING_CAPITAL / 5.0 for offset in range(5)}
    first_entry = p["entry_timestamp_utc"].min()
    rows = [{"timestamp": _iso(first_entry), "equity": STARTING_CAPITAL, "source": "V10 starting capital"}]
    for exit_ts, g in p.groupby("exit_timestamp_utc", sort=True):
        for row in g.itertuples(index=False):
            offset = int(row.cohort_offset)
            if offset in cohort_equity:
                cohort_equity[offset] *= 1.0 + float(row.net_portfolio_return)
        rows.append({
            "timestamp": _iso(exit_ts),
            "equity": float(sum(cohort_equity.values())),
            "source": "Frozen V10 Cycle 3 aggregate of five equal staggered cohorts",
        })
    return _series_record(
        "V10", "V10 Cycle 3 frozen", rows,
        f"Frozen Cycle 3 candidate {spec.get('candidate_id')}, SHA {V10_EXPECTED_SHA}: exact V8 raw distance score outside confirmed negative regimes; fixed 50/50 percentile-rank distance and defensive-signal blend after two consecutive completed negative-SPY20 decisions. Five equal staggered cohort sleeves, Top-10, next-open entry, 5-session hold, and 10-bps transaction-cost contract.",
        "frozen Cycle 3 development reconstruction; January 2027 forward holdout remains separate",
    )


def _load_v11():
    payload = build_v11_reconstruction(write=True)
    if payload.get("status") != "POST_HOC_DEVELOPMENT_RECONSTRUCTION":
        raise ValueError("V11 reconstruction classification is invalid")
    if payload.get("fresh_evidence_included") is not False:
        raise ValueError("V11 fresh evidence entered development reconstruction")
    if payload.get("model_frozen") is not False:
        raise ValueError("V11 development reconstruction is mislabeled frozen")
    rows = [
        {
            "timestamp": str(row["timestamp"]),
            "equity": float(row["equity"]),
            "source": str(row.get("source") or "V11 Phase 2 development reconstruction"),
        }
        for row in payload.get("history") or []
    ]
    series = _series_record(
        "V11",
        "V11 Phase 2 development",
        rows,
        (
            "Post-hoc development reconstruction of the preregistered "
            f"{payload.get('configuration')} rules, contract SHA "
            f"{payload.get('contract_sha256')}; five-minute completed bars, "
            "Top-10 equal weight, next-bar entry, six-bar hold and 10-bps "
            "round-trip cost. This is not a frozen model or fresh confirmation."
        ),
        "post-hoc development reconstruction; fresh September confirmation remains separate",
    )
    series["research_lineage"] = {
        "contract_sha256": payload["contract_sha256"],
        "reconstruction_sha256": payload["reconstruction_sha256"],
        "source_manifest_sha256": payload["source_manifest_sha256"],
        "classification": payload["status"],
        "model_frozen": False,
        "fresh_evidence_included": False,
    }
    return series


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
    v10 = _load_v10()
    v11 = _load_v11()
    earliest = min(
        pd.Timestamp(item["start_timestamp"])
        for item in [v4, v5, v8, v10, v11]
    )
    spy = _load_spy(earliest)
    series = [v4, v5, v8, v10, v11, spy]
    latest = max(pd.Timestamp(s["end_timestamp"]) for s in series)

    payload = {
        "schema_version": 3,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "title": "Stock model performance comparison",
        "starting_capital": STARTING_CAPITAL,
        "default_range": "3Y",
        "excluded_models": ["V6", "V7"],
        "latest_timestamp": latest.isoformat(),
        "comparison_policy": "Each model is shown as its own historical strategy curve on the same hypothetical $100,000 basis. Live paper-account balances are intentionally excluded. Model curves begin only when their scientifically eligible evidence begins; no history is backfilled before eligibility.",
        "holdout_note": "The V8 line is its frozen-candidate historical reconstruction. The V10 line is the separately frozen Cycle 3 candidate development reconstruction. The V11 line is an explicitly post-hoc Phase 2 development reconstruction and is not frozen. Genuine V8 forward evidence, V11 fresh paper confirmation beginning 2026-09-01, and genuine V10 Cycle 3 forward evidence beginning 2027-01-04 remain separate and are never backfilled.",
        "lineage": {
            "v8_candidate_id": V8_SCORE_ID,
            "v8_frozen_sha256": V8_EXPECTED_SHA,
            "v8_forward_holdout_start_utc": "2026-09-01T00:00:00+00:00",
            "v10_candidate_id": V10_CANDIDATE_ID,
            "v10_frozen_sha256": V10_EXPECTED_SHA,
            "v10_forward_holdout_start_utc": V10_HOLDOUT_START_UTC.isoformat(),
            "v10_classification": "FROZEN_CYCLE3_DEVELOPMENT_RECONSTRUCTION",
            "v11_contract_sha256": v11["research_lineage"]["contract_sha256"],
            "v11_reconstruction_sha256": v11["research_lineage"]["reconstruction_sha256"],
            "v11_source_manifest_sha256": v11["research_lineage"]["source_manifest_sha256"],
            "v11_classification": "POST_HOC_DEVELOPMENT_RECONSTRUCTION",
            "v11_model_frozen": False,
            "v11_fresh_confirmation_start_utc": "2026-09-01T14:00:00+00:00",
            "v11_fresh_evidence_included": False,
            "forward_evidence_included": False,
            "live_paper_balances_included": False,
            "brokerage_orders": False,
        },
        "series": series,
        "research_safety": {
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "v8_frozen_spec_modified": False,
            "v8_future_holdout_scored": False,
            "v10_future_holdout_scored": False,
            "v10_cycle3_frozen_spec_modified": False,
            "v10_cycle3_forward_holdout_scored": False,
            "v11_fresh_confirmation_scored": False,
            "v11_model_frozen": False,
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
    print("V6/V7 excluded. V8/V10 forward holdouts, V11 fresh confirmation, and live paper balance excluded. No orders or state changes.")


if __name__ == "__main__":
    main()
