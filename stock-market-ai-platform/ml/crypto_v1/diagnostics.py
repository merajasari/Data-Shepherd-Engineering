"""Read-only diagnostics for the frozen Crypto V1 Phase 3 checkpoint.

This module consumes Phase 3 prediction/metric artifacts only. It never fits
models, changes predictions, or promotes a candidate. Outputs are descriptive
diagnostics intended to explain stability and failure modes without retuning
the frozen holdout.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.crypto_v1.config import MODEL_ROOT


PHASE3_ROOT = MODEL_ROOT / "phase3"
DIAGNOSTICS_ROOT = PHASE3_ROOT / "diagnostics"
DEFAULT_BOOTSTRAP_SAMPLES = 2000
DEFAULT_RANDOM_SEED = 1729
TOP_COUNTS = (3, 5)
KEYS = ["horizon_days", "model_id", "fold_id", "split", "timestamp_utc"]


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_phase3_outputs(phase3_root=PHASE3_ROOT):
    """Load frozen Phase 3 outputs without mutating them."""
    root = Path(phase3_root)
    paths = {
        "predictions": root / "predictions.parquet",
        "daily_metrics": root / "daily_metrics.csv",
        "metrics_summary": root / "metrics_summary.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Phase 3 output(s): " + ", ".join(missing))

    predictions = pd.read_parquet(paths["predictions"])
    daily = pd.read_csv(paths["daily_metrics"])
    summary = pd.read_csv(paths["metrics_summary"])

    predictions["timestamp_utc"] = pd.to_datetime(predictions["timestamp_utc"], utc=True)
    daily["timestamp_utc"] = pd.to_datetime(daily["timestamp_utc"], utc=True)

    required = {
        "timestamp_utc", "product_id", "actual_btc_relative_forward_return",
        "predicted_score", "fold_id", "split", "model_id", "horizon_days",
        "btc_regime",
    }
    missing_columns = sorted(required - set(predictions.columns))
    if missing_columns:
        raise ValueError("Phase 3 predictions missing columns: " + ", ".join(missing_columns))

    return paths, predictions, daily, summary


def _ranked_predictions(predictions):
    ranked = predictions.copy()
    ranked = ranked.sort_values(
        KEYS + ["predicted_score", "product_id"],
        ascending=[True, True, True, True, True, False, True],
    )
    ranked["selection_rank"] = ranked.groupby(KEYS, sort=False).cumcount() + 1
    return ranked


def stability_diagnostics(daily):
    """Summarize IC and realized ranking returns by fold, year, and regime."""
    frame = daily.copy()
    frame["calendar_year"] = frame["timestamp_utc"].dt.year

    rows = []
    dimensions = {
        "fold": ["horizon_days", "model_id", "split", "fold_id"],
        "year": ["horizon_days", "model_id", "split", "calendar_year"],
        "btc_regime": ["horizon_days", "model_id", "split", "btc_regime"],
    }
    metrics = (
        "ic", "top_minus_bottom_spread",
        "top_3_realized_return", "top_5_realized_return",
    )

    for breakdown, keys in dimensions.items():
        for values, group in frame.groupby(keys, sort=True, dropna=False):
            values = values if isinstance(values, tuple) else (values,)
            row = {"breakdown": breakdown, **dict(zip(keys, values))}
            row["day_count"] = len(group)
            for metric in metrics:
                series = pd.to_numeric(group[metric], errors="coerce").dropna()
                row[f"{metric}_mean"] = series.mean()
                row[f"{metric}_median"] = series.median()
                row[f"{metric}_std"] = series.std()
                row[f"{metric}_positive_rate"] = series.gt(0).mean() if len(series) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def breadth_diagnostics(predictions):
    """Measure cross-sectional score breadth and selection concentration."""
    ranked = _ranked_predictions(predictions)
    rows = []
    for values, day in ranked.groupby(KEYS, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        scores = day["predicted_score"].astype(float)
        row = dict(zip(KEYS, values))
        row.update({
            "asset_count": len(day),
            "unique_score_count": scores.nunique(),
            "score_std": scores.std(),
            "score_iqr": scores.quantile(0.75) - scores.quantile(0.25),
            "score_range": scores.max() - scores.min(),
        })
        for top_n in TOP_COUNTS:
            cutoff = min(top_n, len(day))
            leaders = scores.nlargest(cutoff)
            row[f"top_{top_n}_score_gap"] = (
                leaders.min() - scores.drop(leaders.index).max()
                if len(day) > cutoff else np.nan
            )
        rows.append(row)

    daily_breadth = pd.DataFrame(rows)

    concentration_rows = []
    group_keys = ["horizon_days", "model_id", "split"]
    for values, group in ranked.groupby(group_keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        base = dict(zip(group_keys, values))
        for top_n in TOP_COUNTS:
            selected = group[group["selection_rank"] <= top_n]
            counts = selected.groupby("product_id").size().astype(float)
            total = counts.sum()
            shares = counts / total if total else counts
            concentration_rows.append(base | {
                "top_n": top_n,
                "selected_asset_count": int(counts.size),
                "selection_hhi": float((shares ** 2).sum()) if total else np.nan,
                "largest_selection_share": float(shares.max()) if total else np.nan,
            })
    return daily_breadth, pd.DataFrame(concentration_rows)


def turnover_diagnostics(predictions):
    """Estimate membership turnover of predicted Top 3/Top 5 selections."""
    ranked = _ranked_predictions(predictions)
    rows = []
    group_keys = ["horizon_days", "model_id", "split", "fold_id"]

    for values, group in ranked.groupby(group_keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        base = dict(zip(group_keys, values))
        for top_n in TOP_COUNTS:
            previous = None
            for timestamp, day in group.groupby("timestamp_utc", sort=True):
                current = set(day.loc[day["selection_rank"] <= top_n, "product_id"])
                if previous is not None:
                    denominator = max(1, min(top_n, len(current), len(previous)))
                    overlap = len(current & previous)
                    rows.append(base | {
                        "timestamp_utc": timestamp,
                        "top_n": top_n,
                        "overlap_count": overlap,
                        "replacement_count": denominator - overlap,
                        "turnover_fraction": 1.0 - overlap / denominator,
                    })
                previous = current
    return pd.DataFrame(rows)


def asset_contribution_diagnostics(predictions):
    """Describe which assets drive realized Top-N outcomes."""
    ranked = _ranked_predictions(predictions)
    rows = []
    keys = ["horizon_days", "model_id", "split"]

    for values, group in ranked.groupby(keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        base = dict(zip(keys, values))
        available_days = group.groupby("product_id")["timestamp_utc"].nunique()
        for top_n in TOP_COUNTS:
            selected = group[group["selection_rank"] <= top_n]
            for product_id, asset in selected.groupby("product_id", sort=True):
                actual = asset["actual_btc_relative_forward_return"].astype(float)
                rows.append(base | {
                    "top_n": top_n,
                    "product_id": product_id,
                    "selection_count": len(asset),
                    "available_day_count": int(available_days.get(product_id, 0)),
                    "selection_rate": (
                        len(asset) / available_days[product_id]
                        if available_days.get(product_id, 0) else np.nan
                    ),
                    "mean_realized_return": actual.mean(),
                    "median_realized_return": actual.median(),
                    "positive_return_rate": actual.gt(0).mean(),
                    "sum_realized_return": actual.sum(),
                })
    return pd.DataFrame(rows)


def xrp_gap_sensitivity(predictions, daily):
    """Compare diagnostics on dates where XRP is present versus absent."""
    presence = (
        predictions.groupby(KEYS, sort=True)["product_id"]
        .apply(lambda values: "XRP-USD" in set(values))
        .rename("xrp_present")
        .reset_index()
    )
    merged = daily.merge(presence, on=KEYS, how="left", validate="one_to_one")
    metrics = ["ic", "top_minus_bottom_spread", "top_3_realized_return", "top_5_realized_return"]
    rows = []
    keys = ["horizon_days", "model_id", "split", "xrp_present"]
    for values, group in merged.groupby(keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        row = dict(zip(keys, values))
        row["day_count"] = len(group)
        for metric in metrics:
            series = pd.to_numeric(group[metric], errors="coerce").dropna()
            row[f"{metric}_mean"] = series.mean()
            row[f"{metric}_median"] = series.median()
        rows.append(row)
    return pd.DataFrame(rows)


def bootstrap_uncertainty(daily, samples=DEFAULT_BOOTSTRAP_SAMPLES, seed=DEFAULT_RANDOM_SEED):
    """Bootstrap daily metric means to descriptive 95% intervals.

    Holdout rows are reported but never used to choose a model or parameter.
    """
    rng = np.random.default_rng(seed)
    metrics = ["ic", "top_minus_bottom_spread", "top_3_realized_return", "top_5_realized_return"]
    rows = []
    keys = ["horizon_days", "model_id", "split"]
    for values, group in daily.groupby(keys, sort=True, dropna=False):
        values = values if isinstance(values, tuple) else (values,)
        base = dict(zip(keys, values))
        for metric in metrics:
            values_array = pd.to_numeric(group[metric], errors="coerce").dropna().to_numpy(float)
            if len(values_array) == 0:
                low = center = high = np.nan
            else:
                draws = rng.choice(values_array, size=(samples, len(values_array)), replace=True)
                means = draws.mean(axis=1)
                low, high = np.quantile(means, [0.025, 0.975])
                center = values_array.mean()
            rows.append(base | {
                "metric": metric,
                "day_count": len(values_array),
                "mean": center,
                "ci_2_5": low,
                "ci_97_5": high,
                "bootstrap_samples": samples,
                "seed": seed,
            })
    return pd.DataFrame(rows)


def run_diagnostics(
    phase3_root=PHASE3_ROOT,
    output_root=DIAGNOSTICS_ROOT,
    bootstrap_samples=DEFAULT_BOOTSTRAP_SAMPLES,
    seed=DEFAULT_RANDOM_SEED,
):
    """Generate read-only Phase 3 diagnostics and a provenance manifest."""
    input_paths, predictions, daily, summary = load_phase3_outputs(phase3_root)
    input_hashes_before = {name: _sha256(path) for name, path in input_paths.items()}

    stability = stability_diagnostics(daily)
    breadth_daily, concentration = breadth_diagnostics(predictions)
    turnover = turnover_diagnostics(predictions)
    asset_contribution = asset_contribution_diagnostics(predictions)
    xrp_sensitivity = xrp_gap_sensitivity(predictions, daily)
    uncertainty = bootstrap_uncertainty(daily, bootstrap_samples, seed)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "stability": output_root / "stability.csv",
        "breadth_daily": output_root / "breadth_daily.csv",
        "selection_concentration": output_root / "selection_concentration.csv",
        "turnover": output_root / "turnover.csv",
        "asset_contribution": output_root / "asset_contribution.csv",
        "xrp_gap_sensitivity": output_root / "xrp_gap_sensitivity.csv",
        "uncertainty": output_root / "uncertainty.csv",
    }
    frames = {
        "stability": stability,
        "breadth_daily": breadth_daily,
        "selection_concentration": concentration,
        "turnover": turnover,
        "asset_contribution": asset_contribution,
        "xrp_gap_sensitivity": xrp_sensitivity,
        "uncertainty": uncertainty,
    }
    for name, path in outputs.items():
        frames[name].to_csv(path, index=False)

    input_hashes_after = {name: _sha256(path) for name, path in input_paths.items()}
    if input_hashes_after != input_hashes_before:
        raise RuntimeError("Frozen Phase 3 inputs changed during diagnostics")

    manifest = {
        "phase": "3-diagnostics",
        "research_version": "crypto_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "read-only diagnostics; no fitting, retuning, selection, or promotion",
        "phase3_root": str(Path(phase3_root)),
        "input_hashes": input_hashes_before,
        "input_row_counts": {
            "predictions": len(predictions),
            "daily_metrics": len(daily),
            "metrics_summary": len(summary),
        },
        "bootstrap": {"samples": bootstrap_samples, "seed": seed, "confidence": 0.95},
        "outputs": {name: str(path) for name, path in outputs.items()},
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest, frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--output-root", type=Path, default=DIAGNOSTICS_ROOT)
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    args = parser.parse_args()
    manifest, frames = run_diagnostics(
        phase3_root=args.phase3_root,
        output_root=args.output_root,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    print(json.dumps({
        "manifest": manifest,
        "rows": {name: len(frame) for name, frame in frames.items()},
    }, indent=2))


if __name__ == "__main__":
    main()
