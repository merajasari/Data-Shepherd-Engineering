"""Crypto V5 Phase 4: freeze the selected paper-evaluation contract.

Phase 4 validates development evidence, compares the selected V5 candidate with
the frozen V4 allocator on a common clock, and fits deployment artifacts using
pre-holdout data only.  It does not score the holdout, mutate an existing paper
portfolio, contact a broker, or place an order.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone

from ml.crypto_v5.config import FUTURE_HOLDOUT_START_UTC, PHASE1_ROOT, RESEARCH_VERSION
from ml.crypto_v5.phase2 import FEATURES, model_definitions


MODEL_ROOT = PHASE1_ROOT.parent
PHASE2_ROOT = MODEL_ROOT / "phase2"
PHASE3_ROOT = MODEL_ROOT / "phase3"
OUTPUT_ROOT = MODEL_ROOT / "phase4"
V4_PHASE3_ROOT = MODEL_ROOT.parent / "crypto_v4" / "phase3"

SELECTED_MODEL_ID = "ridge"
SELECTED_HORIZON_DAYS = 3
SELECTED_TOP_N = 3
SELECTED_COST_BPS = 25.0
STRESS_COST_BPS = 50.0
SHADOW_MODEL_ID = "hist_gradient_boosting"
SELECTION_STATUS = "SELECTED_FOR_FORWARD_PAPER_EVALUATION"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate(metrics: pd.DataFrame, cost_bps: float) -> pd.Series:
    rows = metrics[
        (metrics["model_id"] == SELECTED_MODEL_ID)
        & (metrics["horizon_days"] == SELECTED_HORIZON_DAYS)
        & (metrics["top_n"] == SELECTED_TOP_N)
        & np.isclose(metrics["cost_bps_round_trip"], cost_bps)
    ]
    if len(rows) != 1:
        raise ValueError(f"Expected one selected V5 row at {cost_bps:g} bps; found {len(rows)}")
    return rows.iloc[0]


def _compound_metrics(frame: pd.DataFrame, return_column: str, period_days: int) -> dict:
    ordered = frame.sort_values("timestamp_utc").copy()
    if ordered.empty:
        raise ValueError("Cannot summarize an empty comparison frame")
    returns = ordered[return_column].astype(float)
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    elapsed = max((ordered["timestamp_utc"].max() - ordered["timestamp_utc"].min()).days, 1)
    years = elapsed / 365.25
    ending = float(equity.iloc[-1])
    stdev = float(returns.std(ddof=1))
    return {
        "start_utc": ordered["timestamp_utc"].min().isoformat(),
        "end_utc": ordered["timestamp_utc"].max().isoformat(),
        "observations": int(len(ordered)),
        "ending_equity": ending,
        "cumulative_return": ending - 1.0,
        "cagr": ending ** (1.0 / years) - 1.0 if ending > 0 else -1.0,
        "annualized_volatility": stdev * np.sqrt(365.25 / period_days),
        "sharpe": (float(returns.mean()) / stdev * np.sqrt(365.25 / period_days)) if stdev else None,
        "maximum_drawdown": float(drawdown.min()),
        "total_turnover": float(ordered["turnover"].sum()),
    }


def common_clock_comparison(v4_periods: pd.DataFrame, v5_periods: pd.DataFrame) -> dict:
    v4 = v4_periods[
        (v4_periods["variant"] == "v4_hgb_allocator")
        & np.isclose(v4_periods["cost_bps_round_trip"], SELECTED_COST_BPS)
    ].copy()
    v5 = v5_periods[
        (v5_periods["model_id"] == SELECTED_MODEL_ID)
        & (v5_periods["horizon_days"] == SELECTED_HORIZON_DAYS)
        & (v5_periods["top_n"] == SELECTED_TOP_N)
        & np.isclose(v5_periods["cost_bps_round_trip"], SELECTED_COST_BPS)
    ].copy()
    for frame in (v4, v5):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    start = max(v4["timestamp_utc"].min(), v5["timestamp_utc"].min())
    end = min(v4["timestamp_utc"].max(), v5["timestamp_utc"].max())
    if pd.isna(start) or pd.isna(end) or start >= end:
        raise ValueError("V4 and V5 do not have a valid common comparison clock")
    v4 = v4[v4["timestamp_utc"].between(start, end)]
    v5 = v5[v5["timestamp_utc"].between(start, end)]
    return {
        "boundary_start_utc": start.isoformat(),
        "boundary_end_utc": end.isoformat(),
        "v4": _compound_metrics(v4, "net_period_return_7d", 7),
        "v5": _compound_metrics(v5, "net_return", SELECTED_HORIZON_DAYS),
    }


def validate_selection(metrics: pd.DataFrame, comparison: dict) -> dict:
    primary = _candidate(metrics, SELECTED_COST_BPS)
    stress = _candidate(metrics, STRESS_COST_BPS)
    checks = {
        "primary_net_profitable": bool(primary["annualized_return"] > 0),
        "primary_positive_sharpe": bool(primary["sharpe"] > 0),
        "primary_drawdown_at_most_25_pct": bool(primary["maximum_drawdown"] >= -0.25),
        "stress_net_profitable": bool(stress["annualized_return"] > 0),
        "stress_positive_sharpe": bool(stress["sharpe"] > 0),
        "stress_drawdown_at_most_25_pct": bool(stress["maximum_drawdown"] >= -0.25),
        "beats_v4_ending_equity_common_clock": bool(
            comparison["v5"]["ending_equity"] > comparison["v4"]["ending_equity"]
        ),
        "beats_v4_drawdown_common_clock": bool(
            comparison["v5"]["maximum_drawdown"] > comparison["v4"]["maximum_drawdown"]
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("Crypto V5 selection gate failed: " + ", ".join(failed))
    return {
        "checks": checks,
        "primary_metrics": {key: float(primary[key]) for key in (
            "ending_equity", "cumulative_return", "annualized_return", "sharpe",
            "sortino", "maximum_drawdown", "total_turnover", "cash_fraction")},
        "stress_metrics": {key: float(stress[key]) for key in (
            "ending_equity", "cumulative_return", "annualized_return", "sharpe",
            "sortino", "maximum_drawdown", "total_turnover", "cash_fraction")},
    }


def _fit_artifacts(allocation: pd.DataFrame, ranking: pd.DataFrame, artifact_root: Path) -> dict:
    for frame in (allocation, ranking):
        frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
        if (frame["timestamp_utc"] >= FUTURE_HOLDOUT_START_UTC).any():
            raise RuntimeError("Crypto V5 Phase 4 refuses holdout rows")
    ridge = model_definitions()[SELECTED_MODEL_ID]
    outputs = {}
    artifact_root.mkdir(parents=True, exist_ok=True)
    for sleeve in ("btc", "alt", "cash"):
        target = f"{sleeve}_forward_return_{SELECTED_HORIZON_DAYS}d"
        fitted = clone(ridge).fit(allocation[list(FEATURES)], allocation[target])
        path = artifact_root / f"allocation_{sleeve}_{SELECTED_HORIZON_DAYS}d.joblib"
        joblib.dump(fitted, path)
        outputs[f"allocation_{sleeve}"] = str(path)
    target = f"risk_adjusted_forward_return_{SELECTED_HORIZON_DAYS}d"
    fitted = clone(ridge).fit(ranking[list(FEATURES)], ranking[target])
    path = artifact_root / f"ranking_{SELECTED_HORIZON_DAYS}d.joblib"
    joblib.dump(fitted, path)
    outputs["ranking"] = str(path)
    return outputs


def run_phase4(
    phase1_root: Path = PHASE1_ROOT,
    phase3_root: Path = PHASE3_ROOT,
    v4_phase3_root: Path = V4_PHASE3_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    phase1_root, phase3_root = Path(phase1_root), Path(phase3_root)
    v4_phase3_root, output_root = Path(v4_phase3_root), Path(output_root)
    inputs = {
        "allocation_dataset": phase1_root / "allocation_dataset.parquet",
        "ranking_dataset": phase1_root / "ranking_dataset.parquet",
        "phase1_contract": phase1_root / "preregistered_contract.json",
        "phase3_metrics": phase3_root / "portfolio_metrics.csv",
        "phase3_periods": phase3_root / "portfolio_periods.parquet",
        "v4_periods": v4_phase3_root / "portfolio_periods.csv",
    }
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Phase 4 inputs: " + ", ".join(missing))
    input_hashes = {name: _sha256(path) for name, path in inputs.items()}
    allocation = pd.read_parquet(inputs["allocation_dataset"])
    ranking = pd.read_parquet(inputs["ranking_dataset"])
    metrics = pd.read_csv(inputs["phase3_metrics"])
    v5_periods = pd.read_parquet(inputs["phase3_periods"])
    v4_periods = pd.read_csv(inputs["v4_periods"])
    comparison = common_clock_comparison(v4_periods, v5_periods)
    evidence = validate_selection(metrics, comparison)

    output_root.mkdir(parents=True, exist_ok=True)
    artifact_paths = _fit_artifacts(allocation, ranking, output_root / "artifacts")
    artifact_hashes = {name: _sha256(Path(path)) for name, path in artifact_paths.items()}
    contract = {
        "research_version": RESEARCH_VERSION,
        "selection_status": SELECTION_STATUS,
        "selected": {"model_id": SELECTED_MODEL_ID, "horizon_days": SELECTED_HORIZON_DAYS,
                     "top_n": SELECTED_TOP_N, "cost_bps_round_trip": SELECTED_COST_BPS},
        "stress_cost_bps_round_trip": STRESS_COST_BPS,
        "shadow_challenger": {"model_id": SHADOW_MODEL_ID, "horizon_days": 3, "top_n": 3,
                              "may_control_orders": False},
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "activation": "paper observation may begin at the holdout boundary with a fresh causal feature snapshot",
        "evidence": evidence,
        "common_clock_comparison": comparison,
        "input_hashes": input_hashes,
        "artifact_hashes": artifact_hashes,
        "current_phase_prohibited": ["holdout tuning", "automatic promotion", "V4 mutation",
                                     "brokerage order during forward paper evaluation",
                                     "leverage", "shorting", "derivatives"],
        "future_live_path": {
            "allowed_after_separate_explicit_approval": True,
            "requires": ["sufficient forward paper evidence", "independent readiness review",
                         "new live-execution contract", "broker connection and order-limit tests",
                         "manual activation"],
        },
    }
    contract_path = output_root / "selected_contract.json"
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    activation = {
        "research_version": RESEARCH_VERSION,
        "status": "AWAITING_FRESH_HOLDOUT_FEATURE_SNAPSHOT",
        "effective_not_before_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "paper_only": True,
        "brokerage_orders": False,
        "automatic_promotion": False,
        "selected_contract": str(contract_path),
    }
    activation_path = output_root / "paper_activation.json"
    activation_path.write_text(json.dumps(activation, indent=2) + "\n", encoding="utf-8")
    if {name: _sha256(path) for name, path in inputs.items()} != input_hashes:
        raise RuntimeError("A frozen Phase 4 input changed during selection")
    manifest = {
        "research_version": RESEARCH_VERSION, "phase": 4,
        "stage": "immutable_selection_and_paper_preparation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_status": SELECTION_STATUS,
        "future_holdout_start_utc": FUTURE_HOLDOUT_START_UTC.isoformat(),
        "outputs": {"selected_contract": str(contract_path), "paper_activation": str(activation_path),
                    "artifacts": artifact_paths},
        "hashes": {"selected_contract": _sha256(contract_path),
                   "paper_activation": _sha256(activation_path), **artifact_hashes},
        "safety": {"v4_modified": False, "existing_paper_state_modified": False,
                   "holdout_scored": False, "brokerage_orders": False,
                   "new_v5_paper_contract_created": True},
        "next_step": "At/after the holdout boundary, produce a fresh causal feature snapshot and journal paper decisions only.",
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase1-root", type=Path, default=PHASE1_ROOT)
    parser.add_argument("--phase3-root", type=Path, default=PHASE3_ROOT)
    parser.add_argument("--v4-phase3-root", type=Path, default=V4_PHASE3_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    print(json.dumps(run_phase4(args.phase1_root, args.phase3_root,
                                args.v4_phase3_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
