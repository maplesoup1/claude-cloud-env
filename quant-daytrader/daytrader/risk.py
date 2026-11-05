"""Pre-trade risk checks and position sizing."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time

from .broker.base import Broker
from .config import RiskConfig
from .models import Side, Signal
from .sessions import DEFAULT_CALENDAR, SessionCalendar


@dataclass
class Decision:
    qty: int
    reason: str


class RiskManager:
    def __init__(self, cfg: RiskConfig, calendar: SessionCalendar | None = None):
        self.cfg = cfg
        self.calendar = calendar or DEFAULT_CALENDAR
        self.halted_day = None  # date on which the daily loss limit was hit

    def is_halted(self, now: datetime) -> bool:
        return self.halted_day == now.date()

    def flatten_time(self, now: datetime) -> time:
        return self.calendar.flatten_time(now.date(), self.cfg.flatten_at)

    def past_flatten_time(self, now: datetime) -> bool:
        return now.time() >= self.flatten_time(now)

    def daily_loss_breached(self, broker: Broker) -> bool:
        start = broker.day_start_equity()
        return start > 0 and broker.equity() <= start * (1 - self.cfg.daily_max_loss)

    def halt(self, now: datetime) -> None:
        self.halted_day = now.date()

    def size(self, sig: Signal, equity: float, gross_used: float = 0.0) -> int:
        per_share = abs(sig.entry_ref - sig.stop)
        if per_share <= 0 or sig.entry_ref <= 0:
            return 0
        if per_share / sig.entry_ref < self.cfg.min_stop_pct:
            return 0
        by_risk = equity * self.cfg.risk_per_trade / per_share
        by_notional = equity * self.cfg.max_position_pct / sig.entry_ref
        by_gross = max(0.0, equity * self.cfg.max_gross_pct - gross_used) / sig.entry_ref
        return max(0, math.floor(min(by_risk, by_notional, by_gross)))

    def evaluate(self, sig: Signal, broker: Broker, now: datetime, bar_end: datetime | None = None,
                 pending_gross: float = 0.0) -> Decision:
        """`pending_gross`: notional of entries submitted but not yet filled (counted in the cap)."""
        if self.is_halted(now):
            return Decision(0, "halted: daily loss limit")
        if self.past_flatten_time(now):
            return Decision(0, "past flatten time")
        if bar_end is not None and (now - bar_end).total_seconds() > self.cfg.max_signal_delay_minutes * 60:
            return Decision(0, "stale signal bar")
        long_ok = sig.stop < sig.entry_ref < sig.target
        short_ok = sig.target < sig.entry_ref < sig.stop
        if not (long_ok if sig.side is Side.LONG else short_ok):
            return Decision(0, "stop/target on wrong side of entry")
        if abs(sig.entry_ref - sig.stop) / sig.entry_ref < self.cfg.min_stop_pct:
            return Decision(0, "stop too tight")
        busy = broker.busy_symbols()
        if sig.symbol in busy:
            return Decision(0, "symbol already has position/order")
        if len(busy) >= self.cfg.max_positions:
            return Decision(0, "max positions")
        if sig.side is Side.SHORT and not broker.can_short(sig.symbol):
            return Decision(0, "not shortable")
        gross = sum(p.qty * p.entry_price for p in broker.positions().values()) + pending_gross
        qty = self.size(sig, broker.equity(), gross)
        if qty <= 0:
            return Decision(0, "size is zero (risk/notional/gross limits)")
        return Decision(qty, "ok")
