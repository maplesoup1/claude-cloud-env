"""Event-driven core. Backtest and live both push 1-minute bars into `on_minute_bar`."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .aggregator import BarAggregator
from .broker.base import Broker
from .models import Bar, Exit, Signal
from .notify import Notifier
from .risk import RiskManager
from .sessions import DEFAULT_CALENDAR, SessionCalendar
from .strategy.base import Context, Strategy

log = logging.getLogger(__name__)


class _NoPositions:
    """Broker stand-in for warm-up: strategies see no positions and nothing is traded."""

    def positions(self):
        return {}


class Engine:
    def __init__(self, strategy: Strategy, risk: RiskManager, broker: Broker, bar_minutes: int,
                 notifier: Notifier | None = None, journal_dir: str | Path | None = None,
                 name: str = "default", calendar: SessionCalendar | None = None,
                 wall_clock=None, flatten_retry_seconds: float = 10.0):
        self.name = name
        self.calendar = calendar or risk.calendar or DEFAULT_CALENDAR
        risk.calendar = self.calendar
        self.bar_minutes = bar_minutes
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.agg = BarAggregator(bar_minutes)
        self.notifier = notifier or Notifier()
        self.journal_dir = Path(journal_dir) if journal_dir else None
        self.lock = threading.RLock()
        self._flatten_logged: date | None = None
        self._last_flatten_try: datetime | None = None
        self._last_fail_notice: datetime | None = None
        self.flatten_retry = timedelta(seconds=flatten_retry_seconds)
        self.wall_clock = wall_clock  # live: lambda: datetime.now(NY); decisions use the later of bar/wall time
        self._recent_entries: dict[str, tuple[float, datetime]] = {}  # symbol -> (notional, submitted at)
        self.signals: list[dict] = []
        self.exits: list[dict] = []
        self._last_ts: dict[str, datetime] = {}
        self.log = logging.getLogger(f"{__name__}.{name}")

    def client_order_id(self, sig: Signal) -> str:
        # Deterministic per instance/symbol/bar: a restart cannot submit the same entry twice
        # (Alpaca rejects duplicate client_order_ids).
        return f"{self.name}-{sig.symbol}-{sig.ts:%Y%m%d-%H%M}-{sig.side.value}"

    # ---- events -----------------------------------------------------------
    def on_minute_bar(self, bar: Bar, trade: bool = True) -> None:
        """Process one completed 1-minute bar. `trade=False` = warm-up only."""
        if not self.calendar.in_session(bar.ts):
            return
        with self.lock:
            last = self._last_ts.get(bar.symbol)
            if last is not None and bar.ts <= last:
                return  # duplicate / out-of-order (e.g. warm-up overlapping the stream)
            self._last_ts[bar.symbol] = bar.ts
            now = bar.ts + timedelta(minutes=1)  # the 1-minute bar is complete at its end
            if self.wall_clock is not None:
                now = max(now, self.wall_clock())  # live: a processing backlog makes signals stale
            if trade:
                # Flatten/halt first so queued closes fill at this bar's open (sim).
                # A broker/API failure here must not cost the strategy this bar.
                try:
                    self.broker.on_clock(bar.ts)
                    self.check_time_and_loss(bar.ts)
                    self.broker.on_minute_bar(bar)
                except Exception:
                    self.log.exception("broker/risk step failed on %s %s", bar.symbol, bar.ts)
            for b in self.agg.add(bar):
                ctx = Context(self.broker if trade else _NoPositions(), now)
                actions = self.strategy.on_bar(b, ctx) or []
                if not trade:
                    continue
                bar_end = b.ts + timedelta(minutes=self.bar_minutes)
                for a in actions:
                    try:
                        if isinstance(a, Exit):
                            self._exit(a, now)
                        else:
                            self._handle(a, now, bar_end)
                    except Exception:
                        self.log.exception("action failed: %s", a)
                        self.notifier.send(f"[{self.name}] ERROR executing {a}; check the account")

    def check_time_and_loss(self, now: datetime, lock_timeout: float = -1) -> None:
        """EOD flatten and daily-loss halt. Called on every bar AND by the live watchdog,
        and retried (at most every `flatten_retry`) while anything is still open, so a
        failed close never leaves a position overnight."""
        if not self.lock.acquire(timeout=lock_timeout):
            self.log.error("engine busy (lock held > %ss); skipping this check", lock_timeout)
            return
        try:
            self._check_time_and_loss(now)
        finally:
            self.lock.release()

    def _check_time_and_loss(self, now: datetime) -> None:
        if not self.risk.is_halted(now) and self.risk.daily_loss_breached(self.broker):
            self.risk.halt(now)
            eq = self.broker.equity()
            self._event("halt", reason="daily loss limit", equity=eq, ts=now)
            self.notifier.send(f"[{self.name}] HALT: daily loss limit hit, equity={eq:.2f}")
        eod = self.risk.past_flatten_time(now)
        if not (eod or self.risk.is_halted(now)):
            return
        if self._last_flatten_try is not None and timedelta(0) <= now - self._last_flatten_try < self.flatten_retry:
            return  # throttle: retry at most every flatten_retry
        if not self.broker.busy_symbols():
            return
        self._last_flatten_try = now
        reason = "eod" if eod else "daily_loss"
        if self._flatten_logged != now.date():
            self._flatten_logged = now.date()
            self._event("flatten", reason=reason, ts=now)
        try:
            self.broker.flatten_all(reason)
        except Exception as e:
            self.log.exception("flatten failed; will retry")
            if self._last_fail_notice is None or now - self._last_fail_notice >= timedelta(minutes=5):
                self._last_fail_notice = now
                self.notifier.send(f"[{self.name}] FLATTEN FAILED ({e}); retrying - check the account")
            raise

    def _handle(self, sig: Signal, now: datetime, bar_end: datetime | None = None) -> None:
        positions = self.broker.positions()
        pending_gross = sum(n for sym, (n, t) in self._recent_entries.items()
                            if sym not in positions and timedelta(0) <= now - t < timedelta(minutes=3))
        decision = self.risk.evaluate(sig, self.broker, now, bar_end, pending_gross=pending_gross)
        rec = {"strategy": self.name, "symbol": sig.symbol, "side": sig.side.value, "ref": sig.entry_ref,
               "stop": round(sig.stop, 4), "target": round(sig.target, 4), "qty": decision.qty,
               "decision": decision.reason, "ts": sig.ts}
        self.signals.append(rec)
        if decision.qty <= 0:
            self._event("signal_rejected", **rec)
            return
        ok = self.broker.submit_bracket(sig.symbol, sig.side, decision.qty, sig.stop, sig.target,
                                        self.client_order_id(sig))
        if ok:
            self._recent_entries[sig.symbol] = (decision.qty * sig.entry_ref, now)
        self._event("order_submitted" if ok else "order_failed", **rec)
        if ok and self.notifier.enabled:
            self.notifier.send(f"[{self.name}] {sig.side.value.upper()} {decision.qty} {sig.symbol} "
                               f"@~{sig.entry_ref:.2f} stop {sig.stop:.2f} target {sig.target:.2f}")

    def _exit(self, ex: Exit, now: datetime) -> None:
        if ex.symbol not in self.broker.busy_symbols():
            return
        self.broker.close_position(ex.symbol, ex.reason)
        rec = {"strategy": self.name, "symbol": ex.symbol, "reason": ex.reason, "ts": ex.ts}
        self.exits.append(rec)
        self._event("exit", **rec)

    def _event(self, kind: str, **data) -> None:
        self.log.info("%s %s", kind, {k: v for k, v in data.items() if k != "ts"})
        if self.journal_dir is None:
            return
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        ts = data.get("ts") or datetime.now()
        path = self.journal_dir / f"journal-{self.name}-{ts:%Y%m%d}.jsonl"
        with path.open("a") as f:
            f.write(json.dumps({"event": kind, **data}, default=str) + "\n")

    def record_fill(self, **data) -> None:
        """Live: called from the trade-updates stream."""
        self._event("fill", **data)
