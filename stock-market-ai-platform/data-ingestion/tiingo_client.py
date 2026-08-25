"""
Tiingo historical market data client.

Converts Tiingo end-of-day prices into the canonical
Bronze schema used by the Stock Market AI Platform.
"""

import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(
    PROJECT_ROOT / ".env"
)


class TiingoClient:

    def __init__(self):

        self.api_key = os.getenv(
            "TIINGO_API_KEY"
        )

        if not self.api_key:
            raise ValueError(
                "TIINGO_API_KEY environment variable is required"
            )

    @staticmethod
    def _timestamp_ms(date_value: str) -> int:
        """Convert Tiingo ISO date into Unix milliseconds."""

        dt = datetime.fromisoformat(
            date_value.replace(
                "Z",
                "+00:00",
            )
        )

        return int(
            dt.timestamp() * 1000
        )

    def get_daily_prices(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:

        url = (
            "https://api.tiingo.com/"
            f"tiingo/daily/{symbol}/prices"
        )

        params = {
            "startDate": start_date,
            "endDate": end_date,
            "format": "json",
            "token": self.api_key,
        }

        try:
            response = requests.get(
                url,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            # Requests includes the fully prepared URL in its exception text.
            # Tiingo authenticates with a query parameter, so propagating that
            # exception would write the API token into scheduler logs.
            raise RuntimeError(
                f"Tiingo request failed for {symbol} "
                f"({start_date} through {end_date}): "
                f"{type(exc).__name__}; endpoint credentials redacted"
            ) from None

        rows = []

        for item in payload:

            rows.append(
                {
                    "symbol": symbol,
                    "timestamp":
                        self._timestamp_ms(
                            item["date"]
                        ),
                    "open": item["adjOpen"],
                    "high": item["adjHigh"],
                    "low": item["adjLow"],
                    "close": item["adjClose"],
                    "volume": item["adjVolume"],
                    "vwap": None,
                }
            )

        return pd.DataFrame(
            rows
        )
