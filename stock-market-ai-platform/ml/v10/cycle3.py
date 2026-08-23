"""V10 Cycle 3 preregistered transition-efficiency evaluation.

Evaluates exactly three locked candidates against frozen V8 using development
periods whose decisions and exits are strictly earlier than the original V10
protected boundary. It cannot freeze a candidate or activate a holdout.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10 import phase3 as base
from ml.v10.config import FUTURE_HOLDOUT_START_UTC

OUTPUT_ROOT = Path("data/model/v10/cycle3")
SOURCE_CONTRACT = Path(__file__).with_name("cycle3_contract.json")
LOCKED_CONTRACT = OUTPUT_ROOT / "preregistered_contract.json"
LOCK_PATH = OUTPUT_ROOT / "preregistered_contract.sha256"
EXPECTED_CONTRACT_SHA256 = "e1df9ac21457a4494f53069b4513ecd4dfe0ae52a743eabdab6a63374998f051"
BASELINE = base.V8_ID
CANDIDATES = [
    "c3_confirm2_full_defensive",
    "c3_confirm2_blend50",
    "c3_immediate_blend25",
]
ALL_MODELS = [BASELINE, *CANDIDATES]
ROLLING_WINDOW = 252

PERIOD_PATH = OUTPUT_ROOT / "economic_period_results.csv"
COHORT_PATH = OUTPUT_ROOT / "cohort_summary.csv"
PORTFOLIO_PATH = OUTPUT_ROOT / "portfolio_summary.csv"
YEAR_PATH = OUTPUT_ROOT / "year_summary.csv"
REGIME_PATH = OUTPUT_ROOT / "regime_summary.csv"
DAILY_IC_PATH = OUTPUT_ROOT / "daily_ic.csv"
GATE_PATH = OUTPUT_ROOT / "gate_results.csv"
CANDIDATE_SUMMARY_PATH = OUTPUT_ROOT / "candidate_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "evaluation_manifest.json"
RESULT_PATHS = [
    PERIOD_PATH, COHORT_PATH, PORTFOLIO_PATH, YEAR_PATH, REGIME_PATH,
    DAILY_IC_PATH, GATE_PATH, CANDIDATE_SUMMARY_PATH, MANIFEST_PATH,
]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_preregistration():
    if datetime.now(timezone.utc) >= FUTURE_HOLDOUT_START_UTC.to_pydatetime():
        raise RuntimeError(
            "Cycle 3 development evaluation window is closed; refusing to run at or "
            "after the original V10 protected boundary"
        )
    if not SOURCE_CONTRACT.exists() or not LOCKED_CONTRACT.exists() or not LOCK_PATH.exists():
        raise FileNotFoundError(
            "Cycle 3 preregistration lock missing; run python -m ml.v10.cycle3_preregister"
        )
    source_sha = _sha256(SOURCE_CONTRACT)
    lock_sha = LOCK_PATH.read_text(encoding="utf-8").strip()
    locked = json.loads(LOCKED_CONTRACT.read_text(encoding="utf-8"))
    if (
        source_sha != EXPECTED_CONTRACT_SHA256
        or lock_sha != EXPECTED_CONTRACT_SHA256
        or locked.get("contract_sha256") != EXPECTED_CONTRACT_SHA256
    ):
        raise RuntimeError("Cycle 3 preregistration SHA mismatch")
    ids = [item.get("candidate_id") for item in locked.get("candidates", [])]
    if ids != CANDIDATES or len(locked.get("gates", [])) != 13:
        raise RuntimeError("Cycle 3 candidate set or gate policy differs from lock")
    if any(path.exists() for path in RESULT_PATHS):
        existing = [str(path) for path in RESULT_PATHS if path.exists()]
        raise RuntimeError(
            "Cycle 3 evaluation is single-pass; outputs already exist: "
            + ", ".join(existing)
        )
    return locked


def _rank_corr(left, right):
    paired = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(paired) < 20 or paired["left"].nunique() < 2 or paired["right"].nunique() < 2:
        return np.nan
    return float(paired["left"].corr(paired["right"], method="spearman"))


def _build_score_panel():
    panel = base._load_panel()
    if "forward_relative_return_5d" not in panel.columns:
        raise ValueError("Cycle 3 requires forward_relative_return_5d development target")
    if panel["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Cycle 3 panel reaches original V10 protected boundary")

    state = base._market_state(panel).sort_values("timestamp_utc").copy()
    negative = state["negative_spy20"].fillna(False).astype(bool)
    state["confirmed_negative_2d"] = negative & negative.shift(1, fill_value=False)
    state_by_ts = state.set_index("timestamp_utc")

    parts = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        if ts not in state_by_ts.index:
            continue
        market = state_by_ts.loc[ts]
        negative_now = bool(market["negative_spy20"])
        confirmed = bool(market["confirmed_negative_2d"])
        regime = str(market["decision_regime"])

        raw = pd.to_numeric(day["distance_from_low_20d"], errors="coerce")
        raw_rank = raw.rank(pct=True, method="average")
        downside = pd.to_numeric(
            day["downside_vol_ratio_20"], errors="coerce"
        ).rank(pct=True, method="average")
        volume = pd.to_numeric(
            day["volume_trend_5_20"], errors="coerce"
        ).rank(pct=True, method="average")
        defensive = 0.5 * downside + 0.5 * volume
        target = pd.to_numeric(day["forward_relative_return_5d"], errors="coerce")

        scores = {
            BASELINE: raw,
            CANDIDATES[0]: defensive if confirmed else raw,
            CANDIDATES[1]: (0.5 * raw_rank + 0.5 * defensive) if confirmed else raw,
            CANDIDATES[2]: (0.75 * raw_rank + 0.25 * defensive) if negative_now else raw,
        }
        for candidate_id, score in scores.items():
            parts.append(pd.DataFrame({
                "candidate_id": candidate_id,
                "timestamp_utc": ts,
                "symbol": day["symbol"].astype(str).values,
                "score": pd.to_numeric(score, errors="coerce").values,
                "forward_relative_return_5d": target.values,
                "decision_regime": regime,
                "negative_spy20": negative_now,
                "confirmed_negative_2d": confirmed,
            }))

    scored = pd.concat(parts, ignore_index=True)
    if scored["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Cycle 3 score panel reaches protected boundary")
    return scored


def _daily_ic(scored):
    rows = []
    baseline = scored[scored["candidate_id"] == BASELINE]
    for candidate_id in CANDIDATES:
        candidate = scored[scored["candidate_id"] == candidate_id]
        for ts, candidate_day in candidate.groupby("timestamp_utc", sort=True):
            baseline_day = baseline[baseline["timestamp_utc"] == ts]
            merged = candidate_day[
                ["symbol", "score", "forward_relative_return_5d", "decision_regime"]
            ].merge(
                baseline_day[["symbol", "score"]],
                on="symbol",
                suffixes=("_candidate", "_baseline"),
                validate="one_to_one",
            )
            candidate_ic = _rank_corr(
                merged["score_candidate"], merged["forward_relative_return_5d"]
            )
            baseline_ic = _rank_corr(
                merged["score_baseline"], merged["forward_relative_return_5d"]
            )
            rows.append({
                "timestamp_utc": ts,
                "candidate_id": candidate_id,
                "decision_regime": str(merged["decision_regime"].iloc[0]),
                "candidate_ic": candidate_ic,
                "baseline_ic": baseline_ic,
                "delta_ic_vs_v8": (
                    candidate_ic - baseline_ic
                    if np.isfinite(candidate_ic) and np.isfinite(baseline_ic)
                    else np.nan
                ),
            })
    return pd.DataFrame(rows)


def _build_periods(scored):
    symbols = scored["symbol"].unique().tolist()
    opens, trading_dates, date_to_idx = base._load_execution_data(symbols)
    raw_periods = []

    for candidate_id in ALL_MODELS:
        model_scores = scored[scored["candidate_id"] == candidate_id]
        for decision_ts in sorted(model_scores["timestamp_utc"].unique()):
            decision_ts = pd.Timestamp(decision_ts)
            if decision_ts not in date_to_idx:
                continue
            decision_index = date_to_idx[decision_ts]
            entry_index = decision_index + 1
            exit_index = entry_index + base.HOLD_SESSIONS
            if exit_index >= len(trading_dates):
                continue
            entry_ts = trading_dates[entry_index]
            exit_ts = trading_dates[exit_index]
            if decision_ts >= FUTURE_HOLDOUT_START_UTC or exit_ts >= FUTURE_HOLDOUT_START_UTC:
                continue

            day = model_scores[
                model_scores["timestamp_utc"] == decision_ts
            ].dropna(subset=["score"])
            day = day.sort_values(["score", "symbol"], ascending=[False, True])
            picks = day.head(base.TOP_N)["symbol"].astype(str).tolist()
            if len(picks) != base.TOP_N:
                continue

            stock_returns = []
            valid = True
            for symbol in picks:
                series = opens[symbol]
                if entry_ts not in series.index or exit_ts not in series.index:
                    valid = False
                    break
                entry_price = float(series.loc[entry_ts])
                exit_price = float(series.loc[exit_ts])
                if not (
                    np.isfinite(entry_price) and np.isfinite(exit_price)
                    and entry_price > 0 and exit_price > 0
                ):
                    valid = False
                    break
                stock_returns.append(exit_price / entry_price - 1.0)

            spy = opens["SPY"]
            if not valid or entry_ts not in spy.index or exit_ts not in spy.index:
                continue
            spy_entry = float(spy.loc[entry_ts])
            spy_exit = float(spy.loc[exit_ts])
            if not (
                np.isfinite(spy_entry) and np.isfinite(spy_exit)
                and spy_entry > 0 and spy_exit > 0
            ):
                continue

            raw_periods.append({
                "candidate_id": candidate_id,
                "decision_timestamp_utc": decision_ts,
                "entry_timestamp_utc": entry_ts,
                "exit_timestamp_utc": exit_ts,
                "decision_index": int(decision_index),
                "cohort_offset": int(decision_index % base.HOLD_SESSIONS),
                "decision_regime": str(day["decision_regime"].iloc[0]),
                "negative_spy20": bool(day["negative_spy20"].iloc[0]),
                "confirmed_negative_2d": bool(day["confirmed_negative_2d"].iloc[0]),
                "symbols": "|".join(picks),
                "gross_portfolio_return": float(np.mean(stock_returns)),
                "spy_return": float(spy_exit / spy_entry - 1.0),
            })

    periods = pd.DataFrame(raw_periods).sort_values(
        ["candidate_id", "cohort_offset", "decision_index"]
    ).reset_index(drop=True)
    if periods.empty:
        raise RuntimeError("No executable V10 Cycle 3 development periods produced")

    output = []
    for (candidate_id, offset), group in periods.groupby(
        ["candidate_id", "cohort_offset"], sort=True
    ):
        previous = None
        for _, row in group.iterrows():
            picks = row["symbols"].split("|")
            traded = base._transition_notional(previous, picks)
            cost_rate = traded * base.PRIMARY_COST_BPS / 10000.0
            gross = float(row["gross_portfolio_return"])
            net = (1.0 + gross) * (1.0 - cost_rate) - 1.0
            record = row.to_dict()
            record["transition_notional"] = float(traded)
            record["modeled_transaction_cost_rate"] = float(cost_rate)
            record["net_portfolio_return"] = float(net)
            record["net_relative_return"] = float(net - row["spy_return"])
            record["transaction_cost_drag"] = float(gross - net)
            output.append(record)
            previous = picks
    result = pd.DataFrame(output)
    if pd.to_datetime(result["exit_timestamp_utc"], utc=True).max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Cycle 3 executable result reaches protected boundary")
    return result


def _gate_candidate(candidate_id, daily, cohorts, portfolio, years, regimes):
    candidate_portfolio = portfolio.set_index("candidate_id").loc[candidate_id]
    baseline_portfolio = portfolio.set_index("candidate_id").loc[BASELINE]

    candidate_daily = daily[daily["candidate_id"] == candidate_id]
    valid_delta = candidate_daily["delta_ic_vs_v8"].dropna()
    rolling = valid_delta.rolling(
        ROLLING_WINDOW, min_periods=ROLLING_WINDOW
    ).mean().dropna()
    rolling_positive_rate = float((rolling > 0).mean()) if len(rolling) else np.nan

    cc = cohorts[cohorts["candidate_id"] == candidate_id].set_index("cohort_offset")
    bc = cohorts[cohorts["candidate_id"] == BASELINE].set_index("cohort_offset")
    common_cohorts = cc.index.intersection(bc.index)
    cagr_wins = int((cc.loc[common_cohorts, "strategy_cagr"] > bc.loc[common_cohorts, "strategy_cagr"]).sum())
    sharpe_wins = int((cc.loc[common_cohorts, "strategy_sharpe"] > bc.loc[common_cohorts, "strategy_sharpe"]).sum())

    cy = years[years["candidate_id"] == candidate_id].set_index("year")
    by = years[years["candidate_id"] == BASELINE].set_index("year")
    common_years = cy.index.intersection(by.index)
    year_wins = int((cy.loc[common_years, "mean_net_relative_return"] > by.loc[common_years, "mean_net_relative_return"]).sum())

    cr = regimes[regimes["candidate_id"] == candidate_id].set_index("decision_regime")
    br = regimes[regimes["candidate_id"] == BASELINE].set_index("decision_regime")
    negative = [x for x in cr.index if x.startswith("NEGATIVE_") and x in br.index]
    positive = [x for x in cr.index if x.startswith("POSITIVE_") and x in br.index]
    negative_wins = int(sum(cr.loc[x, "mean_net_relative_return"] > br.loc[x, "mean_net_relative_return"] for x in negative))
    positive_noninferior = int(sum(cr.loc[x, "mean_net_relative_return"] >= br.loc[x, "mean_net_relative_return"] - 0.00025 for x in positive))

    gates = [
        ("development_mean_delta_ic_positive", float(valid_delta.mean()) > 0),
        ("rolling_252d_positive_rate_ge_75pct", rolling_positive_rate >= 0.75),
        ("cagr_beats_v8", candidate_portfolio["mean_strategy_cagr_across_cohorts"] > baseline_portfolio["mean_strategy_cagr_across_cohorts"]),
        ("sharpe_beats_v8", candidate_portfolio["mean_strategy_sharpe_across_cohorts"] > baseline_portfolio["mean_strategy_sharpe_across_cohorts"]),
        ("terminal_wealth_beats_v8", candidate_portfolio["mean_strategy_terminal_wealth_across_cohorts"] > baseline_portfolio["mean_strategy_terminal_wealth_across_cohorts"]),
        ("relative_return_beats_v8", candidate_portfolio["mean_mean_net_relative_return_across_cohorts"] > baseline_portfolio["mean_mean_net_relative_return_across_cohorts"]),
        ("drawdown_not_worse_by_more_than_10pct_abs", candidate_portfolio["mean_strategy_max_drawdown_across_cohorts"] >= baseline_portfolio["mean_strategy_max_drawdown_across_cohorts"] - 0.10),
        ("calmar_not_below_90pct_v8", candidate_portfolio["mean_strategy_calmar_across_cohorts"] >= 0.90 * baseline_portfolio["mean_strategy_calmar_across_cohorts"]),
        ("cagr_wins_at_least_3_of_5_cohorts", cagr_wins >= 3),
        ("sharpe_wins_at_least_3_of_5_cohorts", sharpe_wins >= 3),
        ("year_relative_return_wins_at_least_half", year_wins >= (len(common_years) + 1) // 2),
        ("wins_all_negative_regimes", negative_wins == len(negative) and len(negative) > 0),
        ("positive_regime_relative_noninferiority", positive_noninferior == len(positive) and len(positive) > 0),
    ]
    gate_rows = [
        {"candidate_id": candidate_id, "gate": gate, "passed": bool(passed)}
        for gate, passed in gates
    ]
    details = {
        "candidate_id": candidate_id,
        "gates_passed": int(sum(row["passed"] for row in gate_rows)),
        "gates_total": len(gate_rows),
        "rolling_252d_positive_rate": rolling_positive_rate,
        "cohort_cagr_wins": cagr_wins,
        "cohort_sharpe_wins": sharpe_wins,
        "year_relative_return_wins": year_wins,
        "years_compared": int(len(common_years)),
        "negative_regime_wins": negative_wins,
        "negative_regimes_compared": len(negative),
        "positive_regime_noninferior": positive_noninferior,
        "positive_regimes_compared": len(positive),
    }
    return gate_rows, details


def main():
    contract = _verify_preregistration()
    scored = _build_score_panel()
    daily = _daily_ic(scored)
    periods = _build_periods(scored)
    cohorts = base._cohort_summary(periods)
    portfolio = base._portfolio_summary(cohorts)
    years = base._year_summary(periods)
    regimes = base._regime_summary(periods)

    gate_rows = []
    summaries = []
    for candidate_id in CANDIDATES:
        rows, details = _gate_candidate(
            candidate_id, daily, cohorts, portfolio, years, regimes
        )
        gate_rows.extend(rows)
        candidate_periods = periods[periods["candidate_id"] == candidate_id]
        details["mean_transition_notional"] = float(
            candidate_periods["transition_notional"].mean()
        )
        details["mean_cost_drag"] = float(
            candidate_periods["transaction_cost_drag"].mean()
        )
        details["all_gates_passed"] = details["gates_passed"] == details["gates_total"]
        summaries.append(details)

    gate_df = pd.DataFrame(gate_rows)
    summary_df = pd.DataFrame(summaries)
    passers = summary_df[summary_df["all_gates_passed"]].sort_values(
        ["mean_transition_notional", "candidate_id"],
        ascending=[True, True],
    )
    selected = None if passers.empty else str(passers.iloc[0]["candidate_id"])
    decision = (
        "ELIGIBLE_FOR_SEPARATE_FREEZE_AUDIT"
        if selected is not None else "DO_NOT_FREEZE"
    )

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    periods.to_csv(PERIOD_PATH, index=False)
    cohorts.to_csv(COHORT_PATH, index=False)
    portfolio.to_csv(PORTFOLIO_PATH, index=False)
    years.to_csv(YEAR_PATH, index=False)
    regimes.to_csv(REGIME_PATH, index=False)
    daily.to_csv(DAILY_IC_PATH, index=False)
    gate_df.to_csv(GATE_PATH, index=False)
    summary_df.to_csv(CANDIDATE_SUMMARY_PATH, index=False)

    manifest = {
        "research_version": "stock_v10_cycle3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "preregistered_development_only_transition_efficiency_evaluation",
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "candidate_ids": CANDIDATES,
        "baseline": BASELINE,
        "selection_rule": contract["selection_rule"],
        "selected_candidate": selected,
        "decision": decision,
        "original_v10_protected_boundary_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "fresh_future_holdout_boundary_utc": contract["provisional_fresh_future_holdout"]["boundary_utc"],
        "candidate_frozen": False,
        "freeze_audit_completed": False,
        "holdout_activated": False,
        "original_holdout_outcomes_read": False,
        "fresh_holdout_outcomes_read": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("STOCK V10 CYCLE 3 — PREREGISTERED DEVELOPMENT EVALUATION")
    print("=" * 104)
    print(f"Contract SHA-256: {EXPECTED_CONTRACT_SHA256}")
    print(f"Original protected boundary: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print(summary_df[[
        "candidate_id", "gates_passed", "gates_total",
        "mean_transition_notional", "mean_cost_drag",
        "negative_regime_wins", "positive_regime_noninferior",
        "all_gates_passed",
    ]].to_string(index=False))
    print(f"\nDecision: {decision}")
    print(f"Selected candidate: {selected or 'NONE'}")
    print("Candidate frozen: NO | holdout activated/scored: NO")
    print("Original/fresh holdout outcomes read: NO")
    print("V8/production modified: NO | brokerage orders: OFF")


if __name__ == "__main__":
    main()
