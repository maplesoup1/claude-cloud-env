"""Gap fade (morning, counter-gap) on liquid large caps.

Idea: moderate overnight gaps WITHOUT follow-through often partially fill once
the opening auction imbalance is absorbed. We do not fade blindly at the open:
we wait for the gap to show failure, then trade back toward the prior close.

Entry (gap UP -> short; gap DOWN -> long is the mirror)
- gap = today's first regular-session open / prior session close - 1,
  with min_gap <= |gap| <= max_gap (huge gaps are usually news-driven trends)
- wait for the opening range (range_minutes) to complete
- failure confirmation: a bar CLOSES below the opening-range low AND below VWAP
- the gap must not already be filled (session low still above the target)
- no entries after last_entry; one entry per symbol per day

Exit
- target: open - fill_frac * (open - prior close)  (fill_frac=1 -> full fill)
- stop ("vwap", default): VWAP * (1 + stop_buffer) - reclaiming VWAP invalidates
  the "failed gap" thesis; or ("session_high"): above the session high so far
- skip if the stop is farther than max_stop_pct or reward/risk < min_rr
- optional time stop; engine flattens at risk.flatten_at
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from ..indicators import SessionStats
from ..models import MARKET_OPEN, Bar, Exit, Side, Signal
from .base import Context, Strategy, register


@dataclass
class GapFadeParams:
    min_gap: float = 0.01
    max_gap: float = 0.04
    range_minutes: int = 15
    fill_frac: float = 0.75
    stop_mode: str = "vwap"          # vwap | session_high
    stop_buffer: float = 0.002
    max_stop_pct: float = 0.025
    min_rr: float = 1.0
    last_entry: time = time(11, 30)
    allow_long: bool = True
    allow_short: bool = True
    max_hold_minutes: int = 0


@dataclass
class _Day:
    day: date
    or_high: float | None = None
    or_low: float | None = None
    traded: bool = False
    entry_at: datetime | None = None


@register
class GapFade(Strategy):
    name = "gap_fade"
    Params = GapFadeParams

    def __init__(self, params: GapFadeParams, bar_minutes: int):
        super().__init__(params, bar_minutes)
        if params.range_minutes % bar_minutes:
            raise ValueError("range_minutes must be a multiple of bar_minutes")
        if params.stop_mode not in ("vwap", "session_high"):
            raise ValueError("stop_mode must be vwap | session_high")
        if not 0 < params.fill_frac <= 1:
            raise ValueError("fill_frac must be in (0, 1]")
        self.range_end = (datetime.combine(date.min, MARKET_OPEN) + timedelta(minutes=params.range_minutes)).time()
        self._sess: dict[str, SessionStats] = {}
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
        sess.update(bar)
        st = self._day(bar.symbol, bar.ts.date())
        end = bar.ts + timedelta(minutes=self.bar_minutes)

        if p.max_hold_minutes and st.entry_at and ctx.position(bar.symbol) is not None:
            if end - st.entry_at >= timedelta(minutes=p.max_hold_minutes):
                st.entry_at = None
                return [Exit(bar.symbol, "time_stop", bar.ts)]

        # The gap is only valid if we saw the very first bar of the session.
        if sess.bars == 1 and bar.ts.time() != MARKET_OPEN:
            st.traded = True  # joined mid-session without the open: do not trade this symbol today
        if end.time() <= self.range_end:
            st.or_high = bar.high if st.or_high is None else max(st.or_high, bar.high)
            st.or_low = bar.low if st.or_low is None else min(st.or_low, bar.low)
            return []
        if st.traded or end.time() > p.last_entry or st.or_high is None:
            return []
        gap, pc, op, vwap = sess.gap, sess.prev_close, sess.open, sess.vwap
        if gap is None or vwap is None or not (p.min_gap <= abs(gap) <= p.max_gap):
            return []

        c = bar.close
        if gap > 0 and p.allow_short:
            target = op - p.fill_frac * (op - pc)
            if not (c < st.or_low and c < vwap) or sess.low <= target:
                return []
            ref = vwap if p.stop_mode == "vwap" else sess.high
            side, stop = Side.SHORT, ref * (1 + p.stop_buffer)
        elif gap < 0 and p.allow_long:
            target = op + p.fill_frac * (pc - op)
            if not (c > st.or_high and c > vwap) or sess.high >= target:
                return []
            ref = vwap if p.stop_mode == "vwap" else sess.low
            side, stop = Side.LONG, ref * (1 - p.stop_buffer)
        else:
            return []

        risk, reward = abs(stop - c), abs(c - target)
        if risk <= 0 or risk / c > p.max_stop_pct or reward / risk < p.min_rr:
            return []
        st.traded = True
        st.entry_at = end
        return [Signal(bar.symbol, side, c, stop, target, bar.ts, tag=self.name)]
