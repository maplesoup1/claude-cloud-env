"""VWAP mean reversion (mid-day, counter-trend).

Idea: on liquid large caps, sharp intraday stretches away from VWAP that are NOT
part of a strong trend day tend to partially revert toward VWAP, which is where
much institutional execution benchmarks itself.

Entry (long; short is the mirror)
- time window [first_entry, last_entry] (avoid the noisy open and the close)
- close <= VWAP - band_k * sigma, where sigma is the volume-weighted stdev of
  price around VWAP so far today, AND the distance is >= min_band_pct of price
  (early in the day sigma is tiny)
- RSI(rsi_period) on N-minute closes <= rsi_long_max (oversold)
- reversal confirmation: the signal bar closes up (close > open)
- trend-day filter: |price vs prior close (or today's open)| <= max_day_move_pct,
  and the market proxy (market_symbol) is not down more than market_max_move
  (for longs) / up more than it (for shorts). The market proxy's state is taken
  only from bars that ENDED before the current bar, so results do not depend on
  the order symbols arrive in.
- cooldown after an entry, max entries per symbol per day

Exit
- target: VWAP at signal time (target_frac of the way there)
- stop: the farther of (signal bar extreme) and (close - stop_k * sigma)
- skip if reward/risk < min_rr
- time stop after max_hold_minutes; engine flattens at risk.flatten_at
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..indicators import RSI, SessionStats
from ..models import Bar, Exit, Side, Signal
from .base import Context, Strategy, register


@dataclass
class VwapReversionParams:
    band_k: float = 2.0
    min_band_pct: float = 0.004
    rsi_period: int = 7
    rsi_long_max: float = 25.0
    rsi_short_min: float = 75.0
    confirm_reversal: bool = True
    stop_k: float = 1.0
    target_frac: float = 1.0
    min_rr: float = 0.8
    max_day_move_pct: float = 0.025
    market_symbol: str = "SPY"       # "" disables the market filter
    market_max_move: float = 0.01
    first_entry: time = time(10, 0)
    last_entry: time = time(15, 0)
    allow_short: bool = True
    max_trades_per_symbol: int = 2
    cooldown_minutes: int = 30
    max_hold_minutes: int = 60


@dataclass
class _Day:
    day: date
    trades: int = 0
    last_entry_at: datetime | None = None
    entry_at: datetime | None = None


@register
class VwapReversion(Strategy):
    name = "vwap_reversion"
    Params = VwapReversionParams

    def __init__(self, params: VwapReversionParams, bar_minutes: int):
        super().__init__(params, bar_minutes)
        if not 0 < params.target_frac <= 1:
            raise ValueError("target_frac must be in (0, 1]")
        self._sess: dict[str, SessionStats] = {}
        self._rsi: dict[str, RSI] = {}
        self._days: dict[str, _Day] = {}
        # market proxy: list of (bar_end, move) for the current day, newest last
        self._mkt: list[tuple[datetime, float]] = []

    def _day(self, symbol: str, d: date) -> _Day:
        st = self._days.get(symbol)
        if st is None or st.day != d:
            st = self._days[symbol] = _Day(d)
        return st

    def mark_traded(self, symbol: str, day: date) -> None:
        self._day(symbol, day).trades = self.p.max_trades_per_symbol

    @staticmethod
    def _day_move(sess: SessionStats) -> float | None:
        ref = sess.prev_close or sess.open
        return sess.close / ref - 1 if ref and sess.close else None

    def _market_move(self, before: datetime) -> float | None:
        for end, move in reversed(self._mkt):
            if end <= before and end.date() == before.date():
                return move
        return None

    def on_bar(self, bar: Bar, ctx: Context) -> list:
        p = self.p
        sess = self._sess.setdefault(bar.symbol, SessionStats())
        rsi = self._rsi.setdefault(bar.symbol, RSI(p.rsi_period))
        sess.update(bar)
        r = rsi.update(bar.close)
        st = self._day(bar.symbol, bar.ts.date())
        end = bar.ts + timedelta(minutes=self.bar_minutes)

        market_move = self._market_move(bar.ts)  # strictly from bars ended by this bar's start
        if bar.symbol == p.market_symbol:
            mv = self._day_move(sess)
            if mv is not None:
                self._mkt = [x for x in self._mkt if x[0].date() == end.date()] + [(end, mv)]

        out: list = []
        if st.entry_at and ctx.position(bar.symbol) is not None:
            if end - st.entry_at >= timedelta(minutes=p.max_hold_minutes):
                st.entry_at = None
                return [Exit(bar.symbol, "time_stop", bar.ts)]

        if not (p.first_entry <= bar.ts.time() and end.time() <= p.last_entry):
            return out
        if st.trades >= p.max_trades_per_symbol:
            return out
        if st.last_entry_at and end - st.last_entry_at < timedelta(minutes=p.cooldown_minutes):
            return out
        vwap, sigma = sess.vwap, sess.vwap_std
        if vwap is None or not sigma or r is None:
            return out
        day_move = self._day_move(sess)
        if day_move is None or abs(day_move) > p.max_day_move_pct:
            return out

        c = bar.close
        dist = (c - vwap) / c
        if c <= vwap - p.band_k * sigma and -dist >= p.min_band_pct and r <= p.rsi_long_max:
            side = Side.LONG
            if p.confirm_reversal and not bar.close > bar.open:
                return out
            if p.market_symbol and market_move is not None and market_move < -p.market_max_move:
                return out
            stop = min(bar.low, c - p.stop_k * sigma)
            target = c + p.target_frac * (vwap - c)
        elif p.allow_short and c >= vwap + p.band_k * sigma and dist >= p.min_band_pct and r >= p.rsi_short_min:
            side = Side.SHORT
            if p.confirm_reversal and not bar.close < bar.open:
                return out
            if p.market_symbol and market_move is not None and market_move > p.market_max_move:
                return out
            stop = max(bar.high, c + p.stop_k * sigma)
            target = c - p.target_frac * (c - vwap)
        else:
            return out

        risk, reward = abs(c - stop), abs(target - c)
        if risk <= 0 or reward / risk < p.min_rr:
            return out
        st.trades += 1
        st.last_entry_at = end
        st.entry_at = end
        return [Signal(bar.symbol, side, c, stop, target, bar.ts, tag=self.name)]
