"""StockEagle250 Autonomous ML V1 Phase 2: nested walk-forward evaluation.

Trains the preregistered alpha, downside, and meta-allocation learners. The meta
allocator is trained only from inner walk-forward out-of-sample base-model
predictions generated inside each outer training fold. September 23 and later
remain unread.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone

from ml.stock_eagle_250.phase2 import (
    ENDPOINT_COLUMN,
    FOLDS_PATH,
    PANEL_PATH,
    TARGET_COLUMN,
)
from ml.stock_eagle_250.phase3 import (
    build_model_frame,
    fold_masks,
    _safe_correlation,
)
from ml.stock_eagle_250_autonomous_ml_v1 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)
from ml.stock_eagle_250_autonomous_ml_v1.phase1 import (
    CONTRACT_PATH,
    OUTPUT_ROOT as PHASE1_OUTPUT_ROOT,
    load_contract,
    model_templates,
    sha256,
)

PHASE = 2
PHASE1_MANIFEST_PATH = PHASE1_OUTPUT_ROOT / "manifest.json"
OUTPUT_ROOT = Path("data/model/stock_eagle_250_autonomous_ml_v1/phase2")
RESULT_PATH = OUTPUT_ROOT / "manifest.json"
FOLD_METRICS_PATH = OUTPUT_ROOT / "fold_metrics.csv"
GATE_RESULTS_PATH = OUTPUT_ROOT / "gate_results.csv"
OBSERVATIONS_PATH = OUTPUT_ROOT / "validation_observations.parquet"
META_TRAINING_SUMMARY_PATH = OUTPUT_ROOT / "meta_training_summary.csv"
QUALIFICATION_PATH = OUTPUT_ROOT / "qualification.json"

PRIMARY_COST_BPS = 10.0
STRESS_COST_BPS = 20.0
STARTING_EQUITY = 100_000.0
SLEEVE_COUNT = 5
TOP_N = 10
META_FEATURES = (
    "alpha_top10_mean",
    "alpha_top10_min",
    "alpha_top10_vs_next10_gap",
    "alpha_cross_sectional_std",
    "downside_top10_mean",
    "downside_top10_max",
    "downside_top10_std",
    "eligible_stock_count",
)


def _snapshot_sha(model, feature_columns: list[str], training_cutoff: pd.Timestamp) -> str:
    """Hash the actual fitted estimator plus its feature/cutoff binding."""
    payload = {
        "model": model,
        "features": tuple(feature_columns),
        "training_cutoff_utc": pd.Timestamp(training_cutoff).isoformat(),
    }
    return hashlib.sha256(
        pickle.dumps(payload, protocol=5)
    ).hexdigest()


def validate_phase1(manifest: dict, contract: dict) -> None:
    problems = []
    if manifest.get("research_version") != RESEARCH_VERSION:
        problems.append("research_version")
    if manifest.get("phase") != 1:
        problems.append("phase")
    if manifest.get("contract_sha256") != sha256(CONTRACT_PATH):
        problems.append("contract_sha256")
    if manifest.get("guard_band_rows_read") != 0:
        problems.append("guard_band_rows_read")
    if manifest.get("future_rows_read") != 0:
        problems.append("future_rows_read")
    if manifest.get("performance_calculated") is not False:
        problems.append("performance_calculated")
    if manifest.get("learned_component_count") != 3:
        problems.append("learned_component_count")
    if problems:
        raise RuntimeError(
            "Autonomous ML Phase 2 rejected Phase 1: " + ", ".join(problems)
        )
    if contract["nested_walk_forward"].get("hyperparameter_search") is not False:
        raise RuntimeError("Hyperparameter search is not permitted")


def downside_probability(model, matrix: np.ndarray) -> np.ndarray:
    classes = list(model.classes_)
    if 1 not in classes:
        raise RuntimeError("Downside model does not contain class 1")
    return model.predict_proba(matrix)[:, classes.index(1)]


def learned_position_weights(alpha: np.ndarray, downside: np.ndarray) -> np.ndarray:
    alpha = np.asarray(alpha, dtype=float)
    downside = np.asarray(downside, dtype=float)
    if len(alpha) != len(downside) or len(alpha) == 0:
        raise ValueError("Learned weight inputs are invalid")
    std = float(alpha.std(ddof=0))
    z = np.zeros(len(alpha), dtype=float) if std == 0.0 else (alpha - alpha.mean()) / std
    score = np.exp(np.clip(z - downside, -20.0, 20.0))
    total = float(score.sum())
    if not np.isfinite(total) or total <= 0.0:
        raise RuntimeError("Learned position scores are invalid")
    return score / total


def session_meta_row(scored: pd.DataFrame, include_target: bool) -> dict:
    ordered = scored.sort_values(
        ["alpha_prediction", "symbol"],
        ascending=[False, True],
    ).reset_index(drop=True)
    if len(ordered) < 20:
        raise RuntimeError("Fewer than 20 eligible names for meta features")
    top = ordered.head(TOP_N).copy()
    next10 = ordered.iloc[TOP_N:20]
    alpha = top["alpha_prediction"].to_numpy(float)
    downside = top["downside_probability"].to_numpy(float)
    weights = learned_position_weights(alpha, downside)

    row = {
        "timestamp_utc": pd.Timestamp(ordered.iloc[0]["timestamp_utc"]),
        "alpha_top10_mean": float(alpha.mean()),
        "alpha_top10_min": float(alpha.min()),
        "alpha_top10_vs_next10_gap": float(
            alpha.mean() - next10["alpha_prediction"].mean()
        ),
        "alpha_cross_sectional_std": float(
            ordered["alpha_prediction"].std(ddof=0)
        ),
        "downside_top10_mean": float(downside.mean()),
        "downside_top10_max": float(downside.max()),
        "downside_top10_std": float(downside.std(ddof=0)),
        "eligible_stock_count": int(len(ordered)),
        "selected_symbols": ",".join(top["symbol"].astype(str)),
        "selected_weight_vector": weights.tolist(),
    }
    if include_target:
        gross = float(np.dot(weights, top["forward_stock_return"].to_numpy(float)))
        side = PRIMARY_COST_BPS / 10_000.0
        net = (1.0 + gross) * (1.0 - side) ** 2 - 1.0
        row["meta_target_positive"] = int(net > 0.0)
        row["meta_target_net_return"] = net
    return row


def fit_base_models(
    training: pd.DataFrame,
    feature_columns: list[str],
    templates: dict,
):
    X = training[feature_columns].to_numpy(float)
    alpha = clone(templates["alpha_model"]).fit(
        X,
        training[TARGET_COLUMN].to_numpy(float),
    )
    downside_y = (
        training["forward_stock_return"].to_numpy(float) < 0.0
    ).astype(int)
    if len(np.unique(downside_y)) < 2:
        raise RuntimeError("Downside training target contains one class")
    downside = clone(templates["downside_model"]).fit(X, downside_y)
    return alpha, downside


def score_base_models(
    frame: pd.DataFrame,
    feature_columns: list[str],
    alpha_model,
    downside_model,
) -> pd.DataFrame:
    scored = frame.copy()
    X = scored[feature_columns].to_numpy(float)
    scored["alpha_prediction"] = alpha_model.predict(X)
    scored["downside_probability"] = downside_probability(downside_model, X)
    return scored


def inner_meta_training_rows(
    outer_training: pd.DataFrame,
    feature_columns: list[str],
    templates: dict,
    contract: dict,
) -> pd.DataFrame:
    spec = contract["nested_walk_forward"]["inner_meta_training"]
    minimum_sessions = int(spec["minimum_base_training_sessions"])
    block_sessions = int(spec["test_block_sessions"])
    purge_sessions = int(spec["purge_sessions"])

    sessions = sorted(pd.to_datetime(
        outer_training["timestamp_utc"].unique(),
        utc=True,
    ))
    rows = []
    cursor = minimum_sessions + purge_sessions

    while cursor < len(sessions):
        test_sessions = sessions[cursor:cursor + block_sessions]
        if not test_sessions:
            break
        test_start = pd.Timestamp(test_sessions[0])
        last_allowed_index = cursor - purge_sessions - 1
        if last_allowed_index < 0:
            break
        last_allowed_session = pd.Timestamp(sessions[last_allowed_index])

        train_mask = (
            (outer_training["timestamp_utc"] <= last_allowed_session)
            & (outer_training[ENDPOINT_COLUMN] < test_start)
        )
        training = outer_training.loc[train_mask].copy()
        testing = outer_training.loc[
            outer_training["timestamp_utc"].isin(test_sessions)
        ].copy()
        if training.empty or testing.empty:
            cursor += len(test_sessions)
            continue

        alpha, downside = fit_base_models(
            training,
            feature_columns,
            templates,
        )
        scored = score_base_models(
            testing,
            feature_columns,
            alpha,
            downside,
        )
        for timestamp, session in scored.groupby("timestamp_utc", sort=True):
            meta = session_meta_row(session, include_target=True)
            meta.update({
                "inner_test_timestamp_utc": pd.Timestamp(timestamp),
                "inner_training_rows": int(len(training)),
                "inner_training_last_session_utc": last_allowed_session,
                "inner_training_max_target_endpoint_utc":
                    pd.Timestamp(training[ENDPOINT_COLUMN].max()),
            })
            rows.append(meta)
        cursor += len(test_sessions)

    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("No inner OOS meta-training rows were generated")
    if (
        pd.to_datetime(result["inner_training_max_target_endpoint_utc"], utc=True)
        >= pd.to_datetime(result["inner_test_timestamp_utc"], utc=True)
    ).any():
        raise RuntimeError("Inner OOS meta training leaked target endpoints")
    return result


def fit_meta_allocator(meta_rows: pd.DataFrame, template, contract: dict):
    minimum = int(
        contract["nested_walk_forward"]["inner_meta_training"][
            "allocator_minimum_oos_sessions"
        ]
    )
    if len(meta_rows) < minimum:
        raise RuntimeError(
            f"Meta allocator OOS rows below minimum: {len(meta_rows)} < {minimum}"
        )
    y = meta_rows["meta_target_positive"].to_numpy(int)
    if len(np.unique(y)) < 2:
        raise RuntimeError("Meta allocator target contains one class")
    model = clone(template).fit(
        meta_rows[list(META_FEATURES)].to_numpy(float),
        y,
    )
    return model


def simulate_sleeves(returns: list[float]) -> dict:
    sleeves = np.full(SLEEVE_COUNT, STARTING_EQUITY / SLEEVE_COUNT)
    account = [STARTING_EQUITY]
    for index, value in enumerate(returns):
        sleeve = index % SLEEVE_COUNT
        sleeves[sleeve] *= 1.0 + float(value)
        account.append(float(sleeves.sum()))
    curve = pd.Series(account, dtype=float)
    drawdown = curve / curve.cummax() - 1.0
    total_return = float(account[-1] / STARTING_EQUITY - 1.0)
    return {
        "net_return": total_return,
        "maximum_drawdown": float(drawdown.min()),
    }


def outer_validation_observations(
    validation: pd.DataFrame,
    feature_columns: list[str],
    alpha_model,
    downside_model,
    meta_model,
    fold_id: str,
    alpha_sha: str,
    downside_sha: str,
    meta_sha: str,
) -> pd.DataFrame:
    scored = score_base_models(
        validation,
        feature_columns,
        alpha_model,
        downside_model,
    )
    observations = []
    for timestamp, session in scored.groupby("timestamp_utc", sort=True):
        meta = session_meta_row(session, include_target=False)
        meta_frame = pd.DataFrame([{key: meta[key] for key in META_FEATURES}])
        classes = list(meta_model.classes_)
        if 1 not in classes:
            raise RuntimeError("Meta allocator does not contain class 1")
        probability = float(
            meta_model.predict_proba(meta_frame.to_numpy(float))[0, classes.index(1)]
        )
        exposure = float(np.clip(probability, 0.0, 1.0))

        ordered = session.sort_values(
            ["alpha_prediction", "symbol"],
            ascending=[False, True],
        ).reset_index(drop=True)
        top = ordered.head(TOP_N).copy()
        normalized = learned_position_weights(
            top["alpha_prediction"].to_numpy(float),
            top["downside_probability"].to_numpy(float),
        )
        account_weights = exposure * normalized
        gross = float(np.dot(
            account_weights,
            top["forward_stock_return"].to_numpy(float),
        ))
        primary_side = exposure * PRIMARY_COST_BPS / 10_000.0
        stress_side = exposure * STRESS_COST_BPS / 10_000.0
        primary = (1.0 + gross) * (1.0 - primary_side) ** 2 - 1.0
        stress = (1.0 + gross) * (1.0 - stress_side) ** 2 - 1.0

        spy_return = float(session["forward_spy_return"].iloc[0])
        equal_gross = float(session["forward_stock_return"].mean())
        equal_side = PRIMARY_COST_BPS / 10_000.0
        equal_net = (1.0 + equal_gross) * (1.0 - equal_side) ** 2 - 1.0

        observations.append({
            "fold_id": fold_id,
            "timestamp_utc": pd.Timestamp(timestamp),
            "eligible_stock_count": int(len(session)),
            "selected_symbols": ",".join(top["symbol"].astype(str)),
            "gross_exposure": exposure,
            "cash_fraction": 1.0 - exposure,
            "primary_net_return": primary,
            "stress_20bps_net_return": stress,
            "spy_return": spy_return,
            "equal_weight_net_return": equal_net,
            "alpha_model_sha256": alpha_sha,
            "downside_model_sha256": downside_sha,
            "meta_allocator_sha256": meta_sha,
            **{key: meta[key] for key in META_FEATURES},
        })
    return pd.DataFrame(observations)


def fold_rank_ic(scored_validation: pd.DataFrame) -> float:
    values = []
    for _, session in scored_validation.groupby("timestamp_utc", sort=True):
        values.append(_safe_correlation(
            session[TARGET_COLUMN],
            session["alpha_prediction"],
            method="spearman",
        ))
    series = pd.Series(values, dtype=float).dropna()
    return float(series.mean()) if not series.empty else np.nan


def evaluate_gates(metrics: pd.DataFrame, contract: dict):
    gates = contract["development_gates"]
    summary = {
        "median_fold_net_return": float(metrics["net_return"].median()),
        "positive_fold_fraction": float((metrics["net_return"] > 0.0).mean()),
        "median_fold_excess_vs_spy": float(metrics["excess_vs_spy"].median()),
        "positive_excess_vs_spy_fold_fraction":
            float((metrics["excess_vs_spy"] > 0.0).mean()),
        "median_fold_excess_vs_equal_weight":
            float(metrics["excess_vs_equal_weight"].median()),
        "median_fold_rank_ic": float(metrics["mean_rank_ic"].median()),
        "positive_rank_ic_fold_fraction":
            float((metrics["mean_rank_ic"] > 0.0).mean()),
        "worst_fold_maximum_drawdown":
            float(metrics["maximum_drawdown"].min()),
        "median_fold_stress_20bps_net_return":
            float(metrics["stress_20bps_net_return"].median()),
    }
    results = {
        "median_fold_net_return_gt_zero":
            summary["median_fold_net_return"] > float(gates["median_fold_net_return_gt"]),
        "positive_fold_fraction_gte":
            summary["positive_fold_fraction"] >= float(gates["positive_fold_fraction_gte"]),
        "median_fold_excess_vs_spy_gt_zero":
            summary["median_fold_excess_vs_spy"] > float(gates["median_fold_excess_vs_spy_gt"]),
        "positive_excess_vs_spy_fold_fraction_gte":
            summary["positive_excess_vs_spy_fold_fraction"] >=
            float(gates["positive_excess_vs_spy_fold_fraction_gte"]),
        "median_fold_excess_vs_equal_weight_gt_zero":
            summary["median_fold_excess_vs_equal_weight"] >
            float(gates["median_fold_excess_vs_equal_weight_gt"]),
        "median_fold_rank_ic_gt_zero":
            summary["median_fold_rank_ic"] > float(gates["median_fold_rank_ic_gt"]),
        "positive_rank_ic_fold_fraction_gte":
            summary["positive_rank_ic_fold_fraction"] >=
            float(gates["positive_rank_ic_fold_fraction_gte"]),
        "worst_fold_maximum_drawdown_gte":
            summary["worst_fold_maximum_drawdown"] >=
            float(gates["worst_fold_maximum_drawdown_gte"]),
        "median_fold_stress_20bps_net_return_gt_zero":
            summary["median_fold_stress_20bps_net_return"] >
            float(gates["median_fold_stress_20bps_net_return_gt"]),
    }
    gate_frame = pd.DataFrame([
        {"gate": key, "passed": bool(value)}
        for key, value in results.items()
    ])
    passed = int(sum(results.values()))
    total = len(results)
    qualification = {
        "status": (
            "QUALIFIES_FOR_AUTONOMOUS_PAPER_BUILD"
            if passed == total
            else "REJECT_DEVELOPMENT_CANDIDATE"
        ),
        "gates_passed": passed,
        "gates_total": total,
        "failed_gates": [key for key, value in results.items() if not value],
        "autonomous_paper_runtime_enabled": False,
        "model_frozen": False,
    }
    return gate_frame, summary, qualification


def run(
    panel_path: Path = PANEL_PATH,
    folds_path: Path = FOLDS_PATH,
    phase1_manifest_path: Path = PHASE1_MANIFEST_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict:
    contract = load_contract()
    phase1 = json.loads(Path(phase1_manifest_path).read_text(encoding="utf-8"))
    validate_phase1(phase1, contract)

    panel = pd.read_parquet(panel_path)
    frame, feature_columns = build_model_frame(panel)
    folds = json.loads(Path(folds_path).read_text(encoding="utf-8"))
    templates = model_templates(contract)

    fold_rows = []
    observation_frames = []
    meta_rows = []

    for fold in folds:
        fold_id = fold["fold_id"]
        train_mask, validation_mask = fold_masks(frame, fold)
        training = frame.loc[train_mask].copy()
        validation = frame.loc[validation_mask].copy()
        if len(training) != int(fold["train_rows"]):
            raise RuntimeError(f"{fold_id} outer training rows changed")
        if len(validation) != int(fold["validation_rows"]):
            raise RuntimeError(f"{fold_id} outer validation rows changed")

        inner_meta = inner_meta_training_rows(
            training,
            feature_columns,
            templates,
            contract,
        )
        inner_meta.insert(0, "outer_fold_id", fold_id)
        meta_rows.append(inner_meta)
        meta_model = fit_meta_allocator(
            inner_meta,
            templates["meta_allocator"],
            contract,
        )

        alpha_model, downside_model = fit_base_models(
            training,
            feature_columns,
            templates,
        )
        training_cutoff = pd.Timestamp(training[ENDPOINT_COLUMN].max())
        alpha_sha = _snapshot_sha(alpha_model, feature_columns, training_cutoff)
        downside_sha = _snapshot_sha(
            downside_model,
            feature_columns,
            training_cutoff,
        )
        meta_sha = _snapshot_sha(
            meta_model,
            list(META_FEATURES),
            pd.Timestamp(inner_meta["inner_test_timestamp_utc"].max()),
        )

        observations = outer_validation_observations(
            validation,
            feature_columns,
            alpha_model,
            downside_model,
            meta_model,
            fold_id,
            alpha_sha,
            downside_sha,
            meta_sha,
        )
        observation_frames.append(observations)

        scored_validation = score_base_models(
            validation,
            feature_columns,
            alpha_model,
            downside_model,
        )
        rank_ic = fold_rank_ic(scored_validation)
        primary = simulate_sleeves(observations["primary_net_return"].tolist())
        stress = simulate_sleeves(observations["stress_20bps_net_return"].tolist())
        spy = simulate_sleeves(observations["spy_return"].tolist())
        equal = simulate_sleeves(observations["equal_weight_net_return"].tolist())

        fold_rows.append({
            "fold_id": fold_id,
            "training_rows": int(len(training)),
            "validation_rows": int(len(validation)),
            "validation_sessions": int(observations["timestamp_utc"].nunique()),
            "meta_oos_training_sessions": int(len(inner_meta)),
            "mean_gross_exposure": float(observations["gross_exposure"].mean()),
            "net_return": primary["net_return"],
            "maximum_drawdown": primary["maximum_drawdown"],
            "stress_20bps_net_return": stress["net_return"],
            "spy_net_return": spy["net_return"],
            "equal_weight_net_return": equal["net_return"],
            "excess_vs_spy": primary["net_return"] - spy["net_return"],
            "excess_vs_equal_weight": primary["net_return"] - equal["net_return"],
            "mean_rank_ic": rank_ic,
            "alpha_model_sha256": alpha_sha,
            "downside_model_sha256": downside_sha,
            "meta_allocator_sha256": meta_sha,
        })
        print(
            f"[SUCCESS] {fold_id} train={len(training):,} "
            f"validation={len(validation):,} meta_oos={len(inner_meta):,}"
        )

    metrics = pd.DataFrame(fold_rows)
    observations = pd.concat(observation_frames, ignore_index=True)
    meta_training = pd.concat(meta_rows, ignore_index=True)
    gates, summary, qualification = evaluate_gates(metrics, contract)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output_root / "fold_metrics.csv", index=False)
    observations.to_parquet(
        output_root / "validation_observations.parquet",
        index=False,
    )
    meta_training.to_csv(
        output_root / "meta_training_summary.csv",
        index=False,
    )
    gates.to_csv(output_root / "gate_results.csv", index=False)
    (output_root / "qualification.json").write_text(
        json.dumps(qualification, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
        "phase": PHASE,
        "stage": "nested_walk_forward_three_model_ml_evaluation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_sha256": sha256(CONTRACT_PATH),
        "fold_count": int(len(metrics)),
        "learned_components": 3,
        "meta_allocator_training_source": "inner_walk_forward_oos_only",
        "guard_band_rows_read": 0,
        "future_rows_read": 0,
        "summary": summary,
        "qualification": qualification,
        "outputs": {
            "fold_metrics": str(output_root / "fold_metrics.csv"),
            "observations": str(output_root / "validation_observations.parquet"),
            "meta_training": str(output_root / "meta_training_summary.csv"),
            "gates": str(output_root / "gate_results.csv"),
            "qualification": str(output_root / "qualification.json"),
        },
        "safety": {
            "existing_models_modified": False,
            "existing_forward_journals_modified": False,
            "model_frozen": False,
            "autonomous_paper_runtime_enabled": False,
            "live_execution_enabled": False,
        },
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
