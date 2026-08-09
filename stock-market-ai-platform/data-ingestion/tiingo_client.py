"""
Tiingo historical market data client.

Converts Tiingo end-of-day prices into the canonical
Bronze schema used by the Stock Market AI Platform.
"""

import os
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()


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

        response = requests.get(
            url,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()

        rows = []

        for item in payload:

            rows.append(
                {
                    "symbol": symbol,
                    "timestamp":
                        self._timestamp_ms(
                            item["date"]
                        ),
                    "open": item["open"],
                    "high": item["high"],
                    "low": item["low"],
                    "close": item["close"],
                    "volume": item["volume"],
                    "vwap": None,
                }
            )

        return pd.DataFrame(
            rows
        )
