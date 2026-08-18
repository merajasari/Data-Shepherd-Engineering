"""Apply isolated Stock V6 Phase 3 development-only economic validation."""

from pathlib import Path


PHASE3 = Path("ml/v6/phase3.py")


def main():
    PHASE3.parent.mkdir(parents=True, exist_ok=True)
    PHASE3.write_text(r'''"""Stock V6 Phase 3: development-only economic portfolio validation.

Purpose
-------
Translate the strongest Phase 2 development ranking model (Elastic Net) into a
small, pre-registered family of realistic portfolio policies without touching
the final holdout. This phase does not tune thresholds or select a production
candidate.

Economic contract
-----------------
* Model: Elastic Net only, chosen from Phase 2 development diagnostics.
* Candidate universe: 100 stocks; SPY remains benchmark/core context only.
* Policies: Top-3, Top-5, and Top-10. These are diagnostics, not a search grid.
* Capital structure: 60% SPY core + 40% stock sleeve, equally weighted inside
  the selected Top-N.
* Rebalance cadence: every 5 trading sessions on a non-overlapping grid.
* Signals are formed after the completed decision session.
* Entry/exit prices are the next trading-session open.
* Total modeled friction: 10 bps per traded notional per side
  (5 bps transaction cost + 5 bps slippage).
* Turnover costs are charged only on changed stock-sleeve notional; the 60% SPY
  core is initialized once per fold and then held.
* Every fold starts from normalized equity 1.0. Fold metrics are evaluated
  independently to avoid pretending disconnected validation folds are one live
  account history.

Research safety
---------------
The final holdout beginning 2026-02-01 is never read or scored. Frozen V5, V4
paper trading, dashboard runtime, crypto tracks, and brokerage settings are not
modified.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "data-ingestion"))

from v5_symbols import V5_BENCHMARK_SYMBOL  # noqa: E402


PHASE = 3
MODEL_ID = "elastic_net"
TOP_COUNTS = (3, 5, 10)
CORE_WEIGHT = 0.60
STOCK_SLEEVE_WEIGHT = 0.40
COST_BPS_PER_SIDE = 10.0
COST_RATE = COST_BPS_PER_SIDE / 10_000.0
REBALANCE_STEP = 5
FUTURE_HOLDOUT_START_UTC = pd.Timestamp("2026-02-01", tz="UTC")

PHASE1_PANEL = Path("data/model/v6/phase1/research_panel.parquet")
PHASE2_PREDICTIONS = Path("data/model/v6/phase2/predictions.parquet")
OUTPUT_ROOT = Path("data/model/v6/phase3")
DECISIONS_PATH = OUTPUT_ROOT / "portfolio_decisions.parquet"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
SUMMARY_PATH = OUTPUT_ROOT / "metrics_summary.csv"
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"
FEATURE_ROOT = Path("data/features/stocks")


def _load_open_series(symbol: str) -> pd.DataFrame:
    path = FEATURE_ROOT / symbol / f"{symbol}_features.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing feature history for {symbol}: {path}")
    frame = pd.read_parquet(path, columns=["timestamp_utc", "open"]).copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.sort_values("timestamp_utc").drop_duplicates("timestamp_utc")
    return frame


def _execution_returns(symbol: str) -> pd.DataFrame:
    """Return decision-date -> next-open-to-open-5-sessions-later return."""
    frame = _load_open_series(symbol).reset_index(drop=True)
    frame["decision_timestamp_utc"] = frame["timestamp_utc"].shift(1)
    frame["entry_timestamp_utc"] = frame["timestamp_utc"]
    frame["exit_timestamp_utc"] = frame["timestamp_utc"].shift(-REBALANCE_STEP)
    frame["execution_return"] = frame["open"].shift(-REBALANCE_STEP) / frame["open"] - 1.0
    out = frame[
        [
            "decision_timestamp_utc",
            "entry_timestamp_utc",
            "exit_timestamp_utc",
            "execution_return",
        ]
    ].dropna().copy()
    return out


def _load_inputs():
    if not PHASE1_PANEL.exists():
        raise FileNotFoundError(f"Missing V6 Phase 1 panel: {PHASE1_PANEL}")
    if not PHASE2_PREDICTIONS.exists():
        raise FileNotFoundError(f"Missing V6 Phase 2 predictions: {PHASE2_PREDICTIONS}")

    panel = pd.read_parquet(PHASE1_PANEL)
    predictions = pd.read_parquet(PHASE2_PREDICTIONS)
    predictions["timestamp_utc"] = pd.to_datetime(predictions["timestamp_utc"], utc=True)

    predictions = predictions[
        (predictions["model_id"] == MODEL_ID)
        & (predictions["timestamp_utc"] < FUTURE_HOLDOUT_START_UTC)
    ].copy()

    if predictions.empty:
        raise RuntimeError("No development Elastic Net predictions available")
    if (predictions["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
        raise AssertionError("Future holdout leaked into Phase 3 predictions")

    required = {"timestamp_utc", "symbol", "fold_id", "predicted_score"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError("Phase 2 predictions missing: " + ", ".join(missing))

    symbols = sorted(predictions["symbol"].unique())
    if len(symbols) != 100:
        raise RuntimeError(f"Expected 100 prediction symbols, found {len(symbols)}")

    return panel, predictions, symbols


def _build_execution_map(symbols):
    frames = []
    for symbol in [*symbols, V5_BENCHMARK_SYMBOL]:
        x = _execution_returns(symbol)
        x.insert(0, "symbol", symbol)
        frames.append(x)
    execution = pd.concat(frames, ignore_index=True)
    execution["decision_timestamp_utc"] = pd.to_datetime(
        execution["decision_timestamp_utc"], utc=True
    )
    return execution


def _non_overlapping_dates(fold_predictions: pd.DataFrame):
    dates = pd.Index(sorted(fold_predictions["timestamp_utc"].unique()))
    return dates[::REBALANCE_STEP]


def _max_drawdown(period_returns):
    if not period_returns:
        return 0.0
    wealth = np.cumprod(1.0 + np.asarray(period_returns, dtype=float))
    running = np.maximum.accumulate(np.r_[1.0, wealth])
    series = np.r_[1.0, wealth]
    return float(np.min(series / running - 1.0))


def _risk_metrics(period_returns):
    r = np.asarray(period_returns, dtype=float)
    if len(r) == 0:
        return {"mean_period_return": np.nan, "volatility": np.nan, "sharpe_like": np.nan, "sortino_like": np.nan}
    mean = float(np.mean(r))
    vol = float(np.std(r, ddof=1)) if len(r) > 1 else 0.0
    downside = r[r < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    annual_factor = np.sqrt(252.0 / REBALANCE_STEP)
    sharpe = mean / vol * annual_factor if vol > 0 else np.nan
    sortino = mean / downside_std * annual_factor if downside_std > 0 else np.nan
    return {
        "mean_period_return": mean,
        "volatility": vol,
        "sharpe_like": float(sharpe) if np.isfinite(sharpe) else np.nan,
        "sortino_like": float(sortino) if np.isfinite(sortino) else np.nan,
    }


def _simulate_fold(fold_id, fold_pred, execution, top_n):
    selected_dates = _non_overlapping_dates(fold_pred)
    previous_weights = {}
    strategy_returns = []
    spy_returns = []
    rows = []
    total_cost = 0.0
    total_turnover = 0.0
    trade_actions = 0

    spy_exec = execution[execution["symbol"] == V5_BENCHMARK_SYMBOL].set_index(
        "decision_timestamp_utc"
    )

    for decision_date in selected_dates:
        if decision_date >= FUTURE_HOLDOUT_START_UTC:
            raise AssertionError("Holdout date reached in Phase 3")

        daily = fold_pred[fold_pred["timestamp_utc"] == decision_date].copy()
        daily = daily.sort_values("predicted_score", ascending=False)
        chosen = daily.head(top_n)["symbol"].tolist()
        if len(chosen) != top_n:
            continue

        desired_weight = STOCK_SLEEVE_WEIGHT / top_n
        desired = {s: desired_weight for s in chosen}
        all_symbols = set(previous_weights) | set(desired)
        turnover = sum(abs(desired.get(s, 0.0) - previous_weights.get(s, 0.0)) for s in all_symbols)
        # One-way traded fraction of total portfolio. A complete replacement of
        # the 40% sleeve is 80% absolute weight change but 40% one-way turnover.
        one_way_turnover = turnover / 2.0 if previous_weights else STOCK_SLEEVE_WEIGHT
        cost = one_way_turnover * COST_RATE
        actions = sum(1 for s in all_symbols if not np.isclose(desired.get(s, 0.0), previous_weights.get(s, 0.0)))

        period = execution[
            (execution["decision_timestamp_utc"] == decision_date)
            & (execution["symbol"].isin(chosen))
        ]
        if len(period) != top_n:
            continue
        if decision_date not in spy_exec.index:
            continue

        stock_return_map = dict(zip(period["symbol"], period["execution_return"]))
        sleeve_return = float(np.mean([stock_return_map[s] for s in chosen]))
        spy_row = spy_exec.loc[decision_date]
        if isinstance(spy_row, pd.DataFrame):
            spy_row = spy_row.iloc[0]
        spy_return = float(spy_row["execution_return"])

        gross = CORE_WEIGHT * spy_return + STOCK_SLEEVE_WEIGHT * sleeve_return
        net = gross - cost

        strategy_returns.append(net)
        spy_returns.append(spy_return)
        total_cost += cost
        total_turnover += one_way_turnover
        trade_actions += actions

        entry_ts = period["entry_timestamp_utc"].min()
        exit_ts = period["exit_timestamp_utc"].max()
        rows.append(
            {
                "fold_id": fold_id,
                "model_id": MODEL_ID,
                "top_n": top_n,
                "decision_timestamp_utc": decision_date,
                "entry_timestamp_utc": entry_ts,
                "exit_timestamp_utc": exit_ts,
                "selected_symbols": chosen,
                "stock_sleeve_return": sleeve_return,
                "spy_return": spy_return,
                "gross_strategy_return": gross,
                "turnover": one_way_turnover,
                "modeled_cost": cost,
                "net_strategy_return": net,
            }
        )
        previous_weights = desired

    strategy_equity = float(np.prod(1.0 + np.asarray(strategy_returns))) if strategy_returns else 1.0
    spy_equity = float(np.prod(1.0 + np.asarray(spy_returns))) if spy_returns else 1.0
    metrics = _risk_metrics(strategy_returns)
    spy_metrics = _risk_metrics(spy_returns)

    result = {
        "model_id": MODEL_ID,
        "top_n": top_n,
        "fold_id": fold_id,
        "rebalance_periods": len(strategy_returns),
        "trade_actions": trade_actions,
        "average_turnover": total_turnover / len(strategy_returns) if strategy_returns else np.nan,
        "total_modeled_cost_fraction": total_cost,
        "strategy_return": strategy_equity - 1.0,
        "spy_return": spy_equity - 1.0,
        "excess_ending_equity": strategy_equity - spy_equity,
        "max_drawdown": _max_drawdown(strategy_returns),
        "spy_max_drawdown": _max_drawdown(spy_returns),
        "positive_period_fraction": float(np.mean(np.asarray(strategy_returns) > 0)) if strategy_returns else np.nan,
        **metrics,
        "spy_volatility": spy_metrics["volatility"],
    }
    return result, rows


def main():
    _, predictions, symbols = _load_inputs()
    execution = _build_execution_map(symbols)

    fold_results = []
    decision_rows = []

    for top_n in TOP_COUNTS:
        for fold_id, fold_pred in predictions.groupby("fold_id", sort=True):
            result, rows = _simulate_fold(fold_id, fold_pred, execution, top_n)
            fold_results.append(result)
            decision_rows.extend(rows)

    fold_metrics = pd.DataFrame(fold_results)
    decisions = pd.DataFrame(decision_rows)
    if decisions.empty:
        raise RuntimeError("Phase 3 produced no economic decisions")

    summary_rows = []
    for top_n, group in fold_metrics.groupby("top_n"):
        positive = group["excess_ending_equity"] > 0
        summary_rows.append(
            {
                "model_id": MODEL_ID,
                "top_n": int(top_n),
                "folds": int(len(group)),
                "rebalance_periods": int(group["rebalance_periods"].sum()),
                "trade_actions": int(group["trade_actions"].sum()),
                "mean_fold_strategy_return": float(group["strategy_return"].mean()),
                "median_fold_strategy_return": float(group["strategy_return"].median()),
                "mean_fold_spy_return": float(group["spy_return"].mean()),
                "mean_excess_ending_equity": float(group["excess_ending_equity"].mean()),
                "median_excess_ending_equity": float(group["excess_ending_equity"].median()),
                "positive_excess_fold_fraction": float(positive.mean()),
                "positive_excess_folds": int(positive.sum()),
                "mean_max_drawdown": float(group["max_drawdown"].mean()),
                "worst_max_drawdown": float(group["max_drawdown"].min()),
                "mean_sharpe_like": float(group["sharpe_like"].mean()),
                "mean_sortino_like": float(group["sortino_like"].mean()),
                "mean_turnover": float(group["average_turnover"].mean()),
                "total_modeled_cost_fraction_across_folds": float(group["total_modeled_cost_fraction"].sum()),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("top_n")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    decisions.to_parquet(DECISIONS_PATH, index=False)
    fold_metrics.to_csv(FOLD_METRICS_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)

    manifest = {
        "research_version": "v6",
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "development_only_economic_portfolio_validation",
        "model_id": MODEL_ID,
        "candidate_count": 100,
        "benchmark_symbol": V5_BENCHMARK_SYMBOL,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_scored": False,
        "policy_family": {
            "top_counts": list(TOP_COUNTS),
            "core_weight": CORE_WEIGHT,
            "stock_sleeve_weight": STOCK_SLEEVE_WEIGHT,
            "rebalance_every_trading_sessions": REBALANCE_STEP,
            "execution": "decision after completed session; next trading-session open entry; open-to-open 5-session holding period",
            "transaction_cost_bps_per_side": 5.0,
            "slippage_bps_per_side": 5.0,
            "total_friction_bps_per_traded_notional_per_side": COST_BPS_PER_SIDE,
            "policy_selection_in_phase3": False,
        },
        "outputs": {
            "decisions": str(DECISIONS_PATH),
            "fold_metrics": str(FOLD_METRICS_PATH),
            "metrics_summary": str(SUMMARY_PATH),
        },
        "research_safety": {
            "v4_modified": False,
            "v5_modified": False,
            "paper_portfolio_modified": False,
            "paper_journal_modified": False,
            "crypto_tracks_modified": False,
            "threshold_tuning": False,
            "portfolio_policy_optimization": False,
            "candidate_frozen": False,
            "future_holdout_scored": False,
            "brokerage_orders": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("STOCK V6 PHASE 3")
    print("=" * 104)
    print("Model: Elastic Net | 100-stock universe | 60% SPY core / 40% stock sleeve")
    print("Execution: next-session open | 5-session non-overlapping holds | 10 bps traded-notional friction")
    print()
    print("===== POLICY SUMMARY =====")
    print(summary.to_string(index=False))
    print()
    print("===== FOLD METRICS =====")
    print(fold_metrics.to_string(index=False))
    print()
    print(f"Future holdout begins: {FUTURE_HOLDOUT_START_UTC.isoformat()}")
    print("Holdout scored: False")
    print("No policy selection, threshold tuning, candidate freeze, or brokerage orders.")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
    print("[APPLY] ml/v6/phase3.py")
    print()
    print("Stock V6 Phase 3 economic validation patch complete.")
    print("Development-only Elastic Net portfolio diagnostics for pre-registered Top-3/5/10 policies.")
    print("Uses next-session opens, non-overlapping 5-session holds, turnover, and explicit friction.")
    print("The 2026-02-01+ holdout remains untouched; no policy is selected or frozen.")


if __name__ == "__main__":
    main()
