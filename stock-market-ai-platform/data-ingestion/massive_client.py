"""
Massive market data API client wrapper.
"""

import os

import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


class MassiveClient:

    def __init__(self):

        self.api_key = os.getenv("MASSIVE_API_KEY")

        if not self.api_key:
            raise ValueError(
                "MASSIVE_API_KEY environment variable is required"
            )

    def get_daily_prices(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ):

        url = (
            f"https://api.massive.com/v2/aggs/ticker/{symbol}/range/"
            f"1/day/{start_date}/{end_date}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        payload = response.json()

        rows = []

        for item in payload.get("results", []):

            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": item["t"],
                    "open": item["o"],
                    "high": item["h"],
                    "low": item["l"],
                    "close": item["c"],
                    "volume": item["v"],
                    "vwap": item.get("vw"),
                }
            )

        df = pd.DataFrame(rows)

        return df
