"""Massive market data API client wrapper.

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
