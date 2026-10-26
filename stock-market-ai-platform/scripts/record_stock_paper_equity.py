"""Observe local paper valuations for charts; never create trading evidence."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data/observability/stock_paper_equity.sqlite3"
OUTPUT = ROOT / "webapp/static/generated/stock_paper_equity_history.json"
ENDPOINTS = {"v8": "/api/v8/holdout", "v10": "/api/v10/cycle3/accelerated-v2"}


def observation(data, now):
    """Keep observed marks, including their source clock and frozen identity."""
    identity = data.get("frozen_sha256")
    if not isinstance(identity, str) or len(identity) != 64:
        raise ValueError("Missing frozen identity")
    values = [data.get("current_equity"), data.get("current_spy_equity")]
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("Incomplete or invalid equity values")
    if data.get("equity_basis") == "LIVE_MARK_TO_MARKET":
        if int(data.get("priced_open_cohorts", 0)) != int(data.get("open_cohorts", 0)):
            raise ValueError("Incomplete open-cohort valuation")
    row = {
        "timestamp_utc": now.isoformat(),
        "strategy_normalized": values[0],
        "spy_normalized": values[1],
        "frozen_sha256": identity,
        "contract_sha256": data.get("contract_sha256"),
        "valuation_timestamp_utc": data.get("valuation_timestamp_utc"),
        "equity_basis": data.get("equity_basis"),
    }
    signature = {key: value for key, value in row.items() if key != "timestamp_utc"}
    digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    return row, digest


def save(connection, model, data, now):
    row, digest = observation(data, now)
    last = connection.execute(
        "SELECT digest FROM samples WHERE model=? ORDER BY id DESC LIMIT 1", (model,)
    ).fetchone()
    if last and last[0] == digest:
        return False
    connection.execute(
        "INSERT INTO samples(model,epoch,digest,payload) VALUES(?,?,?,?)",
        (model, now.timestamp(), digest, json.dumps(row, separators=(",", ":"))),
    )
    return True


def connect(path):
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("""CREATE TABLE IF NOT EXISTS samples(
        id INTEGER PRIMARY KEY, model TEXT NOT NULL, epoch REAL NOT NULL,
        digest TEXT NOT NULL, payload TEXT NOT NULL)""")
    connection.execute("CREATE INDEX IF NOT EXISTS samples_model ON samples(model,id)")
    return connection


def export(connection, now):
    # Preserve raw observations in SQLite. Thin only the display projection:
    # all observations for 7 days, hourly for a year, daily before that.
    result = {"generated_at_utc": now.isoformat(), "v8": [], "v10": [],
              "basis": "OBSERVED_PAPER_VALUATIONS_NOT_COMPLETED_TRADE_EVIDENCE",
              "sampling": "5-minute checks; unchanged source valuations skipped; older display points thinned"}
    # Model is read explicitly rather than inferred from values or identity.
    for model, payload in connection.execute("""SELECT model,payload FROM samples WHERE id IN (
        SELECT MAX(id) FROM samples GROUP BY model,
        CASE WHEN epoch >= ? THEN id
             WHEN epoch >= ? THEN CAST(epoch/3600 AS INTEGER) + 1000000000
             ELSE CAST(epoch/86400 AS INTEGER) + 2000000000 END
        ) ORDER BY epoch,id""", (now.timestamp()-7*86400, now.timestamp()-365*86400)):
        result[model].append(json.loads(payload))
    return result


def main():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    with connect(DATABASE) as connection:
        for model, endpoint in ENDPOINTS.items():
            try:
                with urlopen("http://127.0.0.1:5001" + endpoint, timeout=15) as response:
                    data = json.load(response)
                now = datetime.now(timezone.utc)
                added = save(connection, model, data, now)
                curve = data.get("operational_curve" if model == "v10" else "curve") or []
                dates = [str(row.get("timestamp_utc")) for row in curve if row.get("timestamp_utc")]
                print(model, "saved" if added else "unchanged", "completed curve points:", len(curve),
                      "first:", min(dates) if dates else None, "last:", max(dates) if dates else None, flush=True)
            except Exception as exc:
                errors.append(model + ":" + type(exc).__name__)
                print("Observation failed:", errors[-1], flush=True)
        payload = export(connection, datetime.now(timezone.utc))
        payload["collection_errors"] = errors
        temporary = OUTPUT.with_suffix(".json.tmp")
        with temporary.open("w") as handle:
            json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(OUTPUT)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
