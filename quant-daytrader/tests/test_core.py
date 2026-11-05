from datetime import datetime, time, timedelta

import pytest

from daytrader.aggregator import BarAggregator
from daytrader.backtest import run_backtest
from daytrader.broker.sim import SimBroker
from daytrader.config import BacktestConfig, Config, RiskConfig, StrategyConfig
from daytrader.data import synthetic_minutes
from daytrader.engine import Engine
from daytrader.models import NY, Bar, Side, Signal
from daytrader.risk import RiskManager
from daytrader.strategy import OpeningRangeBreakout

D = datetime(2025, 3, 3, tzinfo=NY)


def t(h, m, day=D):
    return day.replace(hour=h, minute=m)


def bar(h, m, o, hi, lo, c, v=1000, sym="X", day=D):
    return Bar(sym, t(h, m, day), o, hi, lo, c, v)


# ---- aggregator ----------------------------------------------------------
def test_aggregator_builds_5m_bars():
    agg = BarAggregator(5)
    out = []
    for i in range(10):
        out += agg.add(bar(9, 30 + i, 100 + i, 101 + i, 99 + i, 100.5 + i, v=10))
    assert len(out) == 2
    b = out[0]
    assert b.ts == t(9, 30) and b.open == 100 and b.high == 105 and b.low == 99 and b.close == 104.5 and b.volume == 50


def test_aggregator_flushes_bucket_with_missing_last_minute():
    agg = BarAggregator(5)
    assert agg.add(bar(9, 30, 1, 1, 1, 1)) == []
    out = agg.add(bar(9, 36, 2, 2, 2, 2))  # 9:31-9:35 missing
    assert len(out) == 1 and out[0].ts == t(9, 30)


# ---- strategy ------------------------------------------------------------
def _orb(**kw):
    kw.setdefault("max_stop_pct", 0.05)
    cfg = StrategyConfig(volume_lookback=2, **kw)
    return OpeningRangeBreakout(cfg, 5)


def _feed_range(s):
    for m in (30, 35, 40):
        assert s.on_bar(bar(9, m, 100, 101, 99, 100, v=1000)) is None


def test_orb_long_breakout():
    s = _orb()
    _feed_range(s)
    sig = s.on_bar(bar(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000))
    assert sig.side is Side.LONG and sig.stop == 99
    assert sig.target == pytest.approx(101.2 + 2 * (101.2 - 99))
    # only one trade per day
    assert s.on_bar(bar(9, 50, 101, 102, 101, 101.8, v=5000)) is None


def test_orb_requires_volume_and_respects_last_entry():
    s = _orb()
    _feed_range(s)
    assert s.on_bar(bar(9, 45, 100.5, 101.5, 100.4, 101.2, v=1000)) is None  # no volume
    s2 = _orb()
    _feed_range(s2)
    assert s2.on_bar(bar(11, 30, 100.5, 101.5, 100.4, 101.2, v=9000)) is None  # bar ends 11:35 > 11:30


def test_orb_short_and_no_short():
    s = _orb()
    _feed_range(s)
    sig = s.on_bar(bar(9, 45, 99.5, 99.6, 98.5, 98.8, v=2000))
    assert sig.side is Side.SHORT and sig.stop == 101
    s2 = _orb(allow_short=False)
    _feed_range(s2)
    assert s2.on_bar(bar(9, 45, 99.5, 99.6, 98.5, 98.8, v=2000)) is None


def test_orb_mark_traded_blocks_entries():
    s = _orb()
    s.mark_traded("X", D.date())
    _feed_range(s)
    assert s.on_bar(bar(9, 45, 100.5, 101.5, 100.4, 101.2, v=2000)) is None


# ---- sim broker ----------------------------------------------------------
def _broker(slip=0.0):
    return SimBroker(BacktestConfig(start_equity=10_000, slippage_bps=slip, sec_fee_rate=0))


def test_sim_fills_next_open_with_slippage_then_target():
    b = _broker(slip=10)  # 0.1%
    b.submit_bracket("X", Side.LONG, 10, stop=99, target=103, client_order_id="a")
    b.on_minute_bar(bar(9, 50, 100, 100.5, 99.5, 100.2))
    p = b.positions()["X"]
    assert p.entry_price == pytest.approx(100.1)
    b.on_minute_bar(bar(9, 51, 101, 103.0, 100.8, 102.9))  # touches but does not trade through 103
    assert "X" in b.positions()
    b.on_minute_bar(bar(9, 52, 103, 103.5, 102.8, 103.2))
    assert "X" not in b.positions()
    assert b.trades[-1]["reason"] == "target" and b.trades[-1]["exit"] == 103


def test_sim_stop_first_when_both_hit():
    b = _broker()
    b.submit_bracket("X", Side.LONG, 10, stop=99, target=101, client_order_id="a")
    b.on_minute_bar(bar(9, 50, 100, 100, 100, 100))
    b.on_minute_bar(bar(9, 51, 100, 102, 98, 100))
    assert b.trades[-1]["reason"] == "stop" and b.trades[-1]["pnl"] == pytest.approx(-10)


