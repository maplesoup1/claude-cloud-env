"""Alpaca broker (paper by default). Exits are broker-side bracket legs, so stops
and targets stay active even if this process dies."""
from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, PositionSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest, StopLossRequest, TakeProfitRequest

from ..models import NY, Position, Side
from .base import Broker

log = logging.getLogger(__name__)


class AlpacaBroker(Broker):
    def __init__(self, api_key: str, secret_key: str, paper: bool = True, account_ttl: float = 5.0):
        if not paper:
            log.warning("LIVE (real money) trading enabled")
        self.client = TradingClient(api_key, secret_key, paper=paper)
        self._account = None
        self._account_at = 0.0
        self._ttl = account_ttl
        self._shortable: dict[str, bool] = {}

    def _acct(self):
        if self._account is None or _time.monotonic() - self._account_at > self._ttl:
            self._account = self.client.get_account()
            self._account_at = _time.monotonic()
        return self._account

    def equity(self) -> float:
        return float(self._acct().equity)

    def day_start_equity(self) -> float:
        return float(self._acct().last_equity)  # equity at previous close

    def positions(self) -> dict[str, Position]:
        out = {}
        for p in self.client.get_all_positions():
            side = Side.LONG if p.side == PositionSide.LONG else Side.SHORT
            out[p.symbol] = Position(p.symbol, side, abs(int(float(p.qty))), float(p.avg_entry_price))
        return out

    def open_orders(self):
        return self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True))

    def busy_symbols(self) -> set[str]:
        busy = set(self.positions())
        for o in self.open_orders():
            # A bracket whose parent filled leaves child legs open; those belong to a
            # position (already counted). An unfilled parent = pending entry.
            busy.add(o.symbol)
        return busy

    def can_short(self, symbol: str) -> bool:
        if symbol not in self._shortable:
            a = self.client.get_asset(symbol)
            self._shortable[symbol] = bool(a.shortable and a.easy_to_borrow)
        return self._shortable[symbol]

    def submit_bracket(self, symbol, side, qty, stop, target, client_order_id) -> bool:
        req = MarketOrderRequest(
            symbol=symbol, qty=qty,
            side=OrderSide.BUY if side is Side.LONG else OrderSide.SELL,
            time_in_force=TimeInForce.DAY, order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target, 2)),
            stop_loss=StopLossRequest(stop_price=round(stop, 2)),
            client_order_id=client_order_id,
        )
        try:
            o = self.client.submit_order(req)
            log.info("submitted %s %s %s qty=%s id=%s", side.value, symbol, o.status, qty, o.id)
            self._account = None
            return True
        except APIError as e:
            log.error("order rejected %s %s: %s", symbol, client_order_id, e)
            return False

    def flatten_all(self, reason: str) -> None:
        log.warning("flatten_all (%s)", reason)
        for attempt in range(3):
            try:
                self.client.close_all_positions(cancel_orders=True)
                self._account = None
                return
            except Exception as e:
                log.error("flatten attempt %d failed: %s", attempt + 1, e)
                _time.sleep(2 ** attempt)
        raise RuntimeError("flatten_all failed 3 times - CHECK THE ACCOUNT MANUALLY")

    # ---- live-only helpers -----------------------------------------------
    def symbols_traded_today(self, today: date) -> set[str]:
        """Symbols with an entry already submitted today (any status), for restart safety."""
        after = datetime.combine(today, time(0, 0), NY)
        orders = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, after=after, limit=500))
        return {o.symbol for o in orders if (o.client_order_id or "").startswith("orb-")}

    def clock(self):
        return self.client.get_clock()
