"""Event-driven core. Backtest and live both push 1-minute bars into `on_minute_bar`."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .aggregator import BarAggregator
from .broker.base import Broker
from .models import Bar, Signal, is_regular_hours
from .notify import Notifier
from .risk import RiskManager
from .strategy.base import Strategy

log = logging.getLogger(__name__)


def client_order_id(sig: Signal) -> str:
    # Deterministic per symbol/day/bar: a restart cannot submit the same entry twice
    # (the broker rejects duplicate client_order_ids).
    return f"{sig.tag}-{sig.symbol}-{sig.ts:%Y%m%d-%H%M}-{sig.side.value}"


class Engine:
    def __init__(self, strategy: Strategy, risk: RiskManager, broker: Broker, bar_minutes: int,
                 notifier: Notifier | None = None, journal_dir: str | Path | None = None):
        self.strategy = strategy
        self.risk = risk
        self.broker = broker
        self.agg = BarAggregator(bar_minutes)
        self.notifier = notifier or Notifier()
        self.journal_dir = Path(journal_dir) if journal_dir else None
        self.lock = threading.RLock()
        self._flattened_day: date | None = None
        self.signals: list[dict] = []
        self._last_ts: dict[str, datetime] = {}

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
            if trade:
                # Flatten/halt first so queued closes fill at this bar's open.
                self.broker.on_clock(bar.ts)
                self.check_time_and_loss(bar.ts)
                self.broker.on_minute_bar(bar)
            for b in self.agg.add(bar):
                sig = self.strategy.on_bar(b)
                if sig is not None and trade:
                    # Decision time = end of the 1-minute bar that completed the signal bar.
                    self._handle(sig, now=bar.ts + timedelta(minutes=1))

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
                self._event("halt", reason="daily loss limit", equity=self.broker.equity(), ts=now)
                self.notifier.send(f"HALT: daily loss limit hit, equity={self.broker.equity():.2f}")

    def _handle(self, sig: Signal, now: datetime) -> None:
        decision = self.risk.evaluate(sig, self.broker, now)
        rec = {"symbol": sig.symbol, "side": sig.side.value, "ref": sig.entry_ref, "stop": round(sig.stop, 4),
               "target": round(sig.target, 4), "qty": decision.qty, "decision": decision.reason, "ts": sig.ts}
        self.signals.append(rec)
        if decision.qty <= 0:
            self._event("signal_rejected", **rec)
            return
        ok = self.broker.submit_bracket(sig.symbol, sig.side, decision.qty, sig.stop, sig.target,
                                        client_order_id(sig))
        self._event("order_submitted" if ok else "order_failed", **rec)
        if ok and self.notifier.enabled:
            self.notifier.send(f"{sig.side.value.upper()} {decision.qty} {sig.symbol} @~{sig.entry_ref:.2f} "
                               f"stop {sig.stop:.2f} target {sig.target:.2f}")

    def _event(self, kind: str, **data) -> None:
        log.info("%s %s", kind, {k: v for k, v in data.items() if k != "ts"})
        if self.journal_dir is None:
            return
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        ts = data.get("ts") or datetime.now()
        path = self.journal_dir / f"journal-{ts:%Y%m%d}.jsonl"
        with path.open("a") as f:
            f.write(json.dumps({"event": kind, **data}, default=str) + "\n")
