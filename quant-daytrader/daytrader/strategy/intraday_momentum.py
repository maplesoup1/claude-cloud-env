"""Intraday (end-of-day) momentum on index ETFs.

Idea: documented in academic work on "market intraday momentum" (e.g. Gao, Han,
Li & Zhou; Baltussen, Da, Lammers & Martens): the market's return earlier in the
day predicts the direction of the LAST half hour, attributed to hedging flows
(e.g. gamma hedging, leveraged-ETF rebalancing) and late-informed traders, which
push in the direction of the day's move into the close.

Entry
- at the N-minute bar that ENDS exactly at `signal_time` (default 15:30)
- move = signal close / prior session close - 1     (mode "close_to_signal")
         or the first-half-hour move (prior close -> 10:00 close) ("first_half_hour")
         or both, required to agree in sign ("both")
- trade only if min_move <= |move| <= max_move, in the direction of the move
- optional: require price on the same side of session VWAP (vwap_confirm)

Exit
- held into the close; the engine flattens at risk.flatten_at (set it to ~15:58)
- protective bracket: stop = stop_atr_mult x ATR(N-minute bars) away,
  target = target_atr_mult x ATR (rarely hit; mostly a guard for news spikes)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time, timedelta

from ..indicators import ATR, SessionStats
from ..models import Bar, Side, Signal
from .base import Context, Strategy, register

log = logging.getLogger(__name__)


@dataclass
class IntradayMomentumParams:
    signal_time: time = time(15, 30)
    mode: str = "close_to_signal"     # close_to_signal | first_half_hour | both
    min_move: float = 0.003
    max_move: float = 0.04
    vwap_confirm: bool = True
    atr_period: int = 14
    stop_atr_mult: float = 3.0
    target_atr_mult: float = 6.0
    allow_short: bool = True


@dataclass
class _Day:
    day: date
    first_half_close: float | None = None
    traded: bool = False
    saw_signal_bar: bool = False
    warned: bool = False


@register
class IntradayMomentum(Strategy):
    name = "intraday_momentum"
    Params = IntradayMomentumParams

    FIRST_HALF_END = time(10, 0)

    def __init__(self, params: IntradayMomentumParams, bar_minutes: int):
        super().__init__(params, bar_minutes)
        if params.mode not in ("close_to_signal", "first_half_hour", "both"):
            raise ValueError("mode must be close_to_signal | first_half_hour | both")
        if 30 % bar_minutes:
            raise ValueError("bar_minutes must divide 30")
        if (params.signal_time.hour * 60 + params.signal_time.minute) % bar_minutes:
            raise ValueError("signal_time must fall on a bar boundary")
        if not time(10, 0) < params.signal_time < time(15, 55):
            raise ValueError("signal_time must be between 10:00 and 15:55")
        self._sess: dict[str, SessionStats] = {}
        self._atr: dict[str, ATR] = {}
        self._days: dict[str, _Day] = {}

    def _day(self, symbol: str, d: date) -> _Day:
        st = self._days.get(symbol)
        if st is None or st.day != d:
            st = self._days[symbol] = _Day(d)
        return st

    def mark_traded(self, symbol: str, day: date) -> None:
        self._day(symbol, day).traded = True

    def on_bar(self, bar: Bar, ctx: Context) -> list:
        p = self.p
        sess = self._sess.setdefault(bar.symbol, SessionStats())
        atr = self._atr.setdefault(bar.symbol, ATR(p.atr_period)).update(bar)
        sess.update(bar)
        st = self._day(bar.symbol, bar.ts.date())
        end = (bar.ts + timedelta(minutes=self.bar_minutes)).time()

        if end == self.FIRST_HALF_END:
            st.first_half_close = bar.close
        if end == p.signal_time:
            st.saw_signal_bar = True
        elif end > p.signal_time and not st.saw_signal_bar and not st.warned:
            st.warned = True
            log.warning("intraday_momentum: no %s bar ending %s today - no trade", bar.symbol, p.signal_time)
        if end != p.signal_time or st.traded:
            return []
        if sess.prev_close is None or atr is None:
            return []

        m_late = bar.close / sess.prev_close - 1
        m_first = st.first_half_close / sess.prev_close - 1 if st.first_half_close else None
        if p.mode == "close_to_signal":
            move = m_late
        elif p.mode == "first_half_hour":
            move = m_first
        else:
            move = m_late if (m_first is not None and m_first * m_late > 0) else None
        if move is None or not (p.min_move <= abs(move) <= p.max_move):
            return []

        side = Side.LONG if move > 0 else Side.SHORT
        if side is Side.SHORT and not p.allow_short:
            return []
        vwap = sess.vwap
        if p.vwap_confirm and vwap is not None:
            if (side is Side.LONG and bar.close <= vwap) or (side is Side.SHORT and bar.close >= vwap):
                return []

        c = bar.close
        if side is Side.LONG:
            stop, target = c - p.stop_atr_mult * atr, c + p.target_atr_mult * atr
        else:
            stop, target = c + p.stop_atr_mult * atr, c - p.target_atr_mult * atr
        st.traded = True
        return [Signal(bar.symbol, side, c, stop, target, bar.ts, tag=self.name)]
