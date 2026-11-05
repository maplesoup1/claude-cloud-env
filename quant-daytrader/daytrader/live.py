"""Live / paper trading runner.

Start it before the open (e.g. 9:20 ET from cron). It:
1. checks the market calendar (exits on holidays, adjusts flatten time on half days),
2. warms up the strategy with today's/yesterday's bars,
3. marks symbols already traded today (restart safety),
4. streams 1-minute bars over WebSocket into the same Engine used by the backtest,
5. runs a watchdog thread for end-of-day flatten and the daily-loss kill switch,
6. exits after the close.
"""
from __future__ import annotations

import logging
import threading
import time as _time
from datetime import datetime, timedelta

from .broker.alpaca import AlpacaBroker
from .config import Config, alpaca_keys
from .engine import Engine
from .models import NY, Bar
from .notify import Notifier
from .risk import RiskManager
from .strategy import build_strategy

log = logging.getLogger(__name__)


def _to_bar(b) -> Bar:
    return Bar(b.symbol, b.timestamp.astimezone(NY), float(b.open), float(b.high), float(b.low),
               float(b.close), float(b.volume))


def _warmup(engine: Engine, cfg: Config, key: str, secret: str, now: datetime) -> None:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(key, secret)
    req = StockBarsRequest(symbol_or_symbols=cfg.symbols, timeframe=TimeFrame.Minute,
                           start=now - timedelta(days=4), end=now - timedelta(minutes=1),
                           feed=DataFeed(cfg.live.feed))
    bars = sorted((_to_bar(b) for sym_bars in client.get_stock_bars(req).data.values() for b in sym_bars),
                  key=lambda b: (b.ts, b.symbol))
    for b in bars:
        engine.on_minute_bar(b, trade=False)
    log.info("warm-up: %d bars", len(bars))


def run_live(cfg: Config) -> None:
    from alpaca.data.enums import DataFeed
    from alpaca.data.live import StockDataStream

    key, secret = alpaca_keys()
    notifier = Notifier.from_env()
    broker = AlpacaBroker(key, secret, paper=cfg.live.paper)
    clock = broker.clock()
    now = datetime.now(NY)
    today = now.date()
    next_open = clock.next_open.astimezone(NY)
    close_at = clock.next_close.astimezone(NY)
    if not clock.is_open and next_open.date() != today:
        log.info("market not open today (next open %s); exiting", next_open)
        return
    # Half days: flatten 15 min before the real close if that is earlier than configured.
    early = (close_at - timedelta(minutes=15)).time()
    if close_at.date() == today and early < cfg.risk.flatten_at:
        log.warning("early close today at %s; flattening at %s", close_at.time(), early)
        cfg.risk.flatten_at = early

    acct = broker.client.get_account()
    log.info("account %s equity=%s paper=%s", acct.account_number, acct.equity, cfg.live.paper)
    if not cfg.live.paper:
        notifier.send("WARNING: running with REAL MONEY")

    strategy = build_strategy(cfg.strategy, cfg.bar_minutes)
    risk = RiskManager(cfg.risk)
    engine = Engine(strategy, risk, broker, cfg.bar_minutes, notifier, journal_dir=cfg.live.log_dir)
    _warmup(engine, cfg, key, secret, now)
    for sym in broker.symbols_traded_today(today):
        strategy.mark_traded(sym, today)
        log.info("already traded today: %s", sym)

    stream = StockDataStream(key, secret, feed=DataFeed(cfg.live.feed))
    last_bar_at = [_time.monotonic()]

    async def on_bar(b):
        last_bar_at[0] = _time.monotonic()
        try:
            engine.on_minute_bar(_to_bar(b))
        except Exception:
            log.exception("error handling bar %s", b)
            notifier.send(f"ERROR handling bar for {b.symbol}; see logs")

    stream.subscribe_bars(on_bar, *cfg.symbols)
    stop = threading.Event()

    def watchdog():
        warned = False
        while not stop.wait(15):
            t = datetime.now(NY)
            try:
                engine.check_time_and_loss(t)
            except Exception:
                log.exception("watchdog check failed")
            stale = _time.monotonic() - last_bar_at[0] > 180
            if stale and next_open <= t < close_at and not warned:
                notifier.send("No market data for 3 minutes - check the stream")
                warned = True
            elif not stale:
                warned = False
            if t >= close_at + timedelta(minutes=5):
                log.info("after close; stopping")
                stream.stop()
                return

    threading.Thread(target=watchdog, daemon=True, name="watchdog").start()
    notifier.send(f"daytrader started ({'paper' if cfg.live.paper else 'LIVE'}): {', '.join(cfg.symbols)}")
    try:
        stream.run()  # blocks; alpaca-py reconnects on its own
    finally:
        stop.set()
        notifier.send(f"daytrader stopped. equity={broker.equity():.2f}")


def kill_switch(cfg: Config) -> None:
    key, secret = alpaca_keys()
    AlpacaBroker(key, secret, paper=cfg.live.paper).flatten_all("manual kill switch")
    print("All orders cancelled and positions closed.")


def status(cfg: Config) -> None:
    key, secret = alpaca_keys()
    b = AlpacaBroker(key, secret, paper=cfg.live.paper)
    a = b.client.get_account()
    print(f"paper={cfg.live.paper} equity={a.equity} last_equity={a.last_equity} buying_power={a.buying_power}")
    print(f"day P&L: {float(a.equity) - float(a.last_equity):+.2f}")
    for p in b.positions().values():
        print(f"  {p.side.value:5} {p.qty:>6} {p.symbol:6} @ {p.entry_price:.2f}")
    for o in b.open_orders():
        print(f"  order {o.symbol} {o.side} {o.qty} {o.order_type} {o.status} {o.client_order_id}")
