"""Crypto V2 Phase 5: pre-registered two-stage long-only gate hypothesis.

Phase 4 showed that BTC-relative ranking can separate stronger from weaker
altcoins without producing a profitable long-only portfolio. Phase 5 tests a
materially different, pre-registered hypothesis: first estimate 7-day absolute
return using development-only walk-forward training; only assets with predicted
absolute return > 0 may be owned; among passing assets, use the frozen Phase 3
7-day HGB BTC-relative score for ranking. If no asset passes, hold cash.

No Phase 1-4 artifact is rewritten. No regime filter, threshold search,
hyperparameter tuning, leverage, shorting, derivatives, promotion, or live
execution is permitted. Data at or after 2026-09-01 remains reserved for
future validation.
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
    MODEL_FEATURES,
    enforce_cross_section_breadth,
    make_folds,
    model_definitions,
    validate_fold,
)

PHASE3_ROOT = MODEL_ROOT / "phase3"
PHASE4_ROOT = MODEL_ROOT / "phase4"
PHASE5_ROOT = MODEL_ROOT / "phase5"
HORIZON_DAYS = 7
ABSOLUTE_GATE_THRESHOLD = 0.0
RANK_MODEL_ID = "hist_gradient_boosting"
ABSOLUTE_MODEL_ID = "hist_gradient_boosting_absolute_7d"
VARIANTS = ("gated_top_3", "gated_top_5", "gated_top_quintile")
ROUND_TRIP_COST_BPS = (0.0, 10.0, 25.0, 50.0)
STARTING_EQUITY = 1.0
DAYS_PER_YEAR = 365.0

PREDICTION_COLUMNS = [
    "timestamp_utc", "product_id", "fold_id", "split",
    "predicted_absolute_return_7d", "relative_rank_score",
    "passes_absolute_gate", "actual_forward_return_7d",
    "actual_btc_relative_forward_return",
]


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
    phase3_predictions_path = phase3_root / "predictions.parquet"
    phase3_manifest_path = phase3_root / "manifest.json"
    phase4_manifest_path = Path(PHASE4_ROOT) / "manifest.json"
    for path in (panel_path, phase3_predictions_path, phase3_manifest_path):
        if not path.exists():
            raise FileNotFoundError(str(path))

    panel = pd.read_parquet(panel_path)
    panel["timestamp_utc"] = pd.to_datetime(panel["timestamp_utc"], utc=True)
    required = set(MODEL_FEATURES) | {
        "timestamp_utc", "product_id", "forward_return_7d",
        "forward_return_relative_to_btc_7d", "target_endpoint_utc_7d",
    }
    missing = required - set(panel.columns)
    if missing:
        raise ValueError("7-day panel missing columns: " + ", ".join(sorted(missing)))
    panel = enforce_cross_section_breadth(panel, MIN_CROSS_SECTION_ASSETS)

    p3 = pd.read_parquet(phase3_predictions_path)
    p3["timestamp_utc"] = pd.to_datetime(p3["timestamp_utc"], utc=True)
    p3 = p3[
        (p3["horizon_days"] == HORIZON_DAYS)
        & (p3["model_id"] == RANK_MODEL_ID)
        & (p3["split"] == "development")
    ].copy()
    if p3.empty:
        raise ValueError("Frozen Phase 3 7-day HGB development predictions are required")
    key = ["timestamp_utc", "product_id", "fold_id"]
    if p3.duplicated(key).any():
        raise ValueError("Duplicate frozen Phase 3 HGB keys")

    paths = {
        "research_panel_7d": panel_path,
        "phase3_predictions": phase3_predictions_path,
        "phase3_manifest": phase3_manifest_path,
    }
    if phase4_manifest_path.exists():
        paths["phase4_manifest"] = phase4_manifest_path
    return paths, panel, p3


def build_two_stage_predictions(panel, phase3_predictions):
    """Fit only the new absolute-return model; ranking comes from frozen Phase 3."""
    definition = model_definitions()["hist_gradient_boosting"]
    rows = []
    folds = make_folds(panel["timestamp_utc"], HORIZON_DAYS)
    for fold in folds:
        if fold.split != "development":
            continue
        train, validation = validate_fold(fold, panel)
        model = clone(definition).fit(
            train[list(MODEL_FEATURES)], train["forward_return_7d"]
        )
        absolute_score = model.predict(validation[list(MODEL_FEATURES)])
        out = validation[[
            "timestamp_utc", "product_id", "forward_return_7d",
            "forward_return_relative_to_btc_7d",
        ]].copy()
        out["fold_id"] = fold.fold_id
        out["split"] = fold.split
        out["predicted_absolute_return_7d"] = absolute_score
        out = out.merge(
            phase3_predictions[[
                "timestamp_utc", "product_id", "fold_id", "predicted_score"
            ]].rename(columns={"predicted_score": "relative_rank_score"}),
            on=["timestamp_utc", "product_id", "fold_id"],
            how="left", validate="one_to_one",
        )
        if out["relative_rank_score"].isna().any():
            raise ValueError(f"Missing frozen Phase 3 rank scores in {fold.fold_id}")
        out["passes_absolute_gate"] = (
            out["predicted_absolute_return_7d"] > ABSOLUTE_GATE_THRESHOLD
        )
        out = out.rename(columns={
            "forward_return_7d": "actual_forward_return_7d",
            "forward_return_relative_to_btc_7d": "actual_btc_relative_forward_return",
        })
        rows.append(out[PREDICTION_COLUMNS])
    result = pd.concat(rows, ignore_index=True).sort_values(
        ["timestamp_utc", "fold_id", "product_id"]
    ).reset_index(drop=True)
    if result.duplicated(["timestamp_utc", "product_id", "fold_id"]).any():
        raise ValueError("Duplicate Phase 5 prediction keys")
    return result


def selected_products(day, variant):
    passing = day[day["passes_absolute_gate"]].sort_values(
        ["relative_rank_score", "product_id"], ascending=[False, True]
    )
    if passing.empty:
        return []
    if variant == "gated_top_3":
        n = 3
    elif variant == "gated_top_5":
        n = 5
    elif variant == "gated_top_quintile":
        n = max(1, len(day) // 5)
    else:
        raise ValueError(f"Unknown variant: {variant}")
    return passing["product_id"].head(n).tolist()


def _return_map(panel):
    frame = panel[["timestamp_utc", "product_id", "return_1d"]].copy()
    return {
        ts: dict(zip(g["product_id"], g["return_1d"]))
        for ts, g in frame.groupby("timestamp_utc", sort=True)
    }


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
        selected_count = 0
        passing_count = 0
        if is_rebalance:
            day = signal_map[ts]
            passing_count = int(day["passes_absolute_gate"].sum())
            selected = selected_products(day, variant)
            selected_count = len(selected)
            target = ({p: 1.0 / selected_count for p in selected} if selected else {})
            current = ({p: v / equity for p, v in values.items()} if equity > 0 else {})
            names = set(current) | set(target)
            reb_turnover = 0.5 * sum(
                abs(target.get(p, 0.0) - current.get(p, 0.0)) for p in names
            )
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
            "passing_asset_count": passing_count if is_rebalance else np.nan,
            "selected_asset_count": selected_count if is_rebalance else np.nan,
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
    ann = (ending ** (DAYS_PER_YEAR / obs) - 1.0) if obs and ending > 0 else np.nan
    vol = float(net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR)) if len(net) > 1 else np.nan
    sharpe = (
        float(net.mean() / net.std(ddof=1) * np.sqrt(DAYS_PER_YEAR))
        if len(net) > 1 and net.std(ddof=1) > 0 else np.nan
    )
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
        "average_passing_assets": float(reb["passing_asset_count"].mean()) if len(reb) else np.nan,
        "cash_rebalance_rate": float(reb["selected_asset_count"].eq(0).mean()) if len(reb) else np.nan,
        "average_cash_weight": float(path["cash_weight"].mean()),
        "positive_period_rate": float(net.gt(0).mean()),
    }


def run_phase5(model_root=MODEL_ROOT, phase3_root=PHASE3_ROOT, output_root=PHASE5_ROOT):
    paths, panel, phase3_predictions = load_inputs(model_root, phase3_root)
    hashes_before = {k: _sha256(v) for k, v in paths.items()}
    predictions = build_two_stage_predictions(panel, phase3_predictions)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    pred_path = output_root / "two_stage_predictions.parquet"
    predictions.to_parquet(pred_path, index=False)

    daily_paths, metrics = [], []
    for variant in VARIANTS:
        for cost in ROUND_TRIP_COST_BPS:
            path = simulate(predictions, panel, variant, cost)
            daily_paths.append(path)
            metrics.append(summarize(path))
    daily = pd.concat(daily_paths, ignore_index=True)
    metric_frame = pd.DataFrame(metrics)
    daily.to_csv(output_root / "portfolio_daily.csv", index=False)
    metric_frame.to_csv(output_root / "portfolio_metrics.csv", index=False)

    hashes_after = {k: _sha256(v) for k, v in paths.items()}
    if hashes_after != hashes_before:
        raise RuntimeError("Frozen Phase 2-4 inputs changed during Phase 5")

    by_fold = (
        predictions.groupby("fold_id")
        .agg(
            rows=("product_id", "size"),
            gate_pass_rate=("passes_absolute_gate", "mean"),
            mean_predicted_absolute_return=("predicted_absolute_return_7d", "mean"),
            mean_actual_absolute_return=("actual_forward_return_7d", "mean"),
        )
        .reset_index()
    )
    by_fold.to_csv(output_root / "gate_diagnostics_by_fold.csv", index=False)

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": 5,
        "stage": "pre_registered_absolute_gate_hypothesis",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "disposition_of_phase4": "RESEARCH_ONLY_NOT_PROMOTED",
        "hypothesis": (
            "A development-only 7-day absolute-return forecast can act as a cash gate; "
            "among gate-passing assets, the frozen Phase 3 HGB BTC-relative score may "
            "retain useful cross-sectional ordering for a long-only portfolio."
        ),
        "absolute_gate_threshold": ABSOLUTE_GATE_THRESHOLD,
        "threshold_policy": "Fixed at predicted absolute return > 0 before viewing Phase 5 outcomes; no threshold search is permitted.",
        "ranking_source": "Frozen Crypto V2 Phase 3 7-day hist_gradient_boosting predicted_score.",
        "absolute_model": {
            "model_id": ABSOLUTE_MODEL_ID,
            "family_and_hyperparameters": model_definitions()["hist_gradient_boosting"].named_steps["model"].get_params(deep=False),
            "features": list(MODEL_FEATURES),
            "target": "forward_return_7d",
            "folds": "same pre-registered expanding development folds and 7-day purge as Phase 3",
        },
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": "No data at or after 2026-09-01 is evaluated in current Phase 5.",
        "variants": list(VARIANTS),
        "round_trip_cost_bps": list(ROUND_TRIP_COST_BPS),
        "input_hashes": hashes_before,
        "outputs": {
            "predictions": str(pred_path),
            "portfolio_daily": str(output_root / "portfolio_daily.csv"),
            "portfolio_metrics": str(output_root / "portfolio_metrics.csv"),
            "gate_diagnostics_by_fold": str(output_root / "gate_diagnostics_by_fold.csv"),
        },
        "next_step": (
            "Review the pre-registered development-only gate diagnostics and portfolio outcomes. "
            "Do not tune the gate threshold, rank model, variants, costs, or future holdout based on these results."
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return manifest, predictions, daily, metric_frame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=MODEL_ROOT)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE5_ROOT)
    args = parser.parse_args(argv)
    manifest, predictions, _, metrics = run_phase5(
        args.model_root, args.phase3_root, args.output_root
    )
    print(json.dumps({
        "phase": 5,
        "prediction_rows": int(len(predictions)),
        "gate_pass_rate": float(predictions["passes_absolute_gate"].mean()),
        "metric_rows": int(len(metrics)),
        "absolute_gate_threshold": manifest["absolute_gate_threshold"],
        "future_holdout_start_utc": manifest["future_holdout_start_utc"],
        "outputs": manifest["outputs"],
        "next_step": manifest["next_step"],
    }, indent=2))


if __name__ == "__main__":
    main()
