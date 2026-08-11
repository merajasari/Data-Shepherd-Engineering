"""Coinbase Exchange public REST adapter with bounded candle pagination."""

import json
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ml.crypto_v1.config import SUPPORTED_GRANULARITIES
from ml.crypto_v1.providers.base import Candle, MarketDataProvider


class CoinbaseExchangeProvider(MarketDataProvider):
    name = "coinbase_exchange"
    base_url = "https://api.exchange.coinbase.com"
    max_candles_per_request = 300

    def __init__(self, timeout_seconds=30, max_retries=4, pause_seconds=0.12):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.pause_seconds = pause_seconds

    def _request_json(self, path, params):
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "crypto-v1-research/1.0"},
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    raise RuntimeError(f"Coinbase HTTP {exc.code} for {path}") from exc
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = min(2 ** attempt, 30)
                time.sleep(delay)
            except URLError as exc:
                if attempt == self.max_retries:
                    raise RuntimeError(f"Coinbase request failed for {path}: {exc.reason}") from exc
                time.sleep(min(2 ** attempt, 30))
        raise AssertionError("retry loop exhausted")

    @staticmethod
    def _utc(value):
        if value.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        return value.astimezone(timezone.utc)

    def get_candles(self, product_id, start, end, granularity):
        if granularity not in SUPPORTED_GRANULARITIES:
            raise ValueError(f"Unsupported granularity: {granularity}")
        start = self._utc(start)
        end = self._utc(end)
        if start >= end:
            raise ValueError("start must be before end")

        seconds = SUPPORTED_GRANULARITIES[granularity]
        # Stay one bucket below Coinbase's 300-point hard limit. Responses may
        # include a boundary candle outside the requested interval.
        chunk = timedelta(seconds=seconds * (self.max_candles_per_request - 1))
        by_timestamp = {}
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + chunk, end)
            rows = self._request_json(
                f"/products/{product_id}/candles",
                {
                    "start": cursor.isoformat().replace("+00:00", "Z"),
                    "end": chunk_end.isoformat().replace("+00:00", "Z"),
                    "granularity": seconds,
                },
            )
            if not isinstance(rows, list):
                raise RuntimeError("Unexpected Coinbase candle response")
            for row in rows:
                if len(row) != 6:
                    raise RuntimeError("Unexpected Coinbase candle row")
                timestamp = datetime.fromtimestamp(row[0], tz=timezone.utc)
                if start <= timestamp < end:
                    by_timestamp[timestamp] = Candle(
                        timestamp, float(row[3]), float(row[2]), float(row[1]),
                        float(row[4]), float(row[5]),
                    )
            cursor = chunk_end
            if cursor < end and self.pause_seconds:
                time.sleep(self.pause_seconds)
        return [by_timestamp[key] for key in sorted(by_timestamp)]
