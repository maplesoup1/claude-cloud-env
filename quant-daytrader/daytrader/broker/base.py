from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import Bar, Position, Side


class Broker(ABC):
    """One broker instance per strategy instance. Everything is scoped to that
    strategy's symbols, so strategies sharing an account never touch each other."""

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
    def close_position(self, symbol: str, reason: str) -> None:
        """Cancel the symbol's working orders and close its position at market."""

    @abstractmethod
    def flatten_all(self, reason: str) -> None:
        """close_position for every symbol this broker trades."""

    def can_short(self, symbol: str) -> bool:
        return True

    def on_clock(self, now: datetime) -> None:
        """Simulated brokers roll their trading day here; live brokers ignore it."""

    def on_minute_bar(self, bar: Bar) -> None:
        """Simulated brokers fill orders here; live brokers ignore it."""
