"""Core data types shared by backtest and live trading."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class Bar:
    """An OHLCV bar. `ts` is the bar START time, tz-aware in America/New_York."""

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Side
    entry_ref: float  # reference price (close of the signal bar)
    stop: float
    target: float
    ts: datetime  # start time of the signal bar
    tag: str = ""


@dataclass
class Position:
    symbol: str
    side: Side
    qty: int
    entry_price: float
    stop: float | None = None
    target: float | None = None
    opened_at: datetime | None = None


def is_regular_hours(ts: datetime) -> bool:
    t = ts.astimezone(NY).time()
    return MARKET_OPEN <= t < MARKET_CLOSE
