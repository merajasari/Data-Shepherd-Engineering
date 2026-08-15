"""Keep the Stock V5 data layers current without model fitting.

The Mac runtime may invoke this module every five minutes. A persistent rolling
request ledger limits Tiingo REST usage across invocations, so a startup catch-up
can use the currently available hourly budget immediately and later invocations
resume only as older requests fall out of the rolling window.

If all 101 V5 data symbols are current, Silver, Gold, and feature datasets are
rebuilt only when they are behind the completed EOD target.  Once features are
current, the frozen V5 production inference artifact is refreshed as well.

This module does not fit models, tune parameters, build research targets, place
orders, or evaluate the future holdout.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INGESTION = PROJECT_ROOT / "data-ingestion"
sys.path.insert(0, str(DATA_INGESTION))

from tiingo_client import TiingoClient  # noqa: E402
from tiingo_v5_incremental import DEFAULT_MAX_REQUESTS, run_incremental_refresh  # noqa: E402
from v5_symbols import get_v5_data_symbols  # noqa: E402


REQUEST_LEDGER_PATH = PROJECT_ROOT / "data/live/v5_tiingo_request_ledger.json"
DEFAULT_HOURLY_REQUEST_LIMIT = 45
REQUEST_WINDOW = timedelta(hours=1)


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _load_request_timestamps(path=REQUEST_LEDGER_PATH):
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    for value in payload.get("request_timestamps_utc", []):
        try:
            out.append(_parse_utc(value))
        except (TypeError, ValueError):
            continue
    return out


def _write_request_timestamps(timestamps, path=REQUEST_LEDGER_PATH, updated_at=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    updated_at = updated_at or _utc_now()
    payload = {
        "request_timestamps_utc": [ts.astimezone(timezone.utc).isoformat() for ts in timestamps],
        "updated_at_utc": updated_at.astimezone(timezone.utc).isoformat(),
    }
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


def _active_request_timestamps(now=None, path=REQUEST_LEDGER_PATH):
    """Return ledger requests active in the rolling window without mutating state."""
    now = now or _utc_now()
    cutoff = now - REQUEST_WINDOW
    return [ts for ts in _load_request_timestamps(path) if cutoff < ts <= now]


def prune_request_ledger(now=None, path=REQUEST_LEDGER_PATH):
    """Persist only requests still inside the rolling one-hour quota window."""
    now = now or _utc_now()
    kept = _active_request_timestamps(now=now, path=path)
    _write_request_timestamps(kept, path, updated_at=now)
    return kept


def available_request_budget(hourly_limit=DEFAULT_HOURLY_REQUEST_LIMIT, now=None, path=REQUEST_LEDGER_PATH):
    if hourly_limit < 1:
        raise ValueError("hourly_limit must be at least 1")
    used = len(_active_request_timestamps(now=now, path=path))
    return max(0, hourly_limit - used), used


def record_request_attempt(now=None, path=REQUEST_LEDGER_PATH):
    """Record a Tiingo REST attempt before it is sent, conservatively counting failures."""
    now = now or _utc_now()
    timestamps = _load_request_timestamps(path)
    timestamps.append(now)
    _write_request_timestamps(timestamps, path, updated_at=now)


class QuotaTrackingTiingoClient:
    """Proxy Tiingo client that persists each REST attempt in the rolling ledger."""

    def __init__(self, client=None, ledger_path=REQUEST_LEDGER_PATH):
        self.client = client or TiingoClient()
        self.ledger_path = ledger_path

    def get_daily_prices(self, symbol, start_date, end_date):
        record_request_attempt(path=self.ledger_path)
        return self.client.get_daily_prices(symbol, start_date, end_date)


def feature_path(symbol):
    return PROJECT_ROOT / f"data/features/stocks/{symbol}/{symbol}_features.parquet"


def feature_latest_timestamp_ms(symbol):
    path = feature_path(symbol)
    if not path.exists() or path.stat().st_size == 0:
        return None
    frame = pd.read_parquet(path, columns=["timestamp_utc"])
    if frame.empty:
        return None
    values = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="coerce").dropna()
    if values.empty:
        return None
    return int(values.max().timestamp() * 1000)


def stale_feature_symbols(target_timestamp):
    out = []
    for symbol in get_v5_data_symbols():
        latest = feature_latest_timestamp_ms(symbol)
        if latest is None or latest < target_timestamp:
            out.append(symbol)
    return out


def run_command(args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DATA_INGESTION)
    print("$ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=PROJECT_ROOT, env=env, check=True)


def rebuild_data_layers():
    python = sys.executable
    run_command([python, "-u", "data-ingestion/silver_pipeline.py"])
    run_command([python, "-u", "data-ingestion/gold_pipeline.py"])
    run_command([python, "-u", "data-ingestion/feature_pipeline.py"])


def refresh_v5_rankings():
    """Refresh the frozen production ranking artifact; never fit or tune."""
    run_command([sys.executable, "-u", "ml/run_v5_inference.py"])


def run_data_refresh(
    hourly_request_limit=DEFAULT_HOURLY_REQUEST_LIMIT,
    max_requests=None,
    ledger_path=REQUEST_LEDGER_PATH,
    client=None,
):
    """Run one quota-aware catch-up cycle using whatever rolling budget is free."""
    available, used = available_request_budget(
        hourly_limit=hourly_request_limit,
        path=ledger_path,
    )

    if max_requests is not None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1 when provided")
        available = min(available, max_requests)

    print("V5 DATA REFRESH")
    print(f"Rolling 60m Tiingo usage before run: {used}/{hourly_request_limit}")
    print(f"Available request budget now: {available}")

    if available < 1:
        prune_request_ledger(path=ledger_path)
        print("No Tiingo REST budget available yet; waiting for the rolling window to free capacity.")
        return "quota_wait"

    tracked_client = QuotaTrackingTiingoClient(client=client, ledger_path=ledger_path)
    state = run_incremental_refresh(max_requests=available, client=tracked_client)

    remaining_budget, used_after = available_request_budget(
        hourly_limit=hourly_request_limit,
        path=ledger_path,
    )
    prune_request_ledger(path=ledger_path)

    print(f"Target EOD session: {state['target_date_utc']}")
    print(f"Tiingo requests used this run: {state['requests_used']}")
    print(f"Rolling 60m Tiingo usage after run: {used_after}/{hourly_request_limit}")
    print(f"Rolling budget still available: {remaining_budget}")
    print(f"Bronze complete: {state['complete']}")

    if not state["complete"]:
        print(
            "Bronze universe is still catching up; the next five-minute invocation "
            "will continue as soon as rolling Tiingo capacity is available."
        )
        return "bronze_partial"

    stale = stale_feature_symbols(state["target_timestamp_ms"])
    if stale:
        print(f"Features behind target for {len(stale)} symbol(s); rebuilding data layers.")
        rebuild_data_layers()
        stale = stale_feature_symbols(state["target_timestamp_ms"])
        if stale:
            raise RuntimeError(
                "Feature refresh did not reach target for: " + ", ".join(stale)
            )
        refresh_v5_rankings()
        return "rebuilt"

    print("Features already match the latest completed EOD session.")
    refresh_v5_rankings()
    return "current"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hourly-request-limit",
        type=int,
        default=DEFAULT_HOURLY_REQUEST_LIMIT,
        help="Maximum Tiingo REST attempts allowed in any rolling 60-minute window.",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help=(
            "Optional per-invocation cap. Normally omit this so startup catch-up can use "
            "all currently available rolling-hour capacity."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    run_data_refresh(
        hourly_request_limit=args.hourly_request_limit,
        max_requests=args.max_requests,
    )


if __name__ == "__main__":
    main()
