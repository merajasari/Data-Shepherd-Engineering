"""Purged walk-forward evaluation for registered V9 tuning candidates.

All scoring is development-only and ends before the untouched V9 future
holdout. The evaluator cannot freeze, promote, or deploy a candidate and never
places brokerage orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.v9.config import FUTURE_HOLDOUT_START_UTC, RESEARCH_VERSION
from ml.v9.phase2 import _build_score_panel
from ml.v9.phase3 import (
    PHASE1_PANEL,
    _annualized_stats,
    _load_execution_data,
    _transition_notional,
)
from ml.v9.tuning_registry import (
    HOLD_SESSION_VALUES,
    OBJECTIVE_ID,
    PRIMARY_COST_BPS,
    build_candidate_registry,
)

OUTPUT_ROOT = Path("data/model/v9/tuning/evaluation")
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
LEADERBOARD_PATH = OUTPUT_ROOT / "leaderboard.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

FOLD_COUNT = 5
VALIDATION_SESSIONS = 252
MIN_TRAINING_SESSIONS = 504
PURGE_SESSIONS = max(HOLD_SESSION_VALUES)


def make_folds(decision_dates) -> list[dict]:
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(decision_dates, utc=True).unique()))
    dates = dates[dates < FUTURE_HOLDOUT_START_UTC]
    first_validation = MIN_TRAINING_SESSIONS + PURGE_SESSIONS
    available = len(dates) - first_validation
    if available < FOLD_COUNT * 63:
        raise RuntimeError(
            "Insufficient development history for five walk-forward folds: "
            f"{len(dates)} sessions"
        )

    block = min(VALIDATION_SESSIONS, available // FOLD_COUNT)
    start = len(dates) - block * FOLD_COUNT
    folds = []
    for fold_id in range(FOLD_COUNT):
        val_start_i = start + fold_id * block
        val_end_i = val_start_i + block - 1
        train_end_i = val_start_i - PURGE_SESSIONS - 1
        if train_end_i < MIN_TRAINING_SESSIONS - 1:
            raise RuntimeError("Purged fold leaves insufficient training history")
        folds.append(
            {
                "fold_id": fold_id + 1,
                "training_start_utc": dates[0],
                "training_end_utc": dates[train_end_i],
                "purge_start_utc": dates[train_end_i + 1],
                "purge_end_utc": dates[val_start_i - 1],
                "validation_start_utc": dates[val_start_i],
                "validation_end_utc": dates[val_end_i],
                "training_sessions": train_end_i + 1,
                "purge_sessions": PURGE_SESSIONS,
                "validation_sessions": block,
            }
        )
    return folds


def _load_development_inputs():
    if not PHASE1_PANEL.exists():
        raise FileNotFoundError(f"Missing {PHASE1_PANEL}; run V9 Phase 1 first")
    panel = pd.read_parquet(PHASE1_PANEL).copy()
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    if panel["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("V9 Phase-1 panel reaches the future holdout boundary")

    scores = _build_score_panel(panel)
    scores["timestamp_utc"] = pd.to_datetime(scores["timestamp_utc"], utc=True)
    if scores["timestamp_utc"].max() >= FUTURE_HOLDOUT_START_UTC:
        raise RuntimeError("Score panel reaches the V9 future holdout boundary")

    symbols = scores["symbol"].astype(str).unique().tolist()
    opens, trading_dates, date_to_idx = _load_execution_data(symbols)
    return scores, opens, trading_dates, date_to_idx


def _simulate_candidate_fold(candidate, fold, scores, opens, trading_dates, date_to_idx):
    config = candidate["config"]
    score_id = config["score_id"]
    top_n = int(config["top_n"])
    hold = int(config["holding_sessions"])
    cost_bps = int(config["cost_bps_per_dollar_traded"])
    if cost_bps != PRIMARY_COST_BPS:
        raise RuntimeError("Transaction-cost tuning is forbidden")

    candidate_scores = scores[scores["score_id"] == score_id]
    candidate_scores = candidate_scores[
        candidate_scores["timestamp_utc"].between(
            fold["validation_start_utc"],
            fold["validation_end_utc"],
        )
    ]
    previous_by_cohort = {}
    rows = []
    for decision_ts, day in candidate_scores.groupby("timestamp_utc", sort=True):
        decision_ts = pd.Timestamp(decision_ts)
        i = date_to_idx.get(decision_ts)
        if i is None:
            continue
        entry_i = i + 1
        exit_i = entry_i + hold
        if exit_i >= len(trading_dates):
            continue
        entry_ts = trading_dates[entry_i]
        exit_ts = trading_dates[exit_i]
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
            p0, p1 = float(series.loc[entry_ts]), float(series.loc[exit_ts])
            if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0):
                valid = False
                break
            stock_returns.append(p1 / p0 - 1.0)
        spy = opens["SPY"]
        if (
            not valid
            or entry_ts not in spy.index
            or exit_ts not in spy.index
        ):
            continue
        spy0, spy1 = float(spy.loc[entry_ts]), float(spy.loc[exit_ts])
        if not (np.isfinite(spy0) and np.isfinite(spy1) and spy0 > 0):
            continue

        cohort = int(i % hold)
        previous = previous_by_cohort.get(cohort)
        traded = _transition_notional(previous, picks)
        cost_rate = traded * cost_bps / 10000.0
        gross = float(np.mean(stock_returns))
        net = float((1.0 + gross) * (1.0 - cost_rate) - 1.0)
        spy_return = float(spy1 / spy0 - 1.0)
        rows.append(
            {
                "cohort_offset": cohort,
                "net_portfolio_return": net,
                "spy_return": spy_return,
                "net_relative_return": net - spy_return,
                "transition_notional": traded,
            }
        )
        previous_by_cohort[cohort] = picks

    periods = pd.DataFrame(rows)
    if periods.empty:
        raise RuntimeError(
            f"{candidate['candidate_id']} produced no periods in fold "
            f"{fold['fold_id']}"
        )

    cohort_rows = []
    for _, group in periods.groupby("cohort_offset", sort=True):
        stats = _annualized_stats(group["net_portfolio_return"])
        cohort_rows.append(
            {
                **stats,
                "mean_net_relative_return": float(
                    group["net_relative_return"].mean()
                ),
                "relative_hit_rate": float(
                    (group["net_relative_return"] > 0).mean()
                ),
                "mean_turnover": float(group["transition_notional"].mean()),
                "periods": len(group),
            }
        )
    cohorts = pd.DataFrame(cohort_rows)
    periods_per_year = 252.0 / hold
    annualized_relative_return = float(
        cohorts["mean_net_relative_return"].mean() * periods_per_year
    )
    return {
        "candidate_id": candidate["candidate_id"],
        "fold_id": fold["fold_id"],
        "score_id": score_id,
        "top_n": top_n,
        "holding_sessions": hold,
        "validation_start_utc": fold["validation_start_utc"],
        "validation_end_utc": fold["validation_end_utc"],
        "purge_sessions": fold["purge_sessions"],
        "cohorts": int(len(cohorts)),
        "periods": int(cohorts["periods"].sum()),
        "mean_cagr": float(cohorts["cagr"].mean()),
        "mean_sharpe": float(cohorts["sharpe"].mean()),
        "mean_sortino": float(cohorts["sortino"].mean()),
        "mean_max_drawdown": float(cohorts["max_drawdown"].mean()),
        "mean_calmar": float(cohorts["calmar"].mean()),
        "annualized_relative_return": annualized_relative_return,
        "relative_hit_rate": float(cohorts["relative_hit_rate"].mean()),
        "mean_turnover": float(cohorts["mean_turnover"].mean()),
    }


def build_leaderboard(fold_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for candidate_id, group in fold_metrics.groupby("candidate_id", sort=True):
        if len(group) != FOLD_COUNT:
            raise RuntimeError(f"{candidate_id} does not have {FOLD_COUNT} folds")
        first = group.iloc[0]
        mean_sharpe = float(group["mean_sharpe"].mean())
        mean_sortino = float(group["mean_sortino"].mean())
        mean_calmar = float(group["mean_calmar"].mean())
        mean_relative = float(group["annualized_relative_return"].mean())
        sharpe_stability_penalty = float(group["mean_sharpe"].std(ddof=0))
        positive_fold_rate = float((group["annualized_relative_return"] > 0).mean())
        objective = (
            0.35 * mean_sharpe
            + 0.15 * mean_sortino
            + 0.20 * mean_calmar
            + 0.20 * mean_relative
            + 0.10 * positive_fold_rate
            - 0.20 * sharpe_stability_penalty
        )
        rows.append(
            {
                "candidate_id": candidate_id,
                "score_id": first["score_id"],
                "top_n": int(first["top_n"]),
                "holding_sessions": int(first["holding_sessions"]),
                "folds": len(group),
                "objective_score": objective,
                "mean_cagr": float(group["mean_cagr"].mean()),
                "mean_sharpe": mean_sharpe,
                "worst_fold_sharpe": float(group["mean_sharpe"].min()),
                "sharpe_stability_penalty": sharpe_stability_penalty,
                "mean_sortino": mean_sortino,
                "mean_max_drawdown": float(
                    group["mean_max_drawdown"].mean()
                ),
                "mean_calmar": mean_calmar,
                "mean_annualized_relative_return": mean_relative,
                "positive_relative_fold_rate": positive_fold_rate,
                "mean_relative_hit_rate": float(
                    group["relative_hit_rate"].mean()
                ),
                "mean_turnover": float(group["mean_turnover"].mean()),
                "status": "EVALUATED_DEVELOPMENT_ONLY",
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["objective_score", "worst_fold_sharpe", "candidate_id"],
            ascending=[False, False, True],
        )
        .reset_index(drop=True)
        .assign(development_rank=lambda frame: range(1, len(frame) + 1))
    )


def main():
    registry = build_candidate_registry()
    scores, opens, trading_dates, date_to_idx = _load_development_inputs()
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
                )
            )
        print(f"[EVALUATED] {candidate['candidate_id']}")

    fold_metrics = pd.DataFrame(rows)
    leaderboard = build_leaderboard(fold_metrics)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    fold_metrics.to_csv(FOLD_METRICS_PATH, index=False)
    leaderboard.to_csv(LEADERBOARD_PATH, index=False)

    best = leaderboard.iloc[0]
    manifest = {
        "research_version": RESEARCH_VERSION,
        "stage": "development_only_purged_walk_forward_tuning",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective_id": OBJECTIVE_ID,
        "candidate_count": len(registry),
        "fold_count": FOLD_COUNT,
        "purge_sessions": PURGE_SESSIONS,
        "best_development_candidate": str(best["candidate_id"]),
        "best_development_objective_score": float(best["objective_score"]),
        "challenger_registered": False,
        "candidate_promoted": False,
        "v9_future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "v9_future_holdout_scored": False,
        "v8_modified": False,
        "v8_holdout_scored": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("STOCK V9 PURGED WALK-FORWARD TUNING")
    print("=" * 96)
    print(f"Candidates evaluated: {len(registry)}")
    print(f"Folds per candidate: {FOLD_COUNT} | purge: {PURGE_SESSIONS} sessions")
    print(
        "Best development candidate: "
        f"{best['candidate_id']} | objective={best['objective_score']:.6f}"
    )
    print(f"Leaderboard: {LEADERBOARD_PATH}")
    print(
        "Development results only. No holdout access, challenger freeze, "
        "promotion, production mutation, or brokerage orders."
    )


if __name__ == "__main__":
    main()
