"""Streaming indicators. Every update uses only the bar passed in and earlier bars,
so they are safe from look-ahead by construction. Feed them COMPLETED bars only."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import date

from .models import Bar


@dataclass
class SessionStats:
    """Per-symbol regular-session state, fed with completed bars of one symbol."""

    day: date | None = None
    prev_close: float | None = None  # last close of the previous session seen
    open: float | None = None        # open of the first bar of this session
    high: float | None = None
    low: float | None = None
    close: float | None = None
    bars: int = 0
    _v: float = 0.0
    _pv: float = 0.0
    _p2v: float = 0.0

    def update(self, bar: Bar) -> None:
        d = bar.ts.date()
        if d != self.day:
            if self.day is not None:
                self.prev_close = self.close
            self.day, self.open, self.high, self.low = d, bar.open, bar.high, bar.low
            self.bars, self._v, self._pv, self._p2v = 0, 0.0, 0.0, 0.0
        self.high = max(self.high, bar.high)
        self.low = min(self.low, bar.low)
        self.close = bar.close
        self.bars += 1
        tp = (bar.high + bar.low + bar.close) / 3
        v = max(bar.volume, 0.0)
        self._v += v
        self._pv += tp * v
        self._p2v += tp * tp * v

    @property
    def vwap(self) -> float | None:
        return self._pv / self._v if self._v > 0 else None

    @property
    def vwap_std(self) -> float | None:
        """Volume-weighted standard deviation of typical price around VWAP."""
        if self._v <= 0:
            return None
        vw = self._pv / self._v
        return math.sqrt(max(self._p2v / self._v - vw * vw, 0.0))

    @property
    def gap(self) -> float | None:
        if self.prev_close and self.open:
            return self.open / self.prev_close - 1
        return None


class ATR:
    """Wilder ATR over bars (true range uses the previous bar's close, across sessions)."""

    def __init__(self, n: int = 14):
        self.n = n
        self.value: float | None = None
        self._prev_close: float | None = None
        self._seed: list[float] = []

    def update(self, bar: Bar) -> float | None:
        pc = self._prev_close
        tr = bar.high - bar.low if pc is None else max(bar.high - bar.low, abs(bar.high - pc), abs(bar.low - pc))
        self._prev_close = bar.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self.n:
                self.value = sum(self._seed) / self.n
        else:
            self.value = (self.value * (self.n - 1) + tr) / self.n
        return self.value


class RSI:
    """Wilder RSI on closes."""

    def __init__(self, n: int = 14):
        self.n = n
        self.value: float | None = None
        self._prev: float | None = None
        self._gains: list[float] = []
        self._losses: list[float] = []
        self._ag: float | None = None
        self._al: float | None = None

    def update(self, close: float) -> float | None:
        if self._prev is None:
            self._prev = close
            return None
        ch = close - self._prev
        self._prev = close
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if self._ag is None:
            self._gains.append(g)
            self._losses.append(l)
            if len(self._gains) < self.n:
                return None
            self._ag, self._al = sum(self._gains) / self.n, sum(self._losses) / self.n
        else:
            self._ag = (self._ag * (self.n - 1) + g) / self.n
            self._al = (self._al * (self.n - 1) + l) / self.n
        self.value = 100.0 if self._al == 0 else 100 - 100 / (1 + self._ag / self._al)
        return self.value


class EMA:
    def __init__(self, n: int):
        self.k = 2 / (n + 1)
        self.value: float | None = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        return self.value


class RollingMean:
    def __init__(self, n: int):
        self.q: deque[float] = deque(maxlen=n)

    def update(self, x: float) -> None:
        self.q.append(x)

    def mean(self, min_count: int = 1) -> float | None:
        return sum(self.q) / len(self.q) if len(self.q) >= max(1, min_count) else None
