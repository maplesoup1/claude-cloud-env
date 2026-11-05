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
import queue
import signal
import threading
import time as _time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .broker.alpaca import AlpacaBroker, with_timeout
from .config import Config, alpaca_keys
from .engine import Engine
from .models import NY, Bar
from .notify import Notifier
from .risk import RiskManager
from .sessions import SessionCalendar
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
    client = with_timeout(StockHistoricalDataClient(key, secret))
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
                        cfg.bar_minutes, notifier, journal_dir=cfg.live.log_dir, name=cfg.name,
                        wall_clock=lambda: datetime.now(NY))
        out.append(Instance(cfg, broker, engine, keys, broker.account_number()))
    return out


def run_live(cfgs: list[Config]) -> None:
    from alpaca.data.enums import DataFeed
    from alpaca.data.live import StockDataStream
    from alpaca.trading.enums import TradeEvent
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

    now = datetime.now(NY)
    today = now.date()
    trading = instances[0].broker.client
    calendar = SessionCalendar.from_alpaca(trading, today - timedelta(days=10), today)  # covers warm-up days
    hours = calendar.hours(today)
    if hours is None:
        log.info("market closed today (%s); exiting", today)
        return
    open_at = datetime.combine(today, hours[0], NY)
    close_at = datetime.combine(today, hours[1], NY)
    if now >= close_at:
        log.info("today's session is over; exiting")
        return
    for inst in instances:
        inst.engine.calendar = calendar
        inst.engine.risk.calendar = calendar
        ft = inst.engine.risk.flatten_time(now)
        a = inst.broker.account()
        log.info("[%s] account=%s equity=%s paper=%s flatten=%s symbols=%s", inst.cfg.name, inst.account,
                 a.equity, inst.cfg.live.paper, ft, inst.cfg.symbols)
    if hours[1] < time(16, 0):
        log.warning("early close today at %s; flatten times pulled in", hours[1])
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

    # The WebSocket handler only enqueues. Each instance has its OWN queue + worker thread
    # (and its own watchdog below), so a slow or hung REST call in one strategy never
    # delays bars, flattens or halts of another.
    queues = {inst.cfg.name: queue.Queue() for inst in instances}
    last_bar_at = [_time.monotonic()]
    stop = threading.Event()

    def worker(inst: Instance):
        q = queues[inst.cfg.name]
        while not stop.is_set():
            try:
                bar = q.get(timeout=1)
            except queue.Empty:
                continue
            lag = (datetime.now(NY) - (bar.ts + timedelta(minutes=1))).total_seconds()
            if lag > 90:
                log.warning("[%s] processing %s %s %.0fs late", inst.cfg.name, bar.symbol, bar.ts.time(), lag)
            try:
                inst.engine.on_minute_bar(bar)
            except Exception:
                log.exception("[%s] error handling bar %s", inst.cfg.name, bar)
                notifier.send(f"[{inst.cfg.name}] ERROR handling {bar.symbol} bar; see logs")

    stream = StockDataStream(*instances[0].keys, feed=DataFeed(feed))

    async def on_bar(b):
        last_bar_at[0] = _time.monotonic()
        bar = _to_bar(b)
        for inst in routes.get(bar.symbol, []):
            queues[inst.cfg.name].put(bar)

    stream.subscribe_bars(on_bar, *symbols)

    # One trade-updates stream per distinct account: fills -> journal of the owning instance.
    trade_streams = []
    by_account: dict[str, list[Instance]] = defaultdict(list)
    for inst in instances:
        by_account[inst.account].append(inst)
    fill_events = {TradeEvent.FILL, TradeEvent.PARTIAL_FILL}
    for acct, group in by_account.items():
        ts = TradingStream(*group[0].keys, paper=group[0].cfg.live.paper)

        def make_handler(group=group):
            async def on_trade(u):
                o = u.order
                ev = getattr(u.event, "value", str(u.event))
                for inst in group:
                    own = (o.client_order_id or "").startswith(inst.cfg.name + "-")
                    if own or (o.symbol in inst.broker.symbols and u.event in fill_events):
                        inst.engine.record_fill(event=ev, symbol=o.symbol, side=getattr(o.side, "value", str(o.side)),
                                                qty=str(u.qty), price=str(u.price),
                                                order_type=getattr(o.order_type, "value", str(o.order_type)),
                                                client_order_id=o.client_order_id, ts=datetime.now(NY))
                        break
            return on_trade

        ts.subscribe_trade_updates(make_handler())
        threading.Thread(target=ts.run, daemon=True, name=f"trades-{acct}").start()
        trade_streams.append(ts)

    def watchdog(inst: Instance):
        while not stop.wait(15):
            try:
                inst.engine.check_time_and_loss(datetime.now(NY), lock_timeout=30)
            except Exception:
                log.exception("[%s] watchdog check failed (will retry)", inst.cfg.name)

    def supervisor():
        warned = False
        while not stop.wait(15):
            t = datetime.now(NY)
            stale = _time.monotonic() - last_bar_at[0] > 180
            if stale and open_at + timedelta(minutes=3) <= t < close_at and not warned:
                notifier.send("No market data for 3 minutes - check the stream")
                warned = True
            elif not stale:
                warned = False
            if t >= close_at + timedelta(minutes=5):
                log.info("after close; stopping")
                for s_ in trade_streams:
                    s_.stop()
                stream.stop()
                return

    threads = []
    for inst in instances:
        threads.append(threading.Thread(target=worker, args=(inst,), daemon=True, name=f"worker-{inst.cfg.name}"))
        threads.append(threading.Thread(target=watchdog, args=(inst,), daemon=True, name=f"watchdog-{inst.cfg.name}"))
    threads.append(threading.Thread(target=supervisor, daemon=True, name="supervisor"))
    for th in threads:
        th.start()

    def on_sigterm(signum, frame):  # systemd/kill: run the same shutdown path as Ctrl-C
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, on_sigterm)
    except ValueError:  # not in the main thread (tests)
        pass

    notifier.send(f"daytrader started ({'paper' if cfgs[0].live.paper else 'LIVE'}): "
                  + "; ".join(f"{c.name}={','.join(c.symbols)}" for c in cfgs))
    try:
        stream.run()  # blocks; alpaca-py reconnects on its own
    finally:
        stop.set()
        for th in threads:  # let in-flight bar handling finish before the exit flatten
            th.join(timeout=20)
        t = datetime.now(NY)
        if open_at <= t < close_at:
            # Exiting while the market is open (crash, Ctrl-C, stream error): do not leave
            # positions whose DAY bracket legs will expire at the close.
            notifier.send("daytrader exiting during market hours - flattening all instances")
            for inst in instances:
                try:
                    with inst.engine.lock:
                        inst.broker.flatten_all("process_exit")
                except Exception as e:
                    notifier.send(f"[{inst.cfg.name}] FLATTEN ON EXIT FAILED: {e} - CLOSE MANUALLY")
        summary = []
        for inst in instances:
            try:
                a = inst.broker.client.get_account()
                summary.append(f"{inst.cfg.name}: equity {float(a.equity):.2f} "
                               f"day {float(a.equity) - float(a.last_equity):+.2f}")
            except Exception as e:
                summary.append(f"{inst.cfg.name}: {e}")
        notifier.send("daytrader stopped. " + " | ".join(summary))


