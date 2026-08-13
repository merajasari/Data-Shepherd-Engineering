"""Crypto V2 Phase 6: pre-registered market-level risk exposure gate.

Phase 5 showed weak but real asset-level absolute-return discrimination while
remaining almost fully invested. Phase 6 tests a different development-only
hypothesis: forecast the next 7-day equal-weight eligible-universe return from
market state observable at decision time. If the predicted market return is
positive, deploy a frozen Phase 3 HGB cross-sectional long-only portfolio;
otherwise hold cash.

The gate threshold is fixed at zero before portfolio evaluation. No regime
threshold search, hyperparameter tuning, leverage, shorting, derivatives,
promotion, or live execution is permitted. Data at or after 2026-09-01 remains
reserved for genuinely future validation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
from sklearn.base import clone

from ml.crypto_v2.config import MODEL_ROOT, RESEARCH_VERSION
from ml.crypto_v2.phase3 import (
    FUTURE_HOLDOUT_START_UTC,
    MIN_CROSS_SECTION_ASSETS,
    enforce_cross_section_breadth,
    make_folds,
    model_definitions,
)

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE5_ROOT = MODEL_ROOT / "phase5"
PHASE6_ROOT = MODEL_ROOT / "phase6"
HORIZON_DAYS = 7
RANK_MODEL_ID = "hist_gradient_boosting"
MARKET_MODEL_ID = "hist_gradient_boosting_market_7d"
MARKET_GATE_THRESHOLD = 0.0
VARIANTS = ("market_gated_top_3", "market_gated_top_5", "market_gated_top_quintile")
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
DAYS_PER_YEAR = 365.0

MARKET_FEATURES = (
    "btc_return_7d",
    "btc_return_14d",
    "btc_return_30d",
    "btc_realized_volatility_14d",
    "btc_realized_volatility_30d",
    "btc_close_to_sma_30",
    "eligible_asset_count",
    "xsec_median_return_7d",
    "xsec_median_return_30d",
    "xsec_median_realized_volatility_30d",
    "xsec_median_drawdown_30d",
    "xsec_median_btc_relative_return_7d",
)


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_inputs(model_root=MODEL_ROOT, phase3_root=PHASE3_ROOT):
    model_root, phase3_root = Path(model_root), Path(phase3_root)
    panel_path = model_root / "research_panel_7d.parquet"
    p3_path = phase3_root / "predictions.parquet"
    p3_manifest = phase3_root / "manifest.json"
    p5_manifest = Path(PHASE5_ROOT) / "manifest.json"
    for p in (panel_path, p3_path, p3_manifest):
        if not p.exists():
            raise FileNotFoundError(str(p))

    panel = pd.read_parquet(panel_path)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    needed = {
        "timestamp_utc", "product_id", "return_1d", "return_7d", "return_30d",
        "realized_volatility_30d", "drawdown_from_high_30d",
        "btc_relative_return_7d", "btc_return_7d", "btc_return_14d",
        "btc_return_30d", "btc_realized_volatility_14d",
        "btc_realized_volatility_30d", "btc_close_to_sma_30",
        "forward_return_7d", "target_endpoint_utc_7d",
    }
    missing = needed - set(panel.columns)
    if missing:
        raise ValueError("7-day panel missing columns: " + ", ".join(sorted(missing)))
    panel = enforce_cross_section_breadth(panel, MIN_CROSS_SECTION_ASSETS)

    p3 = pd.read_parquet(p3_path)
    p3["timestamp_utc"] = pd.to_datetime(p3["timestamp_utc"], utc=True)
    p3 = p3[
        (p3["horizon_days"] == HORIZON_DAYS)
        & (p3["model_id"] == RANK_MODEL_ID)
        & (p3["split"] == "development")
    ].copy()
    if p3.empty:
        raise ValueError("Frozen Phase 3 7-day HGB development predictions are required")
    if p3.duplicated(["timestamp_utc", "product_id", "fold_id"]).any():
        raise ValueError("Duplicate frozen Phase 3 HGB keys")

    paths = {
        "research_panel_7d": panel_path,
        "phase3_predictions": p3_path,
        "phase3_manifest": p3_manifest,
    }
    if p5_manifest.exists():
        paths["phase5_manifest"] = p5_manifest
    return paths, panel, p3


def build_market_frame(panel):
    """Create one leakage-safe market-state row per decision timestamp."""
    rows = []
    for ts, day in panel.groupby("timestamp_utc", sort=True):
        btc = day[day["product_id"] == "BTC-USD"]
        if btc.empty:
            continue
        btc = btc.iloc[0]
        target_endpoint = pd.to_datetime(day["target_endpoint_utc_7d"], utc=True).max()
        rows.append({
            "timestamp_utc": ts,
            "target_endpoint_utc_7d": target_endpoint,
            "btc_return_7d": btc["btc_return_7d"],
            "btc_return_14d": btc["btc_return_14d"],
            "btc_return_30d": btc["btc_return_30d"],
            "btc_realized_volatility_14d": btc["btc_realized_volatility_14d"],
            "btc_realized_volatility_30d": btc["btc_realized_volatility_30d"],
            "btc_close_to_sma_30": btc["btc_close_to_sma_30"],
            "eligible_asset_count": int(day["product_id"].nunique()),
            "xsec_median_return_7d": day["return_7d"].median(),
            "xsec_median_return_30d": day["return_30d"].median(),
            "xsec_median_realized_volatility_30d": day["realized_volatility_30d"].median(),
            "xsec_median_drawdown_30d": day["drawdown_from_high_30d"].median(),
            "xsec_median_btc_relative_return_7d": day["btc_relative_return_7d"].median(),
            "actual_market_forward_return_7d": day["forward_return_7d"].mean(),
        })
    out = pd.DataFrame(rows).sort_values("timestamp_utc").reset_index(drop=True)
    if out[list(MARKET_FEATURES)].isna().any().any():
        raise ValueError("Market frame contains missing pre-decision features")
    return out


def build_market_predictions(market_frame):
    """Walk-forward market forecasts with the same purge calendar as Phase 3."""
    definition = model_definitions()["hist_gradient_boosting"]
    rows = []
    folds = make_folds(market_frame["timestamp_utc"], HORIZON_DAYS)
    for fold in folds:
        if fold.split != "development":
            continue
        train = market_frame[market_frame["timestamp_utc"].between(
            fold.train_start_utc, fold.train_end_utc
        )].copy()
        validation = market_frame[market_frame["timestamp_utc"].between(
            fold.validation_start_utc, fold.validation_end_utc
        )].copy()
        if train.empty or validation.empty:
            raise ValueError(f"Empty market train/validation partition in {fold.fold_id}")
        if pd.to_datetime(train["target_endpoint_utc_7d"], utc=True).max() >= validation["timestamp_utc"].min():
            raise ValueError(f"Market target leakage across {fold.fold_id}")
        fitted = clone(definition).fit(
            train[list(MARKET_FEATURES)], train["actual_market_forward_return_7d"]
        )
        pred = fitted.predict(validation[list(MARKET_FEATURES)])
        out = validation[[
            "timestamp_utc", "actual_market_forward_return_7d"
        ]].copy()
        out["fold_id"] = fold.fold_id
        out["split"] = fold.split
        out["predicted_market_forward_return_7d"] = pred
        out["market_risk_on"] = out["predicted_market_forward_return_7d"] > MARKET_GATE_THRESHOLD
        rows.append(out)
    result = pd.concat(rows, ignore_index=True).sort_values("timestamp_utc").reset_index(drop=True)
    if result.duplicated(["timestamp_utc", "fold_id"]).any():
        raise ValueError("Duplicate Phase 6 market prediction keys")
    return result


def combine_with_rank_predictions(market_predictions, phase3_predictions):
    out = phase3_predictions.merge(
        market_predictions[[
            "timestamp_utc", "fold_id", "predicted_market_forward_return_7d",
            "actual_market_forward_return_7d", "market_risk_on",
        ]],
        on=["timestamp_utc", "fold_id"], how="inner", validate="many_to_one",
    )
    if out.empty:
        raise ValueError("No overlap between market gate and frozen Phase 3 rankings")
    return out.sort_values(["timestamp_utc", "product_id"]).reset_index(drop=True)


def selected_products(day, variant):
    if not bool(day["market_risk_on"].iloc[0]):
        return []
    ranked = day.sort_values(["predicted_score", "product_id"], ascending=[False, True])
    if variant == "market_gated_top_3":
        n = 3
    elif variant == "market_gated_top_5":
        n = 5
    elif variant == "market_gated_top_quintile":
        n = max(1, len(ranked) // 5)
    else:
        raise ValueError(f"Unknown variant: {variant}")
    return ranked["product_id"].head(n).tolist()


def _return_map(panel):
    frame = panel[["timestamp_utc", "product_id", "return_1d"]].copy()
    return {ts: dict(zip(g["product_id"], g["return_1d"])) for ts, g in frame.groupby("timestamp_utc", sort=True)}


def _rebalance_dates(timestamps):
    dates = pd.DatetimeIndex(pd.to_datetime(pd.Series(timestamps).unique(), utc=True)).sort_values()
    if dates.empty:
        return set()
    out, due = [], dates[0]
    while due <= dates[-1]:
        later = dates[dates >= due]
        if len(later) == 0:
            break
        chosen = later[0]
        out.append(chosen)
        due = chosen + pd.Timedelta(days=HORIZON_DAYS)
    return set(out)


def simulate(predictions, panel, variant, cost_bps):
    signal_dates = pd.DatetimeIndex(predictions["timestamp_utc"].unique()).sort_values()
    schedule = _rebalance_dates(signal_dates)
    signal_map = {ts: g for ts, g in predictions.groupby("timestamp_utc", sort=True)}
    returns = _return_map(panel)
    dates = pd.DatetimeIndex(panel["timestamp_utc"].unique()).sort_values()
    dates = dates[(dates >= signal_dates.min()) & (dates <= signal_dates.max())]

    values, cash, equity = {}, STARTING_EQUITY, STARTING_EQUITY
    rows = []
    for i, ts in enumerate(dates):
        previous = equity
        turnover = 0.0
        transaction_cost = 0.0
        if i > 0 and values:
            day_returns = returns.get(ts, {})
            missing = [p for p in values if pd.isna(day_returns.get(p, np.nan))]
            if missing:
                current_w = {p: v / equity for p, v in values.items()} if equity > 0 else {}
                forced_turnover = 0.5 * sum(abs(current_w.get(p, 0.0)) for p in missing)
                forced_cost = equity * forced_turnover * cost_bps / 10_000.0
                cash += sum(values[p] for p in missing) - forced_cost
                for p in missing:
                    values.pop(p, None)
                turnover += forced_turnover
                transaction_cost += forced_cost
            for p in list(values):
                values[p] *= 1.0 + float(day_returns[p])
            equity = cash + sum(values.values())

        is_rebalance = ts in schedule and ts in signal_map
        risk_on = np.nan
        selected_count = np.nan
        if is_rebalance:
            day = signal_map[ts]
            risk_on = bool(day["market_risk_on"].iloc[0])
            selected = selected_products(day, variant)
            selected_count = len(selected)
            target = {p: 1.0 / len(selected) for p in selected} if selected else {}
            current = {p: v / equity for p, v in values.items()} if equity > 0 else {}
            names = set(current) | set(target)
            reb_turnover = 0.5 * sum(abs(target.get(p, 0.0) - current.get(p, 0.0)) for p in names)
            reb_cost = equity * reb_turnover * cost_bps / 10_000.0
            post = max(0.0, equity - reb_cost)
            values = {p: post * w for p, w in target.items()}
            cash = post - sum(values.values())
            equity = cash + sum(values.values())
            turnover += reb_turnover
            transaction_cost += reb_cost

        rows.append({
            "timestamp_utc": ts,
            "variant": variant,
            "cost_bps_round_trip": float(cost_bps),
            "is_rebalance": bool(is_rebalance),
            "market_risk_on": risk_on,
            "selected_asset_count": selected_count,
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "net_return": equity / previous - 1.0 if previous > 0 else np.nan,
            "cash_weight": cash / equity if equity > 0 else np.nan,
            "equity": equity,
        })
    return pd.DataFrame(rows)


def summarize(path):
    net = pd.to_numeric(path["net_return"], errors="coerce").dropna()
    ending = float(path["equity"].iloc[-1])
    obs = max(0, len(path) - 1)
    ann = ending ** (DAYS_PER_YEAR / obs) - 1.0 if obs and ending > 0 else np.nan
    vol = float(net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    sharpe = float(net.mean() / net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    running = path["equity"].cummax()
    dd = path["equity"] / running - 1.0
    reb = path[path["is_rebalance"]]
    return {
        "variant": path["variant"].iloc[0],
        "cost_bps_round_trip": path["cost_bps_round_trip"].iloc[0],
        "observation_count": obs,
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "annualized_return": ann,
        "annualized_volatility": vol,
        "sharpe_like": sharpe,
        "maximum_drawdown": float(dd.min()),
        "average_turnover_per_rebalance": float(reb["turnover"].mean()) if len(reb) else 0.0,
        "total_turnover": float(path["turnover"].sum()),
        "number_of_rebalances": int(len(reb)),
        "market_risk_on_rate": float(reb["market_risk_on"].mean()) if len(reb) else np.nan,
        "cash_rebalance_rate": float(reb["selected_asset_count"].eq(0).mean()) if len(reb) else np.nan,
        "average_cash_weight": float(path["cash_weight"].mean()),
        "positive_period_rate": float(net.gt(0).mean()),
    }


def run_phase6(model_root=MODEL_ROOT, phase3_root=PHASE3_ROOT, output_root=PHASE6_ROOT):
    paths, panel, p3 = load_inputs(model_root, phase3_root)
    hashes_before = {k: _sha256(v) for k, v in paths.items()}
    market = build_market_frame(panel)
    market_predictions = build_market_predictions(market)
    combined = combine_with_rank_predictions(market_predictions, p3)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    market_path = output_root / "market_gate_predictions.parquet"
    market_predictions.to_parquet(market_path, index=False)

    all_daily, metrics = [], []
    for variant in VARIANTS:
        for cost in ROUND_TRIP_COST_BPS:
            path = simulate(combined, panel, variant, cost)
            all_daily.append(path)
            metrics.append(summarize(path))
    daily = pd.concat(all_daily, ignore_index=True)
    metric_frame = pd.DataFrame(metrics)
    daily.to_csv(output_root / "portfolio_daily.csv", index=False)
    metric_frame.to_csv(output_root / "portfolio_metrics.csv", index=False)

    diagnostics = (
        market_predictions.groupby("fold_id")
        .agg(
            days=("timestamp_utc", "size"),
            risk_on_rate=("market_risk_on", "mean"),
            mean_predicted_market_return=("predicted_market_forward_return_7d", "mean"),
            mean_actual_market_return=("actual_market_forward_return_7d", "mean"),
        )
        .reset_index()
    )
    diagnostics.to_csv(output_root / "market_gate_diagnostics_by_fold.csv", index=False)

    hashes_after = {k: _sha256(v) for k, v in paths.items()}
    if hashes_after != hashes_before:
        raise RuntimeError("Frozen Phase 2-5 inputs changed during Phase 6")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 6,
        "stage": "pre_registered_market_exposure_gate",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "disposition_of_phase5": "RESEARCH_ONLY_NOT_PROMOTED",
        "hypothesis": (
            "A development-only market-level 7-day forecast can decide whether to hold crypto risk; "
            "when risk-on, frozen Phase 3 HGB scores rank assets; otherwise the portfolio holds cash."
        ),
        "market_target": "equal-weight mean forward_return_7d across the eligible contemporaneous universe",
        "market_features": list(MARKET_FEATURES),
        "market_model_id": MARKET_MODEL_ID,
        "market_gate_threshold": MARKET_GATE_THRESHOLD,
        "rank_model_id": RANK_MODEL_ID,
        "variants": list(VARIANTS),
        "cost_bps_round_trip": list(ROUND_TRIP_COST_BPS),
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": "Data at or after 2026-09-01 remains untouched by current Phase 6 evaluation.",
        "policy": (
            "development-only pre-registered market gate; no threshold search, regime filter search, "
            "hyperparameter tuning, leverage, shorting, derivatives, promotion, or live execution"
        ),
        "source_hashes": hashes_before,
        "outputs": {
            "market_gate_predictions": str(market_path),
            "portfolio_daily": str(output_root / "portfolio_daily.csv"),
            "portfolio_metrics": str(output_root / "portfolio_metrics.csv"),
            "market_gate_diagnostics_by_fold": str(output_root / "market_gate_diagnostics_by_fold.csv"),
        },
        "next_step": (
            "Review development-only market-gate discrimination and portfolio outcomes against frozen Phase 4 benchmarks. "
            "Do not tune the market threshold, feature set, rank model, portfolio variants, or future holdout based on these results."
        ),
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest, market_predictions, metric_frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE6_ROOT)
    args = parser.parse_args(argv)
    manifest, predictions, metrics = run_phase6(args.model_root, args.phase3_root, args.output_root)
    print(json.dumps({
        "phase": manifest["phase"],
        "market_prediction_days": int(len(predictions)),
        "market_risk_on_rate": float(predictions["market_risk_on"].mean()),
        "metric_rows": int(len(metrics)),
        "market_gate_threshold": manifest["market_gate_threshold"],
        "future_holdout_start_utc": manifest["future_holdout_start_utc"],
        "outputs": manifest["outputs"],
        "next_step": manifest["next_step"],
    }, indent=2))


if __name__ == "__main__":
    main()
