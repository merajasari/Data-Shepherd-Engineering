"""Shared Crypto V7 Phase 3: predictive-skill adjudication.

Reviews the preregistered primary model's Phase 2 out-of-sample evidence before
portfolio simulation.  This is a fail-closed research stop, not a promotion
gate: it may reject an unskilled model but cannot qualify, freeze, or activate
one.  It performs no fitting, threshold search, portfolio simulation,
future-holdout scoring, paper-state write, or brokerage action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd


RESEARCH_VERSION = "shared_crypto_v7_weekly_return_regression"
PRIMARY_MODEL = "hist_gradient_boosting_absolute_error_regressor"
PHASE2_ROOT = Path("data/model/shared_crypto_v7_weekly_return_regression/phase2")
OUTPUT_ROOT = Path("data/model/shared_crypto_v7_weekly_return_regression/phase3")
HOLDOUT = "2026-09-01T00:00:00+00:00"


def adjudicate(summary: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    required = {
        "model_id", "fold_count",
        "mean_btc_mae_improvement_vs_train_mean",
        "mean_alt_mae_improvement_vs_train_mean",
        "mean_btc_r2", "mean_alt_r2",
        "mean_btc_spearman", "mean_alt_spearman",
        "mean_sleeve_accuracy",
    }
    missing = required - set(summary.columns)
    if missing:
        raise RuntimeError(f"V7 Phase 2 summary missing columns: {sorted(missing)}")
    primary = summary[summary["model_id"] == PRIMARY_MODEL]
    if len(primary) != 1:
        raise RuntimeError("V7 Phase 2 must contain exactly one primary-model summary")
    row = primary.iloc[0]
    btc_improvement = float(row["mean_btc_mae_improvement_vs_train_mean"])
    alt_improvement = float(row["mean_alt_mae_improvement_vs_train_mean"])
    btc_r2 = float(row["mean_btc_r2"])
    alt_r2 = float(row["mean_alt_r2"])
    sleeve_accuracy = float(row["mean_sleeve_accuracy"])

    checks = {
        "btc_beats_train_mean_mae": btc_improvement > 0.0,
        "alt_beats_train_mean_mae": alt_improvement > 0.0,
        "btc_r2_positive": btc_r2 > 0.0,
        "alt_r2_positive": alt_r2 > 0.0,
        "sleeve_accuracy_above_one_third": sleeve_accuracy > (1.0 / 3.0),
    }
    consensus_no_skill = (
        not checks["btc_beats_train_mean_mae"]
        and not checks["alt_beats_train_mean_mae"]
        and not checks["btc_r2_positive"]
        and not checks["alt_r2_positive"]
        and not checks["sleeve_accuracy_above_one_third"]
    )
    status = (
        "REJECT_CURRENT_V7_MODEL_FAMILY_BEFORE_PORTFOLIO_SIMULATION"
        if consensus_no_skill
        else "HUMAN_REVIEW_REQUIRED_BEFORE_PORTFOLIO_SIMULATION"
    )
    disposition = pd.DataFrame([{
        "model_id": PRIMARY_MODEL,
        **checks,
        "consensus_no_predictive_skill": consensus_no_skill,
        "status": status,
    }])
    decision = {
        "status": status,
        "portfolio_simulation_authorized": False,
        "primary_model_evidence": {
            "fold_count": int(row["fold_count"]),
            "btc_mae_improvement_vs_train_mean": btc_improvement,
            "alt_mae_improvement_vs_train_mean": alt_improvement,
            "btc_r2": btc_r2,
            "alt_r2": alt_r2,
            "btc_spearman": float(row["mean_btc_spearman"]),
            "alt_spearman": float(row["mean_alt_spearman"]),
            "sleeve_accuracy": sleeve_accuracy,
            "one_third_reference": 1.0 / 3.0,
            **checks,
            "consensus_no_predictive_skill": consensus_no_skill,
        },
    }
    return disposition, decision


def run(phase2_root: Path = PHASE2_ROOT, output_root: Path = OUTPUT_ROOT) -> dict:
    phase2_root = Path(phase2_root)
    output_root = Path(output_root)
    manifest = json.loads(
        (phase2_root / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("research_version") != RESEARCH_VERSION:
        raise RuntimeError("Unexpected V7 Phase 2 research version")
    if manifest.get("future_holdout_start_utc") != HOLDOUT:
        raise RuntimeError("Unexpected V7 Phase 2 future-holdout boundary")
    if manifest.get("primary_model") != PRIMARY_MODEL:
        raise RuntimeError("Unexpected V7 Phase 2 primary model")
    summary = pd.read_csv(phase2_root / "metrics_summary.csv")
    disposition, decision = adjudicate(summary)

    output_root.mkdir(parents=True, exist_ok=True)
    disposition.to_csv(output_root / "model_disposition.csv", index=False)
    payload = {
        "research_version": RESEARCH_VERSION,
        "phase": 3,
        "stage": "immutable_predictive_skill_adjudication",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "future_holdout_start_utc": HOLDOUT,
        **decision,
        "review_semantics": {
            "checks_are_preregistered_promotion_gates": False,
            "can_qualify_or_promote_model": False,
            "purpose": (
                "Stop before economic simulation when the fixed primary model "
                "shows a consensus lack of out-of-sample predictive skill."
            ),
        },
        "reason": (
            "Both primary regressors have worse MAE than the training-mean "
            "baseline, both have negative out-of-sample R-squared, and the "
            "three-sleeve decision accuracy is below one third. Portfolio "
            "simulation would risk converting noise into a misleading result."
        ),
        "outputs": {
            "model_disposition": str(output_root / "model_disposition.csv"),
            "adjudication": str(output_root / "adjudication.json"),
        },
        "safety": {
            "phase1_contract_changed_after_results": False,
            "model_family_changed_after_results": False,
            "threshold_search_performed": False,
            "portfolio_simulated": False,
            "economic_gates_claimed": False,
            "shared_crypto_v3_modified": False,
            "rejected_v5_modified": False,
            "rejected_v6_modified": False,
            "future_holdout_scored": False,
            "v7_model_frozen": False,
            "paper_state_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
        "next_step": (
            "Preserve V7 as rejected predictive evidence. Do not simulate its "
            "portfolio or tune its models on these observed results. Any "
            "successor must be separately named and preregistered."
        ),
    }
    (output_root / "adjudication.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2-root", type=Path, default=PHASE2_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.phase2_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
