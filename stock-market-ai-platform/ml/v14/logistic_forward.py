"""Isolated V14 walk-forward logistic-regression paper candidate.

This module is deliberately separate from V8 and V10.  It learns coefficients
from labels that were available before each decision, applies a five-session
purge gap, and records the training cutoff plus model snapshot in every event.
It never places brokerage orders or changes another model's evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.feature_source import (
    feature_dataset_exists,
    get_feature_dataset_path,
    get_feature_root,
)
from ml.v14.logistic_forward_contract import (
    EXPECTED_CANDIDATE_ID,
    canonical_json,
    contract_sha256,
    load_contract,
)

NEW_YORK = ZoneInfo("America/New_York")
ROOT = Path("data/model/v14/logistic_forward")
JOURNAL_PATH = ROOT / "journal.jsonl"
STATUS_PATH = ROOT / "status.json"
V8_UNIVERSE_PANEL = Path("data/model/v8/phase1/orthogonal_signal_panel.parquet")


class LogisticRegression:
    """Small deterministic NumPy binary logistic-regression learner."""

    def __init__(self, *, learning_rate: float, epochs: int, l2: float):
        self.learning_rate = float(learning_rate)
        self.epochs = int(epochs)
        self.l2 = float(l2)
        self.weights: np.ndarray | None = None
        self.bias = 0.0

    @staticmethod
    def sigmoid(values: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(values, -500.0, 500.0)))

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        if X.ndim != 2 or len(X) != len(y) or len(X) == 0:
            raise ValueError("V14_TRAINING_MATRIX_INVALID")
        self.weights = np.zeros(X.shape[1], dtype=float)
        prevalence = float(np.mean(y))
        self.bias = float(np.log(prevalence / (1.0 - prevalence))) if 0.0 < prevalence < 1.0 else 0.0
        for _ in range(self.epochs):
            probabilities = self.sigmoid(X @ self.weights + self.bias)
            error = probabilities - y
            self.weights -= self.learning_rate * ((X.T @ error) / len(X) + self.l2 * self.weights)
            self.bias -= self.learning_rate * float(np.mean(error))

    def predict_probability(self, X: np.ndarray) -> np.ndarray:
        if self.weights is None:
            raise ValueError("V14_MODEL_NOT_FIT")
        return self.sigmoid(X @ self.weights + self.bias)


def _as_utc(value: datetime | pd.Timestamp) -> datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        raise ValueError("V14_NOW_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _timestamp(value: object) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC").normalize()


def _market_open(timestamp: object) -> datetime:
    day = _timestamp(timestamp).date()
    return datetime.combine(day, time(9, 30), tzinfo=NEW_YORK).astimezone(timezone.utc)


def _market_close(timestamp: object) -> datetime:
    day = _timestamp(timestamp).date()
    return datetime.combine(day, time(16, 5), tzinfo=NEW_YORK).astimezone(timezone.utc)


def _feature_files() -> dict[str, Path]:
    root = get_feature_root(project_root=Path("."))
    if not root.is_dir():
        return {}
    output: dict[str, Path] = {}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        symbol = child.name.upper()
        path = get_feature_dataset_path(symbol, project_root=Path("."))
        if feature_dataset_exists(path):
            output[symbol] = path
    return output


def _universe() -> list[str]:
    if not V8_UNIVERSE_PANEL.exists():
        raise FileNotFoundError(f"V14_FIXED_UNIVERSE_MISSING:{V8_UNIVERSE_PANEL}")
    panel = pd.read_parquet(V8_UNIVERSE_PANEL, columns=["symbol"])
    symbols = sorted(set(panel["symbol"].astype(str).str.upper()) - {"SPY"})
    if len(symbols) != 100:
        raise ValueError(f"V14_EXPECTED_100_STOCKS_FOUND_{len(symbols)}")
    return symbols


def _load_symbol_frame(path: Path, features: list[str]) -> pd.DataFrame:
    data = pd.read_parquet(path).copy()
    ts_col = "timestamp_utc" if "timestamp_utc" in data.columns else "timestamp"
    required = {ts_col, "open", "close", "volume", "target_up_5d", *features}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"V14_FEATURE_COLUMNS_MISSING:{path}:{','.join(missing)}")
    data[ts_col] = pd.to_datetime(data[ts_col], utc=True)
    data = data.sort_values(ts_col).drop_duplicates(ts_col, keep="last")
    data = data.rename(columns={ts_col: "timestamp_utc"})
    for column in ["open", "close", "volume", "target_up_5d", *features]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.set_index("timestamp_utc")


def load_market(contract: Mapping[str, object] | None = None):
    contract = load_contract() if contract is None else contract
    features = list(contract["model"]["features"])
    symbols = _universe()
    files = _feature_files()
    missing = sorted(set(symbols + ["SPY"]) - set(files))
    if missing:
        raise FileNotFoundError("V14_MISSING_FEATURE_DATA:" + ",".join(missing))
    frames = {symbol: _load_symbol_frame(files[symbol], features) for symbol in symbols + ["SPY"]}
    dates = sorted(set(frames["SPY"].index[frames["SPY"]["close"].notna()]))
    return symbols, frames, dates, {value: index for index, value in enumerate(dates)}


def _training_rows(
    symbols: list[str],
    frames: Mapping[str, pd.DataFrame],
    features: list[str],
    decision_index: int,
    purge_gap: int,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    if decision_index < purge_gap:
        raise ValueError("V14_INSUFFICIENT_PURGE_HISTORY")
    cutoff = _timestamp(sorted(frames[symbols[0]].index)[0])
    # The cutoff is the last session whose five-session label ends no later
    # than the decision session.  No row from the purge window is admitted.
    all_dates = sorted(set().union(*(set(frames[symbol].index) for symbol in symbols)))
    cutoff = all_dates[decision_index - purge_gap]
    rows: list[pd.DataFrame] = []
    for symbol in symbols:
        frame = frames[symbol].reset_index()
        if "timestamp_utc" not in frame.columns:
            frame = frame.rename(columns={frame.columns[0]: "timestamp_utc"})
        frame = frame[frame["timestamp_utc"] <= cutoff].copy()
        frame["symbol"] = symbol
        rows.append(frame[["timestamp_utc", "symbol", *features, "target_up_5d"]])
    training = pd.concat(rows, ignore_index=True)
    training = training.dropna(subset=[*features, "target_up_5d"])
    finite = np.isfinite(training[features].to_numpy(float)).all(axis=1)
    training = training.loc[finite].copy()
    training["target_up_5d"] = training["target_up_5d"].astype(int)
    return training, _timestamp(cutoff)


def fit_as_of(
    decision_ts: object,
    symbols: list[str],
    frames: Mapping[str, pd.DataFrame],
    dates: list[pd.Timestamp],
    contract: Mapping[str, object],
) -> tuple[LogisticRegression, dict[str, object], pd.DataFrame]:
    model_spec = contract["model"]
    features = list(model_spec["features"])
    decision_index = dates.index(_timestamp(decision_ts))
    training, cutoff = _training_rows(
        symbols, frames, features, decision_index, int(model_spec["purge_gap_sessions"])
    )
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
    current_rows = []
    decision = _timestamp(decision_ts)
    for symbol in symbols:
        frame = frames[symbol]
        if decision not in frame.index:
            continue
        row = frame.loc[decision]
        values = pd.to_numeric(row[features], errors="coerce").to_numpy(float)
        if np.isfinite(values).all():
            current_rows.append({"symbol": symbol, **dict(zip(features, values))})
    current = pd.DataFrame(current_rows)
    if len(current) < int(contract["portfolio"]["top_n"]):
        raise ValueError(f"V14_CURRENT_ELIGIBLE_NAMES_BELOW_TOP_N:{len(current)}")
    probabilities = model.predict_probability((current[features].to_numpy(float) - mean) / std)
    current["predicted_probability"] = probabilities
    current = current.sort_values(["predicted_probability", "symbol"], ascending=[False, True]).reset_index(drop=True)
    snapshot = {
        "feature_columns": features,
        "weights": model.weights.tolist() if model.weights is not None else [],
        "bias": float(model.bias),
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
    }
    model_sha = hashlib.sha256(canonical_json(snapshot)).hexdigest()
    metadata = {
        "model_sha256": model_sha,
        "training_rows": int(len(training)),
        "training_positive_rate": float(y.mean()),
        "training_start_utc": training["timestamp_utc"].min().isoformat(),
        "training_cutoff_utc": cutoff.isoformat(),
        "model_snapshot": snapshot,
    }
    return model, metadata, current


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"V14_JOURNAL_CORRUPT_LINE_{line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"V14_JOURNAL_EVENT_INVALID_LINE_{line_number}")
        events.append(value)
    return events


@contextmanager
def _journal_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _event_key(event: Mapping[str, object]) -> tuple[object, object, object]:
    return event.get("event_type"), event.get("decision_timestamp_utc"), event.get("cohort_offset")


def _append(event: Mapping[str, object], path: Path, lock_path: Path) -> bool:
    with _journal_lock(lock_path):
        events = _read_events(path)
        if _event_key(event) in {_event_key(item) for item in events}:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(event), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True


def _transition_notional(previous: list[str] | None, current: list[str]) -> float:
    if previous is None:
        return 1.0
    weight = 1.0 / len(current)
    old = {symbol: weight for symbol in previous}
    new = {symbol: weight for symbol in current}
    return float(sum(abs(new.get(symbol, 0.0) - old.get(symbol, 0.0)) for symbol in set(old) | set(new)))


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


def _summary(events: list[dict[str, object]], contract: Mapping[str, object]) -> dict[str, object]:
    decisions = [event for event in events if event.get("event_type") == "DECISION"]
    entries = [event for event in events if event.get("event_type") == "ENTRY"]
    exits = [event for event in events if event.get("event_type") == "EXIT"]
    return {
        "decisions": len(decisions),
        "entries": len(entries),
        "completed_exits": len(exits),
        "top_n": int(contract["portfolio"]["top_n"]),
        "holding_sessions": int(contract["portfolio"]["holding_sessions"]),
        "complete_five_sleeve_blocks": min(
            [sum(int(event.get("cohort_offset", -1)) == offset for event in exits) for offset in range(5)]
        ) if exits else 0,
        "paper_trading_only": True,
        "brokerage_orders": False,
    }


def run_once(
    *,
    now_utc: datetime | pd.Timestamp | None = None,
    contract: Mapping[str, object] | None = None,
    journal_path: Path = JOURNAL_PATH,
    status_path: Path = STATUS_PATH,
    load_market_fn: Callable[[Mapping[str, object]], tuple[list[str], Mapping[str, pd.DataFrame], list[pd.Timestamp], Mapping[pd.Timestamp, int]]] | None = None,
) -> dict[str, object]:
    contract = load_contract() if contract is None else contract
    now = _as_utc(now_utc or datetime.now(timezone.utc))
    candidate_sha = contract_sha256(contract)
    start = _timestamp(contract["evaluation"]["paper_forward_start_utc"])
    events = _read_events(journal_path)
    if now < _market_open(start):
        payload = {
            "status": "WAITING_FOR_PAPER_FORWARD_BOUNDARY",
            "checked_at_utc": now.isoformat(),
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "contract_sha256": candidate_sha,
            **_summary(events, contract),
        }
        _atomic_write(status_path, payload)
        return payload

    loader = load_market if load_market_fn is None else load_market_fn
    symbols, frames, dates, date_to_idx = loader(contract)
    dates = sorted(_timestamp(value) for value in dates)
    events = _read_events(journal_path)
    existing = {_event_key(event) for event in events}
    appended = 0
    completed = [value for value in dates if value >= start and _market_close(value) <= now]
    latest_completed = completed[-1] if completed else None
    decision_dates: list[pd.Timestamp] = []
    missed_decision_sessions: list[str] = []
    if latest_completed is not None:
        latest_index = date_to_idx.get(latest_completed)
        next_open = (
            _market_open(dates[latest_index + 1])
            if latest_index is not None and latest_index + 1 < len(dates)
            else None
        )
        if next_open is None or now <= next_open:
            decision_dates = [latest_completed]
        else:
            missed_decision_sessions = [latest_completed.date().isoformat()]
    top_n = int(contract["portfolio"]["top_n"])
    for decision_ts in decision_dates:
        if decision_ts not in date_to_idx:
            continue
        cohort = int(date_to_idx[decision_ts] % len(contract["portfolio"]["cohort_offsets"]))
        key = ("DECISION", decision_ts.isoformat(), cohort)
        if key in existing:
            continue
        try:
            _, metadata, ranked = fit_as_of(decision_ts, symbols, frames, dates, contract)
        except ValueError as exc:
            continue
        picks = ranked.head(top_n)["symbol"].tolist()
        event = {
            "event_type": "DECISION",
            "journal_type": "V14_LOGISTIC_WALK_FORWARD_PAPER_FORWARD",
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "contract_sha256": candidate_sha,
            "decision_timestamp_utc": decision_ts.isoformat(),
            "cohort_offset": cohort,
            "symbols": picks,
            "predicted_probabilities": {row.symbol: float(row.predicted_probability) for row in ranked.head(top_n).itertuples()},
            "ranked_predictions": [
                {
                    "rank": rank,
                    "symbol": row.symbol,
                    "predicted_probability": float(row.predicted_probability),
                    "selected_top10": rank <= top_n,
                }
                for rank, row in enumerate(ranked.itertuples(), 1)
            ],
            **metadata,
            "paper_trading_only": True,
            "brokerage_orders": False,
            "created_at_utc": now.isoformat(),
        }
        appended += int(_append(event, journal_path, journal_path.with_name(journal_path.name + ".lock")))
        existing.add(key)

    events = _read_events(journal_path)
    existing = {_event_key(event) for event in events}
    for decision in [event for event in events if event.get("event_type") == "DECISION"]:
        decision_ts = _timestamp(decision["decision_timestamp_utc"])
        decision_index = date_to_idx.get(decision_ts)
        if decision_index is None or decision_index + 1 >= len(dates):
            continue
        entry_ts = dates[decision_index + 1]
        key = ("ENTRY", decision["decision_timestamp_utc"], decision["cohort_offset"])
        if key in existing or _market_open(entry_ts) > now or entry_ts not in date_to_idx:
            continue
        prices = {}
        if any(symbol not in frames or entry_ts not in frames[symbol].index for symbol in decision["symbols"]):
            continue
        for symbol in decision["symbols"]:
            price = float(frames[symbol].loc[entry_ts, "open"])
            if not np.isfinite(price) or price <= 0:
                break
            prices[symbol] = price
        else:
            spy_entry_price = float(frames["SPY"].loc[entry_ts, "open"])
            if not np.isfinite(spy_entry_price) or spy_entry_price <= 0:
                continue
            previous = None
            prior = [event for event in events if event.get("event_type") == "ENTRY" and event.get("cohort_offset") == decision.get("cohort_offset")]
            if prior:
                prior.sort(key=lambda event: str(event.get("entry_timestamp_utc", "")))
                previous = list(prior[-1].get("symbols", []))
            traded = _transition_notional(previous, decision["symbols"])
            entry = {
                "event_type": "ENTRY",
                "journal_type": "V14_LOGISTIC_WALK_FORWARD_PAPER_FORWARD",
                "candidate_id": EXPECTED_CANDIDATE_ID,
                "contract_sha256": candidate_sha,
                "decision_timestamp_utc": decision["decision_timestamp_utc"],
                "cohort_offset": decision["cohort_offset"],
                "symbols": decision["symbols"],
                "entry_timestamp_utc": entry_ts.isoformat(),
                "entry_prices": prices,
                "spy_entry_price": spy_entry_price,
                "transition_notional": traded,
                "modeled_cost_rate": traded * int(contract["portfolio"]["cost_bps_per_dollar_traded"]) / 10000.0,
                "paper_trading_only": True,
                "brokerage_orders": False,
                "created_at_utc": now.isoformat(),
            }
            appended += int(_append(entry, journal_path, journal_path.with_name(journal_path.name + ".lock")))
            existing.add(key)

    events = _read_events(journal_path)
    existing = {_event_key(event) for event in events}
    holding = int(contract["portfolio"]["holding_sessions"])
    for entry in [event for event in events if event.get("event_type") == "ENTRY"]:
        entry_ts = _timestamp(entry["entry_timestamp_utc"])
        entry_index = date_to_idx.get(entry_ts)
        if entry_index is None or entry_index + holding >= len(dates):
            continue
        exit_ts = dates[entry_index + holding]
        key = ("EXIT", entry["decision_timestamp_utc"], entry["cohort_offset"])
        if key in existing or _market_open(exit_ts) > now:
            continue
        if any(symbol not in frames or exit_ts not in frames[symbol].index for symbol in entry["symbols"]):
            continue
        exit_prices = {
            symbol: float(frames[symbol].loc[exit_ts, "open"])
            for symbol in entry["symbols"]
        }
        returns = {
            symbol: exit_prices[symbol] / float(entry["entry_prices"][symbol]) - 1.0
            for symbol in entry["symbols"]
        }
        gross = float(np.mean(list(returns.values())))
        cost = float(entry.get("modeled_cost_rate", 0.0))
        spy_entry_price = float(entry.get("spy_entry_price", 0.0) or 0.0)
        spy_exit_price = float(frames["SPY"].loc[exit_ts, "open"])
        spy_return = (
            spy_exit_price / spy_entry_price - 1.0
            if spy_entry_price > 0 and np.isfinite(spy_exit_price)
            else None
        )
        exit_event = {
            "event_type": "EXIT",
            "journal_type": "V14_LOGISTIC_WALK_FORWARD_PAPER_FORWARD",
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "contract_sha256": candidate_sha,
            "decision_timestamp_utc": entry["decision_timestamp_utc"],
            "cohort_offset": entry["cohort_offset"],
            "exit_timestamp_utc": exit_ts.isoformat(),
            "exit_prices": exit_prices,
            "symbol_returns": returns,
            "gross_portfolio_return": gross,
            "net_portfolio_return": gross - cost,
            "spy_exit_price": spy_exit_price,
            "spy_return": spy_return,
            "net_relative_return": (
                gross - cost - spy_return if spy_return is not None else None
            ),
            "modeled_cost_rate": cost,
            "paper_trading_only": True,
            "brokerage_orders": False,
            "created_at_utc": now.isoformat(),
        }
        appended += int(_append(exit_event, journal_path, journal_path.with_name(journal_path.name + ".lock")))
        existing.add(key)

    events = _read_events(journal_path)
    summary = _summary(events, contract)
    payload = {
        "status": "COLLECTING_PAPER_FORWARD",
        "checked_at_utc": now.isoformat(),
        "candidate_id": EXPECTED_CANDIDATE_ID,
        "contract_sha256": candidate_sha,
        "feature_backend": os.environ.get("FEATURE_BACKEND", "pandas").strip().lower(),
        "missed_decision_sessions": missed_decision_sessions,
        "appended_this_run": appended,
        **summary,
    }
    latest = sorted(events, key=lambda event: str(event.get("created_at_utc", "")))
    if latest:
        payload["latest_lifecycle_event_type"] = latest[-1].get("event_type")
    latest_decisions = [
        event for event in latest if event.get("event_type") == "DECISION"
    ]
    if latest_decisions:
        payload["latest_model_sha256"] = latest_decisions[-1].get("model_sha256")
    _atomic_write(status_path, payload)
    return payload


def main() -> None:
    result = run_once()
    print("V14 LOGISTIC WALK-FORWARD PAPER CANDIDATE")
    print("=" * 72)
    print(f"Status: {result['status']}")
    print(f"Candidate: {result['candidate_id']}")
    print(f"Decisions / entries / exits: {result['decisions']} / {result['entries']} / {result['completed_exits']}")
    print(f"Feature backend: {result.get('feature_backend', 'not selected')}")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 modified: NO")


if __name__ == "__main__":
    main()
