"""Build a single comparable stock-model performance artifact for the dashboard.

The comparison intentionally excludes V6, V7, V11, and V12. It contains V4, V5,
the exact frozen V8 candidate, the separately frozen V10 Cycle 3 candidate,
the isolated V13 retrospective development reconstruction, and SPY. Every
historical strategy curve starts from the same hypothetical $100,000 capital
basis at its own first scientifically eligible observation. V13 is genuinely
simulated as a $100,000 integer-share portfolio for this retrospective chart;
its separately governed forward paper experiment remains locked to $5,000.
Live paper-account balances are never appended to these historical curves.

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

STARTING_CAPITAL = 100_000.0
V4_PATH = Path("data/model/v4/full_history_equity.json")
V5_PATH = Path("data/model/v5/phase3/portfolio_daily.csv")
V8_PATH = Path("data/model/v8/phase5/economic_period_results.csv")
V8_FREEZE_PATH = Path("data/model/v8/phase7/frozen_candidate_spec.json")
V10_PATH = Path("data/model/v10/cycle3/economic_period_results.csv")
V10_FREEZE_PATH = Path("data/model/v10/cycle3/freeze/frozen_candidate_spec.json")
V13_PATH = Path("data/research/v13/development/retrospective_reconstruction.json")
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
V13_EXPECTED_SHA = "42d7cb6397beb0016715b1dccf4ec070d14132198dc537a6823b68b9546f7702"
V13_RETROSPECTIVE_STARTING_CAPITAL = 100_000.0
V13_FORWARD_PAPER_STARTING_CAPITAL = 5_000.0
V13_FRESH_BOUNDARY_UTC = pd.Timestamp("2026-09-01T14:00:00Z")
V13_MAX_SOURCE_CHUNK_DAYS = 120
V13_RESPONSE_CAP_GUARD = "MAX_120_CALENDAR_DAYS_PER_REQUEST"


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


def _load_v13():
    if not V13_PATH.exists():
        raise FileNotFoundError(
            f"Missing {V13_PATH}; run python -m ml.v13.regime_overlay_backfill "
            "then python -m ml.v13.regime_overlay_reconstruction"
        )
    payload = json.loads(V13_PATH.read_text(encoding="utf-8"))
    if payload.get("status") != "V13_RETROSPECTIVE_DEVELOPMENT_RECONSTRUCTION":
        raise ValueError("V13 retrospective reconstruction status is invalid")
    if payload.get("classification") != "RETROSPECTIVE_DEVELOPMENT_ONLY_NOT_FRESH_EVIDENCE":
        raise ValueError("V13 reconstruction is not labeled development-only")
    if payload.get("v13_contract_sha256") != V13_EXPECTED_SHA:
        raise RuntimeError("V13 retrospective contract SHA mismatch")
    if payload.get("fresh_evidence_included") is not False:
        raise RuntimeError("V13 fresh evidence entered the historical chart")
    if payload.get("candidate_frozen") is not False:
        raise RuntimeError("V13 retrospective result is mislabeled frozen")
    if payload.get("brokerage_orders") is not False:
        raise RuntimeError("V13 retrospective result has brokerage authority")
    source_inputs = payload.get("source_inputs") or {}
    source_chunk_days = int(source_inputs.get("source_chunk_days") or 0)
    if source_chunk_days < 1 or source_chunk_days > V13_MAX_SOURCE_CHUNK_DAYS:
        raise RuntimeError("V13 retrospective source chunks are unsafe")
    if source_inputs.get("provider_response_cap_guard") != V13_RESPONSE_CAP_GUARD:
        raise RuntimeError("V13 retrospective response-cap guard is missing")
    if source_inputs.get("source_coverage_validated") is not True:
        raise RuntimeError("V13 retrospective source coverage is not validated")

    body = dict(payload)
    identity = body.pop("reconstruction_sha256", None)
    body.pop("generated_at_utc", None)
    encoded = json.dumps(
        body, separators=(",", ":"), sort_keys=True, ensure_ascii=True
    ).encode("utf-8")
    import hashlib
    if identity != hashlib.sha256(encoded).hexdigest():
        raise RuntimeError("V13 retrospective reconstruction SHA mismatch")

    raw = payload.get("history") or []
    if not raw:
        raise ValueError("V13 retrospective reconstruction contains no history")
    simulation_capital = float(payload.get("starting_capital_usd") or 0.0)
    if simulation_capital != V13_RETROSPECTIVE_STARTING_CAPITAL:
        raise RuntimeError(
            "V13 reconstruction did not use the actual $100,000 retrospective basis"
        )
    forward_paper_capital = float(
        payload.get("forward_paper_starting_capital_usd") or 0.0
    )
    if forward_paper_capital != V13_FORWARD_PAPER_STARTING_CAPITAL:
        raise RuntimeError("V13 forward paper $5,000 boundary changed")
    rows = [
        {
            "timestamp": str(row["timestamp"]),
            "equity": float(row["portfolio_equity"]),
            "source": (
                "V13 actual $100,000 integer-share retrospective development "
                "portfolio; no capital rebasing"
            ),
        }
        for row in raw
        if row.get("timestamp") is not None
        and row.get("portfolio_equity") is not None
    ]
    if not rows:
        raise ValueError("V13 retrospective chart rows are empty")
    if max(pd.Timestamp(row["timestamp"]) for row in rows) >= V13_FRESH_BOUNDARY_UTC:
        raise RuntimeError("V13 retrospective chart reaches the fresh-evidence boundary")
    methodology = (
        f"Locked V13 contract SHA {V13_EXPECTED_SHA}; negative/high-volatility "
        "entry-confirmation overlay applied "
        "retrospectively to unchanged frozen V10 Cycle 3 ranks. The historical "
        "chart executes an actual $100,000 integer-share, long-only, no-margin "
        "portfolio split across five $20,000 staggered sleeves with 10-bps "
        "modeled round-trip cost; no $5,000 path rebasing is used. The forward "
        "paper experiment remains separately locked to $5,000. Tiingo IEX "
        "five-minute history begins in August 2017 and the fixed "
        "101-symbol universe can make the actual eligible start later. Historical "
        "bid/ask spreads are unavailable from five-minute bars, so this remains "
        "development-only and cannot be fresh evidence."
    )
    record = _series_record(
        "V13",
        "V13 regime overlay retrospective DEV",
        rows,
        methodology,
        "retrospective development reconstruction; not frozen; not fresh evidence",
    )
    record["reconstruction_sha256"] = identity
    record["simulation_starting_capital"] = simulation_capital
    record["forward_paper_starting_capital"] = forward_paper_capital
    record["requested_start_date"] = payload.get("requested_start_date")
    record["ten_calendar_years_available"] = payload.get("ten_calendar_years_available")
    record["actual_first_eligible_session"] = payload.get("actual_first_eligible_session")
    record["historical_spread_policy"] = payload.get("historical_spread_policy")
    record["source_chunk_days"] = source_chunk_days
    record["source_coverage_validated"] = True
    record["source_coverage"] = source_inputs.get("source_coverage")
    return record


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
    v13 = _load_v13()
    earliest = min(
        pd.Timestamp(item["start_timestamp"])
        for item in [v4, v5, v8, v10, v13]
    )
    spy = _load_spy(earliest)
    series = [v4, v5, v8, v10, v13, spy]
    latest = max(pd.Timestamp(s["end_timestamp"]) for s in series)

    payload = {
        "schema_version": 5,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "title": "Stock model performance comparison",
        "starting_capital": STARTING_CAPITAL,
        "default_range": "3Y",
        "excluded_models": ["V6", "V7", "V11", "V12"],
        "latest_timestamp": latest.isoformat(),
        "comparison_policy": "Each model is shown as its own historical strategy curve starting from the same hypothetical $100,000 capital. V13 is genuinely simulated as a $100,000 integer-share portfolio split across five $20,000 sleeves; its separately governed forward paper experiment remains locked to $5,000. No V13 capital rebasing is used. Live paper-account balances are intentionally excluded. Model curves begin only when their scientifically eligible evidence begins; unavailable intraday history is never fabricated.",
        "holdout_note": "The V8 line is its frozen-candidate historical reconstruction. The V10 line is the separately frozen Cycle 3 candidate development reconstruction. V13 is a retrospective development-only counterfactual, not frozen and not fresh evidence; its exact five-minute source begins in August 2017 and complete fixed-universe eligibility can begin later. Genuine V8, V10, and V13 forward/fresh evidence remains separate and is never backfilled. V11 and V12 remain excluded from this model-history chart.",
        "lineage": {
            "v8_candidate_id": V8_SCORE_ID,
            "v8_frozen_sha256": V8_EXPECTED_SHA,
            "v8_forward_holdout_start_utc": "2026-09-01T00:00:00+00:00",
            "v10_candidate_id": V10_CANDIDATE_ID,
            "v10_frozen_sha256": V10_EXPECTED_SHA,
            "v10_forward_holdout_start_utc": V10_HOLDOUT_START_UTC.isoformat(),
            "v10_classification": "FROZEN_CYCLE3_DEVELOPMENT_RECONSTRUCTION",
            "v13_contract_sha256": V13_EXPECTED_SHA,
            "v13_reconstruction_sha256": v13["reconstruction_sha256"],
            "v13_classification": "RETROSPECTIVE_DEVELOPMENT_ONLY_NOT_FRESH_EVIDENCE",
            "v13_requested_start_date": v13["requested_start_date"],
            "v13_actual_first_eligible_session": v13["actual_first_eligible_session"],
            "v13_ten_calendar_years_available": v13["ten_calendar_years_available"],
            "v13_source_chunk_days": v13["source_chunk_days"],
            "v13_source_coverage_validated": v13[
                "source_coverage_validated"
            ],
            "v13_fresh_evidence_boundary_utc": V13_FRESH_BOUNDARY_UTC.isoformat(),
            "v13_retrospective_starting_capital": V13_RETROSPECTIVE_STARTING_CAPITAL,
            "v13_forward_paper_starting_capital": V13_FORWARD_PAPER_STARTING_CAPITAL,
            "v13_fresh_evidence_included": False,
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
            "v13_fresh_evidence_read": False,
            "v13_fresh_evidence_written": False,
            "v13_candidate_frozen": False,
            "v13_production_evidence_modified": False,
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
    print("V6/V7/V11/V12 excluded. V13 is retrospective development only. V8/V10/V13 forward or fresh evidence and live paper balances are excluded. No orders or state changes.")


if __name__ == "__main__":
    main()
