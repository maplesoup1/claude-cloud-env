"""Live / paper trading runner for one or more strategy instances.

    python -m daytrader -c configs/orb.yaml -c configs/vwap.yaml -c configs/momo.yaml paper

One process, ONE market-data WebSocket (the free plan allows a single connection),
bars routed to each strategy's Engine. Each instance trades through its own
AlpacaBroker (ideally its own paper account, chosen via `account_env`).

Start it before the open (e.g. 9:20 ET from cron). It:
1. validates the set of instances (unique names, account/symbol overlap),
2. checks the calendar (exits on holidays, pulls flatten time in on half days),
3. warms strategies up with the last few sessions of 1-minute bars,
4. marks symbols each instance already traded today (restart safety),
5. streams bars + per-account trade updates (fills go to the journals),
6. runs a watchdog for EOD flatten, daily-loss halt and stale-data alerts,
7. exits a few minutes after the close.
"""
from __future__ import annotations

import logging
import threading
import time as _time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from .broker.alpaca import AlpacaBroker
from .config import Config, alpaca_keys
from .engine import Engine
from .models import NY, Bar
from .notify import Notifier
from .risk import RiskManager
from .strategy import build_strategy

log = logging.getLogger(__name__)
IEX_SYMBOL_LIMIT = 30  # free-plan WebSocket subscription limit (check your plan)


@dataclass
class Instance:
    cfg: Config
    broker: AlpacaBroker
    engine: Engine
    keys: tuple[str, str]
    account: str


def _to_bar(b) -> Bar:
    return Bar(b.symbol, b.timestamp.astimezone(NY), float(b.open), float(b.high), float(b.low),
               float(b.close), float(b.volume))


def validate_instances(cfgs: list[Config], accounts: list[str]) -> list[str]:
    """Return warnings; raise on configurations that would make instances interfere."""
    warnings = []
    names = [c.name for c in cfgs]
    if len(set(names)) != len(names):
        raise SystemExit(f"instance names must be unique: {names}")
    for a in names:
        for b in names:
            if a != b and b.startswith(a + "-"):
                raise SystemExit(f"instance name {a!r} is a prefix of {b!r} (order ids would collide)")
    by_acct = defaultdict(list)
    for c, a in zip(cfgs, accounts):
        by_acct[a].append(c)
    for acct, group in by_acct.items():
        if len(group) > 1:
            seen: dict[str, str] = {}
            for c in group:
                for s in c.symbols:
                    if s in seen:
                        raise SystemExit(f"{c.name} and {seen[s]} share account {acct} AND symbol {s}. "
                                         "Use separate paper accounts (account_env) or disjoint symbols.")
                    seen[s] = c.name
            warnings.append(f"{[c.name for c in group]} share account {acct}: daily-loss limits and equity "
                            "are account-wide, so one strategy's losses can halt the others.")
    paper = {c.live.paper for c in cfgs}
    if len(paper) > 1:
        raise SystemExit("mixing paper and live instances in one process is not allowed")
    return warnings


def _warmup(instances: list[Instance], feed: str, now: datetime) -> None:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    key, secret = instances[0].keys
    client = StockHistoricalDataClient(key, secret)
    symbols = sorted({s for i in instances for s in i.cfg.symbols})
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Minute,
                           start=now - timedelta(days=5), end=now - timedelta(minutes=1), feed=DataFeed(feed))
    bars = sorted((_to_bar(b) for sym_bars in client.get_stock_bars(req).data.values() for b in sym_bars),
                  key=lambda b: (b.ts, b.symbol))
    for b in bars:
        for inst in instances:
            if b.symbol in inst.broker.symbols:
                inst.engine.on_minute_bar(b, trade=False)
    log.info("warm-up: %d bars for %d symbols", len(bars), len(symbols))


def build_instances(cfgs: list[Config], notifier: Notifier) -> list[Instance]:
    out = []
    for cfg in cfgs:
        keys = alpaca_keys(cfg.account_env)
        broker = AlpacaBroker(*keys, symbols=cfg.symbols, name=cfg.name, paper=cfg.live.paper)
        engine = Engine(build_strategy(cfg.strategy, cfg.bar_minutes), RiskManager(cfg.risk), broker,
                        cfg.bar_minutes, notifier, journal_dir=cfg.live.log_dir, name=cfg.name)
        out.append(Instance(cfg, broker, engine, keys, broker.account_number()))
    return out


