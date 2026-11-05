from datetime import time, timedelta

import pytest

from conftest import D, FakeCtx, at, flat, mk, sim_broker
from daytrader.aggregator import BarAggregator
from daytrader.config import Config, RiskConfig, StrategyConfig, load_config
from daytrader.engine import Engine
from daytrader.indicators import ATR, RSI, SessionStats
from daytrader.models import Bar, Exit, Side, Signal
from daytrader.risk import RiskManager
from daytrader.strategy import Strategy, build_strategy


# ---- aggregator ----------------------------------------------------------
def test_aggregator_builds_5m_bars():
    agg = BarAggregator(5)
    out = []
    for i in range(10):
        out += agg.add(mk(9, 30 + i, 100 + i, 101 + i, 99 + i, 100.5 + i, v=10))
    assert len(out) == 2
    b = out[0]
    assert b.ts == at(9, 30) and b.open == 100 and b.high == 105 and b.low == 99 and b.close == 104.5 and b.volume == 50


def test_aggregator_flushes_bucket_with_missing_last_minute():
    agg = BarAggregator(5)
    assert agg.add(flat(9, 30, 1)) == []
    out = agg.add(flat(9, 36, 2))
    assert len(out) == 1 and out[0].ts == at(9, 30)


# ---- indicators ----------------------------------------------------------
def test_session_stats_vwap_gap_prev_close():
    s = SessionStats()
    s.update(mk(15, 55, 10, 10, 10, 10, v=1, day=D - timedelta(days=3)))
    s.update(mk(9, 30, 11, 12, 10, 11, v=100))
    s.update(mk(9, 35, 11, 13, 11, 12, v=300))
    assert s.prev_close == 10 and s.open == 11 and s.gap == pytest.approx(0.1)
    assert s.vwap == pytest.approx((11 * 100 + 12 * 300) / 400)
    assert s.high == 13 and s.low == 10 and s.vwap_std > 0


def test_atr_and_rsi_basic():
    atr = ATR(3)
    for i in range(3):
        atr.update(mk(9, 30 + i, 10, 11, 9, 10))
    assert atr.value == pytest.approx(2.0)
    rsi = RSI(3)
    for c in [1, 2, 3, 4, 5]:
        rsi.update(c)
    assert rsi.value == 100.0


# ---- sim broker ----------------------------------------------------------
def test_sim_fills_next_open_with_slippage_then_target():
    b = sim_broker(slip=10)
    b.submit_bracket("X", Side.LONG, 10, stop=99, target=103, client_order_id="a")
    b.on_minute_bar(mk(9, 50, 100, 100.5, 99.5, 100.2))
    assert b.positions()["X"].entry_price == pytest.approx(100.1)
    b.on_minute_bar(mk(9, 51, 101, 103.0, 100.8, 102.9))  # touches, does not trade through
    assert "X" in b.positions()
    b.on_minute_bar(mk(9, 52, 103, 103.5, 102.8, 103.2))
    assert b.trades[-1]["reason"] == "target" and b.trades[-1]["exit"] == 103


def test_sim_stop_first_when_both_hit():
    b = sim_broker()
    b.submit_bracket("X", Side.LONG, 10, stop=99, target=101, client_order_id="a")
    b.on_minute_bar(flat(9, 50, 100))
    b.on_minute_bar(mk(9, 51, 100, 102, 98, 100))
    assert b.trades[-1]["reason"] == "stop" and b.trades[-1]["pnl"] == pytest.approx(-10)


def test_sim_gap_through_stop_fills_at_open():
    b = sim_broker()
    b.submit_bracket("X", Side.SHORT, 10, stop=101, target=95, client_order_id="a")
    b.on_minute_bar(flat(9, 50, 100))
    b.on_minute_bar(mk(9, 51, 102, 102.5, 101.5, 102))
    assert b.trades[-1]["reason"] == "stop_gap" and b.trades[-1]["exit"] == 102


def test_sim_rejects_entry_already_through_stop():
    b = sim_broker()
    b.submit_bracket("X", Side.LONG, 10, stop=99, target=103, client_order_id="a")
    b.on_minute_bar(mk(9, 50, 98.5, 99, 98, 98.7))
    assert b.positions() == {} and b.rejected == 1


def test_sim_close_position_fills_next_open():
    b = sim_broker()
    b.submit_bracket("X", Side.LONG, 10, stop=90, target=110, client_order_id="a")
    b.on_minute_bar(flat(9, 50, 100))
    b.close_position("X", "time_stop")
    assert "X" in b.positions()
    b.on_minute_bar(flat(9, 51, 101))
    assert b.positions() == {} and b.trades[-1]["reason"] == "time_stop" and b.trades[-1]["exit"] == 101


# ---- risk ----------------------------------------------------------------
def test_risk_sizing_caps():
    r = RiskManager(RiskConfig(risk_per_trade=0.01, max_position_pct=0.5))
    assert r.size(Signal("X", Side.LONG, 100, 99, 102, at(9, 45)), 10_000) == 50
    assert r.size(Signal("X", Side.LONG, 100, 96, 108, at(9, 45)), 10_000) == 25


def test_risk_rejects_bad_geometry_and_tight_stops():
    b = sim_broker()
    r = RiskManager(RiskConfig(min_stop_pct=0.001))
    assert r.evaluate(Signal("X", Side.LONG, 100, 101, 102, at(9, 45)), b, at(9, 50)).qty == 0
    assert r.evaluate(Signal("X", Side.SHORT, 100, 99, 98, at(9, 45)), b, at(9, 50)).qty == 0
    assert r.evaluate(Signal("X", Side.LONG, 100, 99.95, 102, at(9, 45)), b, at(9, 50)).reason == "stop too tight"


