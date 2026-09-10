"""Fail-closed V12 development evaluation against the frozen V10 control.

The evaluator joins only two pre-boundary research inputs:

* the unchanged V10 Cycle 3 development ranking builder; and
* the SHA-verified V11 historical five-minute research backfill.

It never reads V10 holdout outcomes, the V11 fresh-evidence journal, production
rankings, or brokerage state.  Results are development evidence only and cannot
freeze a candidate or activate paper/live trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from typing import Mapping, Sequence

from ml.v12.challenger_contract import (
    contract_sha256,
    load_contract,
)


ROOT = Path(__file__).resolve().parents[2]
V11_MANIFEST_PATH = (
    ROOT / "data/research/v11/intraday/backfills/latest_complete_manifest.json"
)
OUTPUT_PATH = ROOT / "data/research/v12/development/latest_evaluation.json"

EXPECTED_CONTRACT_SHA256 = (
    "809d9d7480096cdd4f729eea71d04da85f31ad794cef74f35fb6dbeb8f6d3efc"
)
EXPECTED_V10_CANDIDATE = "c3_confirm2_blend50"
EXPECTED_V10_SPEC_SHA256 = (
    "2bf467ebf1e97c62697a6fdad48b28e20bdfc2092e26abfdebe7aa3de9388d38"
)
V10_ORIGINAL_HOLDOUT_START_UTC = datetime(
    2026, 11, 2, tzinfo=timezone.utc
)
V11_FRESH_CONFIRMATION_START_DATE = date(2026, 9, 1)
V10_CYCLE3_CONTRACT_SHA256 = (
    "e1df9ac21457a4494f53069b4513ecd4dfe0ae52a743eabdab6a63374998f051"
)
V10_FROZEN_SPEC_LOCK_PATH = (
    ROOT / "data/model/v10/cycle3/freeze/frozen_candidate.sha256"
)
HOLD_SESSIONS = 5
COHORT_OFFSETS = tuple(range(HOLD_SESSIONS))


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    intraday_confirmation: bool
    volatility_control: bool


@dataclass(frozen=True)
class MarketPeriod:
    decision_session: str
    entry_session: str
    exit_session: str
    decision_index: int
    cohort_offset: int
    decision_regime: str
    ranked_symbols: tuple[str, ...]
    confirmations: Mapping[str, bool] | None
    spy_annualized_volatility_20d: float | None
    entry_prices: Mapping[str, float]
    exit_prices: Mapping[str, float]
    spy_entry_price: float
    spy_exit_price: float


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


def validate_v11_manifest_preflight(manifest: Mapping[str, object]) -> None:
    """Reject tampering or any dataset that reaches V11 fresh evidence."""
    body = dict(manifest)
    identity = body.pop("manifest_sha256", None)
    if identity != _canonical_sha(body):
        raise ValueError("V11_MANIFEST_SHA_MISMATCH")
    last_common = date.fromisoformat(str(manifest["last_common_session"]))
    if last_common >= V11_FRESH_CONFIRMATION_START_DATE:
        raise RuntimeError("V11_FRESH_EVIDENCE_BOUNDARY_REACHED")


def _growth(returns: Sequence[float]) -> float:
    return math.prod(1.0 + value for value in returns)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        raise ValueError("PERCENTILE_REQUIRES_FINITE_VALUES")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("PERCENTILE_OUT_OF_RANGE")
    location = (len(ordered) - 1) * quantile
    lower = math.floor(location)
    upper = math.ceil(location)
    if lower == upper:
        return ordered[lower]
    weight = location - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _maximum_drawdown(equity: Sequence[float]) -> float:
    if not equity:
        raise ValueError("EMPTY_EQUITY_HISTORY")
    peak = float(equity[0])
    worst = 0.0
    for value in equity:
        value = float(value)
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _candidate_definitions(contract: Mapping[str, object]) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(
            candidate_id=str(item["candidate_id"]),
            intraday_confirmation=bool(item["intraday_confirmation"]),
            volatility_control=bool(item["volatility_control"]),
        )
        for item in contract["candidate_set"]
    )


def _exposure_multiplier(
    candidate: Candidate,
    annualized_volatility: float | None,
    contract: Mapping[str, object],
) -> float | None:
    if not candidate.volatility_control:
        return 1.0
    if (
        annualized_volatility is None
        or not math.isfinite(annualized_volatility)
        or annualized_volatility <= 0
    ):
        return None
    rule = contract["volatility_control_rule"]
    target = float(rule["target_annualized_volatility"])
    minimum = float(rule["minimum_exposure_multiplier"])
    maximum = float(rule["maximum_exposure_multiplier"])
    return min(maximum, max(minimum, target / annualized_volatility))


def integer_allocation(
    *,
    equity: float,
    ranked_symbols: Sequence[str],
    entry_prices: Mapping[str, float],
    exposure_multiplier: float,
    contract: Mapping[str, object],
) -> dict[str, int]:
    """Allocate integer shares without breaching cash or position limits."""
    if equity <= 0 or not math.isfinite(equity):
        raise ValueError("EQUITY_INVALID")
    if not 0.0 < exposure_multiplier <= 1.0:
        raise ValueError("EXPOSURE_MULTIPLIER_INVALID")
    account = contract["small_account_execution"]
    cost = contract["cost_contract"]
    maximum_positions = int(account["maximum_positions"])
    maximum_deployed = float(account["maximum_deployed_capital_pct"])
    maximum_position = float(account["maximum_position_notional_pct"])
    half_cost = (
        float(cost["minimum_modeled_total_cost_bps_round_trip"])
        / 2.0
        / 10000.0
    )
    deployment_budget = (
        equity * maximum_deployed * exposure_multiplier / (1.0 + half_cost)
    )
    available = [
        symbol
        for symbol in ranked_symbols
        if symbol in entry_prices
        and math.isfinite(float(entry_prices[symbol]))
        and float(entry_prices[symbol]) > 0
    ]
    provisional_count = min(maximum_positions, len(available))
    if provisional_count == 0:
        return {}
    target_notional = min(
        deployment_budget / provisional_count,
        equity * maximum_position,
    )
    allocation: dict[str, int] = {}
    deployed = 0.0
    for symbol in available:
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
    period: MarketPeriod,
    candidate: Candidate,
    starting_equity: float,
    contract: Mapping[str, object],
) -> dict[str, object]:
    account = contract["small_account_execution"]
    cost = contract["cost_contract"]
    minimum_positions = int(account["minimum_positions"])
    maximum_positions = int(account["maximum_positions"])

    ranked = list(period.ranked_symbols)
    if candidate.intraday_confirmation:
        if period.confirmations is None:
            ranked = []
            hold_reason = "MISSING_INTRADAY_CONFIRMATION_HOLD_CASH"
        else:
            ranked = [
                symbol for symbol in ranked
                if period.confirmations.get(symbol) is True
            ]
            hold_reason = "INSUFFICIENT_CONFIRMATIONS_HOLD_CASH"
    else:
        hold_reason = "INSUFFICIENT_AFFORDABLE_POSITIONS_HOLD_CASH"

    exposure = _exposure_multiplier(
        candidate,
        period.spy_annualized_volatility_20d,
        contract,
    )
    if exposure is None:
        ranked = []
        hold_reason = "MISSING_VOLATILITY_HOLD_CASH"

    if len(ranked) < minimum_positions:
        allocation: dict[str, int] = {}
    else:
        allocation = integer_allocation(
            equity=starting_equity,
            ranked_symbols=ranked,
            entry_prices=period.entry_prices,
            exposure_multiplier=float(exposure),
            contract=contract,
        )

    if len(allocation) < minimum_positions:
        allocation = {}
        ending_equity = starting_equity
        buy_notional = 0.0
        sell_notional = 0.0
        transaction_cost = 0.0
        traded = False
    else:
        allocation = dict(list(allocation.items())[:maximum_positions])
        buy_notional = sum(
            shares * float(period.entry_prices[symbol])
            for symbol, shares in allocation.items()
        )
        sell_notional = sum(
            shares * float(period.exit_prices[symbol])
            for symbol, shares in allocation.items()
        )
        half_cost_rate = (
            float(cost["minimum_modeled_total_cost_bps_round_trip"])
            / 2.0
            / 10000.0
        )
        transaction_cost = (buy_notional + sell_notional) * half_cost_rate
        ending_equity = (
            starting_equity - buy_notional + sell_notional - transaction_cost
        )
        hold_reason = None
        traded = True

    if ending_equity <= 0 or not math.isfinite(ending_equity):
        raise ValueError("PERIOD_ENDING_EQUITY_INVALID")

    deployed_pct = buy_notional / starting_equity
    maximum_position_pct = max(
        (
            shares * float(period.entry_prices[symbol]) / starting_equity
            for symbol, shares in allocation.items()
        ),
        default=0.0,
    )
    constraint_pass = (
        deployed_pct <= float(account["maximum_deployed_capital_pct"]) + 1e-12
        and maximum_position_pct
        <= float(account["maximum_position_notional_pct"]) + 1e-12
        and all(isinstance(shares, int) and shares > 0 for shares in allocation.values())
        and len(allocation) <= maximum_positions
    )
    if not constraint_pass:
        raise RuntimeError("SMALL_ACCOUNT_CONSTRAINT_VIOLATION")

    return {
        "candidate_id": candidate.candidate_id,
        "decision_session": period.decision_session,
        "entry_session": period.entry_session,
        "exit_session": period.exit_session,
        "decision_index": period.decision_index,
        "cohort_offset": period.cohort_offset,
        "decision_regime": period.decision_regime,
        "starting_equity": starting_equity,
        "ending_equity": ending_equity,
        "period_return": ending_equity / starting_equity - 1.0,
        "spy_return": period.spy_exit_price / period.spy_entry_price - 1.0,
        "selected_symbols": list(allocation),
        "integer_shares": allocation,
        "position_count": len(allocation),
        "exposure_multiplier": exposure,
        "buy_notional": buy_notional,
        "sell_notional": sell_notional,
        "turnover_notional_ratio": (
            (buy_notional + sell_notional) / starting_equity
        ),
        "transaction_cost_usd": transaction_cost,
        "modeled_total_cost_bps_round_trip": cost[
            "minimum_modeled_total_cost_bps_round_trip"
        ],
        "historical_spread_policy": "RUNTIME_GATE_SEPARATE_FROM_MODELED_COST",
        "traded": traded,
        "hold_reason": hold_reason,
        "small_account_constraints_passed": constraint_pass,
        "paper_trading_only": True,
        "brokerage_orders": False,
    }


def simulate_candidate(
    periods: Sequence[MarketPeriod],
    candidate: Candidate,
    contract: Mapping[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    starting_capital = float(
        contract["small_account_execution"]["starting_capital_usd"]
    )
    equity_by_offset = {offset: starting_capital for offset in COHORT_OFFSETS}
    history_by_offset = {
        offset: [starting_capital] for offset in COHORT_OFFSETS
    }
    records: list[dict[str, object]] = []
    for period in sorted(periods, key=lambda item: item.decision_index):
        offset = period.cohort_offset
        record = simulate_period(
            period=period,
            candidate=candidate,
            starting_equity=equity_by_offset[offset],
            contract=contract,
        )
        equity_by_offset[offset] = float(record["ending_equity"])
        history_by_offset[offset].append(equity_by_offset[offset])
        records.append(record)

    annualized_returns = []
    drawdowns = []
    for offset in COHORT_OFFSETS:
        count = len(history_by_offset[offset]) - 1
        terminal = equity_by_offset[offset]
        if count:
            annualized_returns.append(
                (terminal / starting_capital) ** (252.0 / (count * HOLD_SESSIONS))
                - 1.0
            )
        else:
            annualized_returns.append(0.0)
        drawdowns.append(_maximum_drawdown(history_by_offset[offset]))

    summary: dict[str, object] = {
        "candidate_id": candidate.candidate_id,
        "mean_terminal_wealth": statistics.fmean(equity_by_offset.values()),
        "mean_net_annualized_return": statistics.fmean(annualized_returns),
        "maximum_drawdown": min(drawdowns),
        "maximum_drawdown_abs": abs(min(drawdowns)),
        "mean_turnover_notional_ratio": statistics.fmean(
            float(row["turnover_notional_ratio"]) for row in records
        ),
        "trade_rate": statistics.fmean(
            1.0 if row["traded"] else 0.0 for row in records
        ),
        "small_account_feasibility_pass_rate": statistics.fmean(
            1.0 if row["small_account_constraints_passed"] else 0.0
            for row in records
        ),
        "cohort_terminal_wealth": {
            str(offset): equity_by_offset[offset] for offset in COHORT_OFFSETS
        },
        "cohort_annualized_returns": {
            str(offset): annualized_returns[offset] for offset in COHORT_OFFSETS
        },
        "cohort_maximum_drawdowns": {
            str(offset): drawdowns[offset] for offset in COHORT_OFFSETS
        },
        "periods": len(records),
        "costs_included": True,
    }
    return records, summary


def build_walk_forward_folds(
    sessions: Sequence[str],
    *,
    minimum_folds: int,
    purge_sessions: int,
    minimum_train_sessions: int = 20,
) -> list[dict[str, object]]:
    ordered = sorted(dict.fromkeys(sessions))
    required = minimum_train_sessions + minimum_folds * (purge_sessions + 1)
    if len(ordered) < required:
        raise ValueError(
            f"INSUFFICIENT_PURGED_WALK_FORWARD_SESSIONS:{len(ordered)}<{required}"
        )
    available_tests = len(ordered) - minimum_train_sessions - (
        minimum_folds * purge_sessions
    )
    base_size, remainder = divmod(available_tests, minimum_folds)
    cursor = minimum_train_sessions
    folds: list[dict[str, object]] = []
    for index in range(minimum_folds):
        train = ordered[:cursor]
        purge = ordered[cursor : cursor + purge_sessions]
        cursor += purge_sessions
        test_size = base_size + (1 if index < remainder else 0)
        test = ordered[cursor : cursor + test_size]
        cursor += test_size
        if not train or len(purge) != purge_sessions or not test:
            raise ValueError("WALK_FORWARD_FOLD_CONSTRUCTION_FAILED")
        folds.append(
            {
                "fold": index + 1,
                "train_start": train[0],
                "train_end": train[-1],
                "train_sessions": len(train),
                "purge_start": purge[0],
                "purge_end": purge[-1],
                "purge_sessions": len(purge),
                "test_start": test[0],
                "test_end": test[-1],
                "test_sessions": tuple(test),
            }
        )
    return folds


def _fold_growth(
    records: Sequence[Mapping[str, object]],
    sessions: set[str],
) -> float:
    cohort_growth = []
    for offset in COHORT_OFFSETS:
        values = [
            float(row["period_return"])
            for row in records
            if str(row["decision_session"]) in sessions
            and int(row["cohort_offset"]) == offset
        ]
        if values:
            cohort_growth.append(_growth(values))
    if not cohort_growth:
        raise ValueError("FOLD_HAS_NO_COHORT_OBSERVATIONS")
    return statistics.fmean(cohort_growth) - 1.0


def _mean_regime_return(
    records: Sequence[Mapping[str, object]],
    predicate,
) -> float | None:
    values = [
        float(row["period_return"])
        for row in records
        if predicate(str(row["decision_regime"]))
    ]
    return statistics.fmean(values) if values else None


def gate_candidate(
    *,
    candidate_summary: Mapping[str, object],
    control_summary: Mapping[str, object],
    candidate_records: Sequence[Mapping[str, object]],
    control_records: Sequence[Mapping[str, object]],
    folds: Sequence[Mapping[str, object]],
    contract: Mapping[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    requirements = contract["development_validation"]["required_gates"]
    fold_rows = []
    for fold in folds:
        test_sessions = set(fold["test_sessions"])
        candidate_return = _fold_growth(candidate_records, test_sessions)
        control_return = _fold_growth(control_records, test_sessions)
        fold_rows.append(
            {
                "fold": fold["fold"],
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
                "candidate_return": candidate_return,
                "control_return": control_return,
                "candidate_won": candidate_return > control_return,
            }
        )
    fold_win_rate = statistics.fmean(
        1.0 if row["candidate_won"] else 0.0 for row in fold_rows
    )

    candidate_positive = _mean_regime_return(
        candidate_records, lambda regime: regime.startswith("POSITIVE_")
    )
    control_positive = _mean_regime_return(
        control_records, lambda regime: regime.startswith("POSITIVE_")
    )
    candidate_negative = _mean_regime_return(
        candidate_records, lambda regime: regime.startswith("NEGATIVE_")
    )
    control_negative = _mean_regime_return(
        control_records, lambda regime: regime.startswith("NEGATIVE_")
    )
    candidate_high_vol = _mean_regime_return(
        candidate_records, lambda regime: "HIGH_VOL" in regime
    )
    control_high_vol = _mean_regime_return(
        control_records, lambda regime: "HIGH_VOL" in regime
    )

    annualized_delta = (
        float(candidate_summary["mean_net_annualized_return"])
        - float(control_summary["mean_net_annualized_return"])
    )
    turnover_limit = (
        float(control_summary["mean_turnover_notional_ratio"])
        * float(requirements["turnover_not_more_than_control_multiple"])
    )
    comparisons_available = all(
        value is not None
        for value in (
            candidate_positive,
            control_positive,
            candidate_negative,
            control_negative,
            candidate_high_vol,
            control_high_vol,
        )
    )
    gates = [
        (
            "net_annualized_return_delta",
            annualized_delta
            >= float(requirements["net_annualized_return_delta_at_least"]),
        ),
        (
            "terminal_wealth_greater_than_control",
            float(candidate_summary["mean_terminal_wealth"])
            > float(control_summary["mean_terminal_wealth"]),
        ),
        (
            "maximum_drawdown_not_worse_than_control",
            float(candidate_summary["maximum_drawdown"])
            >= float(control_summary["maximum_drawdown"]),
        ),
        (
            "walk_forward_fold_win_rate",
            fold_win_rate
            >= float(requirements["walk_forward_fold_win_rate_at_least"]),
        ),
        (
            "positive_spy_regime_noninferior",
            comparisons_available and candidate_positive >= control_positive,
        ),
        (
            "negative_spy_regime_outperformance",
            comparisons_available and candidate_negative > control_negative,
        ),
        (
            "high_volatility_regime_outperformance",
            comparisons_available and candidate_high_vol > control_high_vol,
        ),
        (
            "turnover_not_more_than_control_multiple",
            float(candidate_summary["mean_turnover_notional_ratio"])
            <= turnover_limit + 1e-12,
        ),
        ("all_costs_included", candidate_summary.get("costs_included") is True),
        (
            "small_account_feasibility_pass_rate",
            float(candidate_summary["small_account_feasibility_pass_rate"])
            == float(requirements["small_account_feasibility_pass_rate"]),
        ),
    ]
    rows = [
        {
            "candidate_id": candidate_summary["candidate_id"],
            "gate": name,
            "passed": bool(passed),
        }
        for name, passed in gates
    ]
    details = {
        "annualized_return_delta": annualized_delta,
        "fold_win_rate": fold_win_rate,
        "folds": fold_rows,
        "positive_regime_mean_return": candidate_positive,
        "control_positive_regime_mean_return": control_positive,
        "negative_regime_mean_return": candidate_negative,
        "control_negative_regime_mean_return": control_negative,
        "high_volatility_mean_return": candidate_high_vol,
        "control_high_volatility_mean_return": control_high_vol,
        "gates_passed": sum(1 for row in rows if row["passed"]),
        "gates_total": len(rows),
        "all_gates_passed": all(row["passed"] for row in rows),
    }
    return rows, details


def select_candidate(
    summaries: Sequence[Mapping[str, object]],
    gate_details: Mapping[str, Mapping[str, object]],
) -> str:
    eligible = [
        summary
        for summary in summaries
        if summary["candidate_id"] != "V10_CONTROL_5K"
        and gate_details[str(summary["candidate_id"])]["all_gates_passed"]
    ]
    if not eligible:
        return "V10_CONTROL_5K"
    eligible.sort(
        key=lambda summary: (
            float(summary["maximum_drawdown_abs"]),
            -float(summary["mean_net_annualized_return"]),
            str(summary["candidate_id"]),
        )
    )
    return str(eligible[0]["candidate_id"])


def evaluate_periods(
    periods: Sequence[MarketPeriod],
    contract: Mapping[str, object],
) -> dict[str, object]:
    if contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V12_CONTRACT_SHA_MISMATCH")
    candidates = _candidate_definitions(contract)
    if not periods:
        raise ValueError("NO_V12_DEVELOPMENT_PERIODS")
    validation = contract["development_validation"]
    folds = build_walk_forward_folds(
        [period.decision_session for period in periods],
        minimum_folds=int(validation["minimum_folds"]),
        purge_sessions=int(validation["purge_sessions"]),
    )

    records_by_candidate: dict[str, list[dict[str, object]]] = {}
    summaries = []
    for candidate in candidates:
        records, summary = simulate_candidate(periods, candidate, contract)
        records_by_candidate[candidate.candidate_id] = records
        summaries.append(summary)

    summary_by_id = {
        str(summary["candidate_id"]): summary for summary in summaries
    }
    control_summary = summary_by_id["V10_CONTROL_5K"]
    control_records = records_by_candidate["V10_CONTROL_5K"]
    all_gate_rows = []
    gate_details: dict[str, dict[str, object]] = {
        "V10_CONTROL_5K": {
            "all_gates_passed": True,
            "classification": "CONTROL_NOT_A_CHALLENGER",
        }
    }
    for candidate in candidates[1:]:
        rows, details = gate_candidate(
            candidate_summary=summary_by_id[candidate.candidate_id],
            control_summary=control_summary,
            candidate_records=records_by_candidate[candidate.candidate_id],
            control_records=control_records,
            folds=folds,
            contract=contract,
        )
        all_gate_rows.extend(rows)
        gate_details[candidate.candidate_id] = details

    selected = select_candidate(summaries, gate_details)
    decision = (
        "RETAIN_FROZEN_V10_CONTROL"
        if selected == "V10_CONTROL_5K"
        else "ELIGIBLE_FOR_SEPARATE_V12_FREEZE_AUDIT"
    )
    serializable_folds = [
        {**fold, "test_sessions": list(fold["test_sessions"])} for fold in folds
    ]
    result: dict[str, object] = {
        "status": "V12_PREREGISTERED_DEVELOPMENT_EVIDENCE",
        "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v10_control_candidate": EXPECTED_V10_CANDIDATE,
        "v10_frozen_spec_sha256": EXPECTED_V10_SPEC_SHA256,
        "candidate_ids": [candidate.candidate_id for candidate in candidates],
        "period_count": len(periods),
        "walk_forward_folds": serializable_folds,
        "candidate_summaries": summaries,
        "gate_results": all_gate_rows,
        "gate_details": gate_details,
        "selected_candidate": selected,
        "decision": decision,
        "candidate_frozen": False,
        "fresh_paper_confirmation_activated": False,
        "v10_holdout_outcomes_read": False,
        "v11_fresh_outcomes_read": False,
        "v11_production_journal_read": False,
        "production_data_read": False,
        "paper_trading_only": True,
        "live_trading_enabled": False,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
        "v11_modified": False,
    }
    result["evaluation_sha256"] = _canonical_sha(result)
    return result


def _session_feature_state(
    *,
    session: str,
    previous_session: str,
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    symbols: Sequence[str],
) -> dict[str, bool] | None:
    from ml.v11.intraday_contract import derive_features

    features = {}
    try:
        for symbol in symbols:
            current = grouped[symbol][session]
            previous = grouped[symbol][previous_session]
            features[symbol] = derive_features(
                current[:6], previous_close=float(previous[-1]["close"])
            )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    candidate_symbols = [symbol for symbol in symbols if symbol != "SPY"]
    volatility_limit = _percentile(
        [features[symbol].realized_volatility_30m for symbol in candidate_symbols],
        0.80,
    )
    spy_return = float(features["SPY"].return_15m)
    return {
        symbol: (
            float(features[symbol].return_15m) - spy_return >= 0.0
            and float(features[symbol].volume_acceleration) >= 0.0
            and float(features[symbol].realized_volatility_30m)
            <= volatility_limit
        )
        for symbol in candidate_symbols
    }


def _spy_annualized_volatility(
    sessions: Sequence[str],
    index: int,
    grouped: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
) -> float | None:
    if index < 20:
        return None
    closes = [
        float(grouped["SPY"][session][-1]["close"])
        for session in sessions[index - 20 : index + 1]
    ]
    returns = [right / left - 1.0 for left, right in zip(closes, closes[1:])]
    if len(returns) != 20 or any(not math.isfinite(value) for value in returns):
        return None
    return statistics.pstdev(returns) * math.sqrt(252.0)


def load_development_periods(
    *,
    manifest_path: Path = V11_MANIFEST_PATH,
) -> tuple[dict[str, object], list[MarketPeriod]]:
    """Load only pre-boundary research inputs and build comparable periods."""
    import pandas as pd

    from ml.v10 import cycle3
    from ml.v11.intraday_walk_forward import (
        _group_sessions,
        get_v5_data_symbols,
        load_dataset,
    )

    manifest_preflight = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_v11_manifest_preflight(manifest_preflight)

    manifest, dataset = load_dataset(manifest_path)
    symbols = tuple(get_v5_data_symbols())
    if len(symbols) != 101 or "SPY" not in symbols:
        raise ValueError("V12_REQUIRES_COMPLETE_101_SYMBOL_UNIVERSE")
    grouped = {
        symbol: _group_sessions(dataset[symbol]) for symbol in symbols
    }
    common_sessions = sorted(
        set.intersection(*(set(grouped[symbol]) for symbol in symbols))
    )
    if len(common_sessions) < 31:
        raise ValueError("V12_REQUIRES_AT_LEAST_31_COMMON_INTRADAY_SESSIONS")

    if cycle3.EXPECTED_CONTRACT_SHA256 != V10_CYCLE3_CONTRACT_SHA256:
        raise RuntimeError("V10_CYCLE3_CONTRACT_IDENTITY_CHANGED")
    if EXPECTED_V10_CANDIDATE not in cycle3.CANDIDATES:
        raise RuntimeError("FROZEN_V10_CANDIDATE_DEFINITION_MISSING")
    if not V10_FROZEN_SPEC_LOCK_PATH.exists():
        raise FileNotFoundError("V10_FROZEN_SPEC_LOCK_MISSING")
    if (
        V10_FROZEN_SPEC_LOCK_PATH.read_text(encoding="utf-8").strip()
        != EXPECTED_V10_SPEC_SHA256
    ):
        raise RuntimeError("V10_FROZEN_SPEC_IDENTITY_CHANGED")

    scored = cycle3._build_score_panel()
    scored = scored[scored["candidate_id"] == EXPECTED_V10_CANDIDATE].copy()
    if scored.empty:
        raise ValueError("FROZEN_V10_DEVELOPMENT_RANKINGS_MISSING")
    scored["timestamp_utc"] = pd.to_datetime(scored["timestamp_utc"], utc=True)
    if scored["timestamp_utc"].max().to_pydatetime() >= V10_ORIGINAL_HOLDOUT_START_UTC:
        raise RuntimeError("V10_HOLDOUT_BOUNDARY_VIOLATION")

    rankings: dict[str, tuple[str, ...]] = {}
    regimes: dict[str, str] = {}
    v10_sessions = sorted(scored["timestamp_utc"].drop_duplicates().tolist())
    v10_index_by_session = {
        stamp.date().isoformat(): index for index, stamp in enumerate(v10_sessions)
    }
    for stamp, day in scored.groupby("timestamp_utc", sort=True):
        session = stamp.date().isoformat()
        ranked = day.dropna(subset=["score"]).sort_values(
            ["score", "symbol"], ascending=[False, True]
        )
        symbols_ranked = tuple(ranked["symbol"].astype(str).tolist())
        if len(symbols_ranked) != 100 or len(set(symbols_ranked)) != 100:
            continue
        rankings[session] = symbols_ranked
        regimes[session] = str(ranked["decision_regime"].iloc[0])

    periods: list[MarketPeriod] = []
    for index in range(1, len(common_sessions) - HOLD_SESSIONS - 1):
        decision_session = common_sessions[index]
        if decision_session not in rankings:
            continue
        entry_session = common_sessions[index + 1]
        exit_session = common_sessions[index + 1 + HOLD_SESSIONS]
        decision_utc = datetime.fromisoformat(decision_session).replace(
            tzinfo=timezone.utc
        )
        exit_utc = datetime.fromisoformat(exit_session).replace(tzinfo=timezone.utc)
        if (
            decision_utc >= V10_ORIGINAL_HOLDOUT_START_UTC
            or exit_utc >= V10_ORIGINAL_HOLDOUT_START_UTC
        ):
            continue
        ranked_symbols = rankings[decision_session]
        confirmations = _session_feature_state(
            session=decision_session,
            previous_session=common_sessions[index - 1],
            grouped=grouped,
            symbols=symbols,
        )
        entry_prices = {
            symbol: float(grouped[symbol][entry_session][0]["open"])
            for symbol in ranked_symbols
        }
        exit_prices = {
            symbol: float(grouped[symbol][exit_session][0]["open"])
            for symbol in ranked_symbols
        }
        original_index = v10_index_by_session.get(decision_session)
        if original_index is None:
            continue
        periods.append(
            MarketPeriod(
                decision_session=decision_session,
                entry_session=entry_session,
                exit_session=exit_session,
                decision_index=original_index,
                cohort_offset=original_index % HOLD_SESSIONS,
                decision_regime=regimes[decision_session],
                ranked_symbols=ranked_symbols,
                confirmations=confirmations,
                spy_annualized_volatility_20d=_spy_annualized_volatility(
                    common_sessions, index, grouped
                ),
                entry_prices=entry_prices,
                exit_prices=exit_prices,
                spy_entry_price=float(
                    grouped["SPY"][entry_session][0]["open"]
                ),
                spy_exit_price=float(
                    grouped["SPY"][exit_session][0]["open"]
                ),
            )
        )
    if not periods:
        raise ValueError("NO_COMMON_V10_V11_DEVELOPMENT_PERIODS")
    source = {
        "v11_manifest_sha256": manifest["manifest_sha256"],
        "v11_first_common_session": manifest.get("first_common_session"),
        "v11_last_common_session": manifest.get("last_common_session"),
        "v10_candidate_id": EXPECTED_V10_CANDIDATE,
        "v10_frozen_spec_sha256": EXPECTED_V10_SPEC_SHA256,
        "v10_original_holdout_start_utc": (
            V10_ORIGINAL_HOLDOUT_START_UTC.isoformat()
        ),
        "production_inputs_read": False,
        "holdout_outcomes_read": False,
    }
    return source, periods


def run(
    *,
    manifest_path: Path = V11_MANIFEST_PATH,
    output_path: Path = OUTPUT_PATH,
    write: bool = True,
) -> dict[str, object]:
    contract = load_contract()
    if contract_sha256(contract) != EXPECTED_CONTRACT_SHA256:
        raise RuntimeError("V12_CONTRACT_IDENTITY_CHANGED")
    source, periods = load_development_periods(manifest_path=manifest_path)
    result = evaluate_periods(periods, contract)
    result["source_inputs"] = source
    body = dict(result)
    body.pop("evaluation_sha256", None)
    result["evaluation_sha256"] = _canonical_sha(body)
    result["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    if write:
        _atomic_write(output_path, result)
    return result


def main() -> None:
    print("DATA SHEPHERD V12 SMALL-ACCOUNT DEVELOPMENT EVALUATION")
    print("=" * 84)
    try:
        result = run()
    except Exception as exc:
        print("Status: REJECTED_FAIL_CLOSED")
        print(f"Reason: {type(exc).__name__}: {exc}")
        print("Development result published: NO")
        print("Candidate frozen: NO")
        print("Fresh paper confirmation: DISABLED")
        print("Brokerage orders: OFF")
        raise SystemExit(1)
    print(f"Status: {result['status']}")
    print(f"Common executable periods: {result['period_count']}")
    print(f"Walk-forward folds: {len(result['walk_forward_folds'])}")
    for summary in result["candidate_summaries"]:
        print(
            f"{summary['candidate_id']}: "
            f"terminal=${summary['mean_terminal_wealth']:,.2f} | "
            f"annualized={summary['mean_net_annualized_return']:+.2%} | "
            f"max drawdown={summary['maximum_drawdown']:.2%} | "
            f"trade rate={summary['trade_rate']:.1%}"
        )
    for candidate_id, details in result["gate_details"].items():
        if candidate_id == "V10_CONTROL_5K":
            continue
        print(
            f"{candidate_id}: gates "
            f"{details['gates_passed']}/{details['gates_total']} | "
            f"fold wins={details['fold_win_rate']:.1%}"
        )
    print(f"Decision: {result['decision']}")
    print(f"Selected candidate: {result['selected_candidate']}")
    print(f"Evaluation SHA-256: {result['evaluation_sha256']}")
    print("Candidate frozen: NO")
    print("Fresh paper confirmation: DISABLED")
    print("V10 holdout / V11 fresh outcomes read: NO")
    print("Live trading: DISABLED")
    print("Brokerage orders: OFF")
    print("V8/V10/V11 production modified: NO")


if __name__ == "__main__":
    main()
