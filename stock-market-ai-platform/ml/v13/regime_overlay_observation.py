"""Guarded V13 fresh-session observation logic.

The V13 contract is preregistered but fresh-evidence activation is disabled.
This module therefore accepts only caller-supplied, SHA-verified inputs and can
write only explicitly labelled rehearsal events to a non-production journal.
It does not load V8/V10/V11 production artifacts, request market data, install
a scheduler, activate V13, or expose brokerage authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from ml.v13.regime_overlay_contract import (
    EXPECTED_CONTRACT_SHA256,
    EXPECTED_V10_CANDIDATE,
    EXPECTED_V10_SHA256,
    EXPECTED_V12_DISPOSITION_SHA256,
    contract_sha256,
    load_contract,
    validate_contract,
)
from ml.v13.regime_overlay_journal import (
    DEFAULT_JOURNAL_PATH,
    RegimeOverlayEvidenceJournal,
    V13EvidenceActivationDisabled,
)
from ml.v13.regime_overlay_reconstruction import (
    MODELED_ROUND_TRIP_COST_BPS,
    integer_allocation,
)


NEW_YORK = ZoneInfo("America/New_York")
FRESH_BOUNDARY = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
EXPECTED_RANKING_STATUS = "COMPLETE_FROZEN_V10_RANKING_SNAPSHOT"
COMPLETE_INPUT_STATUS = "COMPLETE_V13_FRESH_INPUT_SNAPSHOT"
INCOMPLETE_INPUT_STATUS = "INCOMPLETE_V13_FRESH_INPUT_SNAPSHOT"
COMPLETE_REGIME_STATUS = "COMPLETE_V13_REGIME_INPUT_SNAPSHOT"
INCOMPLETE_REGIME_STATUS = "INCOMPLETE_V13_REGIME_INPUT_SNAPSHOT"


@dataclass(frozen=True)
class DecisionRun:
    status: str
    session_date: str
    regime_eligible: bool
    action: str
    hold_reason: str | None
    control_symbols: tuple[str, ...]
    challenger_symbols: tuple[str, ...]
    event_appended: bool
    rehearsal: bool
    brokerage_orders: bool = False


@dataclass(frozen=True)
class PairedObservationRun:
    status: str
    session_date: str
    control_net_return: float
    challenger_net_return: float
    net_return_delta: float
    event_appended: bool
    rehearsal: bool
    brokerage_orders: bool = False


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def signed_payload(payload: Mapping[str, object], field: str) -> dict[str, object]:
    result = dict(payload)
    result[field] = canonical_sha256(result)
    return result


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("V13_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)


def _require_contract() -> dict[str, object]:
    contract = load_contract()
    failures = validate_contract(contract)
    if failures or contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V13_CONTRACT_IDENTITY_CHANGED")
    return contract


def _require_rehearsal_destination(
    *, journal_path: Path, rehearsal: bool
) -> None:
    if not rehearsal:
        raise V13EvidenceActivationDisabled(
            "V13 fresh-evidence activation remains disabled"
        )
    if journal_path.resolve() == DEFAULT_JOURNAL_PATH.resolve():
        raise RuntimeError("V13_REHEARSAL_CANNOT_WRITE_PRODUCTION_JOURNAL")


def _validate_signed_payload(
    payload: Mapping[str, object], field: str, error: str
) -> None:
    body = dict(payload)
    observed = body.pop(field, None)
    if observed != canonical_sha256(body):
        raise ValueError(error)


def _validate_ranking_snapshot(
    snapshot: Mapping[str, object], session_date: str
) -> tuple[str, ...]:
    _validate_signed_payload(
        snapshot,
        "ranking_sha256",
        "V13_V10_RANKING_SNAPSHOT_SHA_MISMATCH",
    )
    if snapshot.get("status") != EXPECTED_RANKING_STATUS:
        raise ValueError("V13_V10_RANKING_SNAPSHOT_INCOMPLETE")
    if snapshot.get("session_date") != session_date:
        raise ValueError("V13_V10_RANKING_SESSION_MISMATCH")
    if snapshot.get("candidate_id") != EXPECTED_V10_CANDIDATE:
        raise ValueError("V13_V10_CANDIDATE_CHANGED")
    if snapshot.get("frozen_spec_sha256") != EXPECTED_V10_SHA256:
        raise ValueError("V13_V10_FROZEN_IDENTITY_CHANGED")
    symbols = tuple(str(value) for value in snapshot.get("symbols", ()))
    if len(symbols) != 100 or len(set(symbols)) != 100 or "SPY" in symbols:
        raise ValueError("V13_REQUIRES_COMPLETE_100_STOCK_V10_RANKING")
    return symbols


def _validate_intraday_snapshot(
    snapshot: Mapping[str, object],
    *,
    session_date: str,
    ranked_symbols: Sequence[str],
    decision_time: datetime,
) -> tuple[
    Mapping[str, Mapping[str, object]] | None,
    Mapping[str, float],
    Mapping[str, float],
    str | None,
]:
    _validate_signed_payload(
        snapshot,
        "source_snapshot_sha256",
        "V13_INTRADAY_SNAPSHOT_SHA_MISMATCH",
    )
    if snapshot.get("session_date") != session_date:
        raise ValueError("V13_INTRADAY_SESSION_MISMATCH")
    collected = _utc(snapshot.get("collected_at_utc"))
    if collected < FRESH_BOUNDARY:
        raise ValueError("V13_PRE_BOUNDARY_INPUT_PROHIBITED")
    completed_bar = _utc(snapshot.get("completed_bar_utc"))
    if (
        completed_bar > decision_time
        or completed_bar > collected
        or completed_bar.date() != decision_time.date()
    ):
        raise ValueError("V13_INTRADAY_COMPLETED_BAR_INVALID")
    if _utc(snapshot.get("entry_timestamp_utc")) != decision_time:
        raise ValueError("V13_ENTRY_TIMESTAMP_MUST_MATCH_1000_DECISION")
    status = snapshot.get("status")
    features = snapshot.get("features")
    entry_prices = snapshot.get("entry_prices")
    spreads_bps = snapshot.get("spreads_bps")
    if not isinstance(entry_prices, Mapping) or not isinstance(spreads_bps, Mapping):
        raise ValueError("V13_INTRADAY_MARKET_MAPS_INVALID")
    expected = set(ranked_symbols) | {"SPY"}
    if (
        status != COMPLETE_INPUT_STATUS
        or snapshot.get("symbol_count") != 101
        or not isinstance(features, Mapping)
        or set(features) != expected
    ):
        if status not in (COMPLETE_INPUT_STATUS, INCOMPLETE_INPUT_STATUS):
            raise ValueError("V13_INTRADAY_SNAPSHOT_STATUS_INVALID")
        return (
            None,
            entry_prices,
            spreads_bps,
            "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH",
        )
    for symbol, values in features.items():
        if not isinstance(values, Mapping):
            return None, entry_prices, spreads_bps, "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
        required = ("return_15m", "volume_acceleration", "realized_volatility_30m")
        try:
            numbers = [float(values[field]) for field in required]
        except (KeyError, TypeError, ValueError):
            return None, entry_prices, spreads_bps, "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
        if any(not math.isfinite(value) for value in numbers):
            return None, entry_prices, spreads_bps, "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
    return features, entry_prices, spreads_bps, None


def _validate_regime_snapshot(
    snapshot: Mapping[str, object],
    *,
    session_date: str,
    decision_time: datetime,
) -> tuple[bool, float | None, bool]:
    _validate_signed_payload(
        snapshot,
        "source_regime_sha256",
        "V13_REGIME_SNAPSHOT_SHA_MISMATCH",
    )
    if snapshot.get("session_date") != session_date:
        raise ValueError("V13_REGIME_SESSION_MISMATCH")
    collected = _utc(snapshot.get("collected_at_utc"))
    if collected < FRESH_BOUNDARY or collected > decision_time:
        raise ValueError("V13_REGIME_COLLECTION_TIME_INVALID")
    status = snapshot.get("status")
    if status not in (COMPLETE_REGIME_STATUS, INCOMPLETE_REGIME_STATUS):
        raise ValueError("V13_REGIME_SNAPSHOT_STATUS_INVALID")
    flags = snapshot.get("v10_negative_flags")
    if (
        not isinstance(flags, Sequence)
        or isinstance(flags, (str, bytes))
        or len(flags) != 2
        or any(not isinstance(value, bool) for value in flags)
    ):
        raise ValueError("V13_REQUIRES_TWO_V10_NEGATIVE_FLAGS")
    confirmed_negative = all(flags)
    volatility = _annualized_spy_volatility(snapshot.get("spy_closes", ()))
    complete = status == COMPLETE_REGIME_STATUS and volatility is not None
    return confirmed_negative, volatility, complete


def _annualized_spy_volatility(spy_closes: Sequence[float]) -> float | None:
    if len(spy_closes) != 21:
        return None
    try:
        closes = [float(value) for value in spy_closes]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        return None
    returns = [right / left - 1.0 for left, right in zip(closes, closes[1:])]
    return statistics.pstdev(returns) * math.sqrt(252.0)


def _confirmations(
    features: Mapping[str, Mapping[str, object]],
    ranked_symbols: Sequence[str],
) -> dict[str, bool]:
    ordered_volatility = sorted(
        float(features[symbol]["realized_volatility_30m"])
        for symbol in ranked_symbols
    )
    location = (len(ordered_volatility) - 1) * 0.80
    lower = math.floor(location)
    upper = math.ceil(location)
    weight = location - lower
    volatility_limit = (
        ordered_volatility[lower] * (1.0 - weight)
        + ordered_volatility[upper] * weight
    )
    spy_return = float(features["SPY"]["return_15m"])
    return {
        symbol: (
            float(features[symbol]["return_15m"]) - spy_return >= 0.0
            and float(features[symbol]["volume_acceleration"]) >= 0.0
            and float(features[symbol]["realized_volatility_30m"])
            <= volatility_limit
        )
        for symbol in ranked_symbols
    }


def _validated_market_maps(
    *,
    ranked_symbols: Sequence[str],
    entry_prices: Mapping[str, float],
    spreads_bps: Mapping[str, float],
    maximum_spread_bps: float,
) -> tuple[dict[str, float], str | None]:
    prices: dict[str, float] = {}
    for symbol in ranked_symbols:
        try:
            price = float(entry_prices[symbol])
            spread = float(spreads_bps[symbol])
        except (KeyError, TypeError, ValueError):
            return {}, "MISSING_QUOTE_OR_SPREAD_HOLD_CASH"
        if (
            not math.isfinite(price)
            or price <= 0
            or not math.isfinite(spread)
            or spread < 0
            or spread > maximum_spread_bps
        ):
            return {}, "MISSING_QUOTE_OR_SPREAD_HOLD_CASH"
        prices[symbol] = price
    return prices, None


def _base_event(
    *, event_type: str, session_date: str, timestamp_utc: str
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "session_date": session_date,
        "timestamp_utc": timestamp_utc,
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v12_disposition_sha256": EXPECTED_V12_DISPOSITION_SHA256,
        "control_candidate": "V10_CONTROL_5K",
        "challenger_candidate": "V13_NEGATIVE_HIGH_VOL_CONFIRM_5K",
        "rehearsal": True,
        "fresh_evidence": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "holdout_outcomes_read": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
        "v12_modified": False,
        "v13_production_evidence_modified": False,
    }


def run_session_decision(
    *,
    session_date: str,
    decision_timestamp_utc: str,
    ranking_snapshot: Mapping[str, object],
    intraday_snapshot: Mapping[str, object],
    regime_snapshot: Mapping[str, object],
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    rehearsal: bool = False,
    starting_equity: float = 5000.0,
) -> DecisionRun:
    """Derive and journal one V13 decision in explicit rehearsal mode."""
    _require_rehearsal_destination(journal_path=journal_path, rehearsal=rehearsal)
    contract = _require_contract()
    decision_time = _utc(decision_timestamp_utc)
    try:
        parsed_session = date.fromisoformat(session_date)
    except ValueError as exc:
        raise ValueError("V13_SESSION_DATE_INVALID") from exc
    if decision_time < FRESH_BOUNDARY:
        raise ValueError("V13_PRE_BOUNDARY_SESSION_PROHIBITED")
    eastern = decision_time.astimezone(NEW_YORK)
    if eastern.date() != parsed_session or (eastern.hour, eastern.minute) != (10, 0):
        raise ValueError("V13_DECISION_MUST_BE_1000_EASTERN")
    ranked = _validate_ranking_snapshot(ranking_snapshot, session_date)
    features, raw_entry_prices, raw_spreads_bps, intraday_hold = _validate_intraday_snapshot(
        intraday_snapshot,
        session_date=session_date,
        ranked_symbols=ranked,
        decision_time=decision_time,
    )
    confirmed_negative, spy_volatility, regime_snapshot_complete = (
        _validate_regime_snapshot(
            regime_snapshot,
            session_date=session_date,
            decision_time=decision_time,
        )
    )
    execution = contract["small_account_execution"]
    if float(starting_equity) != float(execution["starting_capital_usd"]):
        raise ValueError("V13_STARTING_CAPITAL_CHANGED")
    prices, quote_hold = _validated_market_maps(
        ranked_symbols=ranked,
        entry_prices=raw_entry_prices,
        spreads_bps=raw_spreads_bps,
        maximum_spread_bps=float(execution["maximum_spread_bps"]),
    )
    regime_input_complete = not confirmed_negative or regime_snapshot_complete
    regime_eligible = bool(
        regime_input_complete
        and confirmed_negative
        and spy_volatility is not None
        and spy_volatility >= float(contract["regime_gate"]["condition_2_threshold"])
    )

    minimum_positions = int(execution["minimum_positions"])
    control_hold = quote_hold
    control_allocation = (
        integer_allocation(
            equity=starting_equity,
            ranked_symbols=ranked,
            entry_prices=prices,
            execution=execution,
        )
        if control_hold is None
        else {}
    )
    if len(control_allocation) < minimum_positions:
        control_allocation = {}
        control_hold = control_hold or "INSUFFICIENT_AFFORDABLE_POSITIONS_HOLD_CASH"

    action = "EXECUTE_UNCHANGED_V10_CONTROL"
    challenger_hold = control_hold
    challenger_ranked = list(ranked)
    confirmation_state: dict[str, bool] | None = None
    if not regime_input_complete:
        challenger_hold = "MISSING_REGIME_INPUT_HOLD_CASH"
        challenger_ranked = []
    elif regime_eligible:
        action = "APPLY_V13_INTRADAY_CONFIRMATION"
        if features is None:
            challenger_hold = intraday_hold or "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
            challenger_ranked = []
        else:
            confirmation_state = _confirmations(features, ranked)
            challenger_ranked = [
                symbol for symbol in ranked if confirmation_state[symbol]
            ]
            if len(challenger_ranked) < minimum_positions:
                challenger_hold = "INSUFFICIENT_CONFIRMATIONS_HOLD_CASH"
                challenger_ranked = []
    challenger_allocation = (
        integer_allocation(
            equity=starting_equity,
            ranked_symbols=challenger_ranked,
            entry_prices=prices,
            execution=execution,
        )
        if challenger_hold is None and len(challenger_ranked) >= minimum_positions
        else {}
    )
    if len(challenger_allocation) < minimum_positions:
        challenger_allocation = {}
        challenger_hold = challenger_hold or "INSUFFICIENT_AFFORDABLE_POSITIONS_HOLD_CASH"

    event = _base_event(
        event_type="SESSION_DECISION",
        session_date=session_date,
        timestamp_utc=decision_time.isoformat(),
    )
    event.update(
        {
            "regime_gate": "V10_NEGATIVE_2D_AND_SPY_REALIZED_VOL_20D_GTE_25PCT",
            "confirmed_negative_2d": confirmed_negative,
            "spy_annualized_volatility_20d": spy_volatility,
            "regime_input_complete": regime_input_complete,
            "regime_eligible": regime_eligible,
            "action": action,
            "hold_reason": challenger_hold,
            "control_hold_reason": control_hold,
            "v10_ranking_sha256": ranking_snapshot["ranking_sha256"],
            "source_snapshot_sha256": intraday_snapshot["source_snapshot_sha256"],
            "source_regime_sha256": regime_snapshot["source_regime_sha256"],
            "raw_market_inputs_collected_after_boundary": True,
            "entry_prices": prices,
            "control_integer_shares": control_allocation,
            "challenger_integer_shares": challenger_allocation,
            "control_selected_symbols": list(control_allocation),
            "challenger_selected_symbols": list(challenger_allocation),
            "confirmed_symbol_count": (
                sum(confirmation_state.values())
                if confirmation_state is not None
                else None
            ),
            "starting_equity_usd": starting_equity,
            "maximum_spread_bps": execution["maximum_spread_bps"],
            "modeled_total_cost_bps_round_trip": MODELED_ROUND_TRIP_COST_BPS,
        }
    )
    journal = RegimeOverlayEvidenceJournal(journal_path, rehearsal=True)
    appended = journal.append(event)
    return DecisionRun(
        status="REHEARSAL_DECISION_RECORDED",
        session_date=session_date,
        regime_eligible=regime_eligible,
        action=action,
        hold_reason=challenger_hold,
        control_symbols=tuple(control_allocation),
        challenger_symbols=tuple(challenger_allocation),
        event_appended=appended,
        rehearsal=True,
    )


def _portfolio_outcome(
    *,
    allocation: Mapping[str, object],
    entry_prices: Mapping[str, object],
    exit_prices: Mapping[str, float],
    starting_equity: float,
) -> tuple[float, float, float]:
    if not allocation:
        return starting_equity, 0.0, 0.0
    buy_notional = 0.0
    sell_notional = 0.0
    for symbol, raw_shares in allocation.items():
        shares = int(raw_shares)
        if shares <= 0:
            raise ValueError("V13_ALLOCATION_INVALID")
        try:
            entry = float(entry_prices[symbol])
            exit_price = float(exit_prices[symbol])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("V13_EXIT_PRICE_MISSING") from exc
        if not math.isfinite(exit_price) or exit_price <= 0:
            raise ValueError("V13_EXIT_PRICE_INVALID")
        buy_notional += shares * entry
        sell_notional += shares * exit_price
    half_cost = MODELED_ROUND_TRIP_COST_BPS / 2.0 / 10000.0
    cost = (buy_notional + sell_notional) * half_cost
    ending_equity = starting_equity - buy_notional + sell_notional - cost
    if not math.isfinite(ending_equity) or ending_equity <= 0:
        raise ValueError("V13_ENDING_EQUITY_INVALID")
    return ending_equity, ending_equity / starting_equity - 1.0, cost


def run_paired_observation(
    *,
    session_date: str,
    exit_session_date: str,
    exit_timestamp_utc: str,
    exit_prices: Mapping[str, float],
    exit_snapshot_sha256: str,
    completed_holding_sessions: int,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    rehearsal: bool = False,
) -> PairedObservationRun:
    """Complete a prior rehearsal decision after exactly five sessions."""
    _require_rehearsal_destination(journal_path=journal_path, rehearsal=rehearsal)
    _require_contract()
    if completed_holding_sessions != 5:
        raise ValueError("V13_REQUIRES_FIVE_COMPLETED_HOLDING_SESSIONS")
    exit_time = _utc(exit_timestamp_utc)
    if date.fromisoformat(exit_session_date) <= date.fromisoformat(session_date):
        raise ValueError("V13_EXIT_SESSION_INVALID")
    if exit_time.date() != date.fromisoformat(exit_session_date):
        raise ValueError("V13_EXIT_TIMESTAMP_SESSION_MISMATCH")
    if exit_snapshot_sha256 != canonical_sha256(exit_prices):
        raise ValueError("V13_EXIT_SNAPSHOT_SHA_INVALID")

    journal = RegimeOverlayEvidenceJournal(journal_path, rehearsal=True)
    rows = journal.read()
    decisions = [
        row
        for row in rows
        if row["session_date"] == session_date
        and row["event_type"] == "SESSION_DECISION"
    ]
    if len(decisions) != 1:
        raise ValueError("V13_PAIRED_OBSERVATION_REQUIRES_ONE_DECISION")
    decision = decisions[0]
    starting_equity = float(decision["starting_equity_usd"])
    control_equity, control_return, control_cost = _portfolio_outcome(
        allocation=decision["control_integer_shares"],
        entry_prices=decision["entry_prices"],
        exit_prices=exit_prices,
        starting_equity=starting_equity,
    )
    challenger_equity, challenger_return, challenger_cost = _portfolio_outcome(
        allocation=decision["challenger_integer_shares"],
        entry_prices=decision["entry_prices"],
        exit_prices=exit_prices,
        starting_equity=starting_equity,
    )
    delta = challenger_return - control_return
    event = _base_event(
        event_type="PAIRED_SESSION_OBSERVATION",
        session_date=session_date,
        timestamp_utc=exit_time.isoformat(),
    )
    event.update(
        {
            "exit_session_date": exit_session_date,
            "completed_holding_sessions": completed_holding_sessions,
            "regime_eligible": bool(decision["regime_eligible"]),
            "action": decision["action"],
            "hold_reason": decision.get("hold_reason"),
            "control_net_return": control_return,
            "challenger_net_return": challenger_return,
            "net_return_delta": delta,
            "control_ending_equity_usd": control_equity,
            "challenger_ending_equity_usd": challenger_equity,
            "control_transaction_cost_usd": control_cost,
            "challenger_transaction_cost_usd": challenger_cost,
            "paired_session_win": challenger_return > control_return,
            "exit_snapshot_sha256": exit_snapshot_sha256,
            "modeled_total_cost_bps_round_trip": MODELED_ROUND_TRIP_COST_BPS,
        }
    )
    appended = journal.append(event)
    return PairedObservationRun(
        status="REHEARSAL_PAIRED_OBSERVATION_RECORDED",
        session_date=session_date,
        control_net_return=control_return,
        challenger_net_return=challenger_return,
        net_return_delta=delta,
        event_appended=appended,
        rehearsal=True,
    )


def main() -> None:
    print("V13 GUARDED FRESH-SESSION OBSERVATION RUNNER")
    print("=" * 80)
    print("Status: DISABLED_REHEARSAL_ONLY")
    print("Production evidence activation: DISABLED")
    print("Market data requests: NONE")
    print("Production inputs read: NONE")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11/V12 production modified: NO")


if __name__ == "__main__":
    main()
