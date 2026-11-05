"""Alpaca broker (paper by default).

- Entries are bracket orders, so stops/targets live on Alpaca's servers and keep
  working if this process dies - BUT only until the close: legs are DAY orders and
  expire at 16:00, and nothing would flatten the position. Run the separate
  `daytrader flatten` safety net from cron (see README).
- Everything is scoped to `symbols`: flatten/close only touch this strategy's
  symbols, so several strategies can share an account if their symbols differ.
  (Recommended: one paper account per strategy, so daily-loss limits are separate.)
"""
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
    def __init__(self, api_key: str, secret_key: str, symbols: list[str], name: str = "default",
                 paper: bool = True, account_ttl: float = 5.0, positions_ttl: float = 2.0):
        if not paper:
            log.warning("LIVE (real money) trading enabled for %s", name)
        self.client = TradingClient(api_key, secret_key, paper=paper)
        self.symbols = set(symbols)
        self.name = name
        self._cache: dict[str, tuple[float, object]] = {}
        self._ttl = {"account": account_ttl, "positions": positions_ttl, "orders": positions_ttl}
        self._shortable: dict[str, bool] = {}

    # ---- cached reads ------------------------------------------------------
    def _cached(self, key: str, fn):
        hit = self._cache.get(key)
        if hit and _time.monotonic() - hit[0] < self._ttl[key]:
            return hit[1]
        val = fn()
        self._cache[key] = (_time.monotonic(), val)
        return val

    def _invalidate(self) -> None:
        self._cache.clear()

    def account(self):
        return self._cached("account", self.client.get_account)

    def equity(self) -> float:
        return float(self.account().equity)

    def day_start_equity(self) -> float:
        return float(self.account().last_equity)  # equity at previous close

    def positions(self) -> dict[str, Position]:
        def fetch():
            out = {}
            for p in self.client.get_all_positions():
                if p.symbol not in self.symbols:
                    continue
                side = Side.LONG if p.side == PositionSide.LONG else Side.SHORT
                out[p.symbol] = Position(p.symbol, side, abs(int(float(p.qty))), float(p.avg_entry_price))
            return out
        return dict(self._cached("positions", fetch))

    def open_orders(self, symbols: list[str] | None = None):
        """Open orders, FLAT (nested=False): bracket legs whose parent already filled are
        listed as their own orders, so they can be seen and cancelled."""
        syms = sorted(symbols or self.symbols)

        def fetch():
            return self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=False,
                                                           symbols=syms, limit=500))
        return self._cached("orders", fetch) if symbols is None else fetch()

    def busy_symbols(self) -> set[str]:
        return set(self.positions()) | {o.symbol for o in self.open_orders()}

    def can_short(self, symbol: str) -> bool:
        if symbol not in self._shortable:
            a = self.client.get_asset(symbol)
            self._shortable[symbol] = bool(a.shortable and a.easy_to_borrow)
        return self._shortable[symbol]

    # ---- writes ------------------------------------------------------------
    def submit_bracket(self, symbol, side, qty, stop, target, client_order_id) -> bool:
        if symbol not in self.symbols:
            raise ValueError(f"{symbol} is not in this broker's symbols")
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
            log.info("[%s] submitted %s %s qty=%s status=%s id=%s", self.name, side.value, symbol, qty, o.status, o.id)
            return True
        except APIError as e:
            log.error("[%s] order rejected %s %s: %s", self.name, symbol, client_order_id, e)
            return False
        finally:
            self._invalidate()

    def _cancel_symbol_orders(self, symbol: str) -> None:
        for o in self.open_orders([symbol]):
            for oid in [o.id] + [leg.id for leg in (o.legs or [])]:
                try:
                    self.client.cancel_order_by_id(oid)
                except APIError as e:  # already filled/cancelled
                    log.debug("cancel %s: %s", oid, e)

    def close_position(self, symbol: str, reason: str) -> None:
        log.warning("[%s] close %s (%s)", self.name, symbol, reason)
        last_err = None
        for attempt in range(2):  # kept short: the engine/watchdog retries on its next tick
            try:
                self._cancel_symbol_orders(symbol)
                # Bracket legs hold the shares until the cancels are processed.
                for _ in range(10):
                    if not self.open_orders([symbol]):
                        break
                    _time.sleep(0.3)
                self._invalidate()
                if symbol in self.positions():
                    self.client.close_position(symbol)
                self._invalidate()
                return
            except Exception as e:
                last_err = e
                log.error("[%s] close %s attempt %d failed: %s", self.name, symbol, attempt + 1, e)
                _time.sleep(1)
        raise RuntimeError(f"[{self.name}] closing {symbol} failed: {last_err}")

    def flatten_all(self, reason: str) -> None:
        """Close every symbol; one failure does not stop the others. Raises at the end
        if anything failed so the caller retries."""
        self._invalidate()
        failed = []
        for sym in sorted(self.busy_symbols()):
            try:
                self.close_position(sym, reason)
            except Exception as e:
                failed.append(f"{sym}: {e}")
        if failed:
            raise RuntimeError(f"[{self.name}] flatten incomplete: {failed}")

    # ---- live-only helpers -----------------------------------------------
    def symbols_traded_today(self, today: date) -> set[str]:
        """Symbols with an entry from this instance today (any status), for restart safety."""
        after = datetime.combine(today, time(0, 0), NY)
        orders = self.client.get_orders(GetOrdersRequest(status=QueryOrderStatus.ALL, after=after, limit=500,
                                                         symbols=sorted(self.symbols)))
        prefix = f"{self.name}-"
        return {o.symbol for o in orders if (o.client_order_id or "").startswith(prefix)}

    def account_number(self) -> str:
        return str(self.client.get_account().account_number)

    def clock(self):
        return self.client.get_clock()

    def emergency_close_everything(self) -> None:
        """Kill switch: cancels ALL orders and closes ALL positions in the account."""
        self.client.close_all_positions(cancel_orders=True)