def test_risk_max_positions_and_halt():
    b = sim_broker()
    r = RiskManager(RiskConfig(max_positions=1))
    b.submit_bracket("A", Side.LONG, 1, 99, 103, "a")
    sig = Signal("X", Side.LONG, 100, 99, 102, at(9, 45))
    assert r.evaluate(sig, b, at(9, 50)).reason == "max positions"
    r.halt(at(10, 0))
    assert r.evaluate(sig, b, at(10, 5)).qty == 0


# ---- engine --------------------------------------------------------------
class Scripted(Strategy):
    """Emits pre-programmed actions keyed by N-minute bar start time."""

    name = "scripted"
    Params = dict

    def __init__(self, script):
        super().__init__({}, 5)
        self.script = script
        self.seen = []

    def on_bar(self, bar, ctx):
        self.seen.append((bar.ts, dict(ctx.positions)))
        return self.script.get(bar.ts.time(), [])


def test_engine_flattens_at_eod():
    b = sim_broker()
    eng = Engine(Scripted({}), RiskManager(RiskConfig(flatten_at=time(15, 45))), b, 5)
    b.submit_bracket("X", Side.LONG, 10, stop=50, target=200, client_order_id="a")
    eng.on_minute_bar(flat(15, 40, 100))
    eng.on_minute_bar(flat(15, 45, 101))
    assert b.positions() == {} and b.trades[-1]["reason"] == "eod" and b.trades[-1]["exit"] == 101


def test_daily_loss_halts_and_flattens():
    b = sim_broker()
    eng = Engine(Scripted({}), RiskManager(RiskConfig(daily_max_loss=0.02)), b, 5)
    b.submit_bracket("X", Side.LONG, 100, stop=10, target=500, client_order_id="a")
    eng.on_minute_bar(flat(9, 50, 100))
    eng.on_minute_bar(flat(9, 51, 97))
    eng.on_minute_bar(flat(9, 52, 96))
    assert b.positions() == {} and b.trades[-1]["reason"] == "daily_loss"
    assert eng.risk.is_halted(at(10, 0))


def test_engine_signal_fills_after_signal_bar_and_exit_action():
    sig = Signal("X", Side.LONG, 100, 98, 110, at(9, 40))
    strat = Scripted({time(9, 40): [sig], time(9, 50): [Exit("X", "time_stop", at(9, 50))]})
    b = sim_broker()
    eng = Engine(strat, RiskManager(RiskConfig(max_position_pct=1)), b, 5, name="t")
    for m in range(30, 60):
        eng.on_minute_bar(flat(9, m, 100 + (m - 30) * 0.01))
    tr = b.trades[-1]
    assert tr["entry_time"] == at(9, 45)          # signal bar 9:40-9:45 -> fill at 9:45 open
    assert tr["exit_time"] == at(9, 55) and tr["reason"] == "time_stop"
    assert eng.signals[0]["decision"] == "ok"
    assert eng.client_order_id(sig) == "t-X-20250303-0940-long"
    # strategy saw its position in the context on the 9:50 bar
    assert any("X" in pos for ts, pos in strat.seen if ts == at(9, 50))


def test_warmup_does_not_trade_or_query_positions():
    sig = Signal("X", Side.LONG, 100, 98, 110, at(9, 40))
    b = sim_broker()
    eng = Engine(Scripted({time(9, 40): [sig]}), RiskManager(RiskConfig()), b, 5)
    for m in range(30, 50):
        eng.on_minute_bar(flat(9, m, 100), trade=False)
    assert eng.signals == [] and b.positions() == {} and b.busy_symbols() == set()


def test_engine_ignores_duplicate_and_premarket_bars():
    strat = Scripted({})
    eng = Engine(strat, RiskManager(RiskConfig()), sim_broker(), 5)
    eng.on_minute_bar(flat(9, 0, 100))
    for m in range(30, 35):
        eng.on_minute_bar(flat(9, m, 100))
        eng.on_minute_bar(flat(9, m, 999))
    assert len(strat.seen) == 1


# ---- config / registry / live validation -----------------------------------
def test_unknown_params_rejected():
    with pytest.raises(ValueError):
        build_strategy(StrategyConfig("orb", {"nope": 1}), 5)
    with pytest.raises(ValueError):
        build_strategy(StrategyConfig("does_not_exist", {}), 5)


def test_all_shipped_configs_load():
    from pathlib import Path
    for p in sorted(Path(__file__).parent.parent.joinpath("configs").glob("*.yaml")):
        cfg = load_config(p)
        build_strategy(cfg.strategy, cfg.bar_minutes)


def test_validate_instances():
    from daytrader.live import validate_instances
    a = Config(name="a", symbols=["SPY", "QQQ"])
    b = Config(name="b", symbols=["SPY"])
    c = Config(name="c", symbols=["AAPL"])
    assert validate_instances([a, b], ["1", "2"]) == []
    with pytest.raises(SystemExit):
        validate_instances([a, b], ["1", "1"])            # shared account + shared symbol
    assert validate_instances([a, c], ["1", "1"])          # allowed, with a warning
    with pytest.raises(SystemExit):
        validate_instances([a, Config(name="a")], ["1", "2"])
    with pytest.raises(SystemExit):
        validate_instances([Config(name="x"), Config(name="x-2")], ["1", "2"])
