"""Event-driven core. Backtest and live both push 1-minute bars into `on_minute_bar`."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .aggregator import BarAggregator
from .broker.base import Broker
from .models import Bar, Exit, Signal, is_regular_hours
from .notify import Notifier
from .risk import RiskManager
from .strategy.base import Context, Strategy

log = logging.getLogger(__name__)


class _NoPositions:
    """Broker stand-in for warm-up: strategies see no positions and nothing is traded."""

    def positions(self):
        return {}


class Engine:
    def __init__(self, strategy: Strategy, risk: RiskManager, broker: Broker, bar_minutes: int,
                 notifier: Notifier | None = None, journal_dir: str | Path | None = None,
                 name: str = "default"):
        self.name = name
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.agg = BarAggregator(bar_minutes)
        self.notifier = notifier or Notifier()
        self.journal_dir = Path(journal_dir) if journal_dir else None
        self.lock = threading.RLock()
        self._flattened_day: date | None = None
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
        if not is_regular_hours(bar.ts):
            return
        with self.lock:
            last = self._last_ts.get(bar.symbol)
            if last is not None and bar.ts <= last:
                return  # duplicate / out-of-order (e.g. warm-up overlapping the stream)
            self._last_ts[bar.symbol] = bar.ts
            now = bar.ts + timedelta(minutes=1)  # the 1-minute bar is complete at its end
            if trade:
                # Flatten/halt first so queued closes fill at this bar's open (sim).
                self.broker.on_clock(bar.ts)
                self.check_time_and_loss(bar.ts)
                self.broker.on_minute_bar(bar)
            for b in self.agg.add(bar):
                ctx = Context(self.broker if trade else _NoPositions(), now)
                actions = self.strategy.on_bar(b, ctx) or []
                if not trade:
                    continue
                for a in actions:
                    if isinstance(a, Exit):
                        self._exit(a, now)
                    else:
                        self._handle(a, now)

    def check_time_and_loss(self, now: datetime) -> None:
        """End-of-day flatten and daily-loss kill switch. Also called by the live watchdog."""
        with self.lock:
            if self.risk.past_flatten_time(now) and self._flattened_day != now.date():
                self._flattened_day = now.date()
                self.broker.flatten_all("eod")
                self._event("flatten", reason="eod", ts=now)
            if not self.risk.is_halted(now) and self.risk.daily_loss_breached(self.broker):
                self.risk.halt(now)
                self.broker.flatten_all("daily_loss")
                eq = self.broker.equity()
                self._event("halt", reason="daily loss limit", equity=eq, ts=now)
                self.notifier.send(f"[{self.name}] HALT: daily loss limit hit, equity={eq:.2f}")

    def _handle(self, sig: Signal, now: datetime) -> None:
        decision = self.risk.evaluate(sig, self.broker, now)
        rec = {"strategy": self.name, "symbol": sig.symbol, "side": sig.side.value, "ref": sig.entry_ref,
               "stop": round(sig.stop, 4), "target": round(sig.target, 4), "qty": decision.qty,
               "decision": decision.reason, "ts": sig.ts}
        self.signals.append(rec)
        if decision.qty <= 0:
            self._event("signal_rejected", **rec)
            return
        ok = self.broker.submit_bracket(sig.symbol, sig.side, decision.qty, sig.stop, sig.target,
                                        self.client_order_id(sig))
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
