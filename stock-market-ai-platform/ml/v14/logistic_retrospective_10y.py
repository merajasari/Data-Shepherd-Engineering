"""Exact ten-calendar-year retrospective reconstruction for V14.

This is a research counterfactual, never paper-forward evidence.  It replays
the frozen V14 learner and portfolio contract session by session, using only
labels available through the five-session purge cutoff at each decision.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from ml.v14.logistic_forward import LogisticRegression, _transition_notional, load_market
from ml.v14.logistic_forward_contract import canonical_json, contract_sha256, load_contract


STARTING_CAPITAL = 100_000.0
OUTPUT_PATH = Path("data/model/v14/logistic_forward/retrospective_10y.json")
CLASSIFICATION = "RETROSPECTIVE_COUNTERFACTUAL_NOT_PAPER_FORWARD_EVIDENCE"


def _timestamp(value: object) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").normalize()


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _training_panel(
    symbols: list[str],
    frames: Mapping[str, pd.DataFrame],
    features: list[str],
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for symbol in symbols:
        frame = frames[symbol].reset_index()
        if "timestamp_utc" not in frame.columns:
            frame = frame.rename(columns={frame.columns[0]: "timestamp_utc"})
        frame = frame[["timestamp_utc", *features, "target_up_5d"]].copy()
        frame["symbol"] = symbol
        parts.append(frame[["timestamp_utc", "symbol", *features, "target_up_5d"]])
    panel = pd.concat(parts, ignore_index=True)
    panel = panel.dropna(subset=[*features, "target_up_5d"])
    finite = np.isfinite(panel[features].to_numpy(float)).all(axis=1)
    panel = panel.loc[finite].copy()
    panel["target_up_5d"] = panel["target_up_5d"].astype(int)
    return panel


def _fit_rank_as_of(
    decision_ts: object,
    *,
    symbols: list[str],
    frames: Mapping[str, pd.DataFrame],
    dates: list[pd.Timestamp],
    all_dates: list[pd.Timestamp],
    panel: pd.DataFrame,
    contract: Mapping[str, object],
) -> tuple[pd.DataFrame, dict[str, object]]:
    model_spec = contract["model"]
    features = list(model_spec["features"])
    decision = _timestamp(decision_ts)
    decision_index = dates.index(decision)
    purge_gap = int(model_spec["purge_gap_sessions"])
    if decision_index < purge_gap:
        raise ValueError("V14_INSUFFICIENT_PURGE_HISTORY")
    cutoff = all_dates[decision_index - purge_gap]
    training = panel.loc[panel["timestamp_utc"] <= cutoff]
    minimum = int(model_spec["minimum_training_rows"])
    if len(training) < minimum:
        raise ValueError(f"V14_TRAINING_ROWS_BELOW_MINIMUM:{len(training)}<{minimum}")

    X = training[features].to_numpy(float)
    y = training["target_up_5d"].to_numpy(int)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    model = LogisticRegression(
        learning_rate=float(model_spec["learning_rate"]),
        epochs=int(model_spec["epochs"]),
        l2=float(model_spec["l2"]),
    )
    model.fit((X - mean) / std, y)

    current_rows: list[dict[str, object]] = []
    for symbol in symbols:
        frame = frames[symbol]
        if decision not in frame.index:
            continue
        row = frame.loc[decision]
        values = pd.to_numeric(row[features], errors="coerce").to_numpy(float)
        if np.isfinite(values).all():
            current_rows.append({"symbol": symbol, **dict(zip(features, values))})
    current = pd.DataFrame(current_rows)
    top_n = int(contract["portfolio"]["top_n"])
    if len(current) < top_n:
        raise ValueError(f"V14_CURRENT_ELIGIBLE_NAMES_BELOW_TOP_N:{len(current)}")
    current["predicted_probability"] = model.predict_probability(
        (current[features].to_numpy(float) - mean) / std
    )
    current = current.sort_values(
        ["predicted_probability", "symbol"], ascending=[False, True]
    ).reset_index(drop=True)
    snapshot = {
        "feature_columns": features,
        "weights": model.weights.tolist() if model.weights is not None else [],
        "bias": float(model.bias),
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
    }
    metadata = {
        "model_sha256": hashlib.sha256(canonical_json(snapshot)).hexdigest(),
        "training_rows": int(len(training)),
        "training_positive_rate": float(y.mean()),
        "training_start_utc": training["timestamp_utc"].min().isoformat(),
        "training_cutoff_utc": cutoff.isoformat(),
        "model_snapshot": snapshot,
    }
    return current, metadata


def reconstruct(
    *,
    symbols: list[str],
    frames: Mapping[str, pd.DataFrame],
    dates: list[pd.Timestamp],
    contract: Mapping[str, object],
    requested_start: pd.Timestamp | None = None,
    progress: Callable[[int, int, pd.Timestamp, float], None] | None = None,
) -> dict[str, object]:
    dates = sorted(_timestamp(value) for value in dates)
    if len(dates) < 8:
        raise ValueError("V14_RETROSPECTIVE_REQUIRES_AT_LEAST_EIGHT_SESSIONS")
    latest = dates[-1]
    requested = _timestamp(requested_start or (latest - pd.DateOffset(years=10)))
    model_spec = contract["model"]
    portfolio = contract["portfolio"]
    features = list(model_spec["features"])
    all_dates = sorted(set().union(*(set(frames[symbol].index) for symbol in symbols)))
    panel = _training_panel(symbols, frames, features)
    start_indices = [index for index, value in enumerate(dates) if value >= requested]
    if not start_indices:
        raise ValueError("V14_RETROSPECTIVE_START_AFTER_SOURCE_END")

    top_n = int(portfolio["top_n"])
    holding = int(portfolio["holding_sessions"])
    cohort_ids = [int(value) for value in portfolio["cohort_offsets"]]
    cost_bps = float(portfolio["cost_bps_per_dollar_traded"])
    cohort_equity = {offset: STARTING_CAPITAL / len(cohort_ids) for offset in cohort_ids}
    previous_picks: dict[int, list[str]] = {}
    open_sleeves: dict[int, dict[str, object]] = {}
    history: list[dict[str, object]] = []
    training_cutoffs: list[pd.Timestamp] = []
    eligible_counts: list[int] = []
    model_sha_anchors: list[dict[str, object]] = []
    skipped_decisions: list[dict[str, str]] = []
    decisions = entries = completed_exits = 0
    first_decision: pd.Timestamp | None = None
    first_entry: pd.Timestamp | None = None
    started = time.perf_counter()
    candidates = [index for index in start_indices if index + 1 < len(dates)]

    for number, decision_index in enumerate(candidates, 1):
        decision_ts = dates[decision_index]
        try:
            ranked, metadata = _fit_rank_as_of(
                decision_ts,
                symbols=symbols,
                frames=frames,
                dates=dates,
                all_dates=all_dates,
                panel=panel,
                contract=contract,
            )
        except ValueError as exc:
            skipped_decisions.append(
                {"decision_timestamp_utc": decision_ts.isoformat(), "reason": str(exc)}
            )
            continue
        decisions += 1
        first_decision = first_decision or decision_ts
        picks = ranked.head(top_n)["symbol"].tolist()
        eligible_counts.append(int(len(ranked)))
        training_cutoffs.append(_timestamp(metadata["training_cutoff_utc"]))
        if number == 1 or number % 252 == 0 or number == len(candidates):
            model_sha_anchors.append(
                {
                    "decision_timestamp_utc": decision_ts.isoformat(),
                    "model_sha256": metadata["model_sha256"],
                    "training_rows": metadata["training_rows"],
                    "training_cutoff_utc": metadata["training_cutoff_utc"],
                }
            )

        cohort = cohort_ids[decision_index % len(cohort_ids)]
        entry_index = decision_index + 1
        entry_ts = dates[entry_index]
        if any(entry_ts not in frames[symbol].index for symbol in picks):
            skipped_decisions.append(
                {"decision_timestamp_utc": decision_ts.isoformat(), "reason": "ENTRY_PRICE_MISSING"}
            )
            continue
        entry_prices = {symbol: float(frames[symbol].loc[entry_ts, "open"]) for symbol in picks}
        if any(not np.isfinite(price) or price <= 0 for price in entry_prices.values()):
            skipped_decisions.append(
                {"decision_timestamp_utc": decision_ts.isoformat(), "reason": "ENTRY_PRICE_INVALID"}
            )
            continue
        transition = _transition_notional(previous_picks.get(cohort), picks)
        modeled_cost = transition * cost_bps / 10000.0
        previous_picks[cohort] = picks
        entries += 1
        first_entry = first_entry or entry_ts
        if not history:
            history.append(
                {
                    "timestamp": entry_ts.isoformat(),
                    "portfolio_equity": STARTING_CAPITAL,
                    "source": "V14 retrospective starting capital",
                }
            )

        exit_index = entry_index + holding
        if exit_index < len(dates):
            exit_ts = dates[exit_index]
            if any(exit_ts not in frames[symbol].index for symbol in picks):
                skipped_decisions.append(
                    {"decision_timestamp_utc": decision_ts.isoformat(), "reason": "EXIT_PRICE_MISSING"}
                )
                continue
            exit_prices = {symbol: float(frames[symbol].loc[exit_ts, "open"]) for symbol in picks}
            if any(not np.isfinite(price) or price <= 0 for price in exit_prices.values()):
                skipped_decisions.append(
                    {"decision_timestamp_utc": decision_ts.isoformat(), "reason": "EXIT_PRICE_INVALID"}
                )
                continue
            gross_return = float(
                np.mean([exit_prices[symbol] / entry_prices[symbol] - 1.0 for symbol in picks])
            )
            net_return = gross_return - modeled_cost
            if not np.isfinite(net_return) or net_return <= -1.0:
                raise RuntimeError("V14_RETROSPECTIVE_INVALID_NET_RETURN")
            cohort_equity[cohort] *= 1.0 + net_return
            completed_exits += 1
            history.append(
                {
                    "timestamp": exit_ts.isoformat(),
                    "portfolio_equity": float(sum(cohort_equity.values())),
                    "source": "V14 exact-contract completed retrospective exit",
                }
            )
        else:
            open_sleeves[cohort] = {
                "decision_timestamp_utc": decision_ts.isoformat(),
                "entry_timestamp_utc": entry_ts.isoformat(),
                "symbols": picks,
                "entry_prices": entry_prices,
                "modeled_cost_rate": modeled_cost,
            }

        if progress and (number == 1 or number % 25 == 0 or number == len(candidates)):
            progress(number, len(candidates), decision_ts, time.perf_counter() - started)

    if not history or first_entry is None or first_decision is None:
        raise ValueError("V14_RETROSPECTIVE_PRODUCED_NO_PORTFOLIO_HISTORY")

    marked_cohort_equity = dict(cohort_equity)
    for cohort, sleeve in open_sleeves.items():
        picks = list(sleeve["symbols"])
        if any(latest not in frames[symbol].index for symbol in picks):
            continue
        marks = {symbol: float(frames[symbol].loc[latest, "close"]) for symbol in picks}
        if any(not np.isfinite(price) or price <= 0 for price in marks.values()):
            continue
        gross_mark = float(
            np.mean(
                [
                    marks[symbol] / float(sleeve["entry_prices"][symbol]) - 1.0
                    for symbol in picks
                ]
            )
        )
        marked_cohort_equity[cohort] *= 1.0 + gross_mark - float(sleeve["modeled_cost_rate"])
    ending_equity = float(sum(marked_cohort_equity.values()))
    terminal = {
        "timestamp": latest.isoformat(),
        "portfolio_equity": ending_equity,
        "source": "V14 retrospective terminal close mark; open sleeves remain hypothetical",
    }
    if history[-1]["timestamp"] == terminal["timestamp"]:
        history[-1] = terminal
    else:
        history.append(terminal)

    spy_entry = float(frames["SPY"].loc[first_entry, "open"])
    spy_latest = float(frames["SPY"].loc[latest, "close"])
    spy_ending_equity = STARTING_CAPITAL * spy_latest / spy_entry
    first_source_session = dates[start_indices[0]]
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "V14_EXACT_CONTRACT_TEN_YEAR_RETROSPECTIVE_COMPLETE",
        "classification": CLASSIFICATION,
        "candidate_id": contract["candidate_id"],
        "contract_id": contract["contract_id"],
        "contract_sha256": contract_sha256(contract),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_start_date": requested.date().isoformat(),
        "first_source_session_on_or_after_request": first_source_session.isoformat(),
        "actual_first_decision_session": first_decision.isoformat(),
        "actual_first_entry_session": first_entry.isoformat(),
        "latest_completed_source_session": latest.isoformat(),
        "starting_capital": STARTING_CAPITAL,
        "ending_equity": ending_equity,
        "total_return_pct": (ending_equity / STARTING_CAPITAL - 1.0) * 100.0,
        "spy_same_window_ending_equity": float(spy_ending_equity),
        "spy_same_window_total_return_pct": (spy_ending_equity / STARTING_CAPITAL - 1.0) * 100.0,
        "v14_minus_spy_total_return_pct_points": (ending_equity - spy_ending_equity) / STARTING_CAPITAL * 100.0,
        "decisions": decisions,
        "entries": entries,
        "completed_exits": completed_exits,
        "open_sleeves_at_terminal_mark": len(open_sleeves),
        "skipped_decisions": skipped_decisions,
        "minimum_ranked_universe_count": min(eligible_counts) if eligible_counts else 0,
        "median_ranked_universe_count": float(np.median(eligible_counts)) if eligible_counts else 0,
        "maximum_ranked_universe_count": max(eligible_counts) if eligible_counts else 0,
        "model_sha_anchors": model_sha_anchors,
        "history": history,
        "methodology": {
            "learner": "exact frozen V14 NumPy logistic-regression gradient updates",
            "training_scope": model_spec["training_scope"],
            "features": features,
            "target": model_spec["target"],
            "purge_gap_sessions": int(model_spec["purge_gap_sessions"]),
            "retrained_each_decision_session": True,
            "top_n": top_n,
            "weighting": portfolio["weighting"],
            "entry": portfolio["entry"],
            "holding_sessions": holding,
            "cohort_offsets": cohort_ids,
            "cost_bps_per_dollar_traded": cost_bps,
            "terminal_open_sleeves_marked_at_latest_completed_close": True,
        },
        "limitations": {
            "retrospective_not_forward_evidence": True,
            "current_fixed_universe_survivorship_bias": True,
            "historical_constituent_membership_not_reconstructed": True,
            "predicted_probabilities_do_not_guarantee_returns": True,
        },
        "research_safety": {
            "paper_forward_journal_read": False,
            "paper_forward_journal_modified": False,
            "v8_modified": False,
            "v10_modified": False,
            "brokerage_orders": False,
            "automatic_promotion": False,
        },
    }
    identity_body = dict(payload)
    identity_body.pop("generated_at_utc", None)
    payload["reconstruction_sha256"] = hashlib.sha256(canonical_json(identity_body)).hexdigest()
    return payload


def _print_result(payload: Mapping[str, object], output_path: Path, cached: bool) -> None:
    print("V14 TEN-YEAR RETROSPECTIVE COUNTERFACTUAL")
    print("=" * 78)
    print(f"Status: {'CACHED' if cached else payload['status']}")
    print(f"Window: {payload['actual_first_entry_session']} -> {payload['latest_completed_source_session']}")
    print(f"V14: ${float(payload['starting_capital']):,.2f} -> ${float(payload['ending_equity']):,.2f} ({float(payload['total_return_pct']):+.2f}%)")
    print(f"SPY same window: ${float(payload['spy_same_window_ending_equity']):,.2f} ({float(payload['spy_same_window_total_return_pct']):+.2f}%)")
    print(f"V14 minus SPY: {float(payload['v14_minus_spy_total_return_pct_points']):+.2f} percentage points")
    print(f"Decisions / entries / completed exits: {payload['decisions']} / {payload['entries']} / {payload['completed_exits']}")
    print(f"Output: {output_path}")
    print("Classification: RETROSPECTIVE COUNTERFACTUAL — NOT PAPER-FORWARD EVIDENCE")
    print("Fixed-current-universe survivorship bias: DISCLOSED")
    print("Paper journal modified: NO | V8/V10 modified: NO | Brokerage orders: OFF")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even when the exact source endpoint is already cached")
    args = parser.parse_args()
    contract = load_contract()
    symbols, frames, dates, _ = load_market(contract)
    latest = _timestamp(sorted(dates)[-1])
    requested = _timestamp(latest - pd.DateOffset(years=10))
    if OUTPUT_PATH.exists() and not args.force:
        existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        if (
            existing.get("classification") == CLASSIFICATION
            and existing.get("contract_sha256") == contract_sha256(contract)
            and existing.get("latest_completed_source_session") == latest.isoformat()
            and existing.get("requested_start_date") == requested.date().isoformat()
        ):
            _print_result(existing, OUTPUT_PATH, True)
            return

    def show_progress(number: int, total: int, session: pd.Timestamp, elapsed: float) -> None:
        rate = number / elapsed if elapsed > 0 else 0.0
        remaining = (total - number) / rate if rate > 0 else 0.0
        print(
            f"[{number:>4}/{total}] {session.date()} · elapsed {elapsed / 60:.1f}m · ETA {remaining / 60:.1f}m",
            flush=True,
        )

    payload = reconstruct(
        symbols=symbols,
        frames=frames,
        dates=dates,
        contract=contract,
        requested_start=requested,
        progress=show_progress,
    )
    _atomic_write(OUTPUT_PATH, payload)
    _print_result(payload, OUTPUT_PATH, False)


if __name__ == "__main__":
    main()
