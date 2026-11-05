"""Regression tests for issues found by the independent review."""
from datetime import date, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import D, at, flat, mk, sim_broker
from daytrader.aggregator import BarAggregator
from daytrader.config import BacktestConfig, RiskConfig, load_config, parse_time
from daytrader.engine import Engine
from daytrader.models import Position, Side, Signal
from daytrader.risk import RiskManager
from daytrader.sessions import SessionCalendar
from test_framework import Scripted


class FlakyBroker:
    """Minimal broker whose flatten fails the first `fail_times` calls."""

    def __init__(self, fail_times=2):
        self.fail_times = fail_times
        self.calls = 0
        self.open = {"A", "B"}

    def equity(self): return 10_000
    def day_start_equity(self): return 10_000
    def positions(self): return {s: Position(s, Side.LONG, 1, 100) for s in self.open}
    def busy_symbols(self): return set(self.open)
    def on_clock(self, now): pass
    def on_minute_bar(self, bar): pass

    def flatten_all(self, reason):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("api down")
        self.open.clear()


def test_failed_eod_flatten_is_retried_until_flat():
    b = FlakyBroker(fail_times=2)
    eng = Engine(Scripted({}), RiskManager(RiskConfig(flatten_at=time(15, 45))), b, 5)
    for i in range(5):
        try:
            eng.check_time_and_loss(at(15, 45) + timedelta(seconds=15 * i))
        except RuntimeError:
            pass
    assert b.calls == 3 and b.open == set()


def test_failed_flatten_does_not_cost_strategy_its_bar():
    b = FlakyBroker(fail_times=100)
    strat = Scripted({})
    eng = Engine(strat, RiskManager(RiskConfig(flatten_at=time(9, 31))), b, 5)
    for m in range(35, 40):
        eng.on_minute_bar(flat(9, m, 100))   # flatten raises on every bar
    assert len(strat.seen) == 1               # the 9:35 bucket still reached the strategy


def test_alpaca_flatten_continues_after_one_symbol_fails(monkeypatch):
    from daytrader.broker.alpaca import AlpacaBroker
    b = AlpacaBroker.__new__(AlpacaBroker)
    b.name, b.symbols = "t", {"A", "B", "C"}
    closed = []
    b.busy_symbols = lambda: {"A", "B", "C"}
    b._invalidate = lambda: None

    def close(sym, reason):
        if sym == "A":
            raise RuntimeError("boom")
        closed.append(sym)
    b.close_position = close
    with pytest.raises(RuntimeError, match="flatten incomplete"):
        b.flatten_all("eod")
    assert closed == ["B", "C"]


def test_half_day_calendar_flattens_before_early_close_and_ignores_after_hours():
    cal = SessionCalendar({D.date(): (time(9, 30), time(13, 0))}, strict=True)
    b = sim_broker()
    eng = Engine(Scripted({}), RiskManager(RiskConfig(flatten_at=time(15, 45))), b, 5, calendar=cal)
    b.submit_bracket("X", Side.LONG, 10, stop=50, target=200, client_order_id="a")
    eng.on_minute_bar(flat(12, 0, 100))
    eng.on_minute_bar(flat(12, 44, 100))
    eng.on_minute_bar(flat(12, 45, 101))      # 13:00 close - 15 min
    eng.on_minute_bar(flat(14, 0, 95))        # after-hours print: ignored
    assert b.positions() == {} and b.trades[-1]["exit"] == 101 and b.trades[-1]["reason"] == "eod"
    assert cal.in_session(at(12, 59)) and not cal.in_session(at(13, 0))
    assert not cal.in_session(at(10, 0, D + timedelta(days=1)))   # strict: unknown date = holiday


def test_sim_never_holds_overnight_even_without_late_bars():
    b = sim_broker()
    eng = Engine(Scripted({}), RiskManager(RiskConfig()), b, 5)
    b.submit_bracket("X", Side.LONG, 10, stop=50, target=200, client_order_id="a")
    eng.on_minute_bar(flat(10, 0, 100))
    eng.on_minute_bar(flat(11, 0, 102))       # last bar of the day for X (data gap)
    eng.on_minute_bar(flat(9, 30, 90, day=D + timedelta(days=1)))
    tr = b.trades[-1]
    assert tr["reason"] == "session_end" and tr["exit"] == 102 and tr["exit_time"].date() == D.date()


def test_trade_pnl_includes_entry_fees():
    from daytrader.broker.sim import SimBroker
    b = SimBroker(BacktestConfig(start_equity=10_000, slippage_bps=0, fee_per_share=0.01, sec_fee_rate=0))
    b.submit_bracket("X", Side.LONG, 100, stop=90, target=110, client_order_id="a")
    b.on_minute_bar(flat(9, 50, 100))
    b.close_position("X", "manual")
    b.on_minute_bar(flat(9, 51, 100))
    assert b.trades[-1]["pnl"] == pytest.approx(-2.0)
    assert b.equity() == pytest.approx(10_000 - 2.0)


def test_stale_previous_session_bucket_is_dropped():
    agg = BarAggregator(5)
    agg.add(flat(15, 55, 100, day=D - timedelta(days=1)))     # 15:56-15:59 never arrive
    out = agg.add(flat(9, 30, 101))
    assert out == []


def test_aggregated_bar_records_first_minute():
    agg = BarAggregator(5)
    agg.add(flat(9, 31, 100))
    [b] = agg.add(flat(9, 34, 100))
    assert b.ts == at(9, 30) and b.first == at(9, 31)


def test_stale_signal_bar_rejected():
    r = RiskManager(RiskConfig(max_signal_delay_minutes=2))
    sig = Signal("X", Side.LONG, 100, 98, 104, at(14, 25))
    assert r.evaluate(sig, sim_broker(), at(14, 41), bar_end=at(14, 30)).reason == "stale signal bar"
    assert r.evaluate(sig, sim_broker(), at(14, 31), bar_end=at(14, 30)).reason == "ok"


def test_gross_exposure_cap():
    b = sim_broker(equity=10_000)
    b.submit_bracket("A", Side.LONG, 40, stop=90, target=110, client_order_id="a")
    b.on_minute_bar(flat(9, 50, 100, sym="A"))                 # $4,000 open
    r = RiskManager(RiskConfig(max_gross_pct=0.5, max_position_pct=1, risk_per_trade=1))
    d = r.evaluate(Signal("X", Side.LONG, 100, 99, 102, at(9, 50)), b, at(9, 55))
    assert d.qty == 10                                          # only $1,000 of gross left


def test_config_validation(tmp_path):
    assert parse_time(945) == time(15, 45)                      # YAML 1.1: unquoted 15:45
    base = Path(__file__).parent.parent / "configs" / "orb.yaml"
    text = base.read_text()

    def load(t):
        p = tmp_path / "c.yaml"
        p.write_text(t)
        return load_config(p)
    with pytest.raises(ValueError, match="list"):
        load(text.replace("symbols: [SPY, QQQ, NVDA, TSLA, AAPL, AMD, META, MSFT]", "symbols: SPY"))
    with pytest.raises(ValueError, match="bar_minutes"):
        load(text.replace("bar_minutes: 5", "bar_minutes: 20"))
    with pytest.raises(ValueError, match="flatten_at"):
        load(text.replace('flatten_at: "15:45"', 'flatten_at: "16:00"'))
    assert load(text.replace('flatten_at: "15:45"', "flatten_at: 15:45")).risk.flatten_at == time(15, 45)
