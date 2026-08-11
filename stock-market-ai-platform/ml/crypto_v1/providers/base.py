"""Provider-neutral historical market-data contract."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class Candle:
    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_record(self, product_id: str, provider: str, granularity: str):
        record = asdict(self)
        record["timestamp_utc"] = self.timestamp_utc.isoformat()
        return {
            "product_id": product_id,
            "provider": provider,
            "granularity": granularity,
            **record,
        }


class MarketDataProvider(ABC):
    """Interface research code depends on; adapters own API details."""

    name: str

    @abstractmethod
    def get_candles(
        self,
        product_id: str,
        start: datetime,
        end: datetime,
        granularity: str,
    ) -> Iterable[Candle]:
        """Return sorted, deduplicated candles in the half-open range."""