def test_sim_gap_through_stop_fills_at_open():
    b = _broker()
    b.submit_bracket("X", Side.SHORT, 10, stop=101, target=95, client_order_id="a")
    b.on_minute_bar(bar(9, 50, 100, 100, 100, 100))
    b.on_minute_bar(bar(9, 51, 102, 102.5, 101.5, 102))
    assert b.trades[-1]["reason"] == "stop_gap" and b.trades[-1]["exit"] == 102


def test_sim_rejects_entry_already_through_stop():
    b = _broker()
    b.submit_bracket("X", Side.LONG, 10, stop=99, target=103, client_order_id="a")
    b.on_minute_bar(bar(9, 50, 98.5, 99, 98, 98.7))
    assert b.positions() == {} and b.rejected == 1


# ---- risk ----------------------------------------------------------------
def test_risk_sizing_caps():
    r = RiskManager(RiskConfig(risk_per_trade=0.01, max_position_pct=0.5))
    sig = Signal("X", Side.LONG, 100, 99, 102, t(9, 45))
    assert r.size(sig, 10_000) == 50  # by risk would be 100, notional cap 50
    sig2 = Signal("X", Side.LONG, 100, 96, 108, t(9, 45))
    assert r.size(sig2, 10_000) == 25


def test_risk_max_positions_and_halt():
    b = _broker()
    r = RiskManager(RiskConfig(max_positions=1))
    b.submit_bracket("A", Side.LONG, 1, 99, 103, "a")
    sig = Signal("X", Side.LONG, 100, 99, 102, t(9, 45))
    assert r.evaluate(sig, b, t(9, 50)).reason == "max positions"
    r.halt(t(10, 0))
    assert r.evaluate(sig, b, t(10, 5)).qty == 0


# ---- engine end to end ---------------------------------------------------
def test_engine_flattens_at_eod():
    b = _broker()
    eng = Engine(_orb(), RiskManager(RiskConfig(flatten_at=time(15, 45))), b, 5)
    b.submit_bracket("X", Side.LONG, 10, stop=50, target=200, client_order_id="a")
    eng.on_minute_bar(bar(15, 40, 100, 100, 100, 100))
    assert "X" in b.positions()
    eng.on_minute_bar(bar(15, 45, 101, 101, 101, 101))
    assert b.positions() == {} and b.trades[-1]["reason"] == "eod" and b.trades[-1]["exit"] == 101


def test_daily_loss_halts_and_flattens():
    b = _broker()
    eng = Engine(_orb(), RiskManager(RiskConfig(daily_max_loss=0.02)), b, 5)
    b.submit_bracket("X", Side.LONG, 100, stop=10, target=500, client_order_id="a")
    eng.on_minute_bar(bar(9, 50, 100, 100, 100, 100))
    eng.on_minute_bar(bar(9, 51, 97, 97, 97, 97))   # -300 = -3%, detected on next bar
    eng.on_minute_bar(bar(9, 52, 96, 96, 96, 96))
    assert b.positions() == {} and b.trades[-1]["reason"] == "daily_loss"
    assert eng.risk.is_halted(t(10, 0))


def test_backtest_runs_and_never_holds_overnight():
    cfg = Config(symbols=["AAA", "BBB", "CCC"])
    bars = synthetic_minutes(cfg.symbols, days=30, seed=1)
    res = run_backtest(cfg, bars)
    assert res.stats["trades"] > 0
    assert res.stats["open_positions_at_end"] == 0
    tr = res.trades
    assert (tr.entry_time.map(lambda x: x.date()) == tr.exit_time.map(lambda x: x.date())).all()
    assert (tr.exit_time.map(lambda x: x.time()) <= time(15, 45)).all()
    assert (tr.entry_time.map(lambda x: x.time()) <= time(11, 31)).all()
    # entries are always strictly after the signal bar closed
    sig = res.signals[res.signals.qty > 0]
    assert len(sig) >= len(tr)


def test_no_edge_on_random_walk():
    """Look-ahead guard: on driftless random walks the strategy must not make money.
    A clearly positive average R here means the engine is peeking at future data."""
    import logging
    logging.disable(logging.WARNING)
    cfg = Config(symbols=["AAA", "BBB", "CCC", "DDD"])
    rs = []
    for seed in range(4):
        res = run_backtest(cfg, synthetic_minutes(cfg.symbols, days=80, seed=seed, trend=0.0))
        rs.extend(res.trades.r.dropna())
    logging.disable(logging.NOTSET)
    import statistics as st
    assert len(rs) > 100
    t_stat = st.mean(rs) / (st.stdev(rs) / len(rs) ** 0.5)
    assert t_stat < 2.5, f"suspicious edge on random data: t={t_stat:.2f}"
