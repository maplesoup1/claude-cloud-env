"""Opening Range Breakout.

- Opening range = high/low of 9:30 .. 9:30+range_minutes.
- After the range, a bar CLOSING above the range high (below the low, if shorts
  are allowed) with volume >= volume_mult x recent average triggers an entry.
- Stop at the other side of the range (or its midpoint), target = reward_risk x R.
- At most `max_trades_per_symbol` entries per symbol per day, none after `last_entry`.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..config import StrategyConfig
from ..models import MARKET_OPEN, Bar, Side, Signal
from .base import Strategy


@dataclass
class _Day:
    day: date
    high: float | None = None
    low: float | None = None
    trades: int = 0


class OpeningRangeBreakout(Strategy):
    def __init__(self, cfg: StrategyConfig, bar_minutes: int):
        self.cfg = cfg
        self.bar_minutes = bar_minutes
        self.range_end = (datetime.combine(date.min, MARKET_OPEN) + timedelta(minutes=cfg.range_minutes)).time()
        self._days: dict[str, _Day] = {}
        self._vols: dict[str, deque] = defaultdict(lambda: deque(maxlen=cfg.volume_lookback))

    def _day(self, symbol: str, d: date) -> _Day:
        st = self._days.get(symbol)
        if st is None or st.day != d:
            st = self._days[symbol] = _Day(d)
        return st

    def mark_traded(self, symbol: str, day: date) -> None:
        self._day(symbol, day).trades = self.cfg.max_trades_per_symbol

    def on_bar(self, bar: Bar) -> Signal | None:
        cfg = self.cfg
        st = self._day(bar.symbol, bar.ts.date())
        vols = self._vols[bar.symbol]
        avg_vol = sum(vols) / len(vols) if len(vols) >= max(1, cfg.volume_lookback // 2) else None
        vols.append(bar.volume)

        start_t = bar.ts.time()
        end_t = (bar.ts + timedelta(minutes=self.bar_minutes)).time()
        if start_t < MARKET_OPEN:
            return None
        if end_t <= self.range_end:
            st.high = bar.high if st.high is None else max(st.high, bar.high)
            st.low = bar.low if st.low is None else min(st.low, bar.low)
            return None

        if st.high is None or st.low is None or st.high <= st.low:
            return None
        if end_t > cfg.last_entry or st.trades >= cfg.max_trades_per_symbol:
            return None
        if avg_vol is None or bar.volume < cfg.volume_mult * avg_vol:
            return None

        mid = (st.high + st.low) / 2
        if bar.close > st.high:
            side, stop = Side.LONG, (st.low if cfg.stop_mode == "range" else mid)
        elif cfg.allow_short and bar.close < st.low:
            side, stop = Side.SHORT, (st.high if cfg.stop_mode == "range" else mid)
        else:
            return None

        risk = abs(bar.close - stop)
        if risk <= 0 or risk / bar.close > cfg.max_stop_pct:
            return None
        target = bar.close + cfg.reward_risk * risk if side is Side.LONG else bar.close - cfg.reward_risk * risk
        st.trades += 1
        return Signal(bar.symbol, side, bar.close, stop, target, bar.ts, tag="orb")


def build_strategy(cfg: StrategyConfig, bar_minutes: int) -> Strategy:
    if cfg.name == "orb":
        return OpeningRangeBreakout(cfg, bar_minutes)
    raise ValueError(f"Unknown strategy: {cfg.name}")
