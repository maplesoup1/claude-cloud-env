"""Simulated broker for backtests.

Fill model (deliberately conservative):
- Market entries fill at the NEXT 1-minute bar's open, plus slippage.
- Bracket exits are checked on every 1-minute bar. If a gap opens through the
  stop, the exit fills at the open (plus slippage). If stop and target are both
  inside one bar, the STOP is assumed to fill first.
- Targets are limit orders: they fill at the target price only if the bar
  trades strictly through it.
- Flatten orders fill at each symbol's next bar open, plus slippage.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from ..config import BacktestConfig
from ..models import Bar, Position, Side
from .base import Broker

log = logging.getLogger(__name__)


@dataclass
class _Order:
    symbol: str
    side: Side
    qty: int
    stop: float
    target: float
    client_order_id: str


class SimBroker(Broker):
    def __init__(self, cfg: BacktestConfig):
        self.cfg = cfg
        self.cash_pnl = 0.0  # realized P&L net of fees
        self._positions: dict[str, Position] = {}
        self._pending: dict[str, _Order] = {}
        self._to_close: dict[str, str] = {}  # symbol -> reason
        self._last: dict[str, float] = {}
        self._day: date | None = None
        self._day_start_equity = cfg.start_equity
        self.trades: list[dict] = []
        self.daily_equity: list[tuple[date, float]] = []
        self.rejected = 0

    # ---- Broker interface -------------------------------------------------
    def equity(self) -> float:
        unreal = 0.0
        for p in self._positions.values():
            px = self._last.get(p.symbol, p.entry_price)
            sign = 1 if p.side is Side.LONG else -1
            unreal += sign * (px - p.entry_price) * p.qty
        return self.cfg.start_equity + self.cash_pnl + unreal

    def day_start_equity(self) -> float:
        return self._day_start_equity

    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def busy_symbols(self) -> set[str]:
        return set(self._positions) | set(self._pending)

    def submit_bracket(self, symbol, side, qty, stop, target, client_order_id) -> bool:
        if qty <= 0 or symbol in self.busy_symbols():
            return False
        self._pending[symbol] = _Order(symbol, side, qty, stop, target, client_order_id)
        return True

    def close_position(self, symbol: str, reason: str) -> None:
        self._pending.pop(symbol, None)
        if symbol in self._positions:
            self._to_close[symbol] = reason  # market order: fills at the next bar open

    def flatten_all(self, reason: str) -> None:
        self._pending.clear()
        for sym in self._positions:
            self._to_close[sym] = reason

    # ---- simulation -------------------------------------------------------
    def _slip(self, px: float, buying: bool) -> float:
        s = self.cfg.slippage_bps / 10_000
        return px * (1 + s) if buying else px * (1 - s)

    def _fees(self, qty: int, px: float, selling: bool) -> float:
        fee = qty * self.cfg.fee_per_share
        if selling:
            fee += qty * px * self.cfg.sec_fee_rate
        return fee

    def on_clock(self, now) -> None:
        d = now.date()
        if self._day != d:
            if self._day is not None:
                self.daily_equity.append((self._day, self.equity()))
            self._day = d
            self._day_start_equity = self.equity()

    def finish(self) -> None:
        if self._day is not None:
            self.daily_equity.append((self._day, self.equity()))

    def _close(self, p: Position, px: float, bar: Bar, reason: str) -> None:
        sign = 1 if p.side is Side.LONG else -1
        gross = sign * (px - p.entry_price) * p.qty
        fees = self._fees(p.qty, px, selling=p.side is Side.LONG)
        self.cash_pnl += gross - fees
        risk = abs(p.entry_price - p.stop) * p.qty if p.stop is not None else 0.0
        self.trades.append({
            "symbol": p.symbol, "side": p.side.value, "qty": p.qty,
            "entry_time": p.opened_at, "entry": round(p.entry_price, 4),
            "exit_time": bar.ts, "exit": round(px, 4), "reason": reason,
            "pnl": round(gross - fees, 2), "r": round((gross - fees) / risk, 3) if risk else None,
        })
        del self._positions[p.symbol]

    def on_minute_bar(self, bar: Bar) -> None:
        self.on_clock(bar.ts)
        sym = bar.symbol

        if sym in self._to_close and sym in self._positions:
            p = self._positions[sym]
            self._close(p, self._slip(bar.open, buying=p.side is Side.SHORT), bar, self._to_close.pop(sym))
        self._to_close.pop(sym, None)

        order = self._pending.pop(sym, None)
        if order is not None:
            buying = order.side is Side.LONG
            fill = self._slip(bar.open, buying)
            invalid = (fill <= order.stop or fill >= order.target) if buying else (fill >= order.stop or fill <= order.target)
            if invalid:  # price already through stop/target: a real bracket would be rejected
                self.rejected += 1
            else:
                self.cash_pnl -= self._fees(order.qty, fill, selling=not buying)
                self._positions[sym] = Position(sym, order.side, order.qty, fill, order.stop, order.target, bar.ts)

        p = self._positions.get(sym)
        if p is not None:
            if p.side is Side.LONG:
                if bar.open <= p.stop:
                    self._close(p, self._slip(bar.open, False), bar, "stop_gap")
                elif bar.low <= p.stop:
                    self._close(p, self._slip(p.stop, False), bar, "stop")
                elif bar.high > p.target:
                    self._close(p, p.target, bar, "target")
            else:
                if bar.open >= p.stop:
                    self._close(p, self._slip(bar.open, True), bar, "stop_gap")
                elif bar.high >= p.stop:
                    self._close(p, self._slip(p.stop, True), bar, "stop")
                elif bar.low < p.target:
                    self._close(p, p.target, bar, "target")

        self._last[sym] = bar.close
