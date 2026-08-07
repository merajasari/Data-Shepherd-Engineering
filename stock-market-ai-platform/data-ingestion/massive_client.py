"""
Massive market data API client wrapper.

Loads API keys from environment variables.
Returns normalized OHLCV market data.
"""

import os
import pandas as pd
from dotenv import load_dotenv
from massive import RESTClient


load_dotenv()


class MassiveClient:

    def __init__(self):
        self.api_key = os.getenv("MASSIVE_API_KEY")

        if not self.api_key:
            raise ValueError(
                "MASSIVE_API_KEY environment variable is required"
            )

        self.client = RESTClient(api_key=self.api_key)


    def get_daily_prices(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        Retrieve daily OHLCV market data.

        Returns:
            pandas DataFrame
        """

        response = self.client.get_aggs(
            ticker=symbol,
            multiplier=1,
            timespan="day",
            from_=start_date,
            to=end_date,
            limit=50000
        )

        rows = []

        for item in response:
            rows.append(
                {
                    "symbol": symbol,
                    "date": item.timestamp,
                    "open": item.open,
                    "high": item.high,
                    "low": item.low,
                    "close": item.close,
                    "volume": item.volume,
                }
            )

        df = pd.DataFrame(rows)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], unit="ms")
            df = df.sort_values("date")

        return df"""Massive market data API client wrapper.

API keys are loaded from environment variables and should never be committed.
"""

import os
from dotenv import load_dotenv

load_dotenv()

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY")


class MassiveClient:
    def __init__(self):
        if not MASSIVE_API_KEY:
            raise ValueError("MASSIVE_API_KEY environment variable is required")

        self.api_key = MASSIVE_API_KEY

    def get_daily_prices(self, symbol: str, start_date: str, end_date: str):
        """Retrieve daily OHLCV data.

        The API integration layer is intentionally isolated here so future
        changes to providers do not impact downstream analytics.
        """
        # TODO: Add Massive REST client implementation
        # TODO: Return normalized OHLCV dataframe
        return {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "status": "client_ready",
        }
