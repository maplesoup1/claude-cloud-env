from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Bar, Position, Side


class Broker(ABC):
    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def day_start_equity(self) -> float: ...

    @abstractmethod
    def positions(self) -> dict[str, Position]: ...

    @abstractmethod
    def busy_symbols(self) -> set[str]:
        """Symbols with an open position or a working entry order."""

    @abstractmethod
    def submit_bracket(self, symbol: str, side: Side, qty: int, stop: float, target: float,
                       client_order_id: str) -> bool: ...

    @abstractmethod
    def flatten_all(self, reason: str) -> None:
        """Cancel all working orders and close all positions at market."""

    def can_short(self, symbol: str) -> bool:
        return True

    def on_clock(self, now: datetime) -> None:
        """Simulated brokers roll their trading day here; live brokers ignore it."""

    def on_minute_bar(self, bar: Bar) -> None:
        """Simulated brokers fill orders here; live brokers ignore it."""
