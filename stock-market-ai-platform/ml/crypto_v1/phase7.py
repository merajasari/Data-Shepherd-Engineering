"""Crypto V1 Phase 7: frozen evidence synthesis and governance checkpoint.

Phase 7 is read-only. It consolidates Phase 6 robustness diagnostics into
human-auditable evidence tables and a research disposition. It does not fit,
retrain, retune, select a threshold, select a strategy, alter the universe,
create a regime filter, promote a model, or execute trades.

The Phase 3 holdout beginning 2025-08-01 has already been observed. Phase 7
therefore treats all holdout-derived evidence as descriptive only.
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

PHASE6_ROOT = MODEL_ROOT / "phase6"
PHASE7_ROOT = MODEL_ROOT / "phase7"

PRIMARY_MODEL_ID = "momentum"
CONTROL_MODEL_IDS = ("hist_gradient_boosting", "random", "equal_score")
MODEL_IDS = (PRIMARY_MODEL_ID,) + CONTROL_MODEL_IDS
TOP_COUNTS = (3, 5)

SIGNAL_SUMMARY_COLUMNS = [
    "split", "model_id", "top_n", "observation_count",
    "mean_ic", "median_ic", "ic_positive_rate",
    "mean_top_minus_bottom_spread", "median_top_minus_bottom_spread",
    "positive_spread_rate", "mean_top_relative_return",
    "mean_bottom_relative_return", "ic_ci_lower_2_5", "ic_ci_upper_97_5",
    "ic_bootstrap_positive_rate", "spread_ci_lower_2_5",
    "spread_ci_upper_97_5", "spread_bootstrap_positive_rate",
]
TEMPORAL_CONSISTENCY_COLUMNS = [
    "split", "model_id", "top_n", "breakdown", "period_count",
    "positive_mean_ic_period_count", "negative_mean_ic_period_count",
    "positive_mean_ic_period_fraction", "positive_mean_spread_period_count",
    "negative_mean_spread_period_count", "positive_mean_spread_period_fraction",
    "mean_of_period_mean_ic", "min_period_mean_ic", "max_period_mean_ic",
    "mean_of_period_mean_spread", "min_period_mean_spread",
    "max_period_mean_spread",
]
ASSET_PERSISTENCE_COLUMNS = [
    "model_id", "variant", "top_n", "asset_count", "common_asset_count",
    "persisted_count", "reversed_count", "zero_or_negligible_count",
    "not_common_count", "persisted_fraction_of_common",
    "reversed_fraction_of_common", "pearson_contribution_correlation",
    "spearman_contribution_correlation", "mean_contribution_change",
    "median_contribution_change",
]
SENSITIVITY_SUMMARY_COLUMNS = [
    "split", "model_id", "top_n", "asset_count",
    "baseline_mean_spread", "mean_leave_one_out_spread_change",
    "max_absolute_spread_change", "most_influential_asset",
    "most_influential_spread_change", "min_leave_one_out_mean_spread",
    "max_leave_one_out_mean_spread", "sign_flip_count",
]
CONCENTRATION_SUMMARY_COLUMNS = [
    "split", "model_id", "variant", "top_n", "asset_count",
    "positive_asset_fraction", "total_contribution",
    "largest_absolute_contributor", "largest_absolute_contribution_share",
    "positive_contribution_hhi", "absolute_contribution_hhi",
    "top_1_share_of_positive_contribution",
    "top_3_share_of_positive_contribution",
    "top_5_share_of_positive_contribution",
]
EVIDENCE_REGISTER_COLUMNS = [
    "evidence_area", "split", "model_id", "top_n", "metric",
    "value", "interpretation", "usage_policy",
]


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _require_columns(frame, required, label):
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} missing columns: " + ", ".join(missing))


def load_inputs(phase6_root=PHASE6_ROOT):
    phase6_root = Path(phase6_root)
    paths = {
        "phase6_manifest": phase6_root / "manifest.json",
        "rolling_stability": phase6_root / "rolling_stability.csv",
        "calendar_stability": phase6_root / "calendar_stability.csv",
        "regime_stability": phase6_root / "regime_stability.csv",
        "asset_stability": phase6_root / "asset_stability.csv",
        "leave_one_asset_out": phase6_root / "leave_one_asset_out.csv",
        "contribution_concentration": phase6_root / "contribution_concentration.csv",
        "bootstrap_uncertainty": phase6_root / "bootstrap_uncertainty.csv",
        "control_comparison": phase6_root / "control_comparison.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Phase 7 input(s): " + ", ".join(missing))

    frames = {
        name: pd.read_csv(path)
        for name, path in paths.items()
        if name != "phase6_manifest"
    }

    _require_columns(frames["control_comparison"], {
        "split", "model_id", "top_n", "observation_count", "mean_ic",
        "median_ic", "ic_positive_rate", "mean_top_minus_bottom_spread",
        "median_top_minus_bottom_spread", "positive_spread_rate",
        "mean_top_relative_return", "mean_bottom_relative_return",
    }, "Phase 6 control_comparison")
    _require_columns(frames["bootstrap_uncertainty"], {
        "split", "model_id", "top_n", "metric", "ci_lower_2_5",
        "ci_upper_97_5", "bootstrap_positive_rate",
    }, "Phase 6 bootstrap_uncertainty")
    _require_columns(frames["calendar_stability"], {
        "split", "model_id", "top_n", "breakdown", "period", "mean_ic",
        "mean_top_minus_bottom_spread",
    }, "Phase 6 calendar_stability")
    _require_columns(frames["asset_stability"], {
        "model_id", "variant", "top_n", "product_id", "sign_status",
        "development_contribution", "observed_holdout_contribution",
        "contribution_change", "pearson_contribution_correlation",
        "spearman_contribution_correlation",
    }, "Phase 6 asset_stability")
    _require_columns(frames["leave_one_asset_out"], {
        "split", "model_id", "top_n", "excluded_product_id",
        "baseline_mean_spread", "leave_one_out_mean_spread", "spread_change",
    }, "Phase 6 leave_one_asset_out")
    _require_columns(frames["contribution_concentration"], {
        "split", "model_id", "variant", "top_n", "asset_count",
        "positive_asset_fraction", "total_contribution",
        "largest_absolute_contributor", "largest_absolute_contribution_share",
        "positive_contribution_hhi", "absolute_contribution_hhi",
        "top_1_share_of_positive_contribution",
        "top_3_share_of_positive_contribution",
        "top_5_share_of_positive_contribution",
    }, "Phase 6 contribution_concentration")

    for name, frame in frames.items():
        if "model_id" in frame.columns:
            unexpected = set(frame["model_id"].dropna().unique()) - set(MODEL_IDS)
            if unexpected:
                raise ValueError(f"Unexpected model_id(s) in {name}: {sorted(unexpected)}")
    return paths, frames


def signal_summary(control, bootstrap):
    base = control.copy()
    boot = bootstrap.copy()

    def metric_frame(metric, prefix):
        x = boot[boot["metric"] == metric][[
            "split", "model_id", "top_n", "ci_lower_2_5",
            "ci_upper_97_5", "bootstrap_positive_rate",
        ]].copy()
        return x.rename(columns={
            "ci_lower_2_5": f"{prefix}_ci_lower_2_5",
            "ci_upper_97_5": f"{prefix}_ci_upper_97_5",
            "bootstrap_positive_rate": f"{prefix}_bootstrap_positive_rate",
        })

    out = base.merge(
        metric_frame("ic", "ic"),
        on=["split", "model_id", "top_n"],
        how="left",
        validate="one_to_one",
    ).merge(
        metric_frame("top_minus_bottom_spread", "spread"),
        on=["split", "model_id", "top_n"],
        how="left",
        validate="one_to_one",
    )
    return out.reindex(columns=SIGNAL_SUMMARY_COLUMNS).sort_values(
        ["split", "model_id", "top_n"]
    ).reset_index(drop=True)


def temporal_consistency(calendar):
    x = calendar[calendar["breakdown"].isin(["year", "quarter", "fold"])].copy()
    rows = []
    keys = ["split", "model_id", "top_n", "breakdown"]
    for values, group in x.groupby(keys, sort=True, dropna=False):
        ic = pd.to_numeric(group["mean_ic"], errors="coerce").dropna()
        spread = pd.to_numeric(
            group["mean_top_minus_bottom_spread"], errors="coerce"
        ).dropna()
        rows.append(dict(zip(keys, values)) | {
            "period_count": len(group),
            "positive_mean_ic_period_count": int(ic.gt(0).sum()),
            "negative_mean_ic_period_count": int(ic.lt(0).sum()),
            "positive_mean_ic_period_fraction": float(ic.gt(0).mean()) if len(ic) else np.nan,
            "positive_mean_spread_period_count": int(spread.gt(0).sum()),
            "negative_mean_spread_period_count": int(spread.lt(0).sum()),
            "positive_mean_spread_period_fraction": float(spread.gt(0).mean()) if len(spread) else np.nan,
            "mean_of_period_mean_ic": float(ic.mean()) if len(ic) else np.nan,
            "min_period_mean_ic": float(ic.min()) if len(ic) else np.nan,
            "max_period_mean_ic": float(ic.max()) if len(ic) else np.nan,
            "mean_of_period_mean_spread": float(spread.mean()) if len(spread) else np.nan,
            "min_period_mean_spread": float(spread.min()) if len(spread) else np.nan,
            "max_period_mean_spread": float(spread.max()) if len(spread) else np.nan,
        })
    return pd.DataFrame(rows, columns=TEMPORAL_CONSISTENCY_COLUMNS)


def asset_persistence(asset):
    rows = []
    keys = ["model_id", "variant", "top_n"]
    for values, group in asset.groupby(keys, sort=True, dropna=False):
        status = group["sign_status"].fillna("not_common")
        common = status.ne("not_common")
        common_count = int(common.sum())
        persisted = int(status.eq("persisted").sum())
        reversed_count = int(status.eq("reversed").sum())
        zero = int(status.eq("zero_or_negligible").sum())
        not_common = int(status.eq("not_common").sum())
        change = pd.to_numeric(group["contribution_change"], errors="coerce").dropna()
        pearson = pd.to_numeric(group["pearson_contribution_correlation"], errors="coerce").dropna()
        spearman = pd.to_numeric(group["spearman_contribution_correlation"], errors="coerce").dropna()
        rows.append(dict(zip(keys, values)) | {
            "asset_count": len(group),
            "common_asset_count": common_count,
            "persisted_count": persisted,
            "reversed_count": reversed_count,
            "zero_or_negligible_count": zero,
            "not_common_count": not_common,
            "persisted_fraction_of_common": persisted / common_count if common_count else np.nan,
            "reversed_fraction_of_common": reversed_count / common_count if common_count else np.nan,
            "pearson_contribution_correlation": float(pearson.iloc[0]) if len(pearson) else np.nan,
            "spearman_contribution_correlation": float(spearman.iloc[0]) if len(spearman) else np.nan,
            "mean_contribution_change": float(change.mean()) if len(change) else np.nan,
            "median_contribution_change": float(change.median()) if len(change) else np.nan,
        })
    return pd.DataFrame(rows, columns=ASSET_PERSISTENCE_COLUMNS)


def sensitivity_summary(leave_one_out):
    rows = []
    keys = ["split", "model_id", "top_n"]
    for values, group in leave_one_out.groupby(keys, sort=True, dropna=False):
        changes = pd.to_numeric(group["spread_change"], errors="coerce")
        baseline = pd.to_numeric(group["baseline_mean_spread"], errors="coerce")
        loo = pd.to_numeric(group["leave_one_out_mean_spread"], errors="coerce")
        valid = changes.notna()
        if valid.any():
            influential_idx = changes.abs().idxmax()
            influential_asset = group.loc[influential_idx, "excluded_product_id"]
            influential_change = float(changes.loc[influential_idx])
        else:
            influential_asset = None
            influential_change = np.nan
        base_value = float(baseline.dropna().iloc[0]) if baseline.notna().any() else np.nan
        sign_flip_count = 0
        if pd.notna(base_value):
            clean_loo = loo.dropna()
            sign_flip_count = int(((np.sign(clean_loo) != np.sign(base_value)) & (clean_loo != 0)).sum())
        rows.append(dict(zip(keys, values)) | {
            "asset_count": len(group),
            "baseline_mean_spread": base_value,
            "mean_leave_one_out_spread_change": float(changes.mean()) if valid.any() else np.nan,
            "max_absolute_spread_change": float(changes.abs().max()) if valid.any() else np.nan,
            "most_influential_asset": influential_asset,
            "most_influential_spread_change": influential_change,
            "min_leave_one_out_mean_spread": float(loo.min()) if loo.notna().any() else np.nan,
            "max_leave_one_out_mean_spread": float(loo.max()) if loo.notna().any() else np.nan,
            "sign_flip_count": sign_flip_count,
        })
    return pd.DataFrame(rows, columns=SENSITIVITY_SUMMARY_COLUMNS)


def concentration_summary(concentration):
    return concentration.reindex(columns=CONCENTRATION_SUMMARY_COLUMNS).sort_values(
        ["split", "model_id", "variant", "top_n"]
    ).reset_index(drop=True)


def evidence_register(signal, temporal, persistence, sensitivity, concentration):
    rows = []
    usage = (
        "descriptive only; must not select/tune a strategy or convert the observed "
        "holdout into a fresh validation sample"
    )
    primary = signal[signal["model_id"] == PRIMARY_MODEL_ID]
    for row in primary.itertuples(index=False):
        for metric in (
            "mean_ic", "mean_top_minus_bottom_spread",
            "ic_bootstrap_positive_rate", "spread_bootstrap_positive_rate",
        ):
            rows.append({
                "evidence_area": "signal", "split": row.split,
                "model_id": row.model_id, "top_n": row.top_n,
                "metric": metric, "value": getattr(row, metric),
                "interpretation": "frozen Phase 6 signal/uncertainty diagnostic",
                "usage_policy": usage,
            })

    for _, row in temporal[temporal["model_id"] == PRIMARY_MODEL_ID].iterrows():
        rows.append({
            "evidence_area": f"temporal_{row['breakdown']}", "split": row["split"],
            "model_id": row["model_id"], "top_n": row["top_n"],
            "metric": "positive_mean_spread_period_fraction",
            "value": row["positive_mean_spread_period_fraction"],
            "interpretation": "fraction of predetermined periods with positive mean spread",
            "usage_policy": usage,
        })

    for _, row in persistence[persistence["model_id"] == PRIMARY_MODEL_ID].iterrows():
        rows.append({
            "evidence_area": "asset_persistence",
            "split": "development_vs_observed_holdout",
            "model_id": row["model_id"], "top_n": row["top_n"],
            "metric": "reversed_fraction_of_common",
            "value": row["reversed_fraction_of_common"],
            "interpretation": "share of common assets whose contribution sign reversed",
            "usage_policy": usage,
        })

    for _, row in sensitivity[sensitivity["model_id"] == PRIMARY_MODEL_ID].iterrows():
        rows.append({
            "evidence_area": "leave_one_asset_out", "split": row["split"],
            "model_id": row["model_id"], "top_n": row["top_n"],
            "metric": "max_absolute_spread_change",
            "value": row["max_absolute_spread_change"],
            "interpretation": "largest descriptive change after excluding one asset",
            "usage_policy": usage,
        })

    for _, row in concentration[concentration["model_id"] == PRIMARY_MODEL_ID].iterrows():
        rows.append({
            "evidence_area": "concentration", "split": row["split"],
            "model_id": row["model_id"], "top_n": row["top_n"],
            "metric": "top_3_share_of_positive_contribution",
            "value": row["top_3_share_of_positive_contribution"],
            "interpretation": "positive contribution share attributable to top three contributors",
            "usage_policy": usage,
        })
    return pd.DataFrame(rows, columns=EVIDENCE_REGISTER_COLUMNS)


def governance_report(signal, temporal, persistence, sensitivity, concentration):
    primary_signal = signal[signal["model_id"] == PRIMARY_MODEL_ID]
    holdout = primary_signal[primary_signal["split"] == "holdout"]
    development = primary_signal[primary_signal["split"] == "development"]
    return {
        "research_disposition": "RESEARCH_ONLY_NOT_PROMOTED",
        "disposition_is_rule": False,
        "primary_model_id": PRIMARY_MODEL_ID,
        "primary_horizon_days": 7,
        "top_counts_reported": list(TOP_COUNTS),
        "reason": (
            "Phase 7 is a synthesis checkpoint over already-observed evidence. "
            "It is not a fresh validation stage and cannot authorize promotion."
        ),
        "observed_holdout_policy": (
            "The holdout beginning 2025-08-01 was observed before Phase 7. "
            "Holdout-derived statistics are descriptive only and may not be used "
            "to invent, tune, or validate a new trading rule."
        ),
        "phase7_policy": (
            "read-only evidence synthesis only; no fitting, retraining, retuning, "
            "threshold selection, strategy selection, universe changes, asset "
            "blacklists, regime filters, portfolio-rule changes, promotion, live "
            "execution, leverage, or derivatives"
        ),
        "development_signal_rows": len(development),
        "observed_holdout_signal_rows": len(holdout),
        "temporal_summary_rows": len(temporal),
        "asset_persistence_rows": len(persistence),
        "sensitivity_rows": len(sensitivity),
        "concentration_rows": len(concentration),
        "next_valid_research_step": (
            "Pre-register a materially different hypothesis using development-only "
            "selection and reserve genuinely new future data for unbiased validation."
        ),
    }


def run_phase7(phase6_root=PHASE6_ROOT, output_root=PHASE7_ROOT):
    paths, inputs = load_inputs(phase6_root)
    before = {name: _sha256(path) for name, path in paths.items()}

    frames = {
        "signal_summary": signal_summary(inputs["control_comparison"], inputs["bootstrap_uncertainty"]),
        "temporal_consistency": temporal_consistency(inputs["calendar_stability"]),
        "asset_persistence": asset_persistence(inputs["asset_stability"]),
        "sensitivity_summary": sensitivity_summary(inputs["leave_one_asset_out"]),
        "concentration_summary": concentration_summary(inputs["contribution_concentration"]),
    }
    frames["evidence_register"] = evidence_register(
        frames["signal_summary"], frames["temporal_consistency"],
        frames["asset_persistence"], frames["sensitivity_summary"],
        frames["concentration_summary"],
    )
    report = governance_report(
        frames["signal_summary"], frames["temporal_consistency"],
        frames["asset_persistence"], frames["sensitivity_summary"],
        frames["concentration_summary"],
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {name: output_root / f"{name}.csv" for name in frames}
    for name, path in outputs.items():
        frames[name].to_csv(path, index=False)

    report_path = output_root / "governance_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    after = {name: _sha256(path) for name, path in paths.items()}
    if after != before:
        raise RuntimeError("Frozen Phase 6 inputs changed during Phase 7")

    manifest = {
        "phase": 7,
        "research_version": "crypto_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "objective": (
            "Synthesize frozen Phase 6 robustness evidence into a deterministic "
            "research-governance checkpoint without changing any trading rule."
        ),
        "policy": report["phase7_policy"],
        "research_disposition": report["research_disposition"],
        "observed_holdout_policy": report["observed_holdout_policy"],
        "source_files": {
            name: {"path": str(path), "sha256": before[name]}
            for name, path in paths.items()
        },
        "outputs": {
            **{name: str(path) for name, path in outputs.items()},
            "governance_report": str(report_path),
        },
        "output_row_counts": {name: len(frame) for name, frame in frames.items()},
        "phase6_manifest": _json_load(paths["phase6_manifest"]),
        "next_valid_research_step": report["next_valid_research_step"],
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return manifest, frames, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase6-root", type=Path, default=PHASE6_ROOT)
    parser.add_argument("--output-root", type=Path, default=PHASE7_ROOT)
    args = parser.parse_args(argv)
    manifest, _, report = run_phase7(args.phase6_root, args.output_root)
    print(json.dumps({
        "phase": manifest["phase"],
        "policy": manifest["policy"],
        "research_disposition": report["research_disposition"],
        "observed_holdout_policy": manifest["observed_holdout_policy"],
        "output_row_counts": manifest["output_row_counts"],
        "outputs": manifest["outputs"],
        "next_valid_research_step": manifest["next_valid_research_step"],
    }, indent=2))


if __name__ == "__main__":
    main()