def run_live(cfgs: list[Config]) -> None:
    from alpaca.data.enums import DataFeed
    from alpaca.data.live import StockDataStream
    from alpaca.trading.stream import TradingStream

    notifier = Notifier.from_env()
    instances = build_instances(cfgs, notifier)
    for w in validate_instances(cfgs, [i.account for i in instances]):
        log.warning(w)
    feeds = {c.live.feed for c in cfgs}
    if len(feeds) > 1:
        raise SystemExit(f"all instances must use the same live feed, got {feeds}")
    feed = feeds.pop()
    symbols = sorted({s for c in cfgs for s in c.symbols})
    if feed == "iex" and len(symbols) > IEX_SYMBOL_LIMIT:
        log.warning("%d symbols may exceed the free plan's WebSocket limit (%d)", len(symbols), IEX_SYMBOL_LIMIT)

    clock = instances[0].broker.clock()
    now = datetime.now(NY)
    today = now.date()
    next_open = clock.next_open.astimezone(NY)
    close_at = clock.next_close.astimezone(NY)
    if not clock.is_open and next_open.date() != today:
        log.info("market not open today (next open %s); exiting", next_open)
        return
    early = (close_at - timedelta(minutes=15)).time()
    for inst in instances:
        if close_at.date() == today and early < inst.cfg.risk.flatten_at:
            log.warning("[%s] early close %s; flattening at %s", inst.cfg.name, close_at.time(), early)
            inst.cfg.risk.flatten_at = early
        a = inst.broker.account()
        log.info("[%s] account=%s equity=%s paper=%s symbols=%s", inst.cfg.name, inst.account, a.equity,
                 inst.cfg.live.paper, inst.cfg.symbols)
    if not cfgs[0].live.paper:
        notifier.send("WARNING: running with REAL MONEY")

    _warmup(instances, feed, now)
    for inst in instances:
        for sym in inst.broker.symbols_traded_today(today):
            inst.engine.strategy.mark_traded(sym, today)
            log.info("[%s] already traded today: %s", inst.cfg.name, sym)

    routes: dict[str, list[Instance]] = defaultdict(list)
    for inst in instances:
        for s in inst.cfg.symbols:
            routes[s].append(inst)

    stream = StockDataStream(*instances[0].keys, feed=DataFeed(feed))
    last_bar_at = [_time.monotonic()]

    async def on_bar(b):
        last_bar_at[0] = _time.monotonic()
        bar = _to_bar(b)
        for inst in routes.get(bar.symbol, []):
            try:
                inst.engine.on_minute_bar(bar)
            except Exception:
                log.exception("[%s] error handling bar %s", inst.cfg.name, b)
                notifier.send(f"[{inst.cfg.name}] ERROR handling {b.symbol} bar; see logs")

    stream.subscribe_bars(on_bar, *symbols)

    # One trade-updates stream per distinct account: fills -> journal of the owning instance.
    trade_streams = []
    by_account: dict[str, list[Instance]] = defaultdict(list)
    for inst in instances:
        by_account[inst.account].append(inst)
    for acct, group in by_account.items():
        ts = TradingStream(*group[0].keys, paper=group[0].cfg.live.paper)

        def make_handler(group=group):
            async def on_trade(u):
                o = u.order
                for inst in group:
                    if (o.client_order_id or "").startswith(inst.cfg.name + "-") or (
                            o.symbol in inst.broker.symbols and str(u.event) in ("fill", "partial_fill")):
                        inst.engine.record_fill(event=str(u.event), symbol=o.symbol, side=str(o.side),
                                                qty=str(u.qty), price=str(u.price), order_type=str(o.order_type),
                                                client_order_id=o.client_order_id, ts=datetime.now(NY))
                        break
            return on_trade

        ts.subscribe_trade_updates(make_handler())
        threading.Thread(target=ts.run, daemon=True, name=f"trades-{acct}").start()
        trade_streams.append(ts)

    stop = threading.Event()

    def watchdog():
        warned = False
        while not stop.wait(15):
            t = datetime.now(NY)
            for inst in instances:
                try:
                    inst.engine.check_time_and_loss(t)
                except Exception:
                    log.exception("[%s] watchdog check failed", inst.cfg.name)
                    notifier.send(f"[{inst.cfg.name}] watchdog error - check positions manually")
            stale = _time.monotonic() - last_bar_at[0] > 180
            if stale and next_open + timedelta(minutes=3) <= t < close_at and not warned:
                notifier.send("No market data for 3 minutes - check the stream")
                warned = True
            elif not stale:
                warned = False
            if t >= close_at + timedelta(minutes=5):
                log.info("after close; stopping")
                for s in trade_streams:
                    s.stop()
                stream.stop()
                return

    threading.Thread(target=watchdog, daemon=True, name="watchdog").start()
    notifier.send(f"daytrader started ({'paper' if cfgs[0].live.paper else 'LIVE'}): "
                  + "; ".join(f"{c.name}={','.join(c.symbols)}" for c in cfgs))
    try:
        stream.run()  # blocks; alpaca-py reconnects on its own
    finally:
        stop.set()
        summary = []
        for inst in instances:
            try:
                a = inst.broker.client.get_account()
                summary.append(f"{inst.cfg.name}: equity {float(a.equity):.2f} "
                               f"day {float(a.equity) - float(a.last_equity):+.2f}")
            except Exception as e:
                summary.append(f"{inst.cfg.name}: {e}")
        notifier.send("daytrader stopped. " + " | ".join(summary))


def kill_switch(cfgs: list[Config]) -> None:
    done = set()
    for cfg in cfgs:
        keys = alpaca_keys(cfg.account_env)
        if keys in done:
            continue
        done.add(keys)
        b = AlpacaBroker(*keys, symbols=cfg.symbols, name=cfg.name, paper=cfg.live.paper)
        b.emergency_close_everything()
        print(f"[{cfg.account_env}] all orders cancelled and positions closed.")


def status(cfgs: list[Config]) -> None:
    for cfg in cfgs:
        b = AlpacaBroker(*alpaca_keys(cfg.account_env), symbols=cfg.symbols, name=cfg.name, paper=cfg.live.paper)
        a = b.client.get_account()
        print(f"== {cfg.name} ({cfg.strategy.name}) account={a.account_number} paper={cfg.live.paper}")
        print(f"   equity={a.equity} last_equity={a.last_equity} buying_power={a.buying_power} "
              f"day P&L {float(a.equity) - float(a.last_equity):+.2f}")
        for p in b.positions().values():
            print(f"   {p.side.value:5} {p.qty:>6} {p.symbol:6} @ {p.entry_price:.2f}")
        for o in b.open_orders():
            print(f"   order {o.symbol} {o.side} {o.qty} {o.order_type} {o.status} {o.client_order_id}")
