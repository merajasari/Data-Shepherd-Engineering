"""Crypto V4 Phase 3: frozen market-allocation portfolio diagnostics.

Consumes only frozen Crypto V4 Phase 2 out-of-sample development predictions
and the frozen Phase 1 BTC/ALT/CASH allocation dataset.  Phase 3 does not fit or
retune any model.  The pre-registered primary strategy is the Phase 2
HistGradientBoosting classifier with its direct predicted BTC/ALT/CASH class.

Portfolio contract
------------------
* Decision cadence: every 7 calendar days from the first available Phase 2 OOS
  prediction date, choosing the first available decision row at or after each
  due date.
* BTC signal: 100% BTC sleeve for the next 7-day period.
* ALT signal: 100% equal-weight eligible non-BTC sleeve represented by the
  frozen Phase 1 alt_forward_return_7d target construction.
* CASH signal: 100% cash at 0% return.
* Transaction costs: fixed 0/10/25/50 bps scenarios applied to one-way portfolio
  turnover at each rebalance.  Turnover is 0.5 * L1 distance across BTC/ALT/CASH
  sleeve weights, so a full switch between sleeves has turnover 1.0.
* Benchmarks: BTC, ALT equal-weight, and CASH under the same cadence/cost rules.
* No leverage, shorting, derivatives, live execution, threshold search, model
  fitting, or future-holdout evaluation.

The future holdout beginning 2026-09-01 UTC remains untouched.
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

from ml.crypto_v4.phase1 import FUTURE_HOLDOUT_START_UTC, HORIZON_DAYS

RESEARCH_VERSION = "crypto_v4"
PHASE = 3
PHASE1_ROOT = Path("data/model/crypto_v4/phase1")
PHASE2_ROOT = Path("data/model/crypto_v4/phase2")
DATASET_PATH = PHASE1_ROOT / "market_allocation_dataset.parquet"
PHASE1_MANIFEST_PATH = PHASE1_ROOT / "manifest.json"
PREDICTIONS_PATH = PHASE2_ROOT / "predictions.parquet"
PHASE2_MANIFEST_PATH = PHASE2_ROOT / "manifest.json"
OUTPUT_ROOT = Path("data/model/crypto_v4/phase3")
PRIMARY_MODEL_ID = "hist_gradient_boosting"
SLEEVES = ("BTC", "ALT", "CASH")
COST_SCENARIOS_BPS = (0.0, 10.0, 25.0, 50.0)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_hash() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _rebalance_dates(timestamps) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(
        pd.to_datetime(pd.Series(timestamps).dropna().unique(), utc=True)
    ).sort_values()
    if dates.empty:
        return pd.DatetimeIndex([])
    chosen = []
    due = dates[0]
    while due <= dates[-1]:
        later = dates[dates >= due]
        if len(later) == 0:
            break
        decision = later[0]
        chosen.append(decision)
        due = decision + pd.Timedelta(days=HORIZON_DAYS)
    return pd.DatetimeIndex(list(dict.fromkeys(chosen)))


def _weights(sleeve: str) -> dict[str, float]:
    if sleeve not in SLEEVES:
        raise ValueError(f"Unsupported sleeve: {sleeve}")
    return {name: 1.0 if name == sleeve else 0.0 for name in SLEEVES}


def _turnover(current: dict[str, float], target: dict[str, float]) -> float:
    return 0.5 * sum(abs(float(target[k]) - float(current[k])) for k in SLEEVES)


def _sleeve_return(row: pd.Series, sleeve: str) -> float:
    if sleeve == "BTC":
        return float(row["btc_forward_return_7d"])
    if sleeve == "ALT":
        return float(row["alt_forward_return_7d"])
    if sleeve == "CASH":
        return 0.0
    raise ValueError(f"Unsupported sleeve: {sleeve}")


def load_inputs(
    dataset_path=DATASET_PATH,
    phase1_manifest_path=PHASE1_MANIFEST_PATH,
    predictions_path=PREDICTIONS_PATH,
    phase2_manifest_path=PHASE2_MANIFEST_PATH,
):
    paths = {
        "phase1_dataset": Path(dataset_path),
        "phase1_manifest": Path(phase1_manifest_path),
        "phase2_predictions": Path(predictions_path),
        "phase2_manifest": Path(phase2_manifest_path),
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)

    hashes = {name: _sha256(path) for name, path in paths.items()}
    phase1_manifest = json.loads(paths["phase1_manifest"].read_text(encoding="utf-8"))
    phase2_manifest = json.loads(paths["phase2_manifest"].read_text(encoding="utf-8"))

    expected_phase1_hash = phase1_manifest.get("dataset_sha256")
    if expected_phase1_hash and expected_phase1_hash != hashes["phase1_dataset"]:
        raise RuntimeError("Crypto V4 Phase 1 dataset hash does not match its manifest")
    phase2_inputs = phase2_manifest.get("inputs", {})
    if phase2_inputs.get("phase1_dataset") and phase2_inputs["phase1_dataset"] != hashes["phase1_dataset"]:
        raise RuntimeError("Crypto V4 Phase 2 was not built from the current frozen Phase 1 dataset")

    data = pd.read_parquet(paths["phase1_dataset"]).copy()
    predictions = pd.read_parquet(paths["phase2_predictions"]).copy()
    for frame in (data, predictions):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)

    if (data["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any() or (
        predictions["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC
    ).any():
        raise RuntimeError("Future holdout leakage detected in Crypto V4 Phase 3 inputs")

    required_data = {
        "timestamp_utc", "btc_forward_return_7d", "alt_forward_return_7d",
        "cash_forward_return_7d", "allocation_target",
    }
    required_predictions = {
        "timestamp_utc", "fold_id", "model_id", "predicted_label", "actual_label",
    }
    missing_data = required_data - set(data.columns)
    missing_predictions = required_predictions - set(predictions.columns)
    if missing_data:
        raise ValueError("Phase 1 dataset missing columns: " + ", ".join(sorted(missing_data)))
    if missing_predictions:
        raise ValueError("Phase 2 predictions missing columns: " + ", ".join(sorted(missing_predictions)))

    primary = predictions[predictions["model_id"] == PRIMARY_MODEL_ID].copy()
    if primary.empty:
        raise ValueError(f"No frozen Phase 2 predictions for {PRIMARY_MODEL_ID}")
    key = ["timestamp_utc"]
    if primary.duplicated(key).any():
        duplicates = primary.loc[primary.duplicated(key, keep=False), key + ["fold_id"]]
        raise ValueError("Duplicate primary prediction timestamps: " + duplicates.head().to_json())
    if not set(primary["predicted_label"].dropna().unique()).issubset(SLEEVES):
        raise ValueError("Unexpected predicted sleeve in Phase 2 predictions")

    decisions = primary[["timestamp_utc", "fold_id", "predicted_label", "actual_label"]].merge(
        data[[
            "timestamp_utc", "btc_forward_return_7d", "alt_forward_return_7d",
            "cash_forward_return_7d", "allocation_target",
        ]],
        on="timestamp_utc", how="inner", validate="one_to_one",
    ).sort_values("timestamp_utc").reset_index(drop=True)
    if len(decisions) != len(primary):
        raise ValueError("Phase 2 primary predictions do not align one-to-one with Phase 1 rows")
    if not (decisions["actual_label"] == decisions["allocation_target"]).all():
        raise RuntimeError("Phase 2 actual labels disagree with frozen Phase 1 labels")

    rebalance = _rebalance_dates(decisions["timestamp_utc"])
    decisions = decisions[decisions["timestamp_utc"].isin(rebalance)].copy().reset_index(drop=True)
    if decisions.empty:
        raise ValueError("No Crypto V4 Phase 3 rebalance decisions")

    return paths, hashes, phase1_manifest, phase2_manifest, decisions


def simulate(decisions: pd.DataFrame, variant: str, cost_bps: float) -> pd.DataFrame:
    if variant == "v4_hgb_allocator":
        sleeves = decisions["predicted_label"].tolist()
    elif variant == "btc_benchmark":
        sleeves = ["BTC"] * len(decisions)
    elif variant == "alt_equal_weight_benchmark":
        sleeves = ["ALT"] * len(decisions)
    elif variant == "cash_benchmark":
        sleeves = ["CASH"] * len(decisions)
    else:
        raise ValueError(f"Unknown variant: {variant}")

    equity = 1.0
    current = _weights("CASH")
    rows = []
    for i, (_, row) in enumerate(decisions.iterrows()):
        sleeve = sleeves[i]
        target = _weights(sleeve)
        turnover = _turnover(current, target)
        transaction_cost = equity * turnover * float(cost_bps) / 10_000.0
        equity_after_cost = max(0.0, equity - transaction_cost)
        period_return = _sleeve_return(row, sleeve)
        gross_pnl = equity_after_cost * period_return
        ending_equity = max(0.0, equity_after_cost + gross_pnl)
        net_period_return = ending_equity / equity - 1.0 if equity > 0 else -1.0
        rows.append({
            "timestamp_utc": row["timestamp_utc"],
            "fold_id": row["fold_id"],
            "variant": variant,
            "cost_bps_round_trip": float(cost_bps),
            "selected_sleeve": sleeve,
            "actual_best_sleeve": row["allocation_target"],
            "turnover": turnover,
            "transaction_cost": transaction_cost,
            "gross_forward_return_7d": period_return,
            "net_period_return_7d": net_period_return,
            "starting_equity": equity,
            "ending_equity": ending_equity,
        })
        equity = ending_equity
        current = target
    return pd.DataFrame(rows)


def summarize(frame: pd.DataFrame) -> dict:
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    equity = pd.to_numeric(frame["ending_equity"], errors="coerce")
    net_returns = pd.to_numeric(frame["net_period_return_7d"], errors="coerce")
    n = len(frame)
    ending = float(equity.iloc[-1]) if n else 1.0
    years = (n * HORIZON_DAYS) / 365.25 if n else 0.0
    annualized_return = ending ** (1.0 / years) - 1.0 if years > 0 and ending > 0 else np.nan
    annualized_volatility = float(net_returns.std(ddof=1) * np.sqrt(365.25 / HORIZON_DAYS)) if n > 1 else np.nan
    mean_period = float(net_returns.mean()) if n else np.nan
    sharpe_like = (
        float(mean_period / net_returns.std(ddof=1) * np.sqrt(365.25 / HORIZON_DAYS))
        if n > 1 and net_returns.std(ddof=1) > 0 else np.nan
    )
    path = pd.concat([pd.Series([1.0]), equity], ignore_index=True)
    drawdown = path / path.cummax() - 1.0
    counts = frame["selected_sleeve"].value_counts()
    return {
        "variant": frame["variant"].iloc[0] if n else None,
        "cost_bps_round_trip": float(frame["cost_bps_round_trip"].iloc[0]) if n else np.nan,
        "observation_count": n,
        "starting_equity": 1.0,
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_like": sharpe_like,
        "maximum_rebalance_drawdown": float(drawdown.min()) if len(drawdown) else 0.0,
        "average_turnover_per_rebalance": float(frame["turnover"].mean()) if n else 0.0,
        "total_turnover": float(frame["turnover"].sum()) if n else 0.0,
        "total_transaction_cost_dollars_per_starting_dollar": float(frame["transaction_cost"].sum()) if n else 0.0,
        "positive_period_rate": float((net_returns > 0).mean()) if n else 0.0,
        "worst_period_return": float(net_returns.min()) if n else np.nan,
        "best_period_return": float(net_returns.max()) if n else np.nan,
        "btc_allocation_fraction": float(counts.get("BTC", 0) / n) if n else 0.0,
        "alt_allocation_fraction": float(counts.get("ALT", 0) / n) if n else 0.0,
        "cash_allocation_fraction": float(counts.get("CASH", 0) / n) if n else 0.0,
    }


def run_phase3(
    dataset_path=DATASET_PATH,
    phase1_manifest_path=PHASE1_MANIFEST_PATH,
    predictions_path=PREDICTIONS_PATH,
    phase2_manifest_path=PHASE2_MANIFEST_PATH,
    output_root=OUTPUT_ROOT,
):
    paths, hashes_before, phase1_manifest, phase2_manifest, decisions = load_inputs(
        dataset_path, phase1_manifest_path, predictions_path, phase2_manifest_path
    )

    variants = (
        "v4_hgb_allocator",
        "btc_benchmark",
        "alt_equal_weight_benchmark",
        "cash_benchmark",
    )
    frames = []
    metrics = []
    for variant in variants:
        for cost in COST_SCENARIOS_BPS:
            frame = simulate(decisions, variant, cost)
            frames.append(frame)
            metrics.append(summarize(frame))

    daily = pd.concat(frames, ignore_index=True)
    metrics_df = pd.DataFrame(metrics).sort_values(["cost_bps_round_trip", "variant"]).reset_index(drop=True)

    # Frozen, descriptive comparisons only.  These fields do not alter the rule.
    allocator = metrics_df[metrics_df["variant"] == "v4_hgb_allocator"].copy()
    comparison_rows = []
    for _, row in allocator.iterrows():
        cost = row["cost_bps_round_trip"]
        peers = metrics_df[metrics_df["cost_bps_round_trip"] == cost].set_index("variant")
        comparison_rows.append({
            "cost_bps_round_trip": cost,
            "allocator_cumulative_return": row["cumulative_return"],
            "btc_cumulative_return": peers.loc["btc_benchmark", "cumulative_return"],
            "alt_cumulative_return": peers.loc["alt_equal_weight_benchmark", "cumulative_return"],
            "cash_cumulative_return": peers.loc["cash_benchmark", "cumulative_return"],
            "allocator_minus_btc_cumulative_return": row["cumulative_return"] - peers.loc["btc_benchmark", "cumulative_return"],
            "allocator_minus_alt_cumulative_return": row["cumulative_return"] - peers.loc["alt_equal_weight_benchmark", "cumulative_return"],
            "allocator_maximum_rebalance_drawdown": row["maximum_rebalance_drawdown"],
            "btc_maximum_rebalance_drawdown": peers.loc["btc_benchmark", "maximum_rebalance_drawdown"],
            "alt_maximum_rebalance_drawdown": peers.loc["alt_equal_weight_benchmark", "maximum_rebalance_drawdown"],
        })
    comparison_df = pd.DataFrame(comparison_rows)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    decisions_path = output_root / "rebalance_decisions.csv"
    daily_path = output_root / "portfolio_periods.csv"
    metrics_path = output_root / "portfolio_metrics.csv"
    comparisons_path = output_root / "benchmark_comparison.csv"
    decisions.to_csv(decisions_path, index=False)
    daily.to_csv(daily_path, index=False)
    metrics_df.to_csv(metrics_path, index=False)
    comparison_df.to_csv(comparisons_path, index=False)

    hashes_after = {name: _sha256(path) for name, path in paths.items()}
    if hashes_before != hashes_after:
        raise RuntimeError("Frozen Crypto V4 Phase 1/2 inputs changed during Phase 3")

    manifest = {
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "frozen_market_allocation_portfolio_diagnostics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit_hash": _git_hash(),
        "primary_strategy": {
            "model_id": PRIMARY_MODEL_ID,
            "rule": "direct predicted BTC/ALT/CASH class from frozen Phase 2 HGB classifier",
            "rebalance_days": HORIZON_DAYS,
            "btc_allocation": "100% BTC when BTC selected",
            "alt_allocation": "100% equal-weight eligible non-BTC sleeve when ALT selected",
            "cash_allocation": "100% cash when CASH selected",
        },
        "cost_bps_round_trip": list(COST_SCENARIOS_BPS),
        "turnover_definition": "0.5 * L1 distance across BTC/ALT/CASH sleeve weights",
        "benchmarks": ["btc_benchmark", "alt_equal_weight_benchmark", "cash_benchmark"],
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "future_holdout_policy": "No rows at or after 2026-09-01 UTC are present or evaluated.",
        "decision_count": int(len(decisions)),
        "decision_date_range": {
            "start_utc": decisions["timestamp_utc"].min().isoformat(),
            "end_utc": decisions["timestamp_utc"].max().isoformat(),
        },
        "inputs": {name: {"path": str(paths[name]), "sha256": hashes_before[name]} for name in paths},
        "outputs": {
            "rebalance_decisions": str(decisions_path),
            "portfolio_periods": str(daily_path),
            "portfolio_metrics": str(metrics_path),
            "benchmark_comparison": str(comparisons_path),
        },
        "drawdown_note": "maximum_rebalance_drawdown is measured only at 7-day rebalance endpoints; intraperiod drawdown is not reconstructed in Phase 3",
        "policy": (
            "development-only frozen Phase 2 HGB allocation diagnostics; no model fitting, "
            "feature search, threshold search, cadence search, cost-scenario selection, promotion, "
            "live execution, leverage, shorting, derivatives, or future-holdout evaluation"
        ),
        "next_step": (
            "Review allocator economics across all pre-registered costs versus BTC/ALT/CASH. "
            "Do not retune Phase 2 from Phase 3 results.  If the fixed architecture is economically "
            "credible, pre-register any Layer-2 altcoin-selection integration before implementation."
        ),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest, metrics_df, comparison_df


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=DATASET_PATH)
    ap.add_argument("--phase1-manifest", type=Path, default=PHASE1_MANIFEST_PATH)
    ap.add_argument("--predictions", type=Path, default=PREDICTIONS_PATH)
    ap.add_argument("--phase2-manifest", type=Path, default=PHASE2_MANIFEST_PATH)
    ap.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = ap.parse_args(argv)
    manifest, metrics, comparisons = run_phase3(
        args.dataset, args.phase1_manifest, args.predictions, args.phase2_manifest, args.output_root
    )
    print("CRYPTO V4 PHASE 3")
    print("=" * 80)
    print(f"Rebalance decisions: {manifest['decision_count']}")
    print(f"Date range: {manifest['decision_date_range']['start_utc']} -> {manifest['decision_date_range']['end_utc']}")
    print("\nPORTFOLIO METRICS")
    show = [
        "variant", "cost_bps_round_trip", "ending_equity", "cumulative_return",
        "annualized_return", "maximum_rebalance_drawdown", "total_turnover",
        "btc_allocation_fraction", "alt_allocation_fraction", "cash_allocation_fraction",
    ]
    print(metrics[show].to_string(index=False))
    print("\nALLOCATOR VS BENCHMARKS")
    print(comparisons.to_string(index=False))
    print(f"\nOutput: {manifest['outputs']['portfolio_metrics']}")
    print("Future holdout remains untouched from 2026-09-01 UTC.")


if __name__ == "__main__":
    main()
