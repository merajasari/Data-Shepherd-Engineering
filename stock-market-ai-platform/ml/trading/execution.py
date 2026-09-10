"""Broker-neutral execution types with a permanently disabled default adapter."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


class LiveTradingDisabled(RuntimeError):
    """Raised whenever an order reaches the disabled execution boundary."""


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    idempotency_key: str
    strategy_id: str
    frozen_strategy_sha256: str
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    created_at_utc: datetime
    limit_price: Decimal | None = None

    @property
    def requested_notional(self) -> Decimal | None:
        if self.limit_price is None:
            return None
        return self.quantity * self.limit_price


class BrokerAdapter(ABC):
    """Interface only. Implementations must live outside strategy/model code."""

    @abstractmethod
    def account_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def orders(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        raise NotImplementedError


class DisabledBrokerAdapter(BrokerAdapter):
    """Safe default: exposes no account and refuses every mutation."""

    def account_snapshot(self) -> dict[str, Any]:
        return {"connected": False, "brokerage_orders": False}

    def positions(self) -> list[dict[str, Any]]:
        return []

    def orders(self) -> list[dict[str, Any]]:
        return []

    def submit_order(self, intent: OrderIntent) -> dict[str, Any]:
        raise LiveTradingDisabled(
            f"Live trading is disabled; intent {intent.intent_id} was not submitted"
        )

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        raise LiveTradingDisabled(
            f"No live broker authority; order {broker_order_id} was not canceled"
        )
