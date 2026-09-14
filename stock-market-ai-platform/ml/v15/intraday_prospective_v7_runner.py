"""V15 V7 fixed-model prospective intraday paper-shadow runner."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from ml.v11.intraday_contract import derive_features
from ml.v14.logistic_forward import load_market as load_daily_market
from ml.v15.intraday_adaptive_v4 import _session_prediction
from ml.v15.intraday_hybrid_v2 import (
    FAST_FEATURE_NAMES,
    HYBRID_FEATURE_NAMES,
    SLOW_FEATURE_NAMES,
    _daily_context_for_session,
    _daily_rows,
    _interactions,
    _pretrain_daily_context,
    load_contract as load_v2_contract,
)
from ml.v15.intraday_logistic import (
    FEATURE_NAMES,
    V11_BALANCED_WEIGHTS,
    _group_sessions,
    _zscore,
    canonical_sha256,
    load_dataset,
)
from ml.v15.intraday_prospective_v7_contract import (
    EXPECTED_CONTRACT_SHA256,
    load_contract,
)
from ml.v15.intraday_prospective_v7_journal import (
    DEFAULT_JOURNAL_PATH,
    V7EvidenceJournal,
    build_event,
)
from ml.v15.intraday_risk_managed_v5 import (
    MANIFEST_PATH,
    _gap_aware_stop_return,
    build_risk_managed_examples,
    load_contract as load_v5_contract,
    select_configuration,
)
from ml.v15.intraday_selective_v3 import RidgeReturnRegression


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = ROOT / "data/research/v15/prospective_v7/latest_complete_snapshot.json"
MODEL_PATH = ROOT / "data/research/v15/prospective_v7/model_snapshot.json"


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("V15_V7_TIMESTAMP_MUST_BE_AWARE")
    return parsed.astimezone(timezone.utc)


def _artifact_unsigned(payload: Mapping[str, object]) -> dict[str, object]:
    unsigned = dict(payload)
    unsigned.pop("prepared_artifact_sha256", None)
    return unsigned


def load_prepared_model(path: Path = MODEL_PATH) -> dict[str, object]:
    if not path.exists():
        raise ValueError("V15_V7_MODEL_PREPARATION_REQUIRED")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("prepared_artifact_sha256") != canonical_sha256(
        _artifact_unsigned(payload)
    ):
        raise ValueError("V15_V7_PREPARED_MODEL_SHA_MISMATCH")
    contract = load_contract()
    training = contract["training_policy"]
    if payload.get("contract_sha256") != EXPECTED_CONTRACT_SHA256:
        raise ValueError("V15_V7_PREPARED_MODEL_CONTRACT_MISMATCH")
    if payload.get("source_manifest_sha256") != training[
        "fixed_history_manifest_sha256"
    ]:
        raise ValueError("V15_V7_PREPARED_MODEL_SOURCE_MISMATCH")
    if payload.get("eligible_history_end_session") != training[
        "fixed_history_last_session"
    ]:
        raise ValueError("V15_V7_PREPARED_MODEL_CUTOFF_MISMATCH")
    snapshot = payload.get("model_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("V15_V7_PREPARED_MODEL_SNAPSHOT_MISSING")
    if snapshot.get("model_sha256") != canonical_sha256(
        {key: value for key, value in snapshot.items() if key != "model_sha256"}
    ):
        raise ValueError("V15_V7_PREPARED_MODEL_IDENTITY_INVALID")
    if tuple(snapshot.get("feature_names", ())) != HYBRID_FEATURE_NAMES:
        raise ValueError("V15_V7_PREPARED_MODEL_FEATURES_INVALID")
    return payload


def prepare_model(
    *,
    manifest_path: Path = MANIFEST_PATH,
    output_path: Path = MODEL_PATH,
) -> dict[str, object]:
    contract = load_contract()
    training = contract["training_policy"]
    if output_path.exists():
        return load_prepared_model(output_path)

    manifest, intraday = load_dataset(manifest_path)
    if manifest.get("manifest_sha256") != training["fixed_history_manifest_sha256"]:
        raise ValueError("V15_V7_FIXED_HISTORY_MANIFEST_MISMATCH")
    symbols, daily_frames, _, _ = load_daily_market()
    if sorted(symbols) != sorted(symbol for symbol in intraday if symbol != "SPY"):
        raise ValueError("V15_V7_DAILY_UNIVERSE_MISMATCH")
    v5_contract = load_v5_contract()
    sessions, by_session, audit = build_risk_managed_examples(
        intraday, daily_frames, v5_contract
    )
    if not sessions or sessions[-1] != training["fixed_history_last_session"]:
        raise ValueError("V15_V7_FIXED_HISTORY_CUTOFF_MISMATCH")
    configuration, diagnostics, _, _, _, snapshot = select_configuration(
        sessions, by_session, v5_contract
    )
    payload: dict[str, object] = {
        "status": "V15_V7_PREPARED_MODEL_IMMUTABLE",
        "candidate_id": contract["candidate_id"],
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "source_manifest_sha256": manifest["manifest_sha256"],
        "v5_contract_sha256": canonical_sha256(v5_contract),
        "eligible_history_start_session": sessions[0],
        "eligible_history_end_session": sessions[-1],
        "eligible_history_sessions": len(sessions),
        "configuration": configuration,
        "configuration_diagnostics_sha256": canonical_sha256(diagnostics),
        "model_snapshot": snapshot,
        "slow_context_model_sha256": audit["slow_context_model_sha256"],
        "historical_results_are_v7_evidence": False,
        "prepared_before_activation_required": True,
        "paper_shadow_only": True,
        "brokerage_orders": False,
    }
    payload["prepared_artifact_sha256"] = canonical_sha256(payload)
    _atomic_write(output_path, payload)
    return load_prepared_model(output_path)


def _validate_snapshot(
    snapshot: Mapping[str, object],
) -> tuple[str, dict[str, list[dict[str, object]]]]:
    if snapshot.get("status") != "COMPLETE_RESEARCH_SNAPSHOT":
        raise ValueError("V15_V7_SNAPSHOT_NOT_COMPLETE")
    series = snapshot.get("series")
    if not isinstance(series, dict) or len(series) != 101 or "SPY" not in series:
        raise ValueError("V15_V7_SNAPSHOT_UNIVERSE_INVALID")
    if snapshot.get("symbol_count") != 101:
        raise ValueError("V15_V7_SNAPSHOT_SYMBOL_COUNT_INVALID")
    if snapshot.get("series_sha256") != canonical_sha256(series):
        raise ValueError("V15_V7_SNAPSHOT_SHA_MISMATCH")
    session = str(snapshot.get("session_date", ""))
    boundary = str(load_contract()["evidence_boundary"]["first_eligible_session"])
    if session < boundary:
        raise ValueError("V15_V7_SNAPSHOT_BEFORE_BOUNDARY")
    normalized: dict[str, list[dict[str, object]]] = {}
    for symbol, raw_rows in series.items():
        if not isinstance(raw_rows, list):
            raise ValueError(f"V15_V7_SNAPSHOT_ROWS_INVALID:{symbol}")
        rows = [dict(row) for row in raw_rows]
        rows.sort(key=lambda row: str(row["timestamp_utc"]))
        normalized[str(symbol)] = rows
    counts = {len(rows) for rows in normalized.values()}
    if len(counts) != 1:
        raise ValueError("V15_V7_SNAPSHOT_BAR_COUNTS_UNALIGNED")
    timestamps = {
        tuple(str(row["timestamp_utc"]) for row in rows)
        for rows in normalized.values()
    }
    if len(timestamps) != 1:
        raise ValueError("V15_V7_SNAPSHOT_TIMESTAMPS_UNALIGNED")
    return session, normalized


def _decision_source_sha(
    series: Mapping[str, Sequence[Mapping[str, object]]],
) -> str:
    decision_index = int(load_contract()["frozen_mechanics"]["decision_bar_index"])
    if any(len(rows) <= decision_index for rows in series.values()):
        raise ValueError("V15_V7_DECISION_BARS_INCOMPLETE")
    frozen = {
        symbol: [dict(row) for row in rows[: decision_index + 1]]
        for symbol, rows in series.items()
    }
    return canonical_sha256(frozen)


def _model_from_artifact(
    artifact: Mapping[str, object],
) -> tuple[RidgeReturnRegression, np.ndarray, np.ndarray]:
    v5 = load_v5_contract()
    snapshot = artifact["model_snapshot"]
    model = RidgeReturnRegression(alpha=float(v5["model"]["ridge_alpha"]))
    model.weights = np.asarray(snapshot["weights"], dtype=float)
    model.bias = float(snapshot["bias"])
    mean = np.asarray(snapshot["feature_mean"], dtype=float)
    std = np.asarray(snapshot["feature_std"], dtype=float)
    if (
        model.weights.shape != (len(HYBRID_FEATURE_NAMES),)
        or mean.shape != model.weights.shape
        or std.shape != model.weights.shape
        or not np.isfinite(model.weights).all()
        or not np.isfinite(mean).all()
        or not np.isfinite(std).all()
    ):
        raise ValueError("V15_V7_PREPARED_MODEL_NUMERICS_INVALID")
    return model, mean, std


def _build_current_feature_rows(
    snapshot: Mapping[str, object],
    artifact: Mapping[str, object],
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> list[dict[str, object]]:
    session, series = _validate_snapshot(snapshot)
    decision_index = int(load_contract()["frozen_mechanics"]["decision_bar_index"])
    _decision_source_sha(series)

    manifest, intraday = load_dataset(manifest_path)
    if manifest.get("manifest_sha256") != artifact["source_manifest_sha256"]:
        raise ValueError("V15_V7_RUNTIME_HISTORY_MANIFEST_DRIFT")
    grouped = {symbol: _group_sessions(rows) for symbol, rows in intraday.items()}
    common_history = sorted(set.intersection(*(set(rows) for rows in grouped.values())))
    prior_sessions = [value for value in common_history if value < session]
    if not prior_sessions:
        raise ValueError("V15_V7_PREVIOUS_INTRADAY_SESSION_MISSING")
    previous = prior_sessions[-1]
    candidates = sorted(symbol for symbol in series if symbol != "SPY")
    if len(candidates) != 100 or sorted(grouped) != sorted(candidates + ["SPY"]):
        raise ValueError("V15_V7_RUNTIME_UNIVERSE_MISMATCH")

    raw: dict[str, dict[str, float]] = {}
    for symbol in candidates + ["SPY"]:
        previous_rows = grouped[symbol].get(previous)
        if not previous_rows:
            raise ValueError(f"V15_V7_PREVIOUS_CLOSE_MISSING:{symbol}")
        features = derive_features(
            series[symbol][: decision_index + 1],
            previous_close=float(previous_rows[-1]["close"]),
        )
        raw[symbol] = {
            name: float(getattr(features, name)) for name in FEATURE_NAMES
        }
    relative = {
        symbol: {
            name: (
                raw[symbol][name]
                if name == "realized_volatility_30m"
                else raw[symbol][name] - raw["SPY"][name]
            )
            for name in FEATURE_NAMES
        }
        for symbol in candidates
    }
    standardized = {
        name: _zscore({symbol: relative[symbol][name] for symbol in candidates})
        for name in FEATURE_NAMES
    }

    daily_symbols, daily_frames, _, _ = load_daily_market()
    if sorted(daily_symbols) != candidates:
        raise ValueError("V15_V7_RUNTIME_DAILY_UNIVERSE_MISMATCH")
    v2_contract = load_v2_contract()
    slow_model, slow_mean, slow_std, slow_snapshot, mapped = _pretrain_daily_context(
        daily_frames,
        candidates,
        str(artifact["eligible_history_start_session"]),
        v2_contract,
    )
    if slow_snapshot["model_sha256"] != artifact["slow_context_model_sha256"]:
        raise ValueError("V15_V7_SLOW_CONTEXT_MODEL_DRIFT")
    common_daily = sorted(set.intersection(*(set(rows) for rows in mapped.values())))
    prior_daily = [value for value in common_daily if value < session]
    if not prior_daily:
        raise ValueError("V15_V7_PRIOR_DAILY_CONTEXT_MISSING")
    daily_session = prior_daily[-1]
    context, _ = _daily_context_for_session(
        daily_session, candidates, mapped, slow_model, slow_mean, slow_std
    )

    rows: list[dict[str, object]] = []
    for symbol in candidates:
        fast = {name: standardized[name][symbol] for name in FAST_FEATURE_NAMES}
        slow = context[symbol]
        combined = {**fast, **{name: slow[name] for name in SLOW_FEATURE_NAMES}}
        vector = (
            [combined[name] for name in FAST_FEATURE_NAMES]
            + [combined[name] for name in SLOW_FEATURE_NAMES]
            + _interactions(combined)
        )
        if len(vector) != len(HYBRID_FEATURE_NAMES) or not np.isfinite(vector).all():
            raise ValueError(f"V15_V7_CURRENT_FEATURES_INVALID:{symbol}")
        rows.append(
            {
                "session": session,
                "symbol": symbol,
                "features": vector,
                "v11_score": statistics.fmean(
                    standardized[name][symbol] * V11_BALANCED_WEIGHTS[name]
                    for name in FEATURE_NAMES
                ),
                "v14_daily_probability": slow["v14_daily_probability_raw"],
                "daily_context_session": daily_session,
            }
        )
    return rows


def build_decision_payload(
    snapshot: Mapping[str, object],
    artifact: Mapping[str, object],
) -> dict[str, object]:
    rows = _build_current_feature_rows(snapshot, artifact)
    configuration = artifact["configuration"]
    cash_fallback = bool(configuration["cash_fallback"])
    if cash_fallback:
        selected: list[tuple[Mapping[str, object], float]] = []
        expected: float | None = None
        trade = False
        top_n = None
    else:
        top_n = int(configuration["top_n"])
        model, mean, std = _model_from_artifact(artifact)
        selected, raw_expected = _session_prediction(rows, model, mean, std, top_n)
        expected = float(raw_expected)
        threshold = float(configuration["applied_threshold"])
        trade = expected >= threshold and expected > 0.0
    selected_symbols = [str(row["symbol"]) for row, _ in selected] if trade else []
    v11_controls = (
        [
            str(row["symbol"])
            for row in sorted(
                rows, key=lambda row: (-float(row["v11_score"]), str(row["symbol"]))
            )[: int(top_n)]
        ]
        if trade
        else []
    )
    v14_controls = (
        [
            str(row["symbol"])
            for row in sorted(
                rows,
                key=lambda row: (
                    -float(row["v14_daily_probability"]),
                    str(row["symbol"]),
                ),
            )[: int(top_n)]
        ]
        if trade
        else []
    )
    return {
        "trade": trade,
        "cash_fallback": cash_fallback,
        "selected_symbols": selected_symbols,
        "v11_control_symbols": v11_controls,
        "v14_control_symbols": v14_controls,
        "top_n": top_n,
        "predicted_topk_net_return": expected,
        "participation_quantile": configuration["participation_quantile"],
        "applied_threshold": configuration["applied_threshold"],
        "daily_context_session": rows[0]["daily_context_session"],
        "model_snapshot_sha256": artifact["model_snapshot"]["model_sha256"],
        "prepared_artifact_sha256": artifact["prepared_artifact_sha256"],
        "training_cutoff_session": artifact["model_snapshot"]["training_cutoff_session"],
    }


def _event_payload(row: Mapping[str, object]) -> dict[str, object]:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("V15_V7_JOURNAL_EVENT_PAYLOAD_INVALID")
    return payload


def _scaled_portfolio_return(
    symbols: Sequence[str],
    series: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    entry_index: int,
    exit_index: int,
    stop_fraction: float,
    exposure: float,
    cost: float,
) -> tuple[float, int, dict[str, float]]:
    gross_by_symbol: dict[str, float] = {}
    stopped = 0
    for symbol in symbols:
        gross, triggered, _ = _gap_aware_stop_return(
            series[symbol],
            entry_bar_index=entry_index,
            exit_bar_index=exit_index,
            stop_fraction=stop_fraction,
        )
        gross_by_symbol[symbol] = gross
        stopped += int(triggered)
    gross = statistics.fmean(gross_by_symbol.values())
    return exposure * (gross - cost), stopped, gross_by_symbol


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    decisions = [row for row in rows if row["event_type"] == "DECISION"]
    entries = [row for row in rows if row["event_type"] == "ENTRY"]
    exits = [row for row in rows if row["event_type"] == "EXIT"]
    trade_decisions = [
        row for row in decisions if bool(_event_payload(row).get("trade"))
    ]
    cash_decisions = len(decisions) - len(trade_decisions)
    return {
        "status": "COLLECTING_PROSPECTIVE_PAPER_SHADOW",
        "decisions": len(decisions),
        "trade_decisions": len(trade_decisions),
        "cash_decisions": cash_decisions,
        "entries": len(entries),
        "completed_exits": len(exits),
        "journal_events": len(rows),
        "paper_shadow_only": True,
        "automatic_promotion": False,
        "human_review_required": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v13_modified": False,
        "v14_modified": False,
    }


def run_snapshot(
    *,
    snapshot: Mapping[str, object],
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    prepared_model: Mapping[str, object] | None = None,
    decision_builder: Callable[[Mapping[str, object]], Mapping[str, object]]
    | None = None,
    collected_at_utc: datetime | None = None,
) -> dict[str, object]:
    session, series = _validate_snapshot(snapshot)
    journal = V7EvidenceJournal(journal_path)
    rows = journal.read()
    session_rows = [row for row in rows if row["session_date"] == session]
    by_type = {str(row["event_type"]): row for row in session_rows}
    appended = 0
    collection_time = collected_at_utc or datetime.now(timezone.utc)
    if collection_time.tzinfo is None:
        raise ValueError("V15_V7_COLLECTION_TIME_MUST_BE_AWARE")

    if "DECISION" not in by_type:
        if decision_builder is not None:
            payload = dict(decision_builder(snapshot))
        else:
            artifact = prepared_model or load_prepared_model()
            payload = build_decision_payload(snapshot, artifact)
        payload.setdefault("decision_source_sha256", _decision_source_sha(series))
        payload.setdefault("source_snapshot_sha256", snapshot["series_sha256"])
        payload.setdefault("collected_at_utc", collection_time.isoformat())
        decision_index = int(load_contract()["frozen_mechanics"]["decision_bar_index"])
        occurred = _utc(series["SPY"][decision_index]["timestamp_utc"]) + timedelta(
            minutes=5
        )
        appended += int(
            journal.append(
                build_event(
                    event_type="DECISION",
                    session_date=session,
                    occurred_at_utc=occurred,
                    payload=payload,
                )
            )
        )
        rows = journal.read()
        session_rows = [row for row in rows if row["session_date"] == session]
        by_type = {str(row["event_type"]): row for row in session_rows}

    decision = _event_payload(by_type["DECISION"])
    trade = bool(decision.get("trade"))
    if not trade:
        result = summarize(rows)
        result.update(
            {
                "status": "CASH_SESSION_COMPLETE",
                "session_date": session,
                "appended_this_run": appended,
                "next_expected_lifecycle_event": "NEXT_ELIGIBLE_DECISION",
            }
        )
        return result

    selected = [str(value) for value in decision.get("selected_symbols") or []]
    v11_controls = [str(value) for value in decision.get("v11_control_symbols") or []]
    v14_controls = [str(value) for value in decision.get("v14_control_symbols") or []]
    top_n = int(decision.get("top_n") or 0)
    if (
        top_n < 1
        or len(selected) != top_n
        or len(v11_controls) != top_n
        or len(v14_controls) != top_n
        or len(set(selected)) != top_n
    ):
        raise ValueError("V15_V7_DECISION_SELECTION_INVALID")

    mechanics = load_contract()["frozen_mechanics"]
    entry_index = int(mechanics["entry_bar_index"])
    exit_index = int(mechanics["scheduled_exit_bar_index"])
    minimum_count = min(len(value) for value in series.values())
    required_symbols = sorted(set(selected + v11_controls + v14_controls + ["SPY"]))

    if "ENTRY" not in by_type and minimum_count > entry_index:
        entry_prices = {
            symbol: float(series[symbol][entry_index]["open"])
            for symbol in required_symbols
        }
        if any(not math.isfinite(value) or value <= 0.0 for value in entry_prices.values()):
            raise ValueError("V15_V7_ENTRY_PRICE_INVALID")
        entry_time = _utc(series["SPY"][entry_index]["timestamp_utc"])
        appended += int(
            journal.append(
                build_event(
                    event_type="ENTRY",
                    session_date=session,
                    occurred_at_utc=entry_time,
                    payload={
                        "selected_symbols": selected,
                        "v11_control_symbols": v11_controls,
                        "v14_control_symbols": v14_controls,
                        "entry_prices": entry_prices,
                        "maximum_invested_fraction": mechanics[
                            "maximum_invested_fraction"
                        ],
                        "required_cash_fraction": mechanics["required_cash_fraction"],
                        "source_snapshot_sha256": snapshot["series_sha256"],
                        "collected_at_utc": collection_time.isoformat(),
                    },
                )
            )
        )
        rows = journal.read()
        session_rows = [row for row in rows if row["session_date"] == session]
        by_type = {str(row["event_type"]): row for row in session_rows}

    if "ENTRY" in by_type and "EXIT" not in by_type and minimum_count > exit_index:
        stored_prices = _event_payload(by_type["ENTRY"]).get("entry_prices")
        if not isinstance(stored_prices, Mapping):
            raise ValueError("V15_V7_STORED_ENTRY_PRICES_INVALID")
        for symbol in required_symbols:
            observed = float(series[symbol][entry_index]["open"])
            if not math.isclose(float(stored_prices[symbol]), observed, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"V15_V7_ENTRY_PRICE_PROVENANCE_DRIFT:{symbol}")
        exposure = float(mechanics["maximum_invested_fraction"])
        cost = float(mechanics["modeled_total_cost_bps_round_trip"]) / 10000.0
        stop_fraction = float(mechanics["protective_stop_loss_fraction"])
        v15_return, v15_stops, v15_gross = _scaled_portfolio_return(
            selected,
            series,
            entry_index=entry_index,
            exit_index=exit_index,
            stop_fraction=stop_fraction,
            exposure=exposure,
            cost=cost,
        )
        v11_return, v11_stops, v11_gross = _scaled_portfolio_return(
            v11_controls,
            series,
            entry_index=entry_index,
            exit_index=exit_index,
            stop_fraction=stop_fraction,
            exposure=exposure,
            cost=cost,
        )
        v14_return, v14_stops, v14_gross = _scaled_portfolio_return(
            v14_controls,
            series,
            entry_index=entry_index,
            exit_index=exit_index,
            stop_fraction=stop_fraction,
            exposure=exposure,
            cost=cost,
        )
        spy_gross = (
            float(series["SPY"][exit_index]["close"])
            / float(series["SPY"][entry_index]["open"])
            - 1.0
        )
        spy_return = exposure * spy_gross
        exit_time = _utc(series["SPY"][exit_index]["timestamp_utc"]) + timedelta(
            minutes=5
        )
        appended += int(
            journal.append(
                build_event(
                    event_type="EXIT",
                    session_date=session,
                    occurred_at_utc=exit_time,
                    payload={
                        "selected_symbols": selected,
                        "v11_control_symbols": v11_controls,
                        "v14_control_symbols": v14_controls,
                        "v15_net_return": v15_return,
                        "matched_v11_net_return": v11_return,
                        "matched_v14_context_net_return": v14_return,
                        "matched_spy_return": spy_return,
                        "v15_gross_returns": v15_gross,
                        "matched_v11_gross_returns": v11_gross,
                        "matched_v14_gross_returns": v14_gross,
                        "v15_stop_triggered_positions": v15_stops,
                        "matched_v11_stop_triggered_positions": v11_stops,
                        "matched_v14_stop_triggered_positions": v14_stops,
                        "maximum_invested_fraction": exposure,
                        "required_cash_fraction": mechanics["required_cash_fraction"],
                        "modeled_total_cost_bps_round_trip": mechanics[
                            "modeled_total_cost_bps_round_trip"
                        ],
                        "source_snapshot_sha256": snapshot["series_sha256"],
                        "collected_at_utc": collection_time.isoformat(),
                    },
                )
            )
        )
        rows = journal.read()
        by_type["EXIT"] = next(
            row
            for row in rows
            if row["session_date"] == session and row["event_type"] == "EXIT"
        )

    result = summarize(rows)
    if "EXIT" in by_type:
        status = "SESSION_EXIT_COMPLETE"
        next_event = "NEXT_ELIGIBLE_DECISION"
    elif "ENTRY" in by_type:
        status = "WAITING_FOR_EXIT"
        next_event = f"EXIT:{session}"
    else:
        status = "WAITING_FOR_ENTRY"
        next_event = f"ENTRY:{session}"
    result.update(
        {
            "status": status,
            "session_date": session,
            "appended_this_run": appended,
            "next_expected_lifecycle_event": next_event,
        }
    )
    return result


def run_from_files(
    *,
    snapshot_path: Path = SNAPSHOT_PATH,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
) -> dict[str, object]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return run_snapshot(snapshot=snapshot, journal_path=journal_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    arguments = parser.parse_args()
    print("V15 V7 PROSPECTIVE INTRADAY PAPER-SHADOW RUNNER")
    print("=" * 80)
    try:
        if arguments.prepare:
            prepared = prepare_model()
            print("Status: V15_V7_PREPARED_MODEL_IMMUTABLE")
            print(
                "Prepared artifact SHA-256: "
                f"{prepared['prepared_artifact_sha256']}"
            )
            print(
                "History: "
                f"{prepared['eligible_history_start_session']} -> "
                f"{prepared['eligible_history_end_session']}"
            )
            print("Prospective evidence written: NO")
        else:
            result = run_from_files()
            print(f"Status: {result['status']}")
            print(f"Session: {result['session_date']}")
            print(f"Appended this run: {result['appended_this_run']}")
            print(
                "Decisions / entries / exits: "
                f"{result['decisions']} / {result['entries']} / "
                f"{result['completed_exits']}"
            )
    except Exception as exc:
        print("Status: DISABLED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Prospective evidence written: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print("Paper shadow only: YES")
    print("Automatic promotion: NO")
    print("Brokerage orders: OFF")
    print("Existing models modified: NO")


if __name__ == "__main__":
    main()
