"""Pre-trade risk checks and position sizing."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .broker.base import Broker
from .config import RiskConfig
from .models import Side, Signal


@dataclass
class Decision:
    qty: int
    reason: str


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.halted_day = None  # date on which the daily loss limit was hit

    def is_halted(self, now: datetime) -> bool:
        return self.halted_day == now.date()

    def past_flatten_time(self, now: datetime) -> bool:
        return now.time() >= self.cfg.flatten_at

    def daily_loss_breached(self, broker: Broker) -> bool:
        start = broker.day_start_equity()
        return start > 0 and broker.equity() <= start * (1 - self.cfg.daily_max_loss)

    def halt(self, now: datetime) -> None:
        self.halted_day = now.date()

    def size(self, sig: Signal, equity: float) -> int:
        per_share = abs(sig.entry_ref - sig.stop)
        if per_share <= 0 or sig.entry_ref <= 0:
            return 0
        by_risk = equity * self.cfg.risk_per_trade / per_share
        by_notional = equity * self.cfg.max_position_pct / sig.entry_ref
        return max(0, math.floor(min(by_risk, by_notional)))

    def evaluate(self, sig: Signal, broker: Broker, now: datetime) -> Decision:
        if self.is_halted(now):
            return Decision(0, "halted: daily loss limit")
        if self.past_flatten_time(now):
            return Decision(0, "past flatten time")
        busy = broker.busy_symbols()
        if sig.symbol in busy:
            return Decision(0, "symbol already has position/order")
        if len(busy) >= self.cfg.max_positions:
            return Decision(0, "max positions")
        if sig.side is Side.SHORT and not broker.can_short(sig.symbol):
            return Decision(0, "not shortable")
        qty = self.size(sig, broker.equity())
        if qty <= 0:
            return Decision(0, "size is zero")
        return Decision(qty, "ok")
