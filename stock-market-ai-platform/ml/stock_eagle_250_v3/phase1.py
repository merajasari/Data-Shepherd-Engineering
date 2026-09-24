"""StockEagle250 V3 Phase 1: preregistered volatility-budget risk control.

V3 is created after the fixed V2 trend-conditioned regime overlay failed its
preregistered development gates. Phase 1 validates only preserved pre-guard V2
evidence and the fixed V3 contract. It does not calculate V3 performance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.stock_eagle_250_v3 import DISPLAY_NAME, MODEL_ID, RESEARCH_VERSION


PHASE = 1
CONTRACT_PATH = Path(__file__).with_name("phase1_contract.json")
V2_PHASE2_ROOT = Path("data/model/stock_eagle_250_v2/phase2")
V2_MANIFEST_PATH = V2_PHASE2_ROOT / "manifest.json"
V2_QUALIFICATION_PATH = V2_PHASE2_ROOT / "qualification.json"
V2_REGIME_SUMMARY_PATH = V2_PHASE2_ROOT / "regime_summary.csv"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_v3/phase1")
MANIFEST_PATH = OUTPUT_ROOT / "manifest.json"

V1_RANKING_CANDIDATE = "ridge_fixed_v1"
V2_CANDIDATE = "ridge_v1_rank_v10_regime_exposure_v2"
V3_CANDIDATE = "ridge_v1_rank_volatility_budget_v3"
V2_RESEARCH_VERSION = "stock_eagle_250_v2_risk_controlled_ridge"
GUARD_BAND_START_UTC = pd.Timestamp("2026-09-23", tz="UTC")
FUTURE_START_UTC = pd.Timestamp("2026-10-01", tz="UTC")
MAXIMUM_DEVELOPMENT_ENDPOINT_UTC = pd.Timestamp("2026-09-22", tz="UTC")
SPY_VOL_LOOKBACK = 20
SPY_VOL_BASELINE_LOOKBACK = 252
SPY_VOL_BASELINE_MINIMUM = 60

EXPECTED_V2_FAILED_GATES = {
    "gate_median_fold_excess_vs_spy_gt_zero",
    "gate_positive_excess_vs_spy_fold_fraction_gte_60pct",
    "gate_median_fold_excess_vs_v1_ridge_gte_minus_2pct",
    "gate_median_drawdown_improvement_vs_v1_gte_5pct",
    "gate_median_calmar_gte_v1_ridge",
}
V2_GATE_KEYS = {
    "median_fold_primary_net_return_gt",
    "positive_primary_fold_fraction_gte",
    "median_fold_excess_vs_spy_gt",
    "positive_excess_vs_spy_fold_fraction_gte",
    "median_fold_excess_vs_equal_weight_gt",
    "median_fold_excess_vs_v1_ridge_gte",
    "worst_fold_maximum_drawdown_gte",
    "median_fold_drawdown_improvement_vs_v1_ridge_gte",
    "drawdown_improvement_fold_fraction_gte",
    "median_fold_calmar_gte_v1_ridge",
    "median_fold_stress_20bps_net_return_gt",
}


def _utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    mismatches = {
        key: {"expected": value, "actual": contract.get(key)}
        for key, value in expected.items()
        if contract.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"StockEagle250 V3 identity mismatch: {mismatches}")
    if contract.get("created_before_v3_results") is not True:
        raise RuntimeError("V3 contract was not marked preregistered")

    candidate = contract["fixed_candidate"]
    if candidate.get("candidate_id") != V3_CANDIDATE:
        raise RuntimeError("Unexpected V3 candidate identity")
    if candidate.get("ranking_source") != V1_RANKING_CANDIDATE:
        raise RuntimeError("V3 ranking source is not the fixed V1 Ridge ranker")
    if candidate.get("spy_trend_direction_used") is not False:
        raise RuntimeError("V3 must not use SPY trend direction")
    if candidate.get("gross_exposure_rule") != (
        "if inputs_not_ready_or_nonpositive then 0.0 else min(1.0, "
        "lagged_rolling_median_spy_volatility_252 / spy_realized_volatility_20)"
    ):
        raise RuntimeError("V3 exposure formula differs from preregistration")
    if any(candidate.get(key) is not False for key in (
        "threshold_search",
        "exposure_search",
        "model_search",
        "hyperparameter_search",
    )):
        raise RuntimeError("V3 contract permits a prohibited search")

    budget = contract["volatility_budget"]
    expected_budget = {
        "spy_volatility_lookback_sessions": SPY_VOL_LOOKBACK,
        "spy_volatility_baseline_sessions": SPY_VOL_BASELINE_LOOKBACK,
        "spy_volatility_baseline_minimum_sessions": SPY_VOL_BASELINE_MINIMUM,
        "volatility_baseline_lag_sessions": 1,
        "completed_session_information_only": True,
    }
    if any(budget.get(key) != value for key, value in expected_budget.items()):
        raise RuntimeError("V3 volatility-budget parameters differ from code")

    boundaries = contract["data_boundaries"]
    if _utc(boundaries["sealed_guard_band_start_utc"]) != GUARD_BAND_START_UTC:
        raise RuntimeError("V3 guard-band start differs from code")
    if _utc(boundaries["new_untouched_future_start_utc"]) != FUTURE_START_UTC:
        raise RuntimeError("V3 untouched future boundary differs from code")
    if _utc(boundaries["maximum_development_target_endpoint_utc"]) != MAXIMUM_DEVELOPMENT_ENDPOINT_UTC:
        raise RuntimeError("V3 development endpoint differs from code")

    gates = contract["preregistered_development_gates"]
    if gates.get("policy") != "reuse_v2_gates_without_relaxation":
        raise RuntimeError("V3 must reuse the V2 gate policy without relaxation")
    if set(gates) - {"policy"} != V2_GATE_KEYS:
        raise RuntimeError("V3 preregistered gate set is incomplete or changed")

    authority = contract["authority"]
    if any(authority.get(key) is not False for key in (
        "model_freezing_enabled",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
    )):
        raise RuntimeError("V3 Phase 1 has trading or freezing authority")
    return contract


def validate_v2_evidence(
    manifest: dict,
    qualification: dict,
    regime_summary: pd.DataFrame,
) -> dict:
    problems = []
    if manifest.get("research_version") != V2_RESEARCH_VERSION:
        problems.append("unexpected V2 research version")
    if manifest.get("phase") != 2:
        problems.append("V2 evidence is not Phase 2")
    if manifest.get("candidate_id") != V2_CANDIDATE:
        problems.append("unexpected V2 candidate")
    if manifest.get("guard_band_rows_read") != 0:
        problems.append("V2 reports guard-band rows")
    if manifest.get("future_rows_read") != 0:
        problems.append("V2 reports future rows")

    safety = manifest.get("safety", {})
    if any(safety.get(key) is not False for key in (
        "future_holdout_scored",
        "candidate_frozen",
        "paper_trading_enabled",
        "live_trading_enabled",
        "brokerage_orders",
        "automatic_promotion",
    )):
        problems.append("V2 evidence reports forbidden activity")

    if qualification.get("candidate_id") != V2_CANDIDATE:
        problems.append("V2 qualification candidate differs")
    if qualification.get("status") != "REJECT_CURRENT_STOCK_EAGLE_250_V2_CANDIDATE":
        problems.append("V2 is not preserved as rejected")
    if qualification.get("qualified_for_human_review") is not False:
        problems.append("V2 unexpectedly qualified for human review")
    if qualification.get("gates_passed") != 6 or qualification.get("gates_total") != 11:
        problems.append("V2 gate count differs from preserved result")
    failed = set(qualification.get("failed_gates", []))
    if failed != EXPECTED_V2_FAILED_GATES:
        problems.append("V2 failed-gate set differs from preserved result")

    required_columns = {
        "market_state",
        "periods",
        "mean_gross_exposure",
        "mean_unscaled_ridge_return",
        "mean_v2_net_return",
    }
    missing = sorted(required_columns - set(regime_summary.columns))
    if missing:
        problems.append(f"V2 regime summary missing columns: {missing}")
    else:
        negative_high = regime_summary.loc[
            regime_summary["market_state"] == "NEGATIVE_HIGH_VOL"
        ]
        if len(negative_high) != 1:
            problems.append("V2 NEGATIVE_HIGH_VOL diagnostic is missing or duplicated")
        else:
            row = negative_high.iloc[0]
            if not np.isclose(float(row["mean_gross_exposure"]), 0.0, atol=1e-12):
                problems.append("V2 NEGATIVE_HIGH_VOL did not use zero exposure")
            if not float(row["mean_unscaled_ridge_return"]) > 0.0:
                problems.append(
                    "V2 NEGATIVE_HIGH_VOL no longer shows positive unscaled Ridge return"
                )

    if problems:
        raise RuntimeError(
            "StockEagle250 V3 rejected its V2 evidence:\n- "
            + "\n- ".join(problems)
        )

    summary = manifest.get("summary", {})
    return {
        "v2_status": qualification["status"],
        "v2_gates_passed": int(qualification["gates_passed"]),
        "v2_gates_total": int(qualification["gates_total"]),
        "v2_failed_gates": sorted(failed),
        "v2_worst_fold_maximum_drawdown":
            float(summary.get("worst_fold_maximum_drawdown")),
        "v2_median_fold_excess_vs_v1_ridge":
            float(summary.get("median_fold_excess_vs_v1_ridge")),
        "negative_high_vol_unscaled_ridge_return": float(
            regime_summary.loc[
                regime_summary["market_state"] == "NEGATIVE_HIGH_VOL",
                "mean_unscaled_ridge_return",
            ].iloc[0]
        ),
        "negative_high_vol_v2_exposure": 0.0,
    }


def volatility_budget_frame(spy_returns: pd.DataFrame) -> pd.DataFrame:
    """Build the fixed trend-agnostic V3 exposure from completed SPY sessions."""
    required = {"timestamp_utc", "spy_return_1d"}
    missing = sorted(required - set(spy_returns.columns))
    if missing:
        raise ValueError(f"SPY state input is missing columns: {missing}")

    frame = spy_returns[["timestamp_utc", "spy_return_1d"]].copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    if (frame["timestamp_utc"] >= GUARD_BAND_START_UTC).any():
        raise RuntimeError("SPY state input enters the sealed V3 guard band")
    frame = frame.sort_values("timestamp_utc").drop_duplicates(
        "timestamp_utc",
        keep="last",
    )

    returns = pd.to_numeric(frame["spy_return_1d"], errors="coerce")
    frame["spy_realized_volatility_20"] = returns.rolling(
        SPY_VOL_LOOKBACK,
        min_periods=SPY_VOL_LOOKBACK,
    ).std(ddof=0)
    frame["lagged_rolling_median_spy_volatility_252"] = (
        frame["spy_realized_volatility_20"]
        .shift(1)
        .rolling(
            SPY_VOL_BASELINE_LOOKBACK,
            min_periods=SPY_VOL_BASELINE_MINIMUM,
        )
        .median()
    )

    current = frame["spy_realized_volatility_20"]
    baseline = frame["lagged_rolling_median_spy_volatility_252"]
    ready = (
        np.isfinite(current)
        & np.isfinite(baseline)
        & (current > 0.0)
        & (baseline > 0.0)
    )
    frame["gross_exposure"] = 0.0
    frame.loc[ready, "gross_exposure"] = np.minimum(
        1.0,
        baseline.loc[ready] / current.loc[ready],
    )
    frame["cash_fraction"] = 1.0 - frame["gross_exposure"]

    if not frame["gross_exposure"].between(0.0, 1.0).all():
        raise RuntimeError("V3 volatility budget produced exposure outside [0, 1]")
    if (frame.loc[ready, "gross_exposure"] <= 0.0).any():
        raise RuntimeError("V3 valid volatility input produced zero stock exposure")
    return frame


def build_manifest(contract: dict, v2_evidence: dict) -> dict:
    return {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "preregistered_trend_agnostic_volatility_budget_readiness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_id": V3_CANDIDATE,
        "candidate_count": 1,
        "ranking_source": V1_RANKING_CANDIDATE,
        "spy_trend_direction_used": False,
        "contract_sha256": _sha256(CONTRACT_PATH),
        "v2_development_evidence": v2_evidence,
        "sealed_guard_band_start_utc": GUARD_BAND_START_UTC.isoformat(),
        "sealed_guard_band_end_exclusive_utc": FUTURE_START_UTC.isoformat(),
        "new_untouched_future_start_utc": FUTURE_START_UTC.isoformat(),
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "v3_performance_calculated": False,
        "qualification_gates_fixed_before_v3_results": bool(
            contract["created_before_v3_results"]
        ),
        "gate_policy": contract["preregistered_development_gates"]["policy"],
        "safety": {
            "v1_artifacts_modified": False,
            "v2_artifacts_modified": False,
            "hyperparameter_search_performed": False,
            "threshold_search_performed": False,
            "exposure_search_performed": False,
            "future_holdout_scored": False,
            "candidate_frozen": False,
            "paper_trading_enabled": False,
            "live_trading_enabled": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
            "existing_forward_journals_modified": False,
        },
        "next_step": (
            "Implement Phase 2 only after this preregistration exists. Evaluate "
            "this one fixed volatility-budget challenger on the same saved V1 "
            "out-of-sample development portfolios at 10-bps primary and 20-bps "
            "stress costs. Do not read September 23 or later."
        ),
    }


def run(
    v2_manifest_path: Path = V2_MANIFEST_PATH,
    v2_qualification_path: Path = V2_QUALIFICATION_PATH,
    v2_regime_summary_path: Path = V2_REGIME_SUMMARY_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    v2_manifest = json.loads(
        Path(v2_manifest_path).read_text(encoding="utf-8")
    )
    v2_qualification = json.loads(
        Path(v2_qualification_path).read_text(encoding="utf-8")
    )
    v2_regime = pd.read_csv(v2_regime_summary_path)
    evidence = validate_v2_evidence(
        v2_manifest,
        v2_qualification,
        v2_regime,
    )
    payload = build_manifest(contract, evidence)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-manifest", type=Path, default=V2_MANIFEST_PATH)
    parser.add_argument(
        "--v2-qualification",
        type=Path,
        default=V2_QUALIFICATION_PATH,
    )
    parser.add_argument(
        "--v2-regime-summary",
        type=Path,
        default=V2_REGIME_SUMMARY_PATH,
    )
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run(
        v2_manifest_path=args.v2_manifest,
        v2_qualification_path=args.v2_qualification,
        v2_regime_summary_path=args.v2_regime_summary,
        output_root=args.output_root,
    ), indent=2))


if __name__ == "__main__":
    main()
