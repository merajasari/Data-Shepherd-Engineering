"""Apply isolated Stock V6 Phase 4 robustness/stress validation."""
from pathlib import Path

PHASE4 = Path("ml/v6/phase4.py")


def main():
    PHASE4.parent.mkdir(parents=True, exist_ok=True)
    PHASE4.write_text(r'''"""Stock V6 Phase 4: fixed Top-10 robustness and stress validation.

This phase keeps the Phase 3 Elastic Net / Top-10 policy fixed and deliberately
makes the economic assumptions harder. The 2026-02-01+ holdout remains sealed.
No model, Top-N, threshold, rebalance cadence, or portfolio weight is tuned here.

Stress family, fixed before results are inspected:
* Corrected traded-notional accounting at 10 bps per traded side.
* Cost stress at 20, 30, and 50 bps per traded side.
* Execution delayed by 1 and 2 additional trading sessions, while preserving
  the same decision-date selections and five-session holding horizon.
* Early-vs-late development stability.
* Name/sector selection concentration and realized contribution concentration.

Important audit note: Phase 3 stored one-way turnover. For a rebalance, both
sales and purchases are separately traded notionals. Phase 4 therefore charges
2 * one_way_turnover after the initial allocation; the first allocation charges
only its purchase notional. Phase 3 outputs are not rewritten.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "data-ingestion"))
from v5_symbols import V5_BENCHMARK_SYMBOL, get_v5_sector  # noqa: E402

PHASE = 4
MODEL_ID = "elastic_net"
TOP_N = 10
CORE_WEIGHT = 0.60
STOCK_WEIGHT = 0.40
HOLD_SESSIONS = 5
HOLDOUT = pd.Timestamp("2026-02-01", tz="UTC")
COST_BPS_SCENARIOS = (10, 20, 30, 50)
DELAY_SCENARIOS = (0, 1, 2)

PHASE3_DECISIONS = Path("data/model/v6/phase3/portfolio_decisions.parquet")
FEATURE_ROOT = Path("data/features/stocks")
OUTPUT_ROOT = Path("data/model/v6/phase4")
STRESS_PATH = OUTPUT_ROOT / "stress_summary.csv"
FOLD_PATH = OUTPUT_ROOT / "stress_fold_metrics.csv"
PERIOD_PATH = OUTPUT_ROOT / "stress_periods.parquet"
CONCENTRATION_PATH = OUTPUT_ROOT / "concentration.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"


def _max_drawdown(returns):
    r = np.asarray(returns, dtype=float)
    if len(r) == 0:
        return 0.0
    wealth = np.r_[1.0, np.cumprod(1.0 + r)]
    running = np.maximum.accumulate(wealth)
    return float(np.min(wealth / running - 1.0))


def _risk(returns):
    r = np.asarray(returns, dtype=float)
    if len(r) == 0:
        return np.nan
    vol = np.std(r, ddof=1) if len(r) > 1 else 0.0
    return float(np.mean(r) / vol * np.sqrt(252.0 / HOLD_SESSIONS)) if vol > 0 else np.nan


def _load_prices(symbol):
    p = FEATURE_ROOT / symbol / f"{symbol}_features.parquet"
    x = pd.read_parquet(p, columns=["timestamp_utc", "open"]).copy()
    x["timestamp_utc"] = pd.to_datetime(x["timestamp_utc"], utc=True)
    return x.sort_values("timestamp_utc").drop_duplicates("timestamp_utc").reset_index(drop=True)


def _delayed_return(price_frame, decision_date, delay):
    idx = price_frame.index[price_frame["timestamp_utc"].eq(decision_date)]
    if len(idx) != 1:
        return None
    decision_i = int(idx[0])
    entry_i = decision_i + 1 + int(delay)
    exit_i = entry_i + HOLD_SESSIONS
    if exit_i >= len(price_frame):
        return None
    entry = float(price_frame.loc[entry_i, "open"])
    exit_ = float(price_frame.loc[exit_i, "open"])
    if not np.isfinite(entry) or not np.isfinite(exit_) or entry <= 0:
        return None
    return exit_ / entry - 1.0


def _load_decisions():
    if not PHASE3_DECISIONS.exists():
        raise FileNotFoundError(f"Missing Phase 3 decisions: {PHASE3_DECISIONS}")
    d = pd.read_parquet(PHASE3_DECISIONS)
    d["decision_timestamp_utc"] = pd.to_datetime(d["decision_timestamp_utc"], utc=True)
    d = d[(d["model_id"] == MODEL_ID) & (d["top_n"] == TOP_N)].copy()
    if d.empty:
        raise RuntimeError("No Elastic Net Top-10 Phase 3 decisions found")
    if (d["decision_timestamp_utc"] >= HOLDOUT).any():
        raise AssertionError("Holdout leaked into Phase 4 inputs")
    return d.sort_values(["fold_id", "decision_timestamp_utc"]).reset_index(drop=True)


def _build_periods(decisions):
    symbols = sorted({s for xs in decisions["selected_symbols"] for s in xs})
    prices = {s: _load_prices(s) for s in [*symbols, V5_BENCHMARK_SYMBOL]}
    rows = []
    contributions = defaultdict(float)

    for fold_id, g in decisions.groupby("fold_id", sort=True):
        for seq, row in enumerate(g.itertuples(index=False)):
            chosen = list(row.selected_symbols)
            if len(chosen) != TOP_N:
                raise RuntimeError("Top-10 decision does not contain 10 symbols")
            traded_notional = float(row.turnover) if seq == 0 else 2.0 * float(row.turnover)

            for delay in DELAY_SCENARIOS:
                stock_returns = []
                ok = True
                for s in chosen:
                    rr = _delayed_return(prices[s], row.decision_timestamp_utc, delay)
                    if rr is None:
                        ok = False
                        break
                    stock_returns.append((s, rr))
                spy_r = _delayed_return(prices[V5_BENCHMARK_SYMBOL], row.decision_timestamp_utc, delay)
                if not ok or spy_r is None:
                    continue

                sleeve_r = float(np.mean([r for _, r in stock_returns]))
                gross = CORE_WEIGHT * spy_r + STOCK_WEIGHT * sleeve_r
                if delay == 0:
                    for s, rr in stock_returns:
                        contributions[s] += (STOCK_WEIGHT / TOP_N) * rr

                for bps in COST_BPS_SCENARIOS:
                    cost = traded_notional * (bps / 10_000.0)
                    rows.append({
                        "fold_id": fold_id,
                        "decision_timestamp_utc": row.decision_timestamp_utc,
                        "delay_sessions": delay,
                        "cost_bps_per_traded_side": bps,
                        "traded_notional_fraction": traded_notional,
                        "modeled_cost": cost,
                        "gross_strategy_return": gross,
                        "net_strategy_return": gross - cost,
                        "spy_return": spy_r,
                        "excess_period_return": gross - cost - spy_r,
                        "selected_symbols": chosen,
                    })
    return pd.DataFrame(rows), contributions


def _fold_metrics(periods):
    rows = []
    keys = ["delay_sessions", "cost_bps_per_traded_side", "fold_id"]
    for key, g in periods.groupby(keys, sort=True):
        delay, bps, fold = key
        sr = g["net_strategy_return"].to_numpy(float)
        br = g["spy_return"].to_numpy(float)
        strategy_eq = float(np.prod(1.0 + sr))
        spy_eq = float(np.prod(1.0 + br))
        rows.append({
            "delay_sessions": int(delay),
            "cost_bps_per_traded_side": int(bps),
            "fold_id": fold,
            "periods": int(len(g)),
            "strategy_return": strategy_eq - 1.0,
            "spy_return": spy_eq - 1.0,
            "excess_ending_equity": strategy_eq - spy_eq,
            "max_drawdown": _max_drawdown(sr),
            "sharpe_like": _risk(sr),
            "total_modeled_cost_fraction": float(g["modeled_cost"].sum()),
        })
    return pd.DataFrame(rows)


def _summarize(folds):
    rows = []
    for (delay, bps), g in folds.groupby(["delay_sessions", "cost_bps_per_traded_side"], sort=True):
        pos = g["excess_ending_equity"] > 0
        rows.append({
            "delay_sessions": int(delay),
            "cost_bps_per_traded_side": int(bps),
            "folds": int(len(g)),
            "positive_excess_folds": int(pos.sum()),
            "positive_excess_fold_fraction": float(pos.mean()),
            "mean_strategy_return": float(g["strategy_return"].mean()),
            "mean_spy_return": float(g["spy_return"].mean()),
            "mean_excess_ending_equity": float(g["excess_ending_equity"].mean()),
            "median_excess_ending_equity": float(g["excess_ending_equity"].median()),
            "mean_max_drawdown": float(g["max_drawdown"].mean()),
            "worst_max_drawdown": float(g["max_drawdown"].min()),
            "mean_sharpe_like": float(g["sharpe_like"].mean()),
            "total_modeled_cost_fraction": float(g["total_modeled_cost_fraction"].sum()),
        })
    return pd.DataFrame(rows)


def _concentration(decisions, contributions):
    n_periods = len(decisions)
    names = Counter()
    sectors = Counter()
    for xs in decisions["selected_symbols"]:
        for s in xs:
            names[s] += 1
            sectors[get_v5_sector(s)] += 1
    total_slots = n_periods * TOP_N
    rows = []
    for s, count in names.most_common():
        rows.append({
            "dimension": "symbol",
            "key": s,
            "selection_count": count,
            "selection_period_fraction": count / n_periods,
            "slot_fraction": count / total_slots,
            "realized_stock_contribution": float(contributions.get(s, 0.0)),
        })
    for sec, count in sectors.most_common():
        rows.append({
            "dimension": "sector",
            "key": sec,
            "selection_count": count,
            "selection_period_fraction": np.nan,
            "slot_fraction": count / total_slots,
            "realized_stock_contribution": np.nan,
        })
    return pd.DataFrame(rows)


def _early_late(periods):
    base = periods[(periods["delay_sessions"] == 0) & (periods["cost_bps_per_traded_side"] == 10)].copy()
    dates = sorted(base["decision_timestamp_utc"].unique())
    midpoint = dates[len(dates) // 2]
    out = []
    for label, mask in [
        ("EARLY", base["decision_timestamp_utc"] < midpoint),
        ("LATE", base["decision_timestamp_utc"] >= midpoint),
    ]:
        g = base.loc[mask]
        sr = g["net_strategy_return"].to_numpy(float)
        br = g["spy_return"].to_numpy(float)
        out.append({
            "period": label,
            "observations": int(len(g)),
            "start": g["decision_timestamp_utc"].min().isoformat(),
            "end": g["decision_timestamp_utc"].max().isoformat(),
            "strategy_return": float(np.prod(1 + sr) - 1),
            "spy_return": float(np.prod(1 + br) - 1),
            "excess_ending_equity": float(np.prod(1 + sr) - np.prod(1 + br)),
            "max_drawdown": _max_drawdown(sr),
        })
    return out


def main():
    decisions = _load_decisions()
    periods, contributions = _build_periods(decisions)
    if periods.empty:
        raise RuntimeError("Phase 4 produced no stress periods")

    folds = _fold_metrics(periods)
    summary = _summarize(folds)
    concentration = _concentration(decisions, contributions)
    early_late = _early_late(periods)

    base = summary[(summary.delay_sessions == 0) & (summary.cost_bps_per_traded_side == 10)].iloc[0]
    cost30 = summary[(summary.delay_sessions == 0) & (summary.cost_bps_per_traded_side == 30)].iloc[0]
    delay1 = summary[(summary.delay_sessions == 1) & (summary.cost_bps_per_traded_side == 10)].iloc[0]
    late = next(x for x in early_late if x["period"] == "LATE")
    symbol_rows = concentration[concentration.dimension == "symbol"].copy()
    sector_rows = concentration[concentration.dimension == "sector"].copy()
    max_name_fraction = float(symbol_rows["selection_period_fraction"].max())
    max_sector_slot_fraction = float(sector_rows["slot_fraction"].max())

    gates = {
        "corrected_10bps_positive_fold_fraction_at_least_two_thirds": bool(base.positive_excess_fold_fraction >= 2/3),
        "30bps_mean_excess_positive": bool(cost30.mean_excess_ending_equity > 0),
        "one_session_delay_mean_excess_positive": bool(delay1.mean_excess_ending_equity > 0),
        "late_development_excess_positive": bool(late["excess_ending_equity"] > 0),
        "max_name_selected_in_no_more_than_50pct_periods": bool(max_name_fraction <= 0.50),
        "max_sector_slot_fraction_no_more_than_40pct": bool(max_sector_slot_fraction <= 0.40),
    }
    all_gates = all(gates.values())

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_parquet(PERIOD_PATH, index=False)
    folds.to_csv(FOLD_PATH, index=False)
    summary.to_csv(STRESS_PATH, index=False)
    concentration.to_csv(CONCENTRATION_PATH, index=False)

    manifest = {
        "research_version": "v6",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "fixed_top10_robustness_stress_validation",
        "model_id": MODEL_ID,
        "top_n": TOP_N,
        "candidate_count": 100,
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "future_holdout_start_utc": HOLDOUT.isoformat(),
        "future_holdout_scored": False,
        "stress_contract": {
            "cost_bps_per_traded_side": list(COST_BPS_SCENARIOS),
            "execution_delay_sessions": list(DELAY_SCENARIOS),
            "holding_sessions": HOLD_SESSIONS,
            "core_weight": CORE_WEIGHT,
            "stock_weight": STOCK_WEIGHT,
            "phase3_turnover_audit": "Phase 3 one-way turnover is converted to actual traded notional: initial buy = one-way turnover; subsequent rebalances = 2x one-way turnover for sells plus buys.",
        },
        "early_late": early_late,
        "concentration": {
            "max_name_selection_period_fraction": max_name_fraction,
            "max_sector_slot_fraction": max_sector_slot_fraction,
            "top_10_names": symbol_rows.sort_values("selection_count", ascending=False).head(10)[["key", "selection_count", "selection_period_fraction", "realized_stock_contribution"]].to_dict("records"),
        },
        "pre_registered_robustness_gates": gates,
        "all_robustness_gates_passed": all_gates,
        "candidate_frozen": False,
        "next_step": "If robustness gates pass, review Phase 4 once, then freeze the complete V6 specification before any one-time holdout score. If gates fail, do not inspect the holdout.",
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "model_refit": False,
            "top_n_changed": False,
            "threshold_tuning": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")

    print("STOCK V6 PHASE 4")
    print("=" * 104)
    print("Fixed candidate: Elastic Net | Top-10 | 60% SPY / 40% stock sleeve")
    print("Holdout remains sealed from 2026-02-01 onward")
    print()
    print("===== STRESS SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== EARLY / LATE =====")
    print(pd.DataFrame(early_late).to_string(index=False))
    print()
    print("===== CONCENTRATION =====")
    print("Max name selection-period fraction:", f"{max_name_fraction:.2%}")
    print("Max sector slot fraction:", f"{max_sector_slot_fraction:.2%}")
    print(symbol_rows.sort_values("selection_count", ascending=False).head(10).to_string(index=False))
    print()
    print("===== ROBUSTNESS GATES =====")
    for k, v in gates.items():
        print(f"{k}: {'PASS' if v else 'FAIL'}")
    print("ALL GATES:", "PASS" if all_gates else "FAIL")
    print()
    print("No candidate freeze. No holdout score. No brokerage orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v6/phase4.py")
    print()
    print("Stock V6 Phase 4 robustness/stress patch complete.")
    print("Fixed Elastic Net Top-10 only; corrected traded-notional costs, cost stress, execution-delay stress, stability, and concentration diagnostics.")
    print("The 2026-02-01+ holdout remains sealed. No model tuning, candidate freeze, or orders.")


if __name__ == "__main__":
    main()
