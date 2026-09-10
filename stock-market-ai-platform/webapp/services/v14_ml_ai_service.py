"""Lightweight read-only dashboard service for the V14 ML/AI candidate."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time


ROOT = Path("data/model/v14/logistic_forward")
STATUS_PATH = ROOT / "status.json"
REFRESH_STATUS_PATH = ROOT / "refresh_status.json"
JOURNAL_PATH = ROOT / "journal.jsonl"
CONTRACT_PATH = Path("ml/v14/logistic_forward_contract.json")
LIVE_QUOTES_PATH = Path("data/live/latest_quotes.json")
ROLLING_QUOTES_PATHS = (
    Path("data/live/iex_24h_5m_v5.json"),
    Path("data/live/iex_24h_5m.json"),
    Path("data/live/iex_24h_5m_legacy.json"),
)
STARTING_EQUITY = 100000.0
HOLDING_SLEEVES = 5
_CACHE_TTL_SECONDS = 10.0
_cache = {"signature": None, "expires_at": 0.0, "payload": None}


def _signature(path: Path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_events() -> tuple[list[dict[str, object]], str | None]:
    if not JOURNAL_PATH.exists():
        return [], None
    events: list[dict[str, object]] = []
    for line_number, raw in enumerate(
        JOURNAL_PATH.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return [], f"JOURNAL_CORRUPT_LINE_{line_number}"
        if not isinstance(event, dict):
            return [], f"JOURNAL_EVENT_INVALID_LINE_{line_number}"
        events.append(event)
    return events, None


def _number(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _positive(value):
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _cohort(event: dict[str, object]) -> int:
    try:
        return int(event.get("cohort_offset", -1))
    except (TypeError, ValueError):
        return -1


def _identity(event: dict[str, object]):
    return event.get("decision_timestamp_utc"), _cohort(event)


def _latest_market_marks(required_symbols: set[str]):
    marks: dict[str, dict[str, object]] = {}

    def consider(symbol, price, timestamp, source):
        symbol = str(symbol or "").upper().strip()
        if symbol not in required_symbols:
            return
        price = _positive(price)
        parsed = _timestamp(timestamp)
        if price is None or parsed is None:
            return
        prior = marks.get(symbol)
        if prior is None or parsed > prior["timestamp"]:
            marks[symbol] = {
                "price": price,
                "timestamp": parsed,
                "timestamp_utc": parsed.isoformat(),
                "source": source,
            }

    live = _read_json(LIVE_QUOTES_PATH)
    for symbol, quote in (live.get("quotes") or {}).items():
        if isinstance(quote, dict):
            consider(
                symbol,
                quote.get("reference_price"),
                quote.get("timestamp")
                or quote.get("received_at")
                or live.get("updated_at"),
                "TIINGO_IEX_LIVE_CACHE",
            )
    for path in ROLLING_QUOTES_PATHS:
        if required_symbols.issubset(marks):
            break
        payload = _read_json(path)
        for symbol, rows in (payload.get("series") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in reversed(rows):
                if isinstance(row, dict):
                    consider(
                        symbol,
                        row.get("price"),
                        row.get("t")
                        or row.get("timestamp")
                        or payload.get("updated_at"),
                        "TIINGO_IEX_ROLLING_CACHE",
                    )
                    if symbol.upper() in marks:
                        break
    return marks


def _rankings(latest_decision: dict[str, object] | None):
    if not latest_decision:
        return []
    recorded = latest_decision.get("ranked_predictions")
    if isinstance(recorded, list) and recorded:
        rows = []
        for item in recorded:
            if not isinstance(item, dict):
                continue
            probability = _number(item.get("predicted_probability"))
            if probability is None:
                continue
            rows.append(
                {
                    "rank": int(item.get("rank") or len(rows) + 1),
                    "symbol": str(item.get("symbol") or "").upper(),
                    "predicted_probability": probability,
                    "selected_top10": bool(item.get("selected_top10")),
                }
            )
        return sorted(rows, key=lambda row: row["rank"])
    probabilities = latest_decision.get("predicted_probabilities") or {}
    ordered = sorted(
        (
            (str(symbol).upper(), _number(probability))
            for symbol, probability in probabilities.items()
        ),
        key=lambda item: (-(item[1] or 0.0), item[0]),
    )
    return [
        {
            "rank": index,
            "symbol": symbol,
            "predicted_probability": probability,
            "selected_top10": True,
        }
        for index, (symbol, probability) in enumerate(ordered, 1)
        if probability is not None
    ]


def _coefficients(latest_decision: dict[str, object] | None):
    snapshot = (latest_decision or {}).get("model_snapshot") or {}
    features = snapshot.get("feature_columns") or []
    weights = snapshot.get("weights") or []
    means = snapshot.get("feature_mean") or []
    standard_deviations = snapshot.get("feature_std") or []
    rows = []
    for index, feature in enumerate(features):
        weight = _number(weights[index] if index < len(weights) else None)
        if weight is None:
            continue
        rows.append(
            {
                "feature": str(feature),
                "coefficient": weight,
                "absolute_coefficient": abs(weight),
                "odds_multiplier_per_standard_deviation": math.exp(
                    max(-20.0, min(20.0, weight))
                ),
                "direction": "POSITIVE" if weight >= 0 else "NEGATIVE",
                "training_mean": _number(
                    means[index] if index < len(means) else None
                ),
                "training_std": _number(
                    standard_deviations[index]
                    if index < len(standard_deviations)
                    else None
                ),
            }
        )
    return sorted(rows, key=lambda row: row["absolute_coefficient"], reverse=True)


def _performance(entries, exits):
    wealth = {
        cohort: {"v14": 1.0, "spy": 1.0, "started": False}
        for cohort in range(HOLDING_SLEEVES)
    }
    curve = []
    relative_returns = []
    for event in sorted(exits, key=lambda row: str(row.get("exit_timestamp_utc") or "")):
        cohort = _cohort(event)
        value = wealth.get(cohort)
        net_return = _number(event.get("net_portfolio_return"))
        if value is None or net_return is None:
            continue
        value["v14"] *= 1.0 + net_return
        spy_return = _number(event.get("spy_return"))
        if spy_return is not None:
            value["spy"] *= 1.0 + spy_return
            relative_returns.append(net_return - spy_return)
        value["started"] = True
        active = [item for item in wealth.values() if item["started"]]
        curve.append(
            {
                "timestamp_utc": event.get("exit_timestamp_utc"),
                "event": "COMPLETED_EXIT",
                "cohort_offset": cohort,
                "v14_normalized": STARTING_EQUITY
                * statistics.fmean(item["v14"] for item in active),
                "spy_normalized": (
                    STARTING_EQUITY
                    * statistics.fmean(item["spy"] for item in active)
                    if spy_return is not None
                    else None
                ),
            }
        )

    exited = {_identity(event) for event in exits}
    open_by_cohort = {}
    for entry in sorted(entries, key=lambda row: str(row.get("entry_timestamp_utc") or "")):
        if _identity(entry) not in exited:
            open_by_cohort[_cohort(entry)] = entry
    required = {"SPY"}
    for entry in open_by_cohort.values():
        required.update(str(symbol).upper() for symbol in (entry.get("symbols") or []))
    marks = _latest_market_marks(required) if open_by_cohort else {}
    open_positions = []
    priced_open_cohorts = 0
    valuation_timestamps = []
    for cohort, entry in sorted(open_by_cohort.items()):
        if cohort not in wealth:
            continue
        symbols = [str(symbol).upper() for symbol in (entry.get("symbols") or [])]
        entry_prices = entry.get("entry_prices") or {}
        returns = []
        for symbol in symbols:
            entry_price = _positive(entry_prices.get(symbol))
            mark = marks.get(symbol)
            current_return = (
                mark["price"] / entry_price - 1.0
                if entry_price is not None and mark is not None
                else None
            )
            if current_return is not None:
                returns.append(current_return)
                valuation_timestamps.append(mark["timestamp"])
            open_positions.append(
                {
                    "cohort_offset": cohort,
                    "decision_timestamp_utc": entry.get("decision_timestamp_utc"),
                    "entry_timestamp_utc": entry.get("entry_timestamp_utc"),
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "current_price": mark.get("price") if mark else None,
                    "current_return": current_return,
                    "mark_timestamp_utc": mark.get("timestamp_utc") if mark else None,
                    "mark_source": mark.get("source") if mark else None,
                }
            )
        if symbols and len(returns) == len(symbols):
            cost = _number(entry.get("modeled_cost_rate"), 0.0)
            wealth[cohort]["v14"] *= 1.0 + statistics.fmean(returns) - cost
            priced_open_cohorts += 1
        spy_entry = _positive(entry.get("spy_entry_price"))
        spy_mark = marks.get("SPY")
        if spy_entry is not None and spy_mark is not None:
            wealth[cohort]["spy"] *= 1.0 + spy_mark["price"] / spy_entry - 1.0
            valuation_timestamps.append(spy_mark["timestamp"])
        wealth[cohort]["started"] = True

    active = [item for item in wealth.values() if item["started"]]
    current_equity = (
        STARTING_EQUITY * statistics.fmean(item["v14"] for item in active)
        if active
        else STARTING_EQUITY
    )
    current_spy_equity = (
        STARTING_EQUITY * statistics.fmean(item["spy"] for item in active)
        if active
        else STARTING_EQUITY
    )
    if open_by_cohort and priced_open_cohorts == len(open_by_cohort):
        equity_basis = "LIVE_MARK_TO_MARKET"
    elif open_by_cohort:
        equity_basis = "PARTIAL_MARK_TO_MARKET"
    elif exits:
        equity_basis = "COMPLETED_EXITS"
    else:
        equity_basis = "WAITING_FOR_FIRST_ENTRY"
    if active and open_by_cohort:
        curve.append(
            {
                "timestamp_utc": (
                    max(valuation_timestamps).isoformat()
                    if valuation_timestamps
                    else curve[-1].get("timestamp_utc") if curve else None
                ),
                "event": "CURRENT_MARK" if open_by_cohort else "LATEST_COMPLETED",
                "v14_normalized": current_equity,
                "spy_normalized": current_spy_equity,
            }
        )

    net_returns = [
        value
        for value in (_number(event.get("net_portfolio_return")) for event in exits)
        if value is not None
    ]
    volatility = statistics.stdev(net_returns) if len(net_returns) >= 2 else None
    sharpe = (
        statistics.fmean(net_returns) / volatility * math.sqrt(252.0 / 5.0)
        if volatility is not None and volatility > 0
        else None
    )
    peak = STARTING_EQUITY
    drawdowns = []
    for point in curve:
        value = _number(point.get("v14_normalized"))
        if value is not None:
            peak = max(peak, value)
            drawdowns.append(value / peak - 1.0)
    counts = [sum(_cohort(event) == cohort for event in exits) for cohort in range(5)]
    complete_blocks = min(counts) if exits else 0
    return {
        "starting_equity": STARTING_EQUITY,
        "current_equity": current_equity,
        "current_spy_equity": current_spy_equity,
        "current_return": current_equity / STARTING_EQUITY - 1.0,
        "current_spy_return": current_spy_equity / STARTING_EQUITY - 1.0,
        "current_excess_return": (current_equity - current_spy_equity)
        / STARTING_EQUITY,
        "equity_basis": equity_basis,
        "open_cohorts": len(open_by_cohort),
        "priced_open_cohorts": priced_open_cohorts,
        "open_positions": open_positions,
        "valuation_timestamp_utc": (
            max(valuation_timestamps).isoformat() if valuation_timestamps else None
        ),
        "curve": curve,
        "completed_return_volatility": volatility,
        "diagnostic_annualized_sharpe": sharpe,
        "max_drawdown": min(drawdowns, default=None),
        "relative_hit_rate": (
            sum(value > 0 for value in relative_returns) / len(relative_returns)
            if relative_returns
            else None
        ),
        "complete_five_sleeve_blocks": complete_blocks,
        "completed_exits_by_cohort": {
            str(cohort): count for cohort, count in enumerate(counts)
        },
        "sleeves_toward_next_block": sum(
            count > complete_blocks for count in counts
        ),
    }


def _event_history(events):
    rows = []
    for event in events:
        event_type = str(event.get("event_type") or "UNKNOWN")
        timestamp = (
            event.get("exit_timestamp_utc")
            or event.get("entry_timestamp_utc")
            or event.get("decision_timestamp_utc")
        )
        rows.append(
            {
                "event_type": event_type,
                "timestamp_utc": timestamp,
                "decision_timestamp_utc": event.get("decision_timestamp_utc"),
                "cohort_offset": event.get("cohort_offset"),
                "symbols": list(event.get("symbols") or []),
                "net_portfolio_return": event.get("net_portfolio_return"),
                "spy_return": event.get("spy_return"),
                "net_relative_return": event.get("net_relative_return"),
                "model_sha256": event.get("model_sha256"),
            }
        )
    return sorted(rows, key=lambda row: str(row.get("timestamp_utc") or ""), reverse=True)[:60]


def get_v14_ml_ai_dashboard():
    signature = tuple(
        _signature(path)
        for path in (
            STATUS_PATH,
            REFRESH_STATUS_PATH,
            JOURNAL_PATH,
            CONTRACT_PATH,
            LIVE_QUOTES_PATH,
            *ROLLING_QUOTES_PATHS,
        )
    )
    now = time.monotonic()
    if (
        _cache["payload"] is not None
        and _cache["signature"] == signature
        and now < _cache["expires_at"]
    ):
        return _cache["payload"]

    status = _read_json(STATUS_PATH)
    refresh = _read_json(REFRESH_STATUS_PATH)
    contract = _read_json(CONTRACT_PATH)
    events, journal_error = _read_events()
    decisions = [event for event in events if event.get("event_type") == "DECISION"]
    entries = [event for event in events if event.get("event_type") == "ENTRY"]
    exits = [event for event in events if event.get("event_type") == "EXIT"]
    decisions.sort(key=lambda row: str(row.get("decision_timestamp_utc") or ""))
    latest_decision = decisions[-1] if decisions else None
    performance = _performance(entries, exits)
    model = contract.get("model") or {}
    portfolio = contract.get("portfolio") or {}
    evaluation = contract.get("evaluation") or {}
    authority = contract.get("authority") or {}

    state = "JOURNAL_ERROR" if journal_error else status.get(
        "status", "WAITING_FOR_PAPER_FORWARD_BOUNDARY"
    )
    if state == "WAITING_FOR_PAPER_FORWARD_BOUNDARY":
        next_event = "FIRST_DECISION_AFTER_SEP_11_MARKET_CLOSE"
    elif len(decisions) > len(entries):
        next_event = "NEXT_SESSION_OPEN_ENTRY"
    elif performance["open_cohorts"]:
        next_event = "FIVE_SESSION_EXIT_OR_NEXT_DECISION"
    else:
        next_event = "NEXT_COMPLETED_SESSION_DECISION"

    rankings = _rankings(latest_decision)
    coefficients = _coefficients(latest_decision)
    payload = {
        "classification": "TRAINED_ML_LOGISTIC_REGRESSION_PAPER_FORWARD",
        "state": state,
        "candidate_id": contract.get("candidate_id")
        or status.get("candidate_id")
        or "v14_logistic_walk_forward_top10",
        "contract_id": contract.get("contract_id"),
        "contract_sha256": status.get("contract_sha256"),
        "paper_forward_start_utc": evaluation.get("paper_forward_start_utc"),
        "model_type": model.get("type"),
        "target": model.get("target"),
        "target_definition": model.get("target_definition"),
        "training_scope": model.get("training_scope"),
        "purge_gap_sessions": model.get("purge_gap_sessions"),
        "online_retraining": evaluation.get("online_retraining") is True,
        "features": list(model.get("features") or []),
        "top_n": portfolio.get("top_n"),
        "holding_sessions": portfolio.get("holding_sessions"),
        "modeled_cost_bps": portfolio.get("cost_bps_per_dollar_traded"),
        "decisions": len(decisions),
        "entries": len(entries),
        "completed_exits": len(exits),
        "latest_decision_session_utc": (
            latest_decision.get("decision_timestamp_utc")
            if latest_decision
            else None
        ),
        "latest_model_sha256": (
            latest_decision.get("model_sha256") if latest_decision else None
        ),
        "training_rows": (
            latest_decision.get("training_rows") if latest_decision else None
        ),
        "training_positive_rate": (
            latest_decision.get("training_positive_rate")
            if latest_decision
            else None
        ),
        "training_start_utc": (
            latest_decision.get("training_start_utc")
            if latest_decision
            else None
        ),
        "training_cutoff_utc": (
            latest_decision.get("training_cutoff_utc")
            if latest_decision
            else None
        ),
        "model_bias": _number(
            ((latest_decision or {}).get("model_snapshot") or {}).get("bias")
        ),
        "rankings": rankings,
        "ranked_universe_count": len(rankings),
        "coefficients": coefficients,
        "event_history": _event_history(events),
        "next_lifecycle_event": next_event,
        "refresh_status": refresh.get("status", "UNKNOWN"),
        "feature_backend": refresh.get("feature_backend")
        or status.get("feature_backend"),
        "feature_timestamp_utc": refresh.get("common_feature_timestamp_utc"),
        "required_symbols": refresh.get("required_symbols", 101),
        "ready_for_collection": refresh.get("ready_for_collection") is True,
        "scheduled_network_requests": refresh.get("scheduled_network_requests", 0),
        "checked_at_utc": status.get("checked_at_utc")
        or refresh.get("checked_at_utc"),
        "journal_error": journal_error,
        "paper_trading_only": authority.get("paper_trading_only", True) is True,
        "brokerage_orders": authority.get("brokerage_orders", False) is True,
        "automatic_promotion": authority.get("automatic_promotion", False) is True,
        "human_review_required": authority.get("human_review_required", True) is True,
        "v8_modified": False,
        "v10_modified": False,
        "runner_invoked": False,
        "scheduler_interval_seconds": 300,
        "method_note": (
            "V14 retrains logistic regression on an expanding historical window "
            "with a five-session purge gap, ranks the frozen 100-stock universe "
            "by learned five-session up probability, and records Top 10 paper "
            "positions using next-open entry, five-session holding, and modeled cost."
        ),
        **performance,
    }
    _cache.update(
        {
            "signature": signature,
            "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
            "payload": payload,
        }
    )
    return payload
