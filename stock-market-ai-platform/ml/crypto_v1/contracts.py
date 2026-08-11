"""Leakage-safe contracts shared by future research and paper simulation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Ranking:
    as_of_utc: datetime
    product_id: str
    predicted_relative_return: float
    rank: int
    eligible_asset_count: int
    model_version: str


class RankingConsumer(Protocol):
    """Boundary implemented later by both backtests and paper simulators."""

    def consume(self, as_of_utc: datetime, rankings: Sequence[Ranking]) -> None:
        ...


PORTFOLIO_CONTRACT = (
    "features use only information known at as_of_utc",
    "apply first-available, history, and trailing-liquidity eligibility",
    "predict forward asset return relative to BTC",
    "rank eligible assets cross-sectionally",
    "select Top 3 or Top 5 and equal-weight without leverage",
    "charge fees, slippage, and turnover; compare with BTC buy-and-hold",
)

VALIDATION_CONTRACT = (
    "chronological walk-forward only",
    "no random split or look-ahead leakage",
    "untouched final holdout",
    "no live or real-money order execution",
)
