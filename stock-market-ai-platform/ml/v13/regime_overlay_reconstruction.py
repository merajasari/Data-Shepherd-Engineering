"""Retrospective V13 development reconstruction for the model-history chart.

This module is deliberately separate from the V13 fresh-evidence journal and
activation path.  It joins only pre-boundary V10 development rankings with a
SHA-verified historical V11 five-minute research dataset.  The result is a
counterfactual development reconstruction; it is not fresh evidence, cannot
freeze V13, and has no paper/live/brokerage authority.

Tiingo IEX five-minute history begins in August 2017.  The requested ten-year
window is therefore clamped to that provider boundary, and the final eligible
window can begin later when the fixed 101-symbol universe is not yet complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V10_CANDIDATE,
    EXPECTED_V10_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    ROOT
    / "data/research/v13/development/intraday_backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = (
    ROOT / "data/research/v13/development/retrospective_reconstruction.json"
)
V10_FREEZE_LOCK_PATH = (
    ROOT / "data/model/v10/cycle3/freeze/frozen_candidate.sha256"
)

NEW_YORK = ZoneInfo("America/New_York")
REQUESTED_START_DATE = date(2016, 8, 29)
TIINGO_IEX_INTRADAY_START_DATE = date(2017, 8, 1)
DEVELOPMENT_END_DATE = date(2026, 8, 28)
FRESH_EVIDENCE_BOUNDARY_UTC = datetime(2026, 9, 1, 14, tzinfo=timezone.utc)
V10_CYCLE3_CONTRACT_SHA256 = (
    "e1df9ac21457a4494f53069b4513ecd4dfe0ae52a743eabdab6a63374998f051"
)
V12_DISPOSITION_SHA256 = (
    "d099f7cd1b915f05ef3e57dd1f5f2e6eff21962f3202821cb3a115290915d6f2"
)
HOLD_SESSIONS = 5
COHORT_OFFSETS = tuple(range(HOLD_SESSIONS))
MODELED_ROUND_TRIP_COST_BPS = 10.0
HISTORICAL_SPREAD_POLICY = (
    "NOT_OBSERVABLE_FROM_FIVE_MINUTE_BARS; MODELED_10_BPS_ROUND_TRIP; "
    "NOT_ELIGIBLE_AS_FRESH_EVIDENCE"
)
EXPECTED_SAMPLING_POLICY = "OPENING_SIX_COMPLETED_BARS_PLUS_1555_SESSION_CLOSE"


@dataclass(frozen=True)
class RetrospectivePeriod:
    decision_session: str
    entry_session: str
    exit_session: str
    decision_index: int
    cohort_offset: int
    ranked_symbols: tuple[str, ...]
    confirmed_negative_2d: bool
    spy_annualized_volatility_20d: float | None
    regime_input_complete: bool
    confirmations: Mapping[str, bool] | None
    market_data_complete: bool
    entry_prices: Mapping[str, float]
    exit_prices: Mapping[str, float]


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def validate_historical_manifest(manifest: Mapping[str, object]) -> None:
    body = dict(manifest)
    identity = body.pop("manifest_sha256", None)
    if identity != _canonical_sha(body):
        raise ValueError("V13_HISTORICAL_MANIFEST_SHA_MISMATCH")
    if manifest.get("status") != "COMPLETE_HISTORICAL_RESEARCH_DATASET":
        raise ValueError("V13_HISTORICAL_MANIFEST_INCOMPLETE")
    if manifest.get("published") is not True:
        raise ValueError("V13_HISTORICAL_MANIFEST_NOT_PUBLISHED")
    if int(manifest.get("symbol_count", 0)) != 101:
        raise ValueError("V13_REQUIRES_101_SYMBOL_HISTORY")
    if int(manifest.get("bar_interval_minutes", 0)) != 5:
        raise ValueError("V13_REQUIRES_FIVE_MINUTE_HISTORY")
    if manifest.get("sampling_policy") != EXPECTED_SAMPLING_POLICY:
        raise ValueError("V13_HISTORICAL_SAMPLING_POLICY_CHANGED")
    if int(manifest.get("bars_retained_per_complete_session", 0)) != 7:
        raise ValueError("V13_HISTORICAL_BAR_SET_CHANGED")
    if manifest.get("brokerage_orders") is not False:
        raise ValueError("V13_HISTORICAL_MANIFEST_HAS_BROKERAGE_AUTHORITY")
    last_common = date.fromisoformat(str(manifest["last_common_session"]))
    if last_common > DEVELOPMENT_END_DATE:
        raise RuntimeError("V13_RETROSPECTIVE_REACHES_FRESH_EVIDENCE_WINDOW")


def _maximum_drawdown(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("EMPTY_V13_EQUITY_HISTORY")
    peak = float(values[0])
    worst = 0.0
    for value in values:
        peak = max(peak, float(value))
        if peak > 0:
            worst = min(worst, float(value) / peak - 1.0)
    return worst


def _expected_times(count: int) -> tuple[time, ...]:
    return tuple(time(9, 30 + 5 * index) for index in range(count))


def _bar_time(row: Mapping[str, object]) -> tuple[date, time] | None:
    try:
        stamp = datetime.fromisoformat(str(row["timestamp_utc"]))
        if stamp.tzinfo is None:
            return None
        local = stamp.astimezone(NEW_YORK)
        return local.date(), local.time().replace(tzinfo=None)
    except (KeyError, TypeError, ValueError):
        return None


def _opening_price(
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    symbol: str,
    session: str,
) -> float | None:
    rows = grouped.get(symbol, {}).get(session)
    if not rows:
        return None
    stamp = _bar_time(rows[0])
    if stamp != (date.fromisoformat(session), time(9, 30)):
        return None
    try:
        value = float(rows[0]["open"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _closing_price(
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    symbol: str,
    session: str,
) -> float | None:
    rows = grouped.get(symbol, {}).get(session)
    if not rows:
        return None
    stamp = _bar_time(rows[-1])
    if stamp != (date.fromisoformat(session), time(15, 55)):
        return None
    try:
        value = float(rows[-1]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _confirmation_state(
    *,
    session: str,
    previous_session: str,
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    symbols: Sequence[str],
) -> dict[str, bool] | None:
    from ml.v11.intraday_contract import derive_features

    expected = _expected_times(6)
    features = {}
    try:
        for symbol in symbols:
            current = grouped[symbol][session]
            previous_close = _closing_price(grouped, symbol, previous_session)
            if previous_close is None or len(current) < 6:
                return None
            observed = tuple(
                stamp[1] if stamp is not None else None
                for stamp in (_bar_time(row) for row in current[:6])
            )
            if observed != expected:
                return None
            features[symbol] = derive_features(
                current[:6], previous_close=previous_close
            )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None

    candidates = [symbol for symbol in symbols if symbol != "SPY"]
    ordered_volatility = sorted(
        float(features[symbol].realized_volatility_30m)
        for symbol in candidates
    )
    if len(ordered_volatility) != 100:
        return None
    location = (len(ordered_volatility) - 1) * 0.80
    lower = math.floor(location)
    upper = math.ceil(location)
    weight = location - lower
    volatility_limit = (
        ordered_volatility[lower] * (1.0 - weight)
        + ordered_volatility[upper] * weight
    )
    spy_return = float(features["SPY"].return_15m)
    return {
        symbol: (
            float(features[symbol].return_15m) - spy_return >= 0.0
            and float(features[symbol].volume_acceleration) >= 0.0
            and float(features[symbol].realized_volatility_30m)
            <= volatility_limit
        )
        for symbol in candidates
    }


def _group_compact_rows(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    """Group without copying 1M+ historical row dictionaries."""
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        try:
            stamp = datetime.fromisoformat(str(row["timestamp_utc"]))
            if stamp.tzinfo is None:
                raise ValueError
            session = stamp.astimezone(NEW_YORK).date().isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        grouped.setdefault(session, []).append(row)
    for values in grouped.values():
        values.sort(key=lambda row: str(row["timestamp_utc"]))
    return grouped


def _spy_annualized_volatility(
    sessions: Sequence[str],
    index: int,
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
) -> float | None:
    if index < 20:
        return None
    closes = [
        _closing_price(grouped, "SPY", session)
        for session in sessions[index - 20 : index + 1]
    ]
    if any(value is None for value in closes):
        return None
    returns = [
        float(right) / float(left) - 1.0
        for left, right in zip(closes, closes[1:])
    ]
    if len(returns) != 20 or any(not math.isfinite(value) for value in returns):
        return None
    return statistics.pstdev(returns) * math.sqrt(252.0)


def integer_allocation(
    *,
    equity: float,
    ranked_symbols: Sequence[str],
    entry_prices: Mapping[str, float],
    execution: Mapping[str, object],
) -> dict[str, int]:
    if equity <= 0 or not math.isfinite(equity):
        raise ValueError("V13_EQUITY_INVALID")
    maximum_positions = int(execution["maximum_positions"])
    maximum_deployed = float(execution["maximum_deployed_capital_pct"])
    maximum_position = float(execution["maximum_position_notional_pct"])
    half_cost = MODELED_ROUND_TRIP_COST_BPS / 2.0 / 10000.0
    deployment_budget = equity * maximum_deployed / (1.0 + half_cost)
    affordable = [
        symbol
        for symbol in ranked_symbols
        if symbol in entry_prices
        and math.isfinite(float(entry_prices[symbol]))
        and float(entry_prices[symbol]) > 0
        and float(entry_prices[symbol]) <= equity * maximum_position
    ]
    target_count = min(maximum_positions, len(affordable))
    if target_count == 0:
        return {}
    target_notional = min(
        deployment_budget / target_count,
        equity * maximum_position,
    )
    allocation: dict[str, int] = {}
    deployed = 0.0
    for symbol in affordable:
        price = float(entry_prices[symbol])
        remaining = max(0.0, deployment_budget - deployed)
        shares = math.floor(min(target_notional, remaining) / price)
        if shares < 1:
            continue
        allocation[symbol] = int(shares)
        deployed += shares * price
        if len(allocation) == maximum_positions:
            break
    return allocation


def simulate_period(
    *,
    period: RetrospectivePeriod,
    starting_equity: float,
    contract: Mapping[str, object],
) -> dict[str, object]:
    execution = contract["small_account_execution"]
    threshold = float(contract["regime_gate"]["condition_2_threshold"])
    minimum_positions = int(execution["minimum_positions"])

    regime_eligible = (
        period.regime_input_complete
        and period.confirmed_negative_2d
        and period.spy_annualized_volatility_20d is not None
        and period.spy_annualized_volatility_20d >= threshold
    )
    action = "EXECUTE_UNCHANGED_V10_CONTROL"
    hold_reason: str | None = None
    ranked = list(period.ranked_symbols)
    if not period.market_data_complete:
        ranked = []
        hold_reason = "MISSING_HISTORICAL_OPEN_HOLD_CASH"
    elif not period.regime_input_complete:
        ranked = []
        hold_reason = "MISSING_REGIME_INPUT_HOLD_CASH"
    elif regime_eligible:
        action = "APPLY_V13_INTRADAY_CONFIRMATION"
        if period.confirmations is None:
            ranked = []
            hold_reason = "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
        else:
            ranked = [
                symbol
                for symbol in ranked
                if period.confirmations.get(symbol) is True
            ]
            if len(ranked) < minimum_positions:
                hold_reason = "INSUFFICIENT_CONFIRMATIONS_HOLD_CASH"

    allocation = (
        integer_allocation(
            equity=starting_equity,
            ranked_symbols=ranked,
            entry_prices=period.entry_prices,
            execution=execution,
        )
        if len(ranked) >= minimum_positions
        else {}
    )
    if len(allocation) < minimum_positions:
        allocation = {}
        ending_equity = starting_equity
        buy_notional = 0.0
        sell_notional = 0.0
        transaction_cost = 0.0
        traded = False
        if hold_reason is None:
            hold_reason = "INSUFFICIENT_AFFORDABLE_POSITIONS_HOLD_CASH"
    else:
        buy_notional = sum(
            shares * float(period.entry_prices[symbol])
            for symbol, shares in allocation.items()
        )
        sell_notional = sum(
            shares * float(period.exit_prices[symbol])
            for symbol, shares in allocation.items()
        )
        half_cost = MODELED_ROUND_TRIP_COST_BPS / 2.0 / 10000.0
        transaction_cost = (buy_notional + sell_notional) * half_cost
        ending_equity = (
            starting_equity - buy_notional + sell_notional - transaction_cost
        )
        hold_reason = None
        traded = True

    if ending_equity <= 0 or not math.isfinite(ending_equity):
        raise ValueError("V13_PERIOD_ENDING_EQUITY_INVALID")
    deployed_pct = buy_notional / starting_equity
    maximum_position_pct = max(
        (
            shares * float(period.entry_prices[symbol]) / starting_equity
            for symbol, shares in allocation.items()
        ),
        default=0.0,
    )
    constraints_pass = (
        deployed_pct
        <= float(execution["maximum_deployed_capital_pct"]) + 1e-12
        and maximum_position_pct
        <= float(execution["maximum_position_notional_pct"]) + 1e-12
        and len(allocation) <= int(execution["maximum_positions"])
        and all(isinstance(shares, int) and shares > 0 for shares in allocation.values())
    )
    if not constraints_pass:
        raise RuntimeError("V13_SMALL_ACCOUNT_CONSTRAINT_VIOLATION")

    return {
        "decision_session": period.decision_session,
        "entry_session": period.entry_session,
        "exit_session": period.exit_session,
        "cohort_offset": period.cohort_offset,
        "confirmed_negative_2d": period.confirmed_negative_2d,
        "spy_annualized_volatility_20d": period.spy_annualized_volatility_20d,
        "regime_eligible": regime_eligible,
        "action": action,
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        "period_return": ending_equity / starting_equity - 1.0,
        "selected_symbols": list(allocation),
        "integer_shares": allocation,
        "position_count": len(allocation),
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "transaction_cost_usd": transaction_cost,
        "modeled_total_cost_bps_round_trip": MODELED_ROUND_TRIP_COST_BPS,
        "historical_spread_policy": HISTORICAL_SPREAD_POLICY,
        "traded": traded,
        "hold_reason": hold_reason,
        "small_account_constraints_passed": constraints_pass,
        "retrospective_development_only": True,
        "fresh_evidence": False,
        "brokerage_orders": False,
    }


def reconstruct_periods(
    periods: Sequence[RetrospectivePeriod],
    contract: Mapping[str, object],
    *,
    source: Mapping[str, object] | None = None,
) -> dict[str, object]:
    failures = validate_contract(contract)
    if failures or contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V13_CONTRACT_IDENTITY_CHANGED")
    if not periods:
        raise ValueError("NO_V13_RETROSPECTIVE_PERIODS")

    starting_capital = float(contract["small_account_execution"]["starting_capital_usd"])
    equity_by_offset = {offset: starting_capital for offset in COHORT_OFFSETS}
    first_entry = min(period.entry_session for period in periods)
    history_by_timestamp: dict[str, dict[str, object]] = {
        first_entry: {
            "timestamp": f"{first_entry}T00:00:00+00:00",
            "mean_equity": starting_capital,
            "source": "V13 retrospective starting capital",
        }
    }
    records: list[dict[str, object]] = []
    for period in sorted(periods, key=lambda item: item.decision_index):
        offset = period.cohort_offset
        if offset not in equity_by_offset:
            raise ValueError("V13_COHORT_OFFSET_INVALID")
        record = simulate_period(
            period=period,
            starting_equity=equity_by_offset[offset],
            contract=contract,
        )
        equity_by_offset[offset] = float(record["ending_equity"])
        records.append(record)
        history_by_timestamp[period.exit_session] = {
            "timestamp": f"{period.exit_session}T00:00:00+00:00",
            "mean_equity": statistics.fmean(equity_by_offset.values()),
            "source": (
                "V13 mean of five staggered $5,000 integer-share cohort paths"
            ),
        }

    history = [history_by_timestamp[key] for key in sorted(history_by_timestamp)]
    terminal = float(history[-1]["mean_equity"])
    elapsed_days = max(
        1,
        (date.fromisoformat(history[-1]["timestamp"][:10]) - date.fromisoformat(first_entry)).days,
    )
    annualized = (terminal / starting_capital) ** (365.25 / elapsed_days) - 1.0
    regime_records = [row for row in records if row["regime_eligible"]]
    result: dict[str, object] = {
        "status": "V13_RETROSPECTIVE_DEVELOPMENT_RECONSTRUCTION",
        "classification": "RETROSPECTIVE_DEVELOPMENT_ONLY_NOT_FRESH_EVIDENCE",
        "candidate_id": contract["challenger"]["candidate_id"],
        "v13_contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": V12_DISPOSITION_SHA256,
        "v10_candidate_id": EXPECTED_V10_CANDIDATE,
        "v10_frozen_spec_sha256": EXPECTED_V10_SHA256,
        "requested_start_date": REQUESTED_START_DATE.isoformat(),
        "tiingo_iex_intraday_available_from": "August 2017",
        "ten_calendar_years_available": False,
        "actual_first_eligible_session": first_entry,
        "actual_last_eligible_session": history[-1]["timestamp"][:10],
        "starting_capital_usd": starting_capital,
        "cohort_method": "MEAN_OF_FIVE_STAGGERED_5000_USD_INTEGER_SHARE_COHORTS",
        "ending_equity_usd": terminal,
        "total_return": terminal / starting_capital - 1.0,
        "annualized_return": annualized,
        "maximum_drawdown": _maximum_drawdown(
            [float(row["mean_equity"]) for row in history]
        ),
        "period_count": len(records),
        "regime_eligible_periods": len(regime_records),
        "regime_overlay_trades": sum(1 for row in regime_records if row["traded"]),
        "regime_overlay_holds": sum(1 for row in regime_records if not row["traded"]),
        "history": history,
        "period_records": records,
        "source_inputs": dict(source or {}),
        "historical_spread_policy": HISTORICAL_SPREAD_POLICY,
        "display_normalization": (
            "The $5,000 integer-share return path may be rebased to $100,000 "
            "for chart comparison; execution remains simulated at $5,000."
        ),
        "fresh_evidence_included": False,
        "fresh_journal_read": False,
        "fresh_journal_written": False,
        "manual_approval_read": False,
        "activation_lease_read": False,
        "candidate_frozen": False,
        "fresh_evidence_activation": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
        "v13_production_evidence_modified": False,
    }
    result["reconstruction_sha256"] = _canonical_sha(result)
    return result


def load_retrospective_periods(
    *,
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[dict[str, object], list[RetrospectivePeriod]]:
    import pandas as pd

    from ml.v10 import cycle3
    from ml.v11.intraday_walk_forward import (
        get_v5_data_symbols,
        load_dataset,
    )

    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_historical_manifest(raw_manifest)
    manifest, dataset = load_dataset(manifest_path)
    symbols = tuple(get_v5_data_symbols())
    if len(symbols) != 101 or len(set(symbols)) != 101 or "SPY" not in symbols:
        raise ValueError("V13_REQUIRES_FIXED_101_SYMBOL_UNIVERSE")
    grouped = {
        symbol: _group_compact_rows(dataset[symbol]) for symbol in symbols
    }
    common_sessions = sorted(
        set.intersection(*(set(grouped[symbol]) for symbol in symbols))
    )
    if len(common_sessions) < 31:
        raise ValueError("V13_REQUIRES_AT_LEAST_31_COMPLETE_COMMON_SESSIONS")

    if cycle3.EXPECTED_CONTRACT_SHA256 != V10_CYCLE3_CONTRACT_SHA256:
        raise RuntimeError("V10_CYCLE3_CONTRACT_IDENTITY_CHANGED")
    if not V10_FREEZE_LOCK_PATH.exists():
        raise FileNotFoundError("V10_FROZEN_SPEC_LOCK_MISSING")
    if V10_FREEZE_LOCK_PATH.read_text(encoding="utf-8").strip() != EXPECTED_V10_SHA256:
        raise RuntimeError("V10_FROZEN_SPEC_IDENTITY_CHANGED")

    scored = cycle3._build_score_panel()
    scored = scored[scored["candidate_id"] == EXPECTED_V10_CANDIDATE].copy()
    if scored.empty:
        raise ValueError("V10_DEVELOPMENT_RANKINGS_MISSING")
    scored["timestamp_utc"] = pd.to_datetime(scored["timestamp_utc"], utc=True)
    rankings: dict[str, tuple[str, ...]] = {}
    confirmed: dict[str, bool] = {}
    v10_sessions = sorted(scored["timestamp_utc"].drop_duplicates().tolist())
    v10_indices = {
        stamp.date().isoformat(): index for index, stamp in enumerate(v10_sessions)
    }
    for stamp, day in scored.groupby("timestamp_utc", sort=True):
        session = stamp.date().isoformat()
        ranked = day.dropna(subset=["score"]).sort_values(
            ["score", "symbol"], ascending=[False, True]
        )
        ranked_symbols = tuple(ranked["symbol"].astype(str).tolist())
        if len(ranked_symbols) != 100 or len(set(ranked_symbols)) != 100:
            continue
        rankings[session] = ranked_symbols
        confirmed[session] = bool(ranked["confirmed_negative_2d"].iloc[0])

    periods: list[RetrospectivePeriod] = []
    for index in range(1, len(common_sessions) - HOLD_SESSIONS - 1):
        decision_session = common_sessions[index]
        if decision_session not in rankings:
            continue
        entry_session = common_sessions[index + 1]
        exit_session = common_sessions[index + 1 + HOLD_SESSIONS]
        if date.fromisoformat(exit_session) > DEVELOPMENT_END_DATE:
            continue
        original_index = v10_indices.get(decision_session)
        if original_index is None:
            continue
        ranked_symbols = rankings[decision_session]
        annualized_volatility = _spy_annualized_volatility(
            common_sessions, index, grouped
        )
        confirmed_negative = confirmed[decision_session]
        regime_input_complete = not confirmed_negative or annualized_volatility is not None
        regime_eligible = (
            regime_input_complete
            and confirmed_negative
            and float(annualized_volatility) >= 0.25
        )
        confirmations = (
            _confirmation_state(
                session=decision_session,
                previous_session=common_sessions[index - 1],
                grouped=grouped,
                symbols=symbols,
            )
            if regime_eligible
            else None
        )
        entry_prices = {
            symbol: price
            for symbol in ranked_symbols
            if (price := _opening_price(grouped, symbol, entry_session)) is not None
        }
        exit_prices = {
            symbol: price
            for symbol in ranked_symbols
            if (price := _opening_price(grouped, symbol, exit_session)) is not None
        }
        market_complete = (
            len(entry_prices) == 100 and len(exit_prices) == 100
        )
        periods.append(
            RetrospectivePeriod(
                decision_session=decision_session,
                entry_session=entry_session,
                exit_session=exit_session,
                decision_index=original_index,
                cohort_offset=original_index % HOLD_SESSIONS,
                ranked_symbols=ranked_symbols,
                confirmed_negative_2d=confirmed_negative,
                spy_annualized_volatility_20d=annualized_volatility,
                regime_input_complete=regime_input_complete,
                confirmations=confirmations,
                market_data_complete=market_complete,
                entry_prices=entry_prices,
                exit_prices=exit_prices,
            )
        )
    if not periods:
        raise ValueError("NO_COMMON_V10_V13_RETROSPECTIVE_PERIODS")
    source = {
        "historical_manifest_sha256": manifest["manifest_sha256"],
        "historical_first_common_session": manifest["first_common_session"],
        "historical_last_common_session": manifest["last_common_session"],
        "provider": "Tiingo IEX historical five-minute bars",
        "provider_intraday_history_starts": "August 2017",
        "sampling_policy": manifest["sampling_policy"],
        "bars_retained_per_complete_session": manifest[
            "bars_retained_per_complete_session"
        ],
        "fixed_universe_symbols": 101,
        "v10_candidate_id": EXPECTED_V10_CANDIDATE,
        "v10_frozen_spec_sha256": EXPECTED_V10_SHA256,
        "fresh_inputs_read": False,
        "production_inputs_read": False,
        "holdout_outcomes_read": False,
    }
    return source, periods


def run(
    *,
    manifest_path: Path = MANIFEST_PATH,
    output_path: Path = OUTPUT_PATH,
    write: bool = True,
) -> dict[str, object]:
    contract = load_contract()
    failures = validate_contract(contract)
    if failures or contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V13_CONTRACT_IDENTITY_CHANGED")
    source, periods = load_retrospective_periods(manifest_path=manifest_path)
    result = reconstruct_periods(periods, contract, source=source)
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    if write:
        _atomic_write(output_path, result)
    return result


def main() -> None:
    print("DATA SHEPHERD V13 RETROSPECTIVE DEVELOPMENT RECONSTRUCTION")
    print("=" * 88)
    try:
        result = run()
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Retrospective result published: NO")
        print("Fresh evidence modified: NO")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result['status']}")
    print(f"Classification: {result['classification']}")
    print(
        "Requested / exact source window: "
        f"{result['requested_start_date']} / "
        f"{result['tiingo_iex_intraday_available_from']}"
    )
    print(
        "Actual eligible window: "
        f"{result['actual_first_eligible_session']} -> "
        f"{result['actual_last_eligible_session']}"
    )
    print(f"Executable periods: {result['period_count']:,}")
    print(f"Regime-eligible periods: {result['regime_eligible_periods']:,}")
    print(
        f"$5,000 terminal equity: ${result['ending_equity_usd']:,.2f} | "
        f"return={result['total_return']:+.2%} | "
        f"annualized={result['annualized_return']:+.2%} | "
        f"drawdown={result['maximum_drawdown']:.2%}"
    )
    print(f"Reconstruction SHA-256: {result['reconstruction_sha256']}")
    print("Ten full calendar years available: NO — Tiingo IEX begins August 2017")
    print("Fresh evidence included: NO")
    print("Candidate frozen: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12/V13 production modified: NO")


if __name__ == "__main__":
    main()
