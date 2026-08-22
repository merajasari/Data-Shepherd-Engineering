"""Purged walk-forward evaluator for V10 risk-controlled tuning Cycle 2."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v10.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION
from ml.v10.phase3 import _discover_feature_files
from ml.v10.auto_tuning_evaluator import (
    _annualized_stats,
    _load_development_inputs,
)
from ml.v10.auto_tuning_cycle2_registry import (
    CYCLE_ID,
    MANDATORY_CONFIRMATION_GATES,
    OBJECTIVE_ID,
    PRIMARY_COST_BPS,
    build_candidate_registry,
)

OUTPUT_ROOT = Path("data/model/v10/auto_tuning/cycle2/evaluation")
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
LEADERBOARD_PATH = OUTPUT_ROOT / "leaderboard.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

FOLD_COUNT = 5
VALIDATION_SESSIONS = 252
MIN_TRAINING_SESSIONS = 504
PURGE_SESSIONS = 20


def make_folds(decision_dates):
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(decision_dates, utc=True).unique()))
    dates = dates[dates < FUTURE_HOLDOUT_START_UTC]
    first_validation = MIN_TRAINING_SESSIONS + PURGE_SESSIONS
    available = len(dates) - first_validation
    if available < FOLD_COUNT * 63:
        raise RuntimeError(
            "Insufficient development history for Cycle-2 folds: "
            f"{len(dates)} sessions"
        )
    block = min(VALIDATION_SESSIONS, available // FOLD_COUNT)
    start = len(dates) - block * FOLD_COUNT
    folds = []
    for fold_id in range(FOLD_COUNT):
        validation_start_i = start + fold_id * block
        validation_end_i = validation_start_i + block - 1
        training_end_i = validation_start_i - PURGE_SESSIONS - 1
        if training_end_i < MIN_TRAINING_SESSIONS - 1:
            raise RuntimeError("Cycle-2 purge leaves insufficient training history")
        folds.append(
            {
                "fold_id": fold_id + 1,
                "training_end_utc": dates[training_end_i],
                "purge_start_utc": dates[training_end_i + 1],
                "purge_end_utc": dates[validation_start_i - 1],
                "validation_start_utc": dates[validation_start_i],
                "validation_end_utc": dates[validation_end_i],
                "purge_sessions": PURGE_SESSIONS,
                "validation_sessions": block,
            }
        )
    return folds


def _load_spy_trend():
    files = _discover_feature_files()
    path = files.get("SPY")
    if path is None:
        raise FileNotFoundError("SPY feature parquet is required for Cycle 2")
    frame = pd.read_parquet(path).copy()
    timestamp_column = (
        "timestamp_utc" if "timestamp_utc" in frame.columns else "timestamp"
    )
    if timestamp_column not in frame.columns or "close" not in frame.columns:
        raise ValueError("SPY feature data requires timestamp and close")
    trend = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                frame[timestamp_column],
                utc=True,
                errors="coerce",
            ),
            "spy_close": pd.to_numeric(frame["close"], errors="coerce"),
        }
    )
    trend = (
        trend.dropna(subset=["timestamp_utc", "spy_close"])
        .sort_values("timestamp_utc")
        .drop_duplicates("timestamp_utc", keep="last")
        .set_index("timestamp_utc")
    )
    trend["spy_sma200"] = trend["spy_close"].rolling(
        200,
        min_periods=200,
    ).mean()
    return trend


def _target_exposure(config, decision_ts, spy_trend):
    overlay = config["risk_overlay"]
    if overlay == "NONE":
        return 1.0
    if decision_ts not in spy_trend.index:
        raise RuntimeError(f"Missing SPY trend state for {decision_ts}")
    row = spy_trend.loc[decision_ts]
    if not np.isfinite(row["spy_sma200"]):
        raise RuntimeError(f"SPY SMA200 unavailable for {decision_ts}")
    below = bool(row["spy_close"] < row["spy_sma200"])
    return float(
        config["below_sma200_target_exposure"]
        if below
        else config["above_sma200_target_exposure"]
    )


def _transition_notional(previous, new_symbols, new_exposure, top_n):
    new_weights = {
        symbol: new_exposure / top_n
        for symbol in new_symbols
    }
    if previous is None:
        return float(sum(abs(weight) for weight in new_weights.values()))
    previous_symbols, previous_exposure = previous
    old_weights = {
        symbol: previous_exposure / top_n
        for symbol in previous_symbols
    }
    names = set(old_weights) | set(new_weights)
    return float(
        sum(
            abs(new_weights.get(symbol, 0.0) - old_weights.get(symbol, 0.0))
            for symbol in names
        )
    )


def _simulate_candidate_fold(
    candidate,
    fold,
    scores,
    opens,
    trading_dates,
    date_to_idx,
    spy_trend,
):
    config = candidate["config"]
    score_id = config["score_id"]
    top_n = int(config["top_n"])
    hold = int(config["holding_sessions"])
    if int(config["cost_bps_per_dollar_traded"]) != PRIMARY_COST_BPS:
        raise RuntimeError("Cycle-2 transaction-cost tuning is forbidden")

    selected = scores[
        (scores["score_id"] == score_id)
        & scores["timestamp_utc"].between(
            fold["validation_start_utc"],
            fold["validation_end_utc"],
        )
    ]
    previous_by_cohort = {}
    rows = []
    for decision_ts, day in selected.groupby("timestamp_utc", sort=True):
        decision_ts = pd.Timestamp(decision_ts)
        i = date_to_idx.get(decision_ts)
        if i is None:
            continue
        entry_i, exit_i = i + 1, i + 1 + hold
        if exit_i >= len(trading_dates):
            continue
        entry_ts, exit_ts = trading_dates[entry_i], trading_dates[exit_i]
        if (
            exit_ts > fold["validation_end_utc"]
            or exit_ts >= FUTURE_HOLDOUT_START_UTC
        ):
            continue

        picks = (
            day.sort_values(["score", "symbol"], ascending=[False, True])
            .head(top_n)["symbol"]
            .astype(str)
            .tolist()
        )
        if len(picks) != top_n:
            continue

        stock_returns = []
        valid = True
        for symbol in picks:
            series = opens[symbol]
            if entry_ts not in series.index or exit_ts not in series.index:
                valid = False
                break
            start, end = float(series.loc[entry_ts]), float(series.loc[exit_ts])
            if not (np.isfinite(start) and np.isfinite(end) and start > 0):
                valid = False
                break
            stock_returns.append(end / start - 1.0)
        spy = opens["SPY"]
        if not valid or entry_ts not in spy.index or exit_ts not in spy.index:
            continue
        spy_start, spy_end = float(spy.loc[entry_ts]), float(spy.loc[exit_ts])
        if not (np.isfinite(spy_start) and np.isfinite(spy_end) and spy_start > 0):
            continue

        exposure = _target_exposure(config, decision_ts, spy_trend)
        if exposure not in (0.0, 0.5, 1.0):
            raise RuntimeError(f"Undeclared target exposure: {exposure}")
        cohort = int(i % hold)
        previous = previous_by_cohort.get(cohort)
        turnover = _transition_notional(previous, picks, exposure, top_n)
        gross_stock_return = float(np.mean(stock_returns))
        gross_portfolio_return = exposure * gross_stock_return
        cost_rate = turnover * PRIMARY_COST_BPS / 10000.0
        net_return = float(
            (1.0 + gross_portfolio_return) * (1.0 - cost_rate) - 1.0
        )
        spy_return = float(spy_end / spy_start - 1.0)
        rows.append(
            {
                "cohort_offset": cohort,
                "net_portfolio_return": net_return,
                "spy_return": spy_return,
                "net_relative_return": net_return - spy_return,
                "turnover": turnover,
                "target_exposure": exposure,
            }
        )
        previous_by_cohort[cohort] = (picks, exposure)

    periods = pd.DataFrame(rows)
    if periods.empty:
        raise RuntimeError(
            f"{candidate['candidate_id']} produced no Cycle-2 periods in "
            f"fold {fold['fold_id']}"
        )

    cohort_rows = []
    for _, group in periods.groupby("cohort_offset", sort=True):
        stats = _annualized_stats(group["net_portfolio_return"], hold)
        cohort_rows.append(
            {
                **stats,
                "mean_relative_return": float(
                    group["net_relative_return"].mean()
                ),
                "relative_hit_rate": float(
                    (group["net_relative_return"] > 0).mean()
                ),
                "mean_turnover": float(group["turnover"].mean()),
                "mean_exposure": float(group["target_exposure"].mean()),
                "periods": int(len(group)),
            }
        )
    cohorts = pd.DataFrame(cohort_rows)
    return {
        "candidate_id": candidate["candidate_id"],
        "fold_id": fold["fold_id"],
        "score_id": score_id,
        "top_n": top_n,
        "holding_sessions": hold,
        "risk_overlay": config["risk_overlay"],
        "validation_start_utc": fold["validation_start_utc"],
        "validation_end_utc": fold["validation_end_utc"],
        "purge_sessions": fold["purge_sessions"],
        "periods": int(cohorts["periods"].sum()),
        "mean_cagr": float(cohorts["cagr"].mean()),
        "mean_sharpe": float(cohorts["sharpe"].mean()),
        "mean_sortino": float(cohorts["sortino"].mean()),
        "mean_max_drawdown": float(cohorts["max_drawdown"].mean()),
        "mean_calmar": float(cohorts["calmar"].mean()),
        "annualized_relative_return": float(
            cohorts["mean_relative_return"].mean() * (252.0 / hold)
        ),
        "relative_hit_rate": float(cohorts["relative_hit_rate"].mean()),
        "mean_turnover": float(cohorts["mean_turnover"].mean()),
        "mean_exposure": float(cohorts["mean_exposure"].mean()),
    }


def build_leaderboard(fold_metrics):
    rows = []
    for candidate_id, group in fold_metrics.groupby("candidate_id", sort=True):
        if len(group) != FOLD_COUNT:
            raise RuntimeError(f"{candidate_id} does not have five Cycle-2 folds")
        first = group.iloc[0]
        mean_sharpe = float(group["mean_sharpe"].mean())
        worst_sharpe = float(group["mean_sharpe"].min())
        mean_sortino = float(group["mean_sortino"].mean())
        mean_calmar = float(group["mean_calmar"].mean())
        mean_relative = float(group["annualized_relative_return"].mean())
        mean_drawdown = float(group["mean_max_drawdown"].mean())
        positive_fold_rate = float(
            (group["annualized_relative_return"] > 0).mean()
        )
        stability_penalty = float(group["mean_sharpe"].std(ddof=0))
        mean_turnover = float(group["mean_turnover"].mean())

        objective = (
            0.25 * mean_sharpe
            + 0.15 * worst_sharpe
            + 0.10 * mean_sortino
            + 0.15 * mean_calmar
            + 0.15 * mean_relative
            + 0.10 * positive_fold_rate
            + 0.10 * (1.0 + mean_drawdown)
            - 0.20 * stability_penalty
            - 0.10 * mean_turnover
        )
        preliminary_eligible = bool(
            positive_fold_rate == 1.0
            and worst_sharpe
            >= MANDATORY_CONFIRMATION_GATES["minimum_worst_fold_sharpe"]
            and mean_drawdown
            >= MANDATORY_CONFIRMATION_GATES["minimum_primary_max_drawdown"]
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "score_id": first["score_id"],
                "top_n": int(first["top_n"]),
                "holding_sessions": int(first["holding_sessions"]),
                "risk_overlay": first["risk_overlay"],
                "folds": len(group),
                "objective_score": objective,
                "preliminary_gate_eligible": preliminary_eligible,
                "mean_cagr": float(group["mean_cagr"].mean()),
                "mean_sharpe": mean_sharpe,
                "worst_fold_sharpe": worst_sharpe,
                "sharpe_stability_penalty": stability_penalty,
                "mean_sortino": mean_sortino,
                "mean_max_drawdown": mean_drawdown,
                "mean_calmar": mean_calmar,
                "mean_annualized_relative_return": mean_relative,
                "positive_relative_fold_rate": positive_fold_rate,
                "mean_relative_hit_rate": float(
                    group["relative_hit_rate"].mean()
                ),
                "mean_turnover": mean_turnover,
                "mean_exposure": float(group["mean_exposure"].mean()),
                "status": "EVALUATED_DEVELOPMENT_ONLY",
            }
        )
    leaderboard = pd.DataFrame(rows).sort_values(
        [
            "preliminary_gate_eligible",
            "objective_score",
            "worst_fold_sharpe",
            "candidate_id",
        ],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    leaderboard["development_rank"] = range(1, len(leaderboard) + 1)
    return leaderboard


def main():
    registry = build_candidate_registry()
    scores, opens, trading_dates, date_to_idx = _load_development_inputs()
    spy_trend = _load_spy_trend()
    folds = make_folds(scores["timestamp_utc"])

    rows = []
    for candidate in registry:
        for fold in folds:
            rows.append(
                _simulate_candidate_fold(
                    candidate,
                    fold,
                    scores,
                    opens,
                    trading_dates,
                    date_to_idx,
                    spy_trend,
                )
            )
        print(f"[EVALUATED] {candidate['candidate_id']}")

    fold_metrics = pd.DataFrame(rows)
    leaderboard = build_leaderboard(fold_metrics)
    eligible = leaderboard[leaderboard["preliminary_gate_eligible"]]
    winner = eligible.iloc[0] if not eligible.empty else None

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    fold_metrics.to_csv(FOLD_METRICS_PATH, index=False)
    leaderboard.to_csv(LEADERBOARD_PATH, index=False)
    manifest = {
        "cycle_id": CYCLE_ID,
        "research_version": RESEARCH_VERSION,
        "stage": "development_only_risk_controlled_walk_forward",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective_id": OBJECTIVE_ID,
        "candidate_count": len(registry),
        "fold_count": FOLD_COUNT,
        "purge_sessions": PURGE_SESSIONS,
        "preliminary_eligible_count": int(len(eligible)),
        "best_development_candidate": (
            str(winner["candidate_id"]) if winner is not None else None
        ),
        "best_development_objective_score": (
            float(winner["objective_score"]) if winner is not None else None
        ),
        "candidate_confirmed": False,
        "candidate_promoted": False,
        "v10_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v10_future_holdout_scored": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("STOCK V10 RISK-CONTROLLED TUNING CYCLE 2")
    print("=" * 96)
    print(f"Candidates evaluated: {len(registry)}")
    print(f"Preliminary gate eligible: {len(eligible)}")
    print(
        "Best eligible development candidate: "
        + (
            f"{winner['candidate_id']} | "
            f"objective={winner['objective_score']:.6f}"
            if winner is not None
            else "NONE"
        )
    )
    print(f"Leaderboard: {LEADERBOARD_PATH}")
    print(
        "No holdout access, confirmation, promotion, production mutation, "
        "or brokerage orders."
    )


if __name__ == "__main__":
    main()
