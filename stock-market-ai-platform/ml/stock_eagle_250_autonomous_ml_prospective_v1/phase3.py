"""Fail-closed append-only Oct-2026 prospective runner for Autonomous ML V1/V2/V3.

The runner uses the three exact pre-boundary snapshot hashes sealed in
phase3_contract.json. Decisions are captured only on the same New York calendar
date as the completed session, after 16:05 ET. Missed decision sessions are
never reconstructed. Entry/exit realization is mechanical and may be appended
later when the relevant daily source rows become available.

Paper evidence only. No retraining, automatic selection, promotion, live
execution, or brokerage orders.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pickle
import tempfile
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.stock_eagle_250.phase2 import (
    FEATURE_ROOT,
    MINIMUM_HISTORY_SESSIONS,
    RANK_FEATURE_COLUMNS,
    RAW_FEATURE_COLUMNS,
    STOCK_250_SYMBOLS,
    V5_BENCHMARK_SYMBOL,
    feature_path,
    get_stock_250_sector,
)
from ml.stock_eagle_250_autonomous_ml_prospective_v1 import (
    DISPLAY_NAME,
    MODEL_ID,
    RESEARCH_VERSION,
)
from ml.stock_eagle_250_autonomous_ml_v1 import phase2 as v1_phase2
from ml.stock_eagle_250_autonomous_ml_v2 import phase2 as v2_phase2
from ml.stock_eagle_250_autonomous_ml_v3 import phase2 as v3_phase2


NEW_YORK = ZoneInfo("America/New_York")
PHASE = 3
CONTRACT_PATH = Path(__file__).with_name("phase3_contract.json")
PHASE2_ROOT = Path(
    "data/model/stock_eagle_250_autonomous_ml_prospective_v1/phase2"
)
PHASE2_MANIFEST_PATH = PHASE2_ROOT / "manifest.json"
SNAPSHOT_ROOT = PHASE2_ROOT / "snapshots"
OUTPUT_ROOT = Path(
    "data/model/stock_eagle_250_autonomous_ml_prospective_v1/phase3"
)
JOURNAL_PATH = OUTPUT_ROOT / "journal.jsonl"
STATUS_PATH = OUTPUT_ROOT / "status.json"

EXPECTED_CANDIDATE_ORDER = (
    "autonomous_ml_v1",
    "autonomous_ml_v2",
    "autonomous_ml_v3",
)
TOP_N = 10
PRIMARY_COST_BPS = 10.0
STRESS_COST_BPS = 20.0
SLEEVE_COUNT = 5
STARTING_EQUITY = 100_000.0


def _as_utc(value: datetime | pd.Timestamp) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        raise ValueError("PROSPECTIVE_NOW_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _timestamp(value: object) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").normalize()


def _market_open(timestamp: object) -> datetime:
    day = _timestamp(timestamp).date()
    return datetime.combine(
        day,
        time(9, 30),
        tzinfo=NEW_YORK,
    ).astimezone(timezone.utc)


def _market_close(timestamp: object) -> datetime:
    day = _timestamp(timestamp).date()
    return datetime.combine(
        day,
        time(16, 5),
        tzinfo=NEW_YORK,
    ).astimezone(timezone.utc)


def _ny_date(now_utc: datetime) -> object:
    return now_utc.astimezone(NEW_YORK).date()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def contract_sha256(contract: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(contract),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {
        "display_name": DISPLAY_NAME,
        "model_id": MODEL_ID,
        "research_version": RESEARCH_VERSION,
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise RuntimeError(f"Prospective Phase 3 identity mismatch: {key}")
    if contract.get("created_before_prospective_results") is not True:
        raise RuntimeError("Prospective Phase 3 was not preregistered")

    snapshots = contract.get("fixed_snapshots") or []
    ids = tuple(row.get("candidate_id") for row in snapshots)
    if ids != EXPECTED_CANDIDATE_ORDER:
        raise RuntimeError("Prospective fixed snapshot order changed")

    decision = contract["decision_capture"]
    if decision.get("late_decision_backfill") is not False:
        raise RuntimeError("Late decision backfill must remain disabled")
    if decision.get("historical_decision_reconstruction") is not False:
        raise RuntimeError("Historical decision reconstruction must remain disabled")
    if decision.get("same_decision_batch_required_for_all_candidates") is not True:
        raise RuntimeError("All candidates must share one decision batch")

    authority = contract["authority"]
    for key in (
        "brokerage_orders",
        "live_execution_enabled",
        "model_retraining_enabled",
        "snapshot_replacement_enabled",
        "existing_model_journal_modification",
    ):
        if authority.get(key) is not False:
            raise RuntimeError(f"Prospective authority changed: {key}")
    if authority.get("paper_only") is not True:
        raise RuntimeError("Prospective runner must remain paper-only")

    review = contract["formal_review"]
    if int(review["minimum_completed_cohorts_per_candidate"]) != 60:
        raise RuntimeError("Formal-review cohort threshold changed")
    if int(review["minimum_complete_five_sleeve_blocks"]) != 12:
        raise RuntimeError("Formal-review block threshold changed")
    for key in (
        "automatic_winner_selection",
        "automatic_promotion",
        "new_architecture_before_formal_review",
    ):
        if review.get(key) is not False:
            raise RuntimeError(f"Formal-review authority changed: {key}")
    return contract


def validate_snapshot_manifest(
    manifest: Mapping[str, object],
    contract: Mapping[str, object],
) -> None:
    problems = []
    if manifest.get("research_version") != RESEARCH_VERSION:
        problems.append("research_version")
    if manifest.get("phase") != 2:
        problems.append("phase")
    if manifest.get("snapshots_built") is not True:
        problems.append("snapshots_built")
    if manifest.get("snapshots_fixed_for_prospective_evaluation") is not True:
        problems.append("snapshots_fixed")
    if manifest.get("post_snapshot_retraining_during_evaluation") is not False:
        problems.append("post_snapshot_retraining")
    if manifest.get("sealed_guard_band_read") is not False:
        problems.append("sealed_guard_band_read")
    if manifest.get("prospective_rows_read") != 0:
        problems.append("prospective_rows_read")
    if manifest.get("prospective_performance_calculated") is not False:
        problems.append("prospective_performance_calculated")
    if manifest.get("automatic_winner_selection") is not False:
        problems.append("automatic_winner_selection")
    if manifest.get("automatic_model_promotion") is not False:
        problems.append("automatic_model_promotion")
    if manifest.get("brokerage_orders") is not False:
        problems.append("brokerage_orders")
    if manifest.get("live_execution_enabled") is not False:
        problems.append("live_execution_enabled")

    fixed_source = contract["fixed_source"]
    if manifest.get("source_panel_sha256") != fixed_source[
        "development_panel_sha256"
    ]:
        problems.append("development_panel_sha256")
    source = manifest.get("source") or {}
    if int(source.get("training_rows", -1)) != int(
        fixed_source["training_rows"]
    ):
        problems.append("training_rows")
    if source.get("training_decision_end_utc") != fixed_source[
        "training_decision_end_utc"
    ]:
        problems.append("training_decision_end_utc")
    if source.get("training_target_endpoint_max_utc") != fixed_source[
        "training_target_endpoint_max_utc"
    ]:
        problems.append("training_target_endpoint_max_utc")

    expected = {
        row["candidate_id"]: row
        for row in contract["fixed_snapshots"]
    }
    actual_rows = manifest.get("snapshots") or []
    actual = {
        row.get("candidate_id"): row
        for row in actual_rows
    }
    if tuple(manifest.get("candidate_order") or []) != EXPECTED_CANDIDATE_ORDER:
        problems.append("candidate_order")
    if set(actual) != set(expected):
        problems.append("candidate_set")
    else:
        for candidate_id, fixed in expected.items():
            row = actual[candidate_id]
            for key in (
                "snapshot_sha256",
                "learned_component_count",
                "meta_oos_training_sessions",
                "training_cutoff_utc",
                "meta_oos_cutoff_utc",
            ):
                if row.get(key) != fixed.get(key):
                    problems.append(f"{candidate_id}:{key}")

    if problems:
        raise RuntimeError(
            "Prospective Phase 3 rejected snapshot manifest: "
            + ", ".join(problems)
        )


def load_snapshot_manifest(
    path: Path = PHASE2_MANIFEST_PATH,
    contract: Mapping[str, object] | None = None,
) -> dict:
    contract = load_contract() if contract is None else contract
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_snapshot_manifest(manifest, contract)
    return manifest


def load_snapshots(
    manifest: Mapping[str, object],
    contract: Mapping[str, object],
    snapshot_root: Path = SNAPSHOT_ROOT,
) -> dict[str, dict]:
    manifest_rows = {
        row["candidate_id"]: row
        for row in manifest["snapshots"]
    }
    fixed_rows = {
        row["candidate_id"]: row
        for row in contract["fixed_snapshots"]
    }
    snapshots: dict[str, dict] = {}

    for candidate_id in EXPECTED_CANDIDATE_ORDER:
        manifest_row = manifest_rows[candidate_id]
        expected_sha = fixed_rows[candidate_id]["snapshot_sha256"]
        path = Path(snapshot_root) / f"{candidate_id}.pkl"
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(
                f"PROSPECTIVE_SNAPSHOT_MISSING:{candidate_id}:{path}"
            )
        actual_sha = _sha256_file(path)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"PROSPECTIVE_SNAPSHOT_HASH_MISMATCH:{candidate_id}"
            )
        if manifest_row["snapshot_sha256"] != expected_sha:
            raise RuntimeError(
                f"PROSPECTIVE_MANIFEST_HASH_MISMATCH:{candidate_id}"
            )

        payload = pickle.loads(path.read_bytes())
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"PROSPECTIVE_SNAPSHOT_PAYLOAD_INVALID:{candidate_id}"
            )
        if payload.get("candidate_id") != candidate_id:
            raise RuntimeError(
                f"PROSPECTIVE_SNAPSHOT_ID_MISMATCH:{candidate_id}"
            )
        feature_columns = list(payload.get("feature_columns") or [])
        meta_features = list(payload.get("meta_features") or [])
        if len(feature_columns) != int(manifest_row["feature_count"]):
            raise RuntimeError(
                f"PROSPECTIVE_FEATURE_COUNT_MISMATCH:{candidate_id}"
            )
        if len(meta_features) != int(manifest_row["meta_feature_count"]):
            raise RuntimeError(
                f"PROSPECTIVE_META_FEATURE_COUNT_MISMATCH:{candidate_id}"
            )
        if payload.get("research_version") != manifest_row["research_version"]:
            raise RuntimeError(
                f"PROSPECTIVE_RESEARCH_VERSION_MISMATCH:{candidate_id}"
            )
        if payload.get("training_cutoff_utc") != manifest_row["training_cutoff_utc"]:
            raise RuntimeError(
                f"PROSPECTIVE_TRAINING_CUTOFF_MISMATCH:{candidate_id}"
            )
        if payload.get("meta_oos_cutoff_utc") != manifest_row["meta_oos_cutoff_utc"]:
            raise RuntimeError(
                f"PROSPECTIVE_META_CUTOFF_MISMATCH:{candidate_id}"
            )
        snapshots[candidate_id] = payload

    feature_sets = {
        tuple(snapshot["feature_columns"])
        for snapshot in snapshots.values()
    }
    if len(feature_sets) != 1:
        raise RuntimeError("Prospective snapshots use different stock features")
    return snapshots


def _read_symbol_features(
    symbol: str,
    feature_root: Path = FEATURE_ROOT,
) -> pd.DataFrame:
    path = feature_path(symbol, feature_root)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"FEATURE_DATASET_MISSING:{symbol}:{path}")
    columns = ["timestamp_utc", "open", "close", *RAW_FEATURE_COLUMNS]
    frame = pd.read_parquet(path, columns=columns).copy()
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"],
        utc=True,
        errors="raise",
    ).dt.normalize()
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    if frame.empty:
        raise RuntimeError(f"FEATURE_DATASET_EMPTY:{symbol}")
    if frame["timestamp_utc"].duplicated().any():
        raise RuntimeError(f"FEATURE_DUPLICATE_TIMESTAMP:{symbol}")
    return frame


def load_spy_sessions(
    feature_root: Path = FEATURE_ROOT,
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    frame = _read_symbol_features(V5_BENCHMARK_SYMBOL, feature_root)
    dates = [
        pd.Timestamp(value)
        for value in frame["timestamp_utc"].tolist()
    ]
    return frame, dates


def completed_prospective_sessions(
    dates: list[pd.Timestamp],
    now_utc: datetime,
    start: pd.Timestamp,
) -> list[pd.Timestamp]:
    return [
        _timestamp(value)
        for value in dates
        if _timestamp(value) >= start
        and _market_close(value) <= now_utc
    ]


def decision_session_allowed_now(
    decision_ts: pd.Timestamp,
    now_utc: datetime,
) -> bool:
    decision_ts = _timestamp(decision_ts)
    return (
        _market_close(decision_ts) <= now_utc
        and decision_ts.date() == _ny_date(now_utc)
    )


def build_decision_frame(
    decision_ts: pd.Timestamp,
    feature_columns: list[str],
    *,
    symbols=STOCK_250_SYMBOLS,
    feature_root: Path = FEATURE_ROOT,
    minimum_eligible_names: int = 20,
) -> tuple[pd.DataFrame, str, dict]:
    decision_ts = _timestamp(decision_ts)
    rows = []
    missing_exact_session = []
    incomplete = []

    for symbol in tuple(symbols):
        frame = _read_symbol_features(symbol, feature_root)
        history = frame.loc[
            frame["timestamp_utc"] <= decision_ts
        ].copy()
        exact = history.loc[
            history["timestamp_utc"] == decision_ts
        ]
        if exact.empty:
            missing_exact_session.append(symbol)
            continue
        row = exact.iloc[-1]
        if len(history) < MINIMUM_HISTORY_SESSIONS:
            incomplete.append(symbol)
            continue
        raw = row[list(RAW_FEATURE_COLUMNS)]
        if raw.isna().any() or not np.isfinite(
            raw.to_numpy(dtype=float)
        ).all():
            incomplete.append(symbol)
            continue
        payload = {
            "timestamp_utc": decision_ts,
            "symbol": symbol,
            "sector": get_stock_250_sector(symbol),
        }
        payload.update({
            column: float(row[column])
            for column in RAW_FEATURE_COLUMNS
        })
        rows.append(payload)

    if len(rows) < int(minimum_eligible_names):
        raise RuntimeError(
            "PROSPECTIVE_FEATURE_SNAPSHOT_INCOMPLETE:"
            f"eligible={len(rows)} minimum={minimum_eligible_names}"
        )

    frame = pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)
    for raw_column, rank_column in zip(
        RAW_FEATURE_COLUMNS,
        RANK_FEATURE_COLUMNS,
    ):
        frame[rank_column] = frame[raw_column].rank(
            method="average",
            pct=True,
        )

    sector = pd.get_dummies(
        frame["sector"].astype(str),
        prefix="sector",
        dtype=float,
    )
    sector = sector.reindex(sorted(sector.columns), axis=1)
    frame = pd.concat(
        [frame.reset_index(drop=True), sector.reset_index(drop=True)],
        axis=1,
    )
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = 0.0
    matrix = frame[feature_columns].to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        raise RuntimeError("PROSPECTIVE_MODEL_INPUT_NONFINITE")

    canonical_rows = []
    for _, row in frame.sort_values("symbol").iterrows():
        canonical_rows.append({
            "symbol": str(row["symbol"]),
            "features": [
                float(row[column])
                for column in feature_columns
            ],
        })
    canonical = {
        "decision_timestamp_utc": decision_ts.isoformat(),
        "feature_columns": list(feature_columns),
        "rows": canonical_rows,
    }
    input_sha = _sha256_bytes(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    diagnostics = {
        "universe_count": len(tuple(symbols)),
        "eligible_stock_count": len(frame),
        "missing_exact_session_count": len(missing_exact_session),
        "incomplete_count": len(incomplete),
        "missing_exact_session_symbols": missing_exact_session,
        "incomplete_symbols": incomplete,
    }
    return frame, input_sha, diagnostics


def _candidate_module(candidate_id: str):
    if candidate_id == "autonomous_ml_v1":
        return v1_phase2
    if candidate_id == "autonomous_ml_v2":
        return v2_phase2
    if candidate_id == "autonomous_ml_v3":
        return v3_phase2
    raise RuntimeError(f"Unknown prospective candidate: {candidate_id}")


def _positive_probability(model, matrix: np.ndarray) -> float:
    classes = list(model.classes_)
    if 1 not in classes:
        raise RuntimeError("PROSPECTIVE_META_MODEL_MISSING_POSITIVE_CLASS")
    probability = float(
        model.predict_proba(matrix)[0, classes.index(1)]
    )
    if not np.isfinite(probability):
        raise RuntimeError("PROSPECTIVE_META_PROBABILITY_NONFINITE")
    return float(np.clip(probability, 0.0, 1.0))


def score_candidate(
    candidate_id: str,
    snapshot: Mapping[str, object],
    decision_frame: pd.DataFrame,
) -> dict:
    module = _candidate_module(candidate_id)
    feature_columns = list(snapshot["feature_columns"])
    models = snapshot["models"]

    if candidate_id == "autonomous_ml_v1":
        scored = module.score_base_models(
            decision_frame,
            feature_columns,
            models["alpha_model"],
            models["downside_model"],
        )
    else:
        scored = module.score_base_models(
            decision_frame,
            feature_columns,
            models["alpha_model"],
            models["downside_model"],
            models["tail_model"],
        )

    meta = module.session_meta_row(
        scored,
        include_target=False,
    )
    meta_features = list(snapshot["meta_features"])
    meta_matrix = np.asarray(
        [[float(meta[key]) for key in meta_features]],
        dtype=float,
    )
    active_weight = _positive_probability(
        models["meta_allocator"],
        meta_matrix,
    )

    ordered = scored.sort_values(
        ["alpha_prediction", "symbol"],
        ascending=[False, True],
    ).reset_index(drop=True)
    top = ordered.head(TOP_N).copy()

    if candidate_id == "autonomous_ml_v1":
        normalized = module.learned_position_weights(
            top["alpha_prediction"].to_numpy(float),
            top["downside_probability"].to_numpy(float),
        )
    else:
        normalized = module.learned_position_weights(
            top["alpha_prediction"].to_numpy(float),
            top["downside_probability"].to_numpy(float),
            top["tail10_prediction"].to_numpy(float),
        )

    if candidate_id == "autonomous_ml_v3":
        spy_weight = 1.0 - active_weight
        cash_fraction = 0.0
    else:
        spy_weight = 0.0
        cash_fraction = 1.0 - active_weight

    selected = []
    for index, row in enumerate(top.itertuples(index=False)):
        item = {
            "symbol": str(row.symbol),
            "rank": index + 1,
            "active_sleeve_weight": float(normalized[index]),
            "account_weight": float(active_weight * normalized[index]),
            "alpha_prediction": float(row.alpha_prediction),
            "downside_probability": float(row.downside_probability),
        }
        if hasattr(row, "tail10_prediction"):
            item["tail10_prediction"] = float(row.tail10_prediction)
        selected.append(item)

    return {
        "candidate_id": candidate_id,
        "active_weight": active_weight,
        "spy_weight": spy_weight,
        "cash_fraction": cash_fraction,
        "selected_symbols": [
            row["symbol"] for row in selected
        ],
        "selected_positions": selected,
        "meta_features": {
            key: float(meta[key])
            for key in meta_features
        },
        "paper_only": True,
        "brokerage_orders": False,
    }


def _event_key(event: Mapping[str, object]) -> tuple[object, object]:
    return (
        event.get("event_type"),
        event.get("decision_timestamp_utc"),
    )


def _read_events(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    events = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"PROSPECTIVE_JOURNAL_CORRUPT_LINE_{line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError(
                f"PROSPECTIVE_JOURNAL_INVALID_LINE_{line_number}"
            )
        events.append(value)
    return events


@contextmanager
def _journal_lock(path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_event(event: Mapping[str, object], path: Path) -> bool:
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    with _journal_lock(lock_path):
        events = _read_events(path)
        existing = {_event_key(item) for item in events}
        if _event_key(event) in existing:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    dict(event),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
    return True


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                dict(payload),
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _price_at(
    symbol: str,
    timestamp: pd.Timestamp,
    column: str,
    feature_root: Path,
) -> float | None:
    frame = _read_symbol_features(symbol, feature_root)
    row = frame.loc[
        frame["timestamp_utc"] == _timestamp(timestamp)
    ]
    if row.empty:
        return None
    value = float(row.iloc[-1][column])
    if not np.isfinite(value) or value <= 0.0:
        return None
    return value


def _session_after(
    dates: list[pd.Timestamp],
    decision_ts: pd.Timestamp,
    offset: int,
) -> pd.Timestamp | None:
    normalized = [_timestamp(value) for value in dates]
    decision_ts = _timestamp(decision_ts)
    if decision_ts not in normalized:
        return None
    index = normalized.index(decision_ts)
    target = index + int(offset)
    if target >= len(normalized):
        return None
    return normalized[target]


def candidate_realized_return(
    candidate_id: str,
    decision_payload: Mapping[str, object],
    entry_prices: Mapping[str, float],
    exit_prices: Mapping[str, float],
    spy_entry_price: float,
    spy_exit_price: float,
) -> dict:
    positions = decision_payload["selected_positions"]
    symbol_returns = {
        row["symbol"]:
            float(exit_prices[row["symbol"]])
            / float(entry_prices[row["symbol"]])
            - 1.0
        for row in positions
    }
    active_gross = float(sum(
        float(row["active_sleeve_weight"])
        * symbol_returns[row["symbol"]]
        for row in positions
    ))
    active_weight = float(decision_payload["active_weight"])
    spy_weight = float(decision_payload["spy_weight"])
    cash_fraction = float(decision_payload["cash_fraction"])
    spy_return = float(spy_exit_price / spy_entry_price - 1.0)

    if candidate_id == "autonomous_ml_v3":
        blended_gross = (
            active_weight * active_gross
            + spy_weight * spy_return
        )
        primary_side = PRIMARY_COST_BPS / 10_000.0
        stress_side = STRESS_COST_BPS / 10_000.0
    else:
        blended_gross = active_weight * active_gross
        primary_side = (
            active_weight * PRIMARY_COST_BPS / 10_000.0
        )
        stress_side = (
            active_weight * STRESS_COST_BPS / 10_000.0
        )

    primary = (
        (1.0 + blended_gross)
        * (1.0 - primary_side) ** 2
        - 1.0
    )
    stress = (
        (1.0 + blended_gross)
        * (1.0 - stress_side) ** 2
        - 1.0
    )
    return {
        "candidate_id": candidate_id,
        "active_weight": active_weight,
        "spy_weight": spy_weight,
        "cash_fraction": cash_fraction,
        "active_top10_gross_return": active_gross,
        "blended_gross_return": blended_gross,
        "primary_net_return": float(primary),
        "stress_20bps_net_return": float(stress),
        "spy_return": spy_return,
        "excess_vs_spy": float(primary - spy_return),
        "symbol_returns": symbol_returns,
    }


def _candidate_equity_summary(
    exits: list[dict],
    candidate_id: str,
) -> dict:
    sleeves = np.full(
        SLEEVE_COUNT,
        STARTING_EQUITY / SLEEVE_COUNT,
        dtype=float,
    )
    stress_sleeves = sleeves.copy()
    spy_sleeves = sleeves.copy()
    curve = [STARTING_EQUITY]
    returns = []
    stress_returns = []
    excess = []
    active_weights = []

    ordered = sorted(
        exits,
        key=lambda row: (
            str(row.get("exit_timestamp_utc", "")),
            str(row.get("decision_timestamp_utc", "")),
        ),
    )
    for event in ordered:
        candidate = event["candidates"][candidate_id]
        offset = int(event["cohort_offset"])
        primary = float(candidate["primary_net_return"])
        stress = float(candidate["stress_20bps_net_return"])
        spy = float(candidate["spy_return"])
        sleeves[offset] *= 1.0 + primary
        stress_sleeves[offset] *= 1.0 + stress
        spy_sleeves[offset] *= 1.0 + spy
        curve.append(float(sleeves.sum()))
        returns.append(primary)
        stress_returns.append(stress)
        excess.append(float(candidate["excess_vs_spy"]))
        active_weights.append(float(candidate["active_weight"]))

    equity = float(sleeves.sum())
    stress_equity = float(stress_sleeves.sum())
    spy_equity = float(spy_sleeves.sum())
    curve_series = pd.Series(curve, dtype=float)
    drawdown = curve_series / curve_series.cummax() - 1.0

    return {
        "normalized_equity": equity,
        "total_net_return": equity / STARTING_EQUITY - 1.0,
        "stress_normalized_equity": stress_equity,
        "stress_20bps_total_net_return":
            stress_equity / STARTING_EQUITY - 1.0,
        "matched_spy_equity": spy_equity,
        "matched_spy_return":
            spy_equity / STARTING_EQUITY - 1.0,
        "excess_vs_spy":
            equity / STARTING_EQUITY
            - spy_equity / STARTING_EQUITY,
        "positive_net_return_cohort_fraction":
            float(np.mean(np.asarray(returns) > 0.0))
            if returns else None,
        "positive_excess_vs_spy_cohort_fraction":
            float(np.mean(np.asarray(excess) > 0.0))
            if excess else None,
        "maximum_drawdown":
            float(drawdown.min()) if len(curve) > 1 else 0.0,
        "mean_active_weight":
            float(np.mean(active_weights))
            if active_weights else None,
        "completed_cohorts": len(returns),
    }


def summarize(
    events: list[dict],
    contract: Mapping[str, object],
    *,
    missed_decision_sessions: list[str] | None = None,
) -> dict:
    decisions = [
        row for row in events
        if row.get("event_type") == "DECISION_BATCH"
    ]
    entries = [
        row for row in events
        if row.get("event_type") == "ENTRY_BATCH"
    ]
    exits = [
        row for row in events
        if row.get("event_type") == "EXIT_BATCH"
    ]

    offset_counts = [
        sum(
            int(row.get("cohort_offset", -1)) == offset
            for row in exits
        )
        for offset in range(SLEEVE_COUNT)
    ]
    complete_blocks = min(offset_counts) if exits else 0

    candidate_metrics = {
        candidate_id:
            _candidate_equity_summary(exits, candidate_id)
        for candidate_id in EXPECTED_CANDIDATE_ORDER
    }
    review = contract["formal_review"]
    formal_review_ready = (
        len(exits)
        >= int(review["minimum_completed_cohorts_per_candidate"])
        and complete_blocks
        >= int(review["minimum_complete_five_sleeve_blocks"])
    )

    return {
        "decision_batches": len(decisions),
        "entry_batches": len(entries),
        "exit_batches": len(exits),
        "completed_cohorts_per_candidate": len(exits),
        "complete_five_sleeve_blocks": complete_blocks,
        "cohort_offset_exit_counts": offset_counts,
        "missed_decision_sessions":
            list(missed_decision_sessions or []),
        "candidate_metrics": candidate_metrics,
        "formal_review_ready": bool(formal_review_ready),
        "formal_review_status": (
            "READY_FOR_HUMAN_REVIEW"
            if formal_review_ready
            else "COLLECTING_UNSEEN_EVIDENCE"
        ),
        "automatic_winner_selection": False,
        "automatic_model_promotion": False,
        "new_architecture_before_formal_review": False,
        "paper_only": True,
        "brokerage_orders": False,
        "live_execution_enabled": False,
    }


def _missed_sessions(
    prospective_sessions: list[pd.Timestamp],
    events: list[dict],
    now_utc: datetime,
) -> list[str]:
    recorded = {
        _timestamp(row["decision_timestamp_utc"])
        for row in events
        if row.get("event_type") == "DECISION_BATCH"
    }
    today = _ny_date(now_utc)
    return [
        session.date().isoformat()
        for session in prospective_sessions
        if session not in recorded
        and session.date() < today
    ]


def _process_lifecycle(
    *,
    events: list[dict],
    dates: list[pd.Timestamp],
    now_utc: datetime,
    feature_root: Path,
    journal_path: Path,
    contract: Mapping[str, object],
    contract_sha: str,
) -> int:
    appended = 0
    existing = {_event_key(row) for row in events}

    for decision in [
        row for row in events
        if row.get("event_type") == "DECISION_BATCH"
    ]:
        decision_ts = _timestamp(
            decision["decision_timestamp_utc"]
        )
        key = (
            "ENTRY_BATCH",
            decision["decision_timestamp_utc"],
        )
        if key in existing:
            continue
        entry_ts = _session_after(dates, decision_ts, 1)
        if entry_ts is None or _market_open(entry_ts) > now_utc:
            continue

        symbols = sorted({
            item["symbol"]
            for candidate in decision["candidates"].values()
            for item in candidate["selected_positions"]
        })
        entry_prices = {}
        for symbol in symbols:
            price = _price_at(
                symbol,
                entry_ts,
                "open",
                feature_root,
            )
            if price is None:
                break
            entry_prices[symbol] = price
        else:
            spy_entry = _price_at(
                V5_BENCHMARK_SYMBOL,
                entry_ts,
                "open",
                feature_root,
            )
            if spy_entry is None:
                continue
            event = {
                "event_type": "ENTRY_BATCH",
                "journal_type":
                    "STOCK_EAGLE_AUTONOMOUS_ML_PROSPECTIVE_V1",
                "contract_sha256": contract_sha,
                "decision_timestamp_utc":
                    decision["decision_timestamp_utc"],
                "cohort_offset": decision["cohort_offset"],
                "entry_timestamp_utc": entry_ts.isoformat(),
                "entry_prices": entry_prices,
                "spy_entry_price": spy_entry,
                "snapshot_sha256":
                    decision["snapshot_sha256"],
                "paper_only": True,
                "brokerage_orders": False,
                "created_at_utc": now_utc.isoformat(),
            }
            if _append_event(event, journal_path):
                appended += 1
                existing.add(key)

    events = _read_events(journal_path)
    existing = {_event_key(row) for row in events}
    decisions_by_ts = {
        row["decision_timestamp_utc"]: row
        for row in events
        if row.get("event_type") == "DECISION_BATCH"
    }

    for entry in [
        row for row in events
        if row.get("event_type") == "ENTRY_BATCH"
    ]:
        key = (
            "EXIT_BATCH",
            entry["decision_timestamp_utc"],
        )
        if key in existing:
            continue
        decision = decisions_by_ts.get(
            entry["decision_timestamp_utc"]
        )
        if decision is None:
            raise RuntimeError(
                "PROSPECTIVE_ENTRY_WITHOUT_DECISION"
            )
        decision_ts = _timestamp(
            entry["decision_timestamp_utc"]
        )
        exit_ts = _session_after(dates, decision_ts, 5)
        if exit_ts is None or _market_close(exit_ts) > now_utc:
            continue

        symbols = sorted(entry["entry_prices"])
        exit_prices = {}
        for symbol in symbols:
            price = _price_at(
                symbol,
                exit_ts,
                "close",
                feature_root,
            )
            if price is None:
                break
            exit_prices[symbol] = price
        else:
            spy_exit = _price_at(
                V5_BENCHMARK_SYMBOL,
                exit_ts,
                "close",
                feature_root,
            )
            if spy_exit is None:
                continue

            candidate_results = {}
            for candidate_id in EXPECTED_CANDIDATE_ORDER:
                candidate_results[candidate_id] = (
                    candidate_realized_return(
                        candidate_id,
                        decision["candidates"][candidate_id],
                        entry["entry_prices"],
                        exit_prices,
                        float(entry["spy_entry_price"]),
                        spy_exit,
                    )
                )

            event = {
                "event_type": "EXIT_BATCH",
                "journal_type":
                    "STOCK_EAGLE_AUTONOMOUS_ML_PROSPECTIVE_V1",
                "contract_sha256": contract_sha,
                "decision_timestamp_utc":
                    entry["decision_timestamp_utc"],
                "cohort_offset": entry["cohort_offset"],
                "entry_timestamp_utc":
                    entry["entry_timestamp_utc"],
                "exit_timestamp_utc": exit_ts.isoformat(),
                "exit_prices": exit_prices,
                "spy_exit_price": spy_exit,
                "candidates": candidate_results,
                "snapshot_sha256":
                    entry["snapshot_sha256"],
                "paper_only": True,
                "brokerage_orders": False,
                "created_at_utc": now_utc.isoformat(),
            }
            if _append_event(event, journal_path):
                appended += 1
                existing.add(key)
    return appended


def run_once(
    *,
    now_utc: datetime | pd.Timestamp | None = None,
    contract: Mapping[str, object] | None = None,
    phase2_manifest_path: Path = PHASE2_MANIFEST_PATH,
    snapshot_root: Path = SNAPSHOT_ROOT,
    feature_root: Path = FEATURE_ROOT,
    journal_path: Path = JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
    spy_loader_fn: Callable[
        [Path],
        tuple[pd.DataFrame, list[pd.Timestamp]],
    ] | None = None,
    decision_builder_fn: Callable[..., tuple[pd.DataFrame, str, dict]]
        | None = None,
) -> dict:
    contract = load_contract() if contract is None else dict(contract)
    now = _as_utc(now_utc or datetime.now(timezone.utc))
    contract_sha = contract_sha256(contract)
    start = _timestamp(contract["prospective_start_utc"])

    manifest = load_snapshot_manifest(
        phase2_manifest_path,
        contract,
    )
    snapshots = load_snapshots(
        manifest,
        contract,
        snapshot_root,
    )
    events = _read_events(journal_path)

    if now < _market_close(start):
        payload = {
            "status": "WAITING_FOR_PROSPECTIVE_BOUNDARY",
            "checked_at_utc": now.isoformat(),
            "prospective_start_utc": start.isoformat(),
            "contract_sha256": contract_sha,
            "snapshot_sha256": {
                row["candidate_id"]: row["snapshot_sha256"]
                for row in contract["fixed_snapshots"]
            },
            "appended_this_run": 0,
            **summarize(events, contract),
        }
        _atomic_write(status_path, payload)
        return payload

    loader = spy_loader_fn or (
        lambda root: load_spy_sessions(root)
    )
    _spy_frame, dates = loader(Path(feature_root))
    dates = sorted({_timestamp(value) for value in dates})
    prospective_sessions = completed_prospective_sessions(
        dates,
        now,
        start,
    )
    missed = _missed_sessions(
        prospective_sessions,
        events,
        now,
    )
    appended = 0

    latest_completed = (
        prospective_sessions[-1]
        if prospective_sessions
        else None
    )

    decision_status = "NO_COMPLETED_PROSPECTIVE_SESSION"
    if latest_completed is not None:
        existing_decisions = {
            _timestamp(row["decision_timestamp_utc"])
            for row in events
            if row.get("event_type") == "DECISION_BATCH"
        }
        if latest_completed in existing_decisions:
            decision_status = "DECISION_ALREADY_RECORDED"
        elif not decision_session_allowed_now(
            latest_completed,
            now,
        ):
            decision_status = "NO_FRESH_DECISION_SESSION"
        else:
            common_features = list(
                next(iter(snapshots.values()))["feature_columns"]
            )
            builder = decision_builder_fn or build_decision_frame
            decision_frame, input_sha, diagnostics = builder(
                latest_completed,
                common_features,
                symbols=STOCK_250_SYMBOLS,
                feature_root=Path(feature_root),
                minimum_eligible_names=int(
                    contract["decision_input"][
                        "minimum_eligible_names"
                    ]
                ),
            )
            candidate_payloads = {
                candidate_id: score_candidate(
                    candidate_id,
                    snapshots[candidate_id],
                    decision_frame,
                )
                for candidate_id in EXPECTED_CANDIDATE_ORDER
            }
            session_index = [
                value
                for value in dates
                if value >= start and value <= latest_completed
            ].index(latest_completed)
            event = {
                "event_type": "DECISION_BATCH",
                "journal_type":
                    "STOCK_EAGLE_AUTONOMOUS_ML_PROSPECTIVE_V1",
                "contract_sha256": contract_sha,
                "decision_timestamp_utc":
                    latest_completed.isoformat(),
                "cohort_offset":
                    int(session_index % SLEEVE_COUNT),
                "decision_input_sha256": input_sha,
                "feature_diagnostics": diagnostics,
                "snapshot_sha256": {
                    row["candidate_id"]: row["snapshot_sha256"]
                    for row in contract["fixed_snapshots"]
                },
                "candidates": candidate_payloads,
                "same_decision_clock": True,
                "paper_only": True,
                "brokerage_orders": False,
                "live_execution_enabled": False,
                "created_at_utc": now.isoformat(),
            }
            if _append_event(event, journal_path):
                appended += 1
            decision_status = "DECISION_BATCH_RECORDED"

    events = _read_events(journal_path)
    appended += _process_lifecycle(
        events=events,
        dates=dates,
        now_utc=now,
        feature_root=Path(feature_root),
        journal_path=journal_path,
        contract=contract,
        contract_sha=contract_sha,
    )
    events = _read_events(journal_path)
    missed = _missed_sessions(
        prospective_sessions,
        events,
        now,
    )

    payload = {
        "status": "COLLECTING_PROSPECTIVE_EVIDENCE",
        "decision_status": decision_status,
        "checked_at_utc": now.isoformat(),
        "prospective_start_utc": start.isoformat(),
        "latest_completed_session_utc":
            latest_completed.isoformat()
            if latest_completed is not None
            else None,
        "contract_sha256": contract_sha,
        "snapshot_sha256": {
            row["candidate_id"]: row["snapshot_sha256"]
            for row in contract["fixed_snapshots"]
        },
        "appended_this_run": appended,
        **summarize(
            events,
            contract,
            missed_decision_sessions=missed,
        ),
    }
    _atomic_write(status_path, payload)
    return payload


def main() -> None:
    result = run_once()
    print("STOCKEAGLE250 AUTONOMOUS ML PROSPECTIVE V1")
    print("=" * 72)
    print(f"Status: {result['status']}")
    print(
        "Decision / entry / exit batches: "
        f"{result['decision_batches']} / "
        f"{result['entry_batches']} / "
        f"{result['exit_batches']}"
    )
    print(
        "Complete five-sleeve blocks: "
        f"{result['complete_five_sleeve_blocks']}"
    )
    print(
        "Formal review: "
        f"{result['formal_review_status']}"
    )
    print(
        "Missed decision sessions: "
        f"{len(result.get('missed_decision_sessions', []))}"
    )
    print(f"Appended this run: {result.get('appended_this_run', 0)}")
    print("Fixed snapshots: V1 / V2 / V3")
    print("Retraining: OFF")
    print("Automatic selection/promotion: OFF")
    print("Paper only: YES")
    print("Brokerage orders: OFF")
    print("Live execution: OFF")


if __name__ == "__main__":
    main()
