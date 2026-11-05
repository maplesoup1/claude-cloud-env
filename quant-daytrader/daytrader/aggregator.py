"""Aggregate 1-minute bars into N-minute bars. Same code path in backtest and live."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Bar


@dataclass
class _Bucket:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_bar(self, symbol: str) -> Bar:
        return Bar(symbol, self.start, self.open, self.high, self.low, self.close, self.volume)


class BarAggregator:
    def __init__(self, minutes: int):
        if 60 % minutes:
            raise ValueError("minutes must divide 60")
        self.minutes = minutes
        self._cur: dict[str, _Bucket] = {}

    def _bucket_start(self, ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0, minute=ts.minute - ts.minute % self.minutes)

    def add(self, bar: Bar) -> list[Bar]:
        """Feed a 1-minute bar; returns completed N-minute bars (usually 0 or 1)."""
        out: list[Bar] = []
        start = self._bucket_start(bar.ts)
        cur = self._cur.get(bar.symbol)
        if cur is not None and cur.start != start:
            # A minute was missing at the end of the previous bucket: emit it now.
            out.append(cur.to_bar(bar.symbol))
            cur = None
        if cur is None:
            cur = _Bucket(start, bar.open, bar.high, bar.low, bar.close, bar.volume)
        else:
            cur.high = max(cur.high, bar.high)
            cur.low = min(cur.low, bar.low)
            cur.close = bar.close
            cur.volume += bar.volume
        self._cur[bar.symbol] = cur
        if bar.ts + timedelta(minutes=1) >= start + timedelta(minutes=self.minutes):
            out.append(cur.to_bar(bar.symbol))
            del self._cur[bar.symbol]
        return out
