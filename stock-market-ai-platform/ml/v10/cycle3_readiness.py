"""Read-only readiness audit for the frozen V10 Cycle 3 holdout."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

import pandas as pd

from ml.v10.cycle3_holdout_runner import (
    EXPECTED_SHA,
    HOLDOUT_START,
    JOURNAL_PATH,
    STATUS_PATH as HOLDOUT_STATUS_PATH,
    _load_market,
    _rank_for_date,
    _verify_freeze,
)

OUTPUT_ROOT = Path("data/model/v10/cycle3/readiness")
STATUS_PATH = OUTPUT_ROOT / "status.json"


def _file_sha(path):
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def run_readiness():
    journal_before = _file_sha(JOURNAL_PATH)
    holdout_status_before = _file_sha(HOLDOUT_STATUS_PATH)
    failures = []
    checks = {}
    ranking = None

    try:
        _verify_freeze()
        checks["frozen_contract_verified"] = True
        symbols, frames, dates, date_to_idx = _load_market()
        checks["universe_size"] = len(symbols)
        checks["spy_calendar_sessions"] = len(dates)

        common_latest = min(
            frame.index[frame["close"].notna()].max()
            for frame in frames.values()
        )
        ranking = _rank_for_date(
            common_latest, symbols, frames, dates, date_to_idx
        )
        checks["ranking_timestamp_utc"] = common_latest.isoformat()
        checks["ranking_eligible_count"] = len(ranking)
        checks["defensive_active"] = bool(
            ranking["defensive_active"].iloc[0]
        )
        checks["ranking_top10"] = ranking.head(10)["symbol"].tolist()

        if len(symbols) != 100:
            failures.append(f"expected 100 stocks, found {len(symbols)}")
        if len(ranking) < 80:
            failures.append(f"only {len(ranking)} eligible names")
        if common_latest >= HOLDOUT_START:
            failures.append(
                "feature data has reached the fresh holdout boundary; "
                "use the protected runner, not development readiness"
            )
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}")

    journal_after = _file_sha(JOURNAL_PATH)
    holdout_status_after = _file_sha(HOLDOUT_STATUS_PATH)
    if journal_after != journal_before:
        failures.append("production Cycle 3 journal changed during readiness")
    if holdout_status_after != holdout_status_before:
        failures.append("production Cycle 3 status changed during readiness")

    payload = {
        "status": "READY" if not failures else "NOT_READY",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "holdout_start_utc": HOLDOUT_START.isoformat(),
        "frozen_sha256": EXPECTED_SHA,
        "checks": checks,
        "failures": failures,
        "production_journal_unchanged": journal_after == journal_before,
        "production_status_unchanged": holdout_status_after == holdout_status_before,
        "holdout_outcomes_read": False,
        "holdout_scored": False,
        "v8_modified": False,
        "production_modified": False,
        "brokerage_orders": False,
    }
    _atomic_write(STATUS_PATH, payload)
    return payload


def main():
    result = run_readiness()
    print("V10 CYCLE 3 HOLDOUT READINESS")
    print("=" * 88)
    print(f"Status: {result['status']}")
    print(f"Boundary: {result['holdout_start_utc']}")
    print(f"Frozen SHA: {result['frozen_sha256']}")
    checks = result.get("checks", {})
    if checks:
        print(f"Universe: {checks.get('universe_size')}/100 stocks + SPY")
        print(f"Ranking timestamp: {checks.get('ranking_timestamp_utc')}")
        print(f"Eligible names: {checks.get('ranking_eligible_count')}")
        print(f"Defensive active: {checks.get('defensive_active')}")
        if checks.get("ranking_top10"):
            print("Top 10 rehearsal: " + ", ".join(checks["ranking_top10"]))
    if result["failures"]:
        print("Failures:")
        for failure in result["failures"]:
            print(f"  - {failure}")
    print(
        "Production journal/status unchanged: "
        f"{result['production_journal_unchanged']}/"
        f"{result['production_status_unchanged']}"
    )
    print("Holdout outcomes read/scored: NO")
    print("V8/production modified: NO | brokerage orders: OFF")
    raise SystemExit(0 if result["status"] == "READY" else 2)


if __name__ == "__main__":
    main()
