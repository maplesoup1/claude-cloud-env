"""Opening Range Breakout (momentum, morning).

Idea: the first minutes set a range; a decisive, high-volume break of it on a
liquid name tends to continue for a while (order-flow imbalance after the open).

Rules
- Opening range = high/low of 9:30 .. 9:30+range_minutes.
- Range width must be within [min_range_pct, max_range_pct] of price (too tight
  = noise breakouts, too wide = stop too far / news day).
- After the range, a bar CLOSING beyond the range with volume >= volume_mult x
  recent average (and, optionally, on the right side of VWAP) triggers an entry.
- Stop: other side of the range ("range") or the range midpoint ("mid").
- Target: reward_risk x R. Optional time stop.
- One entry per symbol per day (configurable); none after last_entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..indicators import RollingMean, SessionStats
from ..models import MARKET_OPEN, Bar, Exit, Side, Signal
from .base import Context, Strategy, register


@dataclass
class OrbParams:
    range_minutes: int = 15
    volume_mult: float = 1.5
    volume_lookback: int = 20        # bars, spans days
    reward_risk: float = 2.0
    stop_mode: str = "range"         # range | mid
    min_range_pct: float = 0.002
    max_range_pct: float = 0.02
    vwap_filter: bool = True         # long only above VWAP, short only below
    last_entry: time = time(11, 30)
    allow_short: bool = True
    max_trades_per_symbol: int = 1
    max_hold_minutes: int = 0        # 0 = hold until stop/target/flatten


@dataclass
class _Day:
    day: date
    high: float | None = None
    low: float | None = None
    trades: int = 0
    entry_at: datetime | None = None


@register
class OpeningRangeBreakout(Strategy):
    name = "orb"
    Params = OrbParams

    def __init__(self, params: OrbParams, bar_minutes: int):
        super().__init__(params, bar_minutes)
        if params.stop_mode not in ("range", "mid"):
            raise ValueError("stop_mode must be range|mid")
        if params.range_minutes % bar_minutes:
            raise ValueError("range_minutes must be a multiple of bar_minutes")
        self.range_end = (datetime.combine(date.min, MARKET_OPEN) + timedelta(minutes=params.range_minutes)).time()
        self._days: dict[str, _Day] = {}
        self._vols: dict[str, RollingMean] = {}
        self._sess: dict[str, SessionStats] = {}

    def _day(self, symbol: str, d: date) -> _Day:
        st = self._days.get(symbol)
        if st is None or st.day != d:
            st = self._days[symbol] = _Day(d)
        return st

    def mark_traded(self, symbol: str, day: date) -> None:
        self._day(symbol, day).trades = self.p.max_trades_per_symbol

    def on_bar(self, bar: Bar, ctx: Context) -> list:
        p = self.p
        st = self._day(bar.symbol, bar.ts.date())
        vols = self._vols.setdefault(bar.symbol, RollingMean(p.volume_lookback))
        sess = self._sess.setdefault(bar.symbol, SessionStats())
        avg_vol = vols.mean(min_count=p.volume_lookback // 2)  # BEFORE adding this bar
        vols.update(bar.volume)
        sess.update(bar)

        end = bar.ts + timedelta(minutes=self.bar_minutes)
        out: list = []
        if p.max_hold_minutes and st.entry_at and ctx.position(bar.symbol) is not None:
            if end - st.entry_at >= timedelta(minutes=p.max_hold_minutes):
                out.append(Exit(bar.symbol, "time_stop", bar.ts))
                st.entry_at = None
                return out

        if bar.ts.time() < MARKET_OPEN:
            return out
        if end.time() <= self.range_end:
            st.high = bar.high if st.high is None else max(st.high, bar.high)
            st.low = bar.low if st.low is None else min(st.low, bar.low)
            return out

        if st.high is None or st.low is None or st.high <= st.low:
            return out
        if end.time() > p.last_entry or st.trades >= p.max_trades_per_symbol:
            return out
        width = (st.high - st.low) / bar.close
        if not (p.min_range_pct <= width <= p.max_range_pct):
            return out
        if avg_vol is None or bar.volume < p.volume_mult * avg_vol:
            return out

        mid = (st.high + st.low) / 2
        vwap = sess.vwap
        if bar.close > st.high and (not p.vwap_filter or (vwap and bar.close > vwap)):
            side, stop = Side.LONG, (st.low if p.stop_mode == "range" else mid)
        elif p.allow_short and bar.close < st.low and (not p.vwap_filter or (vwap and bar.close < vwap)):
            side, stop = Side.SHORT, (st.high if p.stop_mode == "range" else mid)
        else:
            return out

        risk = abs(bar.close - stop)
        if risk <= 0:
            return out
        target = bar.close + p.reward_risk * risk if side is Side.LONG else bar.close - p.reward_risk * risk
        st.trades += 1
        st.entry_at = end
        out.append(Signal(bar.symbol, side, bar.close, stop, target, bar.ts, tag=self.name))
        return out
