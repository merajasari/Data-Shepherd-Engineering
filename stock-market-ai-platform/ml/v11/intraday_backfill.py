"""Bounded historical five-minute backfill for V11 research.

Data is written under an isolated run directory. A manifest is published only
after every one of the 100 candidates plus SPY returns valid regular-session
OHLCV data. Partial downloads never become an eligible research dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
INGESTION_ROOT = ROOT / "data-ingestion"
if str(INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(INGESTION_ROOT))
from v5_symbols import get_v5_data_symbols  # noqa: E402

load_dotenv(ROOT / ".env")
NEW_YORK = ZoneInfo("America/New_York")
BASE_ROOT = ROOT / "data/research/v11/intraday/backfills"
COLUMNS = "open,high,low,close,volume"


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _atomic_json_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    if days < 1 or end < start:
        raise ValueError("Invalid historical backfill range")
    result = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=days - 1))
        result.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return result


def normalize_historical_rows(
    symbol: str,
    payload: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    deduplicated: dict[str, dict[str, object]] = {}
    for item in payload:
        timestamp = item.get("date")
        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
            parsed = parsed.astimezone(timezone.utc)
            local = parsed.astimezone(NEW_YORK)
            values = [float(item[name]) for name in ("open", "high", "low", "close")]
            volume = float(item["volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if local.weekday() >= 5 or not (time(9, 30) <= local.time() < time(16, 0)):
            continue
        if (
            any(value <= 0 or not math.isfinite(value) for value in values)
            or volume < 0
            or not math.isfinite(volume)
            or values[1] < max(values[0], values[3])
            or values[2] > min(values[0], values[3])
        ):
            continue
        key = parsed.isoformat()
        deduplicated[key] = {
            "symbol": symbol.upper(),
            "timestamp_utc": key,
            "open": values[0],
            "high": values[1],
            "low": values[2],
            "close": values[3],
            "volume": volume,
        }
    return [deduplicated[key] for key in sorted(deduplicated)]


class TiingoHistoricalIntradayClient:
    def __init__(self, token: str | None = None, *, timeout_seconds: int = 60):
        self._token = (token or os.getenv("TIINGO_API_KEY") or "").strip()
        self.timeout_seconds = timeout_seconds
        if not self._token:
            raise ValueError("TIINGO_API_KEY is required")

    def fetch(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        try:
            response = requests.get(
                f"https://api.tiingo.com/iex/{symbol}/prices",
                headers={"Authorization": f"Token {self._token}"},
                params={
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "resampleFreq": "5min",
                    "columns": COLUMNS,
                    "format": "json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(
                f"Tiingo V11 backfill failed for {symbol}: "
                f"{type(exc).__name__}; endpoint credentials redacted"
            ) from None
        if not isinstance(payload, list):
            raise RuntimeError(f"Tiingo V11 backfill response invalid for {symbol}")
        return normalize_historical_rows(symbol, payload)


def run_backfill(
    *,
    start_date: date,
    end_date: date,
    client: object,
    output_root: Path = BASE_ROOT,
    symbols: Sequence[str] | None = None,
    chunk_days: int = 30,
) -> dict[str, object]:
    universe = tuple(symbols or get_v5_data_symbols())
    if len(universe) != 101 or len(set(universe)) != 101 or "SPY" not in universe:
        raise ValueError("UNIVERSE_CONTRACT_VIOLATION")
    run_id = f"{start_date.isoformat()}_{end_date.isoformat()}"
    final_root = output_root / run_id
    staging_root = output_root / f".{run_id}.staging"
    staging_root.mkdir(parents=True, exist_ok=True)

    symbol_metadata: dict[str, dict[str, object]] = {}
    failures: list[str] = []
    for symbol in universe:
        merged: dict[str, dict[str, object]] = {}
        try:
            for chunk_start, chunk_end in _chunks(start_date, end_date, chunk_days):
                for row in client.fetch(symbol, chunk_start, chunk_end):
                    merged[str(row["timestamp_utc"])] = row
        except Exception:
            failures.append(f"FETCH_FAILED:{symbol}")
            continue
        rows = [merged[key] for key in sorted(merged)]
        if not rows:
            failures.append(f"NO_VALID_ROWS:{symbol}")
            continue
        path = staging_root / f"{symbol}.json"
        _atomic_json_write(path, rows)
        sessions = sorted(
            {
                datetime.fromisoformat(str(row["timestamp_utc"])).astimezone(NEW_YORK).date().isoformat()
                for row in rows
            }
        )
        symbol_metadata[symbol] = {
            "rows": len(rows),
            "sessions": len(sessions),
            "first_timestamp_utc": rows[0]["timestamp_utc"],
            "last_timestamp_utc": rows[-1]["timestamp_utc"],
            "sha256": _canonical_sha(rows),
            "file": path.name,
        }

    if failures or len(symbol_metadata) != 101:
        return {
            "status": "INCOMPLETE_NOT_PUBLISHED",
            "published": False,
            "symbols_ready": len(symbol_metadata),
            "required_symbols": 101,
            "failures": failures,
            "staging_root": str(staging_root),
            "brokerage_orders": False,
            "v8_modified": False,
            "v10_modified": False,
        }

    common_sessions: set[str] | None = None
    for symbol in universe:
        rows = json.loads((staging_root / f"{symbol}.json").read_text())
        sessions = {
            datetime.fromisoformat(str(row["timestamp_utc"])).astimezone(NEW_YORK).date().isoformat()
            for row in rows
        }
        common_sessions = sessions if common_sessions is None else common_sessions & sessions
    if not common_sessions:
        return {
            "status": "NO_COMMON_SESSIONS_NOT_PUBLISHED",
            "published": False,
            "symbols_ready": 101,
            "required_symbols": 101,
            "failures": ["NO_COMMON_SESSIONS"],
            "staging_root": str(staging_root),
            "brokerage_orders": False,
            "v8_modified": False,
            "v10_modified": False,
        }

    if final_root.exists():
        raise FileExistsError(f"Backfill run already exists: {final_root}")
    staging_root.replace(final_root)
    for metadata in symbol_metadata.values():
        metadata["file"] = str(Path(run_id) / str(metadata["file"]))
    manifest: dict[str, object] = {
        "contract_id": "V11_INTRADAY_HISTORICAL_RESEARCH_V1",
        "status": "COMPLETE_HISTORICAL_RESEARCH_DATASET",
        "published": True,
        "source": "tiingo_iex_historical_5min",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "bar_interval_minutes": 5,
        "symbol_count": 101,
        "symbols": list(universe),
        "common_session_count": len(common_sessions),
        "first_common_session": min(common_sessions),
        "last_common_session": max(common_sessions),
        "symbol_metadata": symbol_metadata,
        "paper_trading_only": True,
        "brokerage_orders": False,
        "v8_modified": False,
        "v10_modified": False,
    }
    manifest["manifest_sha256"] = _canonical_sha(manifest)
    _atomic_json_write(final_root / "manifest.json", manifest)
    _atomic_json_write(output_root / "latest_complete_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--chunk-days", type=int, default=30)
    args = parser.parse_args()
    end = date.fromisoformat(args.end_date) if args.end_date else datetime.now(NEW_YORK).date()
    if args.lookback_days < 1:
        raise SystemExit("--lookback-days must be at least 1")
    start = (
        date.fromisoformat(args.start_date)
        if args.start_date
        else end - timedelta(days=args.lookback_days - 1)
    )
    print("V11 HISTORICAL FIVE-MINUTE RESEARCH BACKFILL")
    print("=" * 80)
    result = run_backfill(
        start_date=start,
        end_date=end,
        client=TiingoHistoricalIntradayClient(),
        chunk_days=args.chunk_days,
    )
    print(f"Status: {result['status']}")
    print(f"Published: {result['published']}")
    print(f"Symbols ready: {result.get('symbol_count', result.get('symbols_ready'))}/101")
    if result.get("common_session_count") is not None:
        print(f"Common sessions: {result['common_session_count']}")
        print(f"Window: {result['first_common_session']} -> {result['last_common_session']}")
        print(f"Manifest SHA-256: {result['manifest_sha256']}")
    for failure in result.get("failures", [])[:20]:
        print(f" - {failure}")
    print("Paper trading only: YES")
    print("Brokerage orders: OFF")
    print("V8/V10 production modified: NO")
    if not result["published"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
