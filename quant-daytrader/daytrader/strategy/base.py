"""Strategy interface and registry.

To add a strategy, drop a module into `daytrader/strategy/` that defines a
`@register`-decorated subclass of `Strategy` with a `name` and a `Params`
dataclass. It is discovered automatically (no central list to edit).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar

from ..config import StrategyConfig, build_dataclass
from ..models import Bar, Exit, Position, Signal

if TYPE_CHECKING:
    from ..broker.base import Broker

Action = Signal | Exit


class Context:
    """What a strategy may know besides bars: its own open positions and the time."""

    def __init__(self, broker: "Broker", now: datetime):
        self._broker = broker
        self.now = now

    @cached_property
    def positions(self) -> dict[str, Position]:
        return self._broker.positions()

    def position(self, symbol: str) -> Position | None:
        return self.positions.get(symbol)


class Strategy(ABC):
    """Sees completed N-minute bars for all its symbols, in time order.

    Returns entry `Signal`s (sent as bracket orders) and/or `Exit`s (close at market).
    Stops/targets live at the broker; the engine also flattens at `risk.flatten_at`.
    """

    name: ClassVar[str]
    Params: ClassVar[type]

    def __init__(self, params, bar_minutes: int):
        self.p = params
        self.bar_minutes = bar_minutes

    @abstractmethod
    def on_bar(self, bar: Bar, ctx: Context) -> list[Action]: ...

    def mark_traded(self, symbol: str, day: date) -> None:
        """Live start-up: `symbol` already had an entry today (restart safety)."""


REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    if cls.name in REGISTRY:
        raise ValueError(f"duplicate strategy name {cls.name}")
    REGISTRY[cls.name] = cls
    return cls


def build_strategy(cfg: StrategyConfig, bar_minutes: int) -> Strategy:
    from . import load_all

    load_all()
    if cfg.name not in REGISTRY:
        raise ValueError(f"Unknown strategy {cfg.name!r}; available: {sorted(REGISTRY)}")
    cls = REGISTRY[cfg.name]
    return cls(build_dataclass(cls.Params, cfg.params), bar_minutes)
