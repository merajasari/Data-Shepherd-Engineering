"""Supersede the V4 90-day reconstruction with a daily expanding-history refit.

The 90-day window controls only what is simulated/displayed.  Each historical
V4 decision inside that window is fit from all causally eligible prior V4
history, with a 5-trading-session purge between the last training date and the
decision date.  The generated curve remains reconstructed/simulation-only and
never modifies the genuine paper journal or portfolio state.
"""

from pathlib import Path

RUNNER = Path("ml/run_v4_90d_reconstruction.py")

RUNNER_TEXT = r'''"""Build a leakage-safe 90-day reconstructed V4 portfolio curve.

Training contract
-----------------
* 90 days is only the simulated/displayed portfolio window.
* Every historical decision refits the V4 cross-sectional logistic model from
  all eligible prior V4 history available at that point.
* A five-trading-session purge is retained between training and the decision.
* Same-session cross-sectional normalization is allowed because it uses only
  contemporaneous features across the configured V4 universe.
* A decision made after a completed trading session is executed at the next
  trading-session open.

Portfolio contract
------------------
* Start reconstructed window at $100,000.
* 60% permanent SPY core.
* 40% V4 sleeve: five selected names, 8% target each.
* 10 bps modeled entry and exit friction.
* Existing V4 names are kept; only names leaving the Top-5 are sold/replaced.

Safety
------
This writes only data/paper_trading/v4_reconstructed_90d.json.
It never changes the genuine paper portfolio, genuine journal, frozen models,
or brokerage settings.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.append("data-ingestion")
from symbols import SYMBOLS


FEATURE_COLUMNS = [
    "daily_return",
    "return_2d",
    "return_3d",
    "return_5d",
    "return_10d",
    "return_20d",
    "return_60d",
    "price_vs_sma_7",
    "price_vs_sma_20",
    "price_vs_sma_50",
    "price_vs_sma_200",
    "sma_7_vs_sma_20",
    "sma_20_vs_sma_50",
    "sma_50_vs_sma_200",
    "intraday_range",
    "open_close_range",
    "volume_ratio",
    "volume_change_5d",
    "volatility_5d",
    "volatility_20d",
    "volatility_ratio_5_20",
    "trend_20_50",
    "trend_50_200",
    "distance_from_20d_high",
    "distance_from_20d_low",
    "rsi_centered",
]

STARTING_EQUITY = 100_000.0
CORE_WEIGHT = 0.60
V4_WEIGHT = 0.08
ENTRY_COST = 0.001
EXIT_COST = 0.001
PURGE_GAP = 5
DISPLAY_DAYS = 90
L2 = 0.001
TOP_COUNT = 5

OUT = Path("data/paper_trading/v4_reconstructed_90d.json")
STATE = Path("data/paper_trading/portfolio.json")


def _utc_index(values):
    return pd.to_datetime(values, utc=True)


def load_symbol_frame(symbol: str) -> pd.DataFrame:
    path = Path(f"data/features/stocks/{symbol}/{symbol}_features.parquet")
    if not path.exists():
        raise FileNotFoundError(f"Missing feature history: {path}")

    columns = [
        "timestamp_utc",
        "open",
        "close",
        "forward_return_5d",
        *FEATURE_COLUMNS,
    ]
    df = pd.read_parquet(path, columns=columns).copy()
    df["timestamp_utc"] = _utc_index(df["timestamp_utc"])
    return df.set_index("timestamp_utc").sort_index()


def finite_row(values) -> bool:
    arr = np.asarray(values, dtype=float)
    return bool(np.isfinite(arr).all())


def build_cross_sections(frames: dict[str, pd.DataFrame]):
    model_symbols = list(SYMBOLS)
    common_dates = None
    for symbol in model_symbols:
        idx = frames[symbol].index
        common_dates = idx if common_dates is None else common_dates.intersection(idx)
    common_dates = list(common_dates.sort_values())

    x_by_date = {}
    y_by_date = {}
    usable_feature_dates = []
    target_dates = []

    for date in common_dates:
        raw = []
        forwards = []
        valid_features = True
        valid_targets = True

        for symbol in model_symbols:
            row = frames[symbol].loc[date]
            vals = [row[c] for c in FEATURE_COLUMNS]
            if not finite_row(vals):
                valid_features = False
                break
            raw.append(vals)

            fwd = row["forward_return_5d"]
            if fwd is None or not np.isfinite(float(fwd)):
                valid_targets = False
            forwards.append(float(fwd) if fwd is not None and np.isfinite(float(fwd)) else np.nan)

        if not valid_features:
            continue

        matrix = np.asarray(raw, dtype=float)
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        stds[stds == 0] = 1.0
        xs = (matrix - means) / stds
        x_by_date[date] = xs
        usable_feature_dates.append(date)

        if valid_targets:
            order = np.argsort(np.asarray(forwards, dtype=float))[::-1]
            y = np.zeros(len(model_symbols), dtype=float)
            y[order[:TOP_COUNT]] = 1.0
            y_by_date[date] = y
            target_dates.append(date)

    return model_symbols, usable_feature_dates, x_by_date, y_by_date, target_dates


def objective_and_grad(params, X, y):
    w = params[:-1]
    b = params[-1]
    scores = X @ w + b
    loss = np.mean(np.logaddexp(0.0, scores) - y * scores) + 0.5 * L2 * float(w @ w)
    clipped = np.clip(scores, -500.0, 500.0)
    p = 1.0 / (1.0 + np.exp(-clipped))
    error = p - y
    grad_w = (X.T @ error) / len(X) + L2 * w
    grad_b = float(np.mean(error))
    grad = np.concatenate([grad_w, np.asarray([grad_b])])
    return float(loss), grad


def transform_warm_start(prev_params, prev_mean, prev_std, new_mean, new_std):
    if prev_params is None:
        return np.zeros(len(FEATURE_COLUMNS) + 1, dtype=float)
    old_w = prev_params[:-1]
    old_b = prev_params[-1]
    raw_coef = old_w / prev_std
    raw_intercept = old_b - float(prev_mean @ raw_coef)
    new_w = raw_coef * new_std
    new_b = raw_intercept + float(new_mean @ raw_coef)
    return np.concatenate([new_w, np.asarray([new_b])])


def fit_for_decision(
    decision_date,
    decision_index,
    feature_dates,
    x_by_date,
    y_by_date,
    prev_fit,
):
    # Existing V4 fold semantics: five entire trading sessions are purged.
    train_end_exclusive = decision_index - PURGE_GAP
    if train_end_exclusive <= 0:
        raise RuntimeError("Insufficient history before decision date")

    eligible_train_dates = [
        d for d in feature_dates[:train_end_exclusive]
        if d in y_by_date
    ]
    if not eligible_train_dates:
        raise RuntimeError("No target-complete training history")

    X_train = np.vstack([x_by_date[d] for d in eligible_train_dates])
    y_train = np.concatenate([y_by_date[d] for d in eligible_train_dates])

    mean = X_train.mean(axis=0)
    std = X_train.std(axis=0)
    std[std == 0] = 1.0
    Xs = (X_train - mean) / std

    if prev_fit is None:
        init = np.zeros(Xs.shape[1] + 1, dtype=float)
    else:
        init = transform_warm_start(
            prev_fit["params"],
            prev_fit["mean"],
            prev_fit["std"],
            mean,
            std,
        )

    result = minimize(
        fun=lambda p: objective_and_grad(p, Xs, y_train),
        x0=init,
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 250, "ftol": 1e-11, "gtol": 1e-7},
    )
    if not result.success:
        raise RuntimeError(
            f"Daily expanding fit failed for {decision_date}: {result.message}"
        )

    X_decision = (x_by_date[decision_date] - mean) / std
    scores = X_decision @ result.x[:-1] + result.x[-1]
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(scores, -500.0, 500.0)))
    ranked_idx = np.argsort(probabilities)[::-1][:TOP_COUNT]

    return {
        "params": np.asarray(result.x, dtype=float),
        "mean": mean,
        "std": std,
        "train_start": eligible_train_dates[0],
        "train_end": eligible_train_dates[-1],
        "training_dates": len(eligible_train_dates),
        "training_rows": int(len(X_train)),
        "top_five_indices": ranked_idx.tolist(),
        "probabilities": probabilities,
        "iterations": int(getattr(result, "nit", 0)),
    }


def load_paper_start():
    if not STATE.exists():
        return None
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = state.get("strategy_started_at") or state.get("created_at")
    if not raw:
        return None
    ts = pd.Timestamp(raw)
    return ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")


def px(frames, symbol, date, field):
    try:
        value = float(frames[symbol].at[date, field])
    except Exception:
        return None
    return value if np.isfinite(value) and value > 0 else None


def main():
    model_symbols = list(SYMBOLS)
    price_symbols = sorted(set(model_symbols + ["SPY"]))
    frames = {symbol: load_symbol_frame(symbol) for symbol in price_symbols}

    (
        model_symbols,
        feature_dates,
        x_by_date,
        y_by_date,
        target_dates,
    ) = build_cross_sections(frames)

    if len(feature_dates) < 300:
        raise RuntimeError("Unexpectedly short V4 feature history")

    latest = feature_dates[-1]
    requested_start = latest - pd.Timedelta(days=DISPLAY_DAYS)
    paper_start = load_paper_start()

    display_entry_dates = [
        d for d in feature_dates
        if d >= requested_start and (paper_start is None or d < paper_start)
    ]
    if len(display_entry_dates) < 2:
        raise RuntimeError("Not enough pre-paper dates in the 90-day display window")

    date_index = {d: i for i, d in enumerate(feature_dates)}

    # We need the prior completed session's decision for every displayed entry.
    required_decision_dates = []
    for entry_date in display_entry_dates:
        idx = date_index[entry_date]
        if idx <= 0:
            continue
        decision_date = feature_dates[idx - 1]
        required_decision_dates.append(decision_date)
    required_decision_dates = sorted(set(required_decision_dates))

    fits = {}
    previous_fit = None
    print("V4 DAILY EXPANDING-HISTORY REFITS")
    print("=" * 88)
    for n, decision_date in enumerate(required_decision_dates, start=1):
        idx = date_index[decision_date]
        fit = fit_for_decision(
            decision_date,
            idx,
            feature_dates,
            x_by_date,
            y_by_date,
            previous_fit,
        )
        fits[decision_date] = fit
        previous_fit = fit
        if n == 1 or n == len(required_decision_dates) or n % 10 == 0:
            print(
                f"{n:3d}/{len(required_decision_dates)}  decision={decision_date.date()}  "
                f"train={fit['train_start'].date()}..{fit['train_end'].date()}  "
                f"rows={fit['training_rows']:,}  iter={fit['iterations']}"
            )

    first_entry = None
    for entry_date in display_entry_dates:
        idx = date_index[entry_date]
        if idx <= 0:
            continue
        decision_date = feature_dates[idx - 1]
        fit = fits.get(decision_date)
        if fit is None:
            continue
        selected = [model_symbols[i] for i in fit["top_five_indices"]]
        if all(px(frames, s, entry_date, "open") for s in ["SPY", *selected]):
            first_entry = entry_date
            break
    if first_entry is None:
        raise RuntimeError("Could not find a valid reconstructed starting session")

    cash = STARTING_EQUITY
    positions = {}
    trade_actions = 0
    modeled_friction = 0.0

    def buy(symbol, sleeve, budget, date):
        nonlocal cash, trade_actions, modeled_friction
        price = px(frames, symbol, date, "open")
        if price is None or budget <= 0:
            return False
        effective = price * (1.0 + ENTRY_COST)
        shares = budget / effective
        used = shares * effective
        fee = shares * price * ENTRY_COST
        cash -= used
        modeled_friction += fee
        trade_actions += 1
        positions[symbol] = {"shares": shares, "sleeve": sleeve}
        return True

    first_idx = date_index[first_entry]
    first_decision = feature_dates[first_idx - 1]
    first_fit = fits[first_decision]
    first_top = [model_symbols[i] for i in first_fit["top_five_indices"]]

    buy("SPY", "core", STARTING_EQUITY * CORE_WEIGHT, first_entry)
    for symbol in first_top:
        buy(symbol, "v4", STARTING_EQUITY * V4_WEIGHT, first_entry)

    history = []
    selected_history = []

    for entry_date in [d for d in display_entry_dates if d >= first_entry]:
        idx = date_index[entry_date]
        if idx <= 0:
            continue
        decision_date = feature_dates[idx - 1]
        fit = fits.get(decision_date)
        if fit is None:
            continue
        target = [model_symbols[i] for i in fit["top_five_indices"]]

        if entry_date != first_entry:
            current_v4 = {s for s, p in positions.items() if p["sleeve"] == "v4"}
            target_set = set(target)

            for symbol in sorted(current_v4 - target_set):
                price = px(frames, symbol, entry_date, "open")
                if price is None:
                    continue
                pos = positions.pop(symbol)
                gross = pos["shares"] * price
                fee = gross * EXIT_COST
                cash += gross - fee
                modeled_friction += fee
                trade_actions += 1

            open_equity = cash
            for symbol, pos in positions.items():
                price = px(frames, symbol, entry_date, "open")
                if price is not None:
                    open_equity += pos["shares"] * price

            current_v4 = {s for s, p in positions.items() if p["sleeve"] == "v4"}
            for symbol in target:
                if symbol in current_v4:
                    continue
                budget = min(open_equity * V4_WEIGHT, cash)
                buy(symbol, "v4", budget, entry_date)

        close_equity = cash
        valid = True
        for symbol, pos in positions.items():
            price = px(frames, symbol, entry_date, "close")
            if price is None:
                valid = False
                break
            close_equity += pos["shares"] * price
        if not valid:
            continue

        history.append(
            {
                "timestamp": entry_date.isoformat(),
                "equity": round(close_equity, 2),
                "reconstructed": True,
                "history_type": "RECONSTRUCTED_90D_DAILY_EXPANDING",
                "decision_date": decision_date.isoformat(),
                "top_five": target,
            }
        )
        selected_history.append(target)

    if not history:
        raise RuntimeError("No reconstructed equity observations were produced")

    first_fit_used = fits[feature_dates[date_index[first_entry] - 1]]
    last_entry = pd.Timestamp(history[-1]["timestamp"])
    last_decision = feature_dates[date_index[last_entry] - 1]
    last_fit_used = fits[last_decision]

    payload = {
        "history_type": "RECONSTRUCTED_90D_DAILY_EXPANDING",
        "simulation_only": True,
        "training_policy": "DAILY_REFIT_EXPANDING_ALL_ELIGIBLE_PRIOR_V4_HISTORY",
        "solver": "L-BFGS-B exact V4 logistic objective with warm-start coordinate transform",
        "historical_training_start": first_fit_used["train_start"].isoformat(),
        "historical_training_end": last_fit_used["train_end"].isoformat(),
        "latest_training_rows": last_fit_used["training_rows"],
        "latest_training_dates": last_fit_used["training_dates"],
        "purge_gap_trading_sessions": PURGE_GAP,
        "requested_calendar_days": DISPLAY_DAYS,
        "display_window_only": True,
        "model_universe_size": len(model_symbols),
        "model_universe": model_symbols,
        "start": history[0]["timestamp"],
        "end": history[-1]["timestamp"],
        "observations": len(history),
        "starting_equity": STARTING_EQUITY,
        "ending_equity": history[-1]["equity"],
        "total_return_pct": round((history[-1]["equity"] / STARTING_EQUITY - 1.0) * 100.0, 4),
        "trade_actions": trade_actions,
        "modeled_friction": round(modeled_friction, 2),
        "paper_start_boundary": paper_start.isoformat() if paper_start is not None else None,
        "execution_rule": "decision after completed session; execute at next trading-session open",
        "portfolio_contract": {
            "spy_core_weight": CORE_WEIGHT,
            "v4_sleeve_weight": 0.40,
            "selected_stock_weight": V4_WEIGHT,
            "selected_count": TOP_COUNT,
            "entry_cost_bps": int(ENTRY_COST * 10000),
            "exit_cost_bps": int(EXIT_COST * 10000),
        },
        "genuine_paper_journal_modified": False,
        "portfolio_state_modified": False,
        "brokerage_orders": False,
        "history": history,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print("V4 90-DAY DAILY-EXPANDING RECONSTRUCTED HISTORY")
    print("=" * 88)
    print("Training policy:", payload["training_policy"])
    print("Historical training start:", payload["historical_training_start"])
    print("Historical training end:", payload["historical_training_end"])
    print("Latest training rows:", f"{payload['latest_training_rows']:,}")
    print("Purge gap:", payload["purge_gap_trading_sessions"], "trading sessions")
    print("Display start:", payload["start"])
    print("Display end:", payload["end"])
    print("Observations:", payload["observations"])
    print("Ending equity:", f"${payload['ending_equity']:,.2f}")
    print("Return:", f"{payload['total_return_pct']:+.4f}%")
    print("Trade actions:", payload["trade_actions"])
    print("Modeled friction:", f"${payload['modeled_friction']:,.2f}")
    print("Paper boundary:", payload["paper_start_boundary"])
    print("Model universe size:", payload["model_universe_size"])
    print()
    print("RECONSTRUCTED/SIMULATION ONLY. Genuine paper journal unchanged. No brokerage orders.")


if __name__ == "__main__":
    main()
'''


def main() -> None:
    RUNNER.write_text(RUNNER_TEXT, encoding="utf-8")
    print("[APPLY] daily expanding all-history V4 reconstruction runner")
    print()
    print("V4 90-day daily-expanding reconstruction patch complete.")
    print("The display window remains 90 days, while every historical decision refits")
    print("from all causally eligible prior V4 history with a 5-session purge.")
    print("No genuine paper history, portfolio state, frozen model, or brokerage setting is changed.")


if __name__ == "__main__":
    main()