def flatten_instances(cfgs: list[Config], if_close_within: float | None = None) -> None:
    """Safety net for cron: close each instance's own symbols (scoped, unlike `kill`).
    With `if_close_within=N`, act only if the market is open and closes within N minutes
    (lets one cron line cover both 13:00 half days and normal 16:00 closes)."""
    if if_close_within is not None:
        b0 = AlpacaBroker(*alpaca_keys(cfgs[0].account_env), symbols=cfgs[0].symbols, name=cfgs[0].name,
                          paper=cfgs[0].live.paper)
        clock = b0.clock()
        mins = (clock.next_close - clock.timestamp).total_seconds() / 60
        if not clock.is_open or mins > if_close_within:
            print(f"market {'open' if clock.is_open else 'closed'}, close in {mins:.0f} min: nothing to do")
            return
    failed = False
    for cfg in cfgs:
        b = AlpacaBroker(*alpaca_keys(cfg.account_env), symbols=cfg.symbols, name=cfg.name, paper=cfg.live.paper)
        for attempt in range(3):
            try:
                b.flatten_all("safety_net")
                print(f"[{cfg.name}] flat")
                break
            except Exception as e:
                print(f"[{cfg.name}] attempt {attempt + 1} failed: {e}")
                _time.sleep(5)
        else:
            failed = True
    if failed:
        Notifier.from_env().send("SAFETY-NET FLATTEN FAILED - close positions manually")
        raise SystemExit(1)


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
